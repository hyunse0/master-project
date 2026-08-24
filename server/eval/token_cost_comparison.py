"""KPI 비교 러너 — 같은 벤치마크 질의셋을 여러 태그 조합으로 돌려 토큰/지연시간/성공률을 비교한다.

이 스크립트가 "이 기능을 추가했더니 성능/비용이 이렇게 좋아졌다"는 자료의 원천이다.
사용:
  python eval/token_cost_comparison.py --domain poc_prostate --compare schema_rag_mode=rag,full_dump
  python eval/token_cost_comparison.py --domain poc_prostate --compare max_retries=0,2
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.app_db import get_app_db_connection  # noqa: E402
from app.domain.loader import get_domain  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from scripts.run_graph_cli import run_once  # noqa: E402

_DEFAULT_TAGS = {"schema_rag_mode": "rag", "max_retries": 2}


def _parse_compare(spec: str) -> tuple[str, list[str]]:
    key, values = spec.split("=", 1)
    return key, values.split(",")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--compare", required=True, help="예: schema_rag_mode=rag,full_dump")
    parser.add_argument("--experiment", default=None)
    args = parser.parse_args()

    domain = get_domain(args.domain)
    if not domain.benchmark_queries_path.is_file():
        print(f"[{args.domain}] benchmark_queries.json 없음 ({domain.benchmark_queries_path}) — 스킵")
        return

    queries = json.loads(domain.benchmark_queries_path.read_text())
    key, values = _parse_compare(args.compare)
    experiment = args.experiment or f"{key}_ablation"

    graph = build_graph(domain)

    for raw_value in values:
        tag_value = int(raw_value) if raw_value.isdigit() else raw_value
        tags = {**_DEFAULT_TAGS, key: tag_value, "experiment": experiment}
        print(f"\n--- {key}={tag_value} ({len(queries)}건) ---")
        for q in queries:
            _, status, latency_ms = run_once(args.domain, q["question"], tags, graph=graph)
            print(f"  [{status}] {latency_ms}ms  {q['question']}")

    _print_comparison(experiment, key)


def _print_comparison(experiment: str, key: str) -> None:
    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT tags->>%s AS tag_value,
                       SUM(input_tokens + output_tokens) AS total_tokens,
                       COUNT(*) AS calls
                FROM token_usage
                WHERE tags->>'experiment' = %s
                GROUP BY tag_value ORDER BY tag_value
                """,
                (key, experiment),
            )
            token_rows = cur.fetchall()

            cur.execute(
                """
                SELECT tags->>%s AS tag_value,
                       AVG(latency_ms) AS avg_latency,
                       AVG((status = 'success')::int::float) AS success_rate,
                       COUNT(*) AS runs
                FROM run_metrics
                WHERE tags->>'experiment' = %s
                GROUP BY tag_value ORDER BY tag_value
                """,
                (key, experiment),
            )
            run_rows = cur.fetchall()
    finally:
        conn.close()

    print(f"\n=== {key} 비교 (experiment={experiment}) ===")
    header = f"{'value':<15}{'total_tokens':<15}{'llm_calls':<12}{'avg_latency_ms':<18}{'success_rate':<14}{'runs'}"
    print(header)
    run_by_tag = {r[0]: r for r in run_rows}
    for tag_value, total_tokens, calls in token_rows:
        _, avg_latency, success_rate, runs = run_by_tag.get(tag_value, (tag_value, 0, 0, 0))
        print(
            f"{str(tag_value):<15}{total_tokens:<15}{calls:<12}"
            f"{float(avg_latency or 0):<18.0f}{float(success_rate or 0):<14.1%}{runs}"
        )


if __name__ == "__main__":
    main()
