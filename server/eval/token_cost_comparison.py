"""KPI 비교 러너 — 같은 벤치마크 질의셋을 여러 태그 값으로 돌려 토큰/지연시간/성공률을 비교한다.

이 스크립트가 "이 기능을 추가했더니 성능/비용이 이렇게 좋아졌다"는 자료의 원천이다. 두 가지
사용 패턴이 있다 — 어느 쪽이든 최종 비교는 _print_comparison()이 그때그때 DB에 쌓인 걸 다시
읽어서 보여주므로(방금 이 실행에서 나온 값만 보는 게 아님), 두 패턴을 섞어 써도 된다.

1) 런타임에 tags 값으로 분기하는 기존 기능(schema_rag_mode, routing_mode 등) A/B — 값 두 개를
   콤마로 같이 주면 한 번의 실행으로 둘 다 돌리고 바로 비교까지 나온다:
     python eval/token_cost_comparison.py --domain poc_prostate --compare schema_rag_mode=rag,full_dump

2) 프롬프트 문구 수정처럼 "코드 자체를 바꾸는" 개선 — tags로 토글할 수 없으니 코드 변경 전/후에
   각각 한 번씩 따로 돌린다. 비교축 이름은 자유지만 관례로 phase=before/after를 쓴다. 같은
   --experiment(=kpi-experiment-log.md의 실험 ID)로 묶어야 두 번의 실행이 하나의 비교표로 합쳐진다:
     python eval/token_cost_comparison.py --domain poc_prostate --compare phase=before --experiment EXP-002
     # ...코드 변경...
     python eval/token_cost_comparison.py --domain poc_prostate --compare phase=after --experiment EXP-002
   재실행 없이 지금까지 쌓인 비교표만 다시 보고 싶으면 --report-only(실행 없이 phase 아무 값이나
   하나 넘겨서 key만 지정):
     python eval/token_cost_comparison.py --domain poc_prostate --compare phase=after --experiment EXP-002 --report-only
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
    parser.add_argument("--compare", required=True, help="예: schema_rag_mode=rag,full_dump 또는 phase=before")
    parser.add_argument("--experiment", default=None, help="비교표를 묶을 이름 — before/after 두 번 실행할 땐 반드시 같은 값을 줘야 한다")
    parser.add_argument("--report-only", action="store_true", help="새로 실행하지 않고 지금까지 쌓인 비교표만 다시 출력")
    args = parser.parse_args()

    key, values = _parse_compare(args.compare)
    experiment = args.experiment or f"{key}_ablation"

    if args.report_only:
        _print_comparison(experiment, key)
        return

    domain = get_domain(args.domain)
    if not domain.benchmark_queries_path.is_file():
        print(f"[{args.domain}] benchmark_queries.json 없음 ({domain.benchmark_queries_path}) — 스킵")
        return

    queries = json.loads(domain.benchmark_queries_path.read_text())
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
