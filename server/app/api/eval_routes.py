"""Golden Set 평가 화면용 조회 API. eval/*.py 스크립트가 run_logger.log()로 이미 남긴
run_metrics.tags(experiment별 구분)를 읽기만 한다 — cost_routes.py와 동일하게 새 테이블
없이 기존 관측성 인프라(D단계)를 재사용(data-access-copilot-plan.md H단계).
"""
from fastapi import APIRouter

from app.db.app_db import get_app_db_connection

router = APIRouter(tags=["eval"])


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
