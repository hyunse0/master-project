"""golden_set.json 기반 Execution Accuracy 평가.
사용: python eval/execution_accuracy.py --domain <name>

golden_set.json 포맷: [{"question": "...", "expected_sql": "..."}, ...]
아직 golden_set.json이 없는 도메인은 스킵 메시지만 출력하고 정상 종료한다
(data-access-copilot-plan.md — 실제 데이터셋 확정 후 작성 예정, 지금은 보류).
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.postgres_client import get_domain_connection  # noqa: E402
from app.domain.loader import DomainConfig, get_domain  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.observability import run_logger  # noqa: E402


def _execute_rows(domain: DomainConfig, sql: str) -> set[tuple]:
    conn = get_domain_connection(domain.connection)
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            return {tuple(row) for row in cur.fetchall()}
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    domain = get_domain(args.domain)
    if not domain.golden_set_path.is_file():
        print(f"[{args.domain}] golden_set.json 없음 ({domain.golden_set_path}) — 스킵")
        return

    golden = json.loads(domain.golden_set_path.read_text())
    if not golden:
        print("골든셋이 비어있습니다.")
        return

    graph = build_graph(domain)

    correct = 0
    for item in golden:
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
            except Exception as e:
                print(f"  [ERR] {item['question']} — 비교 실패: {e}")
        correct += int(ok)
        print(f"  [{'OK' if ok else 'FAIL'}] {item['question']}")

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

    total = len(golden)
    print(f"\nExecution Accuracy: {correct}/{total} ({correct / total:.1%})")


if __name__ == "__main__":
    main()
