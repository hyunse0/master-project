"""Golden Set 평가 화면용 조회 API. eval/*.py 스크립트가 run_logger.log()로 이미 남긴
run_metrics.tags(experiment별 구분)를 읽기만 한다 — cost_routes.py와 동일하게 새 테이블
없이 기존 관측성 인프라(D단계)를 재사용(data-access-copilot-plan.md H단계).
"""
import json
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

import eval.execution_accuracy as execution_accuracy_eval
import eval.self_correction_ablation as self_correction_eval
from app.db.app_db import get_app_db_connection
from app.domain.loader import get_domain

router = APIRouter(tags=["eval"])

# domain -> 진행 상태. 그래프 1회 실행이 질문당 수 초~수십 초 걸려 골든셋 전체(14문항
# 기준 수분)를 동기 응답으로 두면 이 요청 하나가 개발서버(단일 워커)의 이벤트루프를
# 그대로 막아버린다 — 그래서 실제 실행은 백그라운드 스레드에 맡기고, 여기 메모리 dict는
# "지금 몇 번째 문항인지"를 폴링해 보여주는 용도로만 쓴다. 최종 결과는 기존과 동일하게
# run_metrics에 남으므로(eval.execution_accuracy.run 내부), 이 dict가 재시작으로
# 날아가도 정답률 집계 자체는 안전하다.
_EXEC_ACC_JOBS: dict[str, dict] = {}


def _run_execution_accuracy_job(domain: str) -> None:
    job = _EXEC_ACC_JOBS[domain]

    def on_case(i: int, total: int, question: str, ok: bool) -> None:
        job["done"] = i
        job["total"] = total
        job["last_question"] = question

    try:
        domain_cfg = get_domain(domain)
        job["result"] = execution_accuracy_eval.run(domain_cfg, on_case=on_case)
        job["status"] = "done"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
    finally:
        job["finished_at"] = datetime.now(timezone.utc).isoformat()


# self_correction_ablation.py는 golden_set.json이 아니라 benchmark_queries.json 기준이고
# graph.stream()으로 중간 재시도 이력을 모아야 해서 execution_accuracy.run()과 같은 루프에
# 합칠 수 없다 — 그래서 별도 job/엔드포인트로 둔다(위 _EXEC_ACC_JOBS와 동일한 이유·패턴).
_SELF_CORRECTION_JOBS: dict[str, dict] = {}


def _run_self_correction_job(domain: str) -> None:
    job = _SELF_CORRECTION_JOBS[domain]

    def on_case(i: int, total: int, question: str, outcome: str) -> None:
        job["done"] = i
        job["total"] = total
        job["last_question"] = question
        job["last_outcome"] = outcome

    try:
        domain_cfg = get_domain(domain)
        job["result"] = self_correction_eval.run(domain_cfg, on_case=on_case)
        job["status"] = "done"
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
    finally:
        job["finished_at"] = datetime.now(timezone.utc).isoformat()


def _rows(sql: str, params: dict) -> list[dict]:
    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


@router.get("/eval/execution-accuracy")
def get_execution_accuracy(domain: str | None = None) -> dict:
    """execution_accuracy.py가 남긴 결과를 난이도별로 묶어 반환. golden_set.json이 아직
    없는 도메인은 experiment='execution_accuracy' 행 자체가 없어 groups가 빈 배열로 온다
    — 프론트는 이걸 "골든셋 없음" 상태로 표시."""
    groups = _rows(
        """
        SELECT tags->>'difficulty' AS difficulty,
               COUNT(*) AS total,
               SUM((tags->>'golden_correct' = 'true')::int) AS correct
        FROM run_metrics
        WHERE tags->>'experiment' = 'execution_accuracy'
          AND (%(domain)s::text IS NULL OR domain = %(domain)s)
        GROUP BY difficulty ORDER BY difficulty
        """,
        {"domain": domain},
    )
    for g in groups:
        g["accuracy"] = round(g["correct"] / g["total"], 4) if g["total"] else 0.0

    last_run_rows = _rows(
        """
        SELECT MAX(created_at) AS last_run_at
        FROM run_metrics
        WHERE tags->>'experiment' = 'execution_accuracy'
          AND (%(domain)s::text IS NULL OR domain = %(domain)s)
        """,
        {"domain": domain},
    )

    total = sum(g["total"] for g in groups)
    correct = sum(g["correct"] for g in groups)
    return {
        "domain": domain,
        "groups": groups,
        "overall": {
            "total": total,
            "correct": correct,
            "accuracy": round(correct / total, 4) if total else None,
            "last_run_at": last_run_rows[0]["last_run_at"] if last_run_rows else None,
        },
    }


@router.get("/eval/schema-mapping-accuracy")
def get_schema_mapping_accuracy(domain: str | None = None) -> dict:
    """schema_mapping_accuracy.py가 남긴 질문별 precision/recall/f1의 평균. 난이도별
    breakdown도 함께 — 어려운 질문일수록 스키마 링킹이 흔들리는지 보기 위함."""
    overall_rows = _rows(
        """
        SELECT COUNT(*) AS total,
               AVG((tags->>'precision')::float) AS precision,
               AVG((tags->>'recall')::float)    AS recall,
               AVG((tags->>'f1')::float)        AS f1
        FROM run_metrics
        WHERE tags->>'experiment' = 'schema_mapping_accuracy'
          AND (%(domain)s::text IS NULL OR domain = %(domain)s)
        """,
        {"domain": domain},
    )
    groups = _rows(
        """
        SELECT tags->>'difficulty' AS difficulty,
               COUNT(*) AS total,
               AVG((tags->>'precision')::float) AS precision,
               AVG((tags->>'recall')::float)    AS recall,
               AVG((tags->>'f1')::float)        AS f1
        FROM run_metrics
        WHERE tags->>'experiment' = 'schema_mapping_accuracy'
          AND (%(domain)s::text IS NULL OR domain = %(domain)s)
        GROUP BY difficulty ORDER BY difficulty
        """,
        {"domain": domain},
    )
    return {"domain": domain, "overall": overall_rows[0] if overall_rows else None, "groups": groups}


@router.get("/eval/faithfulness")
def get_faithfulness(domain: str | None = None, limit: int = 20) -> dict:
    """condition_summary_faithfulness.py 결과 — 전체 비율 + 실패 사례 목록(최신순)."""
    overall_rows = _rows(
        """
        SELECT COUNT(*) AS total,
               SUM((tags->>'faithful' = 'true')::int) AS faithful
        FROM run_metrics
        WHERE tags->>'experiment' = 'condition_summary_faithfulness'
          AND (%(domain)s::text IS NULL OR domain = %(domain)s)
        """,
        {"domain": domain},
    )
    overall = overall_rows[0] if overall_rows else {"total": 0, "faithful": 0}
    overall["ratio"] = round(overall["faithful"] / overall["total"], 4) if overall["total"] else None

    failures = _rows(
        """
        SELECT run_id, question,
               tags->>'reason'  AS reason,
               tags->>'summary' AS summary,
               tags->'columns'  AS columns,
               tags->'rows'     AS rows,
               created_at
        FROM run_metrics
        WHERE tags->>'experiment' = 'condition_summary_faithfulness'
          AND tags->>'faithful' = 'false'
          AND (%(domain)s::text IS NULL OR domain = %(domain)s)
        ORDER BY created_at DESC
        LIMIT %(limit)s
        """,
        {"domain": domain, "limit": limit},
    )
    return {"domain": domain, "overall": overall, "failures": failures}


@router.get("/eval/self-correction")
def get_self_correction(domain: str | None = None) -> dict:
    """self_correction_ablation.py 결과 — outcome 3분류 집계 + 실패유형별 교정 건수."""
    outcomes = _rows(
        """
        SELECT tags->>'outcome' AS outcome, COUNT(*) AS count
        FROM run_metrics
        WHERE tags->>'experiment' = 'self_correction_ablation'
          AND (%(domain)s::text IS NULL OR domain = %(domain)s)
        GROUP BY 1
        """,
        {"domain": domain},
    )
    # 별칭을 "error_code"로 두면 run_metrics의 실제 컬럼명(run_metrics.error_code)과 겹쳐
    # GROUP BY가 별칭이 아니라 그 실제 컬럼으로 해석돼버린다 — "first_error_code"로 회피.
    by_error_code = _rows(
        """
        SELECT tags->>'first_error_code' AS first_error_code, tags->>'outcome' AS outcome, COUNT(*) AS count
        FROM run_metrics
        WHERE tags->>'experiment' = 'self_correction_ablation'
          AND tags->>'first_error_code' IS NOT NULL
          AND (%(domain)s::text IS NULL OR domain = %(domain)s)
        GROUP BY 1, 2 ORDER BY 1
        """,
        {"domain": domain},
    )
    return {"domain": domain, "outcomes": outcomes, "by_error_code": by_error_code}


@router.get("/eval/token-cost")
def get_token_cost(experiment: str, compare_key: str, domain: str | None = None) -> dict:
    """eval/token_cost_comparison.py의 _print_comparison() 쿼리를 그대로 옮긴 것 — 같은
    experiment 태그로 여러 값(예: schema_rag_mode=rag,full_dump)을 비교 실행해뒀다는 전제로,
    태그값별 토큰/지연시간/성공률을 반환한다."""
    token_rows = _rows(
        """
        SELECT tags->>%(compare_key)s AS tag_value,
               SUM(input_tokens + output_tokens) AS total_tokens,
               COUNT(*) AS calls
        FROM token_usage
        WHERE tags->>'experiment' = %(experiment)s
        GROUP BY tag_value ORDER BY tag_value
        """,
        {"compare_key": compare_key, "experiment": experiment},
    )
    run_rows = _rows(
        """
        SELECT tags->>%(compare_key)s AS tag_value,
               AVG(latency_ms) AS avg_latency_ms,
               AVG((status = 'success')::int::float) AS success_rate,
               COUNT(*) AS runs
        FROM run_metrics
        WHERE tags->>'experiment' = %(experiment)s
          AND (%(domain)s::text IS NULL OR domain = %(domain)s)
        GROUP BY tag_value ORDER BY tag_value
        """,
        {"compare_key": compare_key, "experiment": experiment, "domain": domain},
    )
    run_by_tag = {r["tag_value"]: r for r in run_rows}
    groups = []
    for t in token_rows:
        run_info = run_by_tag.get(t["tag_value"], {})
        groups.append({
            "tag_value": t["tag_value"],
            "total_tokens": t["total_tokens"],
            "calls": t["calls"],
            "avg_latency_ms": round(run_info.get("avg_latency_ms") or 0),
            "success_rate": run_info.get("success_rate"),
            "runs": run_info.get("runs", 0),
        })
    return {"domain": domain, "experiment": experiment, "compare_key": compare_key, "groups": groups}


@router.post("/eval/execution-accuracy/run")
def start_execution_accuracy(domain: str) -> dict:
    """골든셋 전체를 백그라운드에서 실행 시작. 이미 실행 중이면 새로 시작하지 않고
    지금 돌고 있는 job을 그대로 돌려준다(중복 실행 방지)."""
    existing = _EXEC_ACC_JOBS.get(domain)
    if existing and existing["status"] == "running":
        return {"status": "already_running", "job": existing}

    domain_cfg = get_domain(domain)
    if not domain_cfg.golden_set_path.is_file():
        raise HTTPException(status_code=400, detail="golden_set.json이 없어 실행할 수 없습니다.")

    job = {
        "status": "running",
        "done": 0,
        "total": 0,
        "last_question": None,
        "result": None,
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    _EXEC_ACC_JOBS[domain] = job
    threading.Thread(target=_run_execution_accuracy_job, args=(domain,), daemon=True).start()
    return {"status": "started", "job": job}


@router.get("/eval/execution-accuracy/run-status")
def get_execution_accuracy_run_status(domain: str) -> dict:
    return {"job": _EXEC_ACC_JOBS.get(domain)}


@router.post("/eval/self-correction/run")
def start_self_correction(domain: str) -> dict:
    """benchmark_queries.json 전체를 백그라운드에서 실행 시작. 이미 실행 중이면 새로 시작하지
    않고 지금 돌고 있는 job을 그대로 돌려준다(중복 실행 방지)."""
    existing = _SELF_CORRECTION_JOBS.get(domain)
    if existing and existing["status"] == "running":
        return {"status": "already_running", "job": existing}

    domain_cfg = get_domain(domain)
    if not domain_cfg.benchmark_queries_path.is_file():
        raise HTTPException(status_code=400, detail="benchmark_queries.json이 없어 실행할 수 없습니다.")

    job = {
        "status": "running",
        "done": 0,
        "total": 0,
        "last_question": None,
        "last_outcome": None,
        "result": None,
        "error": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    _SELF_CORRECTION_JOBS[domain] = job
    threading.Thread(target=_run_self_correction_job, args=(domain,), daemon=True).start()
    return {"status": "started", "job": job}


@router.get("/eval/self-correction/run-status")
def get_self_correction_run_status(domain: str) -> dict:
    return {"job": _SELF_CORRECTION_JOBS.get(domain)}


@router.get("/eval/golden-set")
def get_golden_set(domain: str | None = None) -> dict:
    """golden_set.json 원본(대화 목록, F단계부터 turns 포맷)을 턴 단위로 펼쳐 질문+정답 SQL에
    마지막 execution_accuracy 실행 결과를 붙여 반환한다. 다른 /eval/* 엔드포인트와 달리
    run_metrics만으로는 골든셋 "항목 자체"(질문 텍스트, 정답 SQL)를 알 수 없으므로 도메인
    팩의 golden_set.json을 소스로 읽고, run_metrics는 "이 질문을 마지막으로 돌렸을 때
    어땠는지"만 조인한다."""
    if not domain:
        return {"domain": None, "cases": []}

    domain_cfg = get_domain(domain)
    if not domain_cfg.golden_set_path.is_file():
        return {"domain": domain, "cases": []}

    golden = json.loads(domain_cfg.golden_set_path.read_text())

    last_runs = _rows(
        """
        SELECT DISTINCT ON (question)
               question, run_id, status, sql, created_at,
               tags->>'golden_correct' AS golden_correct
        FROM run_metrics
        WHERE tags->>'experiment' = 'execution_accuracy'
          AND domain = %(domain)s
        ORDER BY question, created_at DESC
        """,
        {"domain": domain},
    )
    last_by_question = {r["question"]: r for r in last_runs}

    cases = []
    for conv_idx, conv in enumerate(golden, start=1):
        for turn_no, item in enumerate(conv["turns"], start=1):
            last = last_by_question.get(item["question"])
            cases.append({
                "question": item["question"],
                "expected_sql": item["expected_sql"],
                "conversation_index": conv_idx,
                "turn_no": turn_no,
                "last_run": None if last is None else {
                    "run_id": last["run_id"],
                    "ok": last["golden_correct"] == "true",
                    "generated_sql": last["sql"],
                    "created_at": last["created_at"],
                },
            })
    return {"domain": domain, "cases": cases}
