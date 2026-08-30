"""golden_set.json 기반 Execution Accuracy + Schema Mapping Accuracy 평가.
사용: python eval/execution_accuracy.py --domain <name>

golden_set.json 포맷: [{"question": "...", "expected_sql": "..."}, ...]
아직 golden_set.json이 없는 도메인은 스킵 메시지만 출력하고 정상 종료한다
(data-access-copilot-plan.md — 실제 데이터셋 확정 후 작성 예정, 지금은 보류).

원래 이 평가와 schema_mapping_accuracy.py(schema_linking이 옳은 테이블을 골랐는지)는 완전히
분리된 스크립트로, 같은 골든셋을 각자 graph.invoke()에 처음부터 다시 태워 LLM을 두 번 호출하고
있었다 — 하지만 graph.invoke() 한 번으로 최종 SQL(execution accuracy용)과 confirmed_schema
(schema mapping accuracy용)가 동시에 나오므로, 여기서 한 번에 계산해 두 experiment 태그로
각각 기록한다. schema_mapping_accuracy.py는 이제 이 run()의 결과 중 schema_mapping 부분만
보여주는 얇은 CLI 래퍼로 남는다.

run()이 실제 평가 로직이고 main()은 CLI 출력용 얇은 래퍼다 — app/api/eval_routes.py의
"지금 실행" 버튼도 run()을 그대로 재사용한다(app/knowledge/few_shot_seeder.seed_domain()을
seed_few_shot.py 스크립트와 API 라우트가 함께 쓰는 것과 같은 패턴). API 쪽은 그래프 실행이
질문당 수 초~수십 초씩 걸려 총 몇 분이 걸릴 수 있어 동기 응답 대신 백그라운드 스레드로 돌리고,
on_case 콜백으로 진행률만 폴링용 상태에 반영한다.
"""
import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Callable

import sqlglot
import sqlglot.expressions as exp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.postgres_client import get_domain_connection  # noqa: E402
from app.domain.loader import DomainConfig, get_domain  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.llm.router import build_llm_router  # noqa: E402
from app.observability import run_logger  # noqa: E402
from eval.condition_summary_faithfulness import extract_summary_section, judge_faithfulness  # noqa: E402


def _execute_rows(domain: DomainConfig, sql: str) -> set[tuple]:
    conn = get_domain_connection(domain.connection)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return {tuple(row) for row in cur.fetchall()}
    finally:
        conn.close()


def _extract_tables(sql: str) -> set[str]:
    """SQL이 참조하는 테이블을 "schema.table" 소문자 집합으로 뽑는다.

    app/sql/schema_provider.py의 TableInfo.full_name("schema.table")과 같은 형식으로
    맞춰야 confirmed_schema(스키마 인덱서가 그 형식으로 색인한 값)와 직접 비교 가능하다.
    """
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return set()
    return {f"{(t.db or 'public')}.{t.name}".lower() for t in tree.find_all(exp.Table) if t.name}


def _prf1(expected: set[str], predicted: set[str]) -> tuple[float, float, float]:
    if not predicted and not expected:
        return 1.0, 1.0, 1.0
    intersection = expected & predicted
    precision = len(intersection) / len(predicted) if predicted else 0.0
    recall = len(intersection) / len(expected) if expected else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return precision, recall, f1


def run(domain: DomainConfig, on_case: Callable[[int, int, str, bool], None] | None = None) -> dict:
    """골든셋 전체를 실행하고 execution accuracy + schema mapping accuracy를 함께 반환한다.

    on_case(index, total, question, ok)가 있으면 항목이 끝날 때마다 호출한다(1-based index,
    ok는 execution accuracy 기준). 두 지표 모두 질문당 graph.invoke() 1회로 계산한다.
    """
    if not domain.golden_set_path.is_file():
        return {"skipped": True, "reason": "golden_set_missing", "total": 0, "correct": 0, "accuracy": None}

    golden = json.loads(domain.golden_set_path.read_text())
    if not golden:
        return {"skipped": True, "reason": "golden_set_empty", "total": 0, "correct": 0, "accuracy": None}

    graph = build_graph(domain)
    # 요약 충실도 판정 자체도 비용이 드는 LLM 호출이라 저비용 티어를 쓴다 — app/llm/router.py의
    # 난이도별 티어 매핑 중 "easy"가 가리키는 저비용 클라이언트를 그대로 재사용.
    judge_llm = build_llm_router()["easy"]

    total = len(golden)
    correct = 0
    sum_p = sum_r = sum_f1 = 0.0
    faithful_total = faithful_count = 0

    for i, item in enumerate(golden, start=1):
        run_id = str(uuid.uuid4())
        state = graph.invoke(
            {
                "question": item["question"],
                "domain": domain.name,
                "run_id": run_id,
                "tags": {"experiment": "execution_accuracy"},
                "review_config": {"schema": False, "sql": False},
            },
            config={"recursion_limit": 50},
        )

        generated_sql = state.get("sql")
        ok = False
        if generated_sql and not state.get("execution_error"):
            try:
                expected_rows = _execute_rows(domain, item["expected_sql"])
                actual_rows = _execute_rows(domain, generated_sql)
                ok = expected_rows == actual_rows
            except Exception:
                ok = False
        correct += int(ok)

        expected_tables = _extract_tables(item["expected_sql"])
        predicted_tables = {t.lower() for t in (state.get("confirmed_schema") or [])}
        precision, recall, f1 = _prf1(expected_tables, predicted_tables)
        sum_p += precision
        sum_r += recall
        sum_f1 += f1

        # 난이도별 정확도 바(GoldenSetPanel)가 tags->>'difficulty'/'golden_correct'로
        # run_metrics를 그룹핑해 읽는다 — 새 테이블 없이 기존 관례(D단계) 그대로 재사용.
        run_logger.log(
            run_id=run_id,
            domain=domain.name,
            question=item["question"],
            status="success" if ok else "error",
            sql=generated_sql,
            tags={
                "experiment": "execution_accuracy",
                "difficulty": state.get("difficulty"),
                "golden_correct": ok,
            },
        )
        run_logger.log(
            run_id=run_id,
            domain=domain.name,
            question=item["question"],
            status="success" if f1 == 1.0 else "error",
            tags={
                "experiment": "schema_mapping_accuracy",
                "difficulty": state.get("difficulty"),
                "precision": round(precision, 4),
                "recall": round(recall, 4),
                "f1": round(f1, 4),
            },
        )

        # 요약 충실도 — 파이프라인이 아예 실패해 요약 자체가 없는 항목은 판정 대상에서 제외
        # (condition_summary_faithfulness.py의 원래 스킵 조건과 동일).
        row_count = state.get("row_count")
        if row_count is not None and not state.get("execution_error"):
            summary_text = extract_summary_section(state.get("summary") or "")
            verdict = judge_faithfulness(
                judge_llm, run_id, item["question"], state.get("columns") or [], state.get("rows") or [], summary_text
            )
            if verdict["faithful"] is not None:
                faithful_total += 1
                faithful_count += int(verdict["faithful"])
                run_logger.log(
                    run_id=run_id,
                    domain=domain.name,
                    question=item["question"],
                    status="success",
                    row_count=row_count,
                    sql=generated_sql,
                    tags={
                        "experiment": "condition_summary_faithfulness",
                        "faithful": verdict["faithful"],
                        "reason": verdict["reason"],
                        "summary": summary_text,
                        "columns": state.get("columns") or [],
                        "rows": (state.get("rows") or [])[:5],
                    },
                )

        if on_case:
            on_case(i, total, item["question"], ok)

    return {
        "skipped": False,
        "reason": None,
        "total": total,
        "correct": correct,
        "accuracy": correct / total,
        "schema_mapping": {"precision": sum_p / total, "recall": sum_r / total, "f1": sum_f1 / total},
        "faithfulness": {
            "total": faithful_total,
            "faithful": faithful_count,
            "ratio": (faithful_count / faithful_total) if faithful_total else None,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    domain = get_domain(args.domain)

    def on_case(i: int, total: int, question: str, ok: bool) -> None:
        print(f"  [{'OK' if ok else 'FAIL'}] ({i}/{total}) {question}")

    result = run(domain, on_case=on_case)

    if result["skipped"]:
        if result["reason"] == "golden_set_missing":
            print(f"[{args.domain}] golden_set.json 없음 ({domain.golden_set_path}) — 스킵")
        else:
            print("골든셋이 비어있습니다.")
        return

    sm = result["schema_mapping"]
    fa = result["faithfulness"]
    print(f"\nExecution Accuracy: {result['correct']}/{result['total']} ({result['accuracy']:.1%})")
    print(f"Schema Mapping Accuracy: precision={sm['precision']:.1%} recall={sm['recall']:.1%} f1={sm['f1']:.1%}")
    if fa["ratio"] is not None:
        print(f"Condition Summary Faithfulness: {fa['faithful']}/{fa['total']} ({fa['ratio']:.1%})")


if __name__ == "__main__":
    main()
