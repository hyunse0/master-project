"""쿼리별 self-correction(재시도) 귀인 분석.
사용: python eval/self_correction_ablation.py --domain <name>

on/off 집계 비교(재시도 켰을 때 vs 껐을 때 전체 성공률)는 이미
`eval/token_cost_comparison.py --compare max_retries=0,2`가 지원한다. 이 스크립트는 그와
겹치지 않게 "쿼리별로 어떤 실패 유형(retry_error_code)이 재시도로 잘 고쳐지는지"만 본다
(data-access-copilot-plan.md H단계, self_correction_ablation.py).

golden_set.json 불필요 — benchmark_queries.json으로 충분(정답을 몰라도 "1차 시도에서
성공했는지 / 재시도로 성공했는지 / 끝내 실패했는지"는 파이프라인 자체 신호로 판별 가능).

각 질문을 graph.stream()으로 실행하며 retry_count가 올라갈 때마다 그 시점의
retry_error_code를 기록한다(graph.invoke()는 최종 state만 주므로 중간 실패 이력을
알 수 없음 — 계획 문서 section 5.6과 동일하게 trace성 정보는 그래프 밖에서 수집).

run()이 실제 평가 로직이고 main()은 CLI 출력용 얇은 래퍼다 — execution_accuracy.py와 같은
이유로 app/api/eval_routes.py의 "지금 실행" 버튼도 run()을 그대로 재사용한다. graph.stream()을
써야 해서(execution_accuracy.run()의 graph.invoke() 기반 골든셋 루프와는 별개) 같은 루프에
합치지 않고 독립된 job으로 둔다.
"""
import argparse
import json
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import DomainConfig, get_domain  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.observability import run_logger  # noqa: E402


def _run_with_history(graph, domain_name: str, question: str, run_id: str) -> tuple[dict, list[str]]:
    """graph.stream()으로 실행하며 retry_count가 증가할 때마다의 retry_error_code를 순서대로 모은다."""
    initial_state = {
        "question": question,
        "domain": domain_name,
        "run_id": run_id,
        "tags": {"max_retries": 2, "experiment": "self_correction_ablation"},
        "review_config": {"schema": False, "sql": False},
    }

    history: list[str] = []
    prev_retry_count = 0
    final_state: dict = {}
    for step_state in graph.stream(initial_state, config={"recursion_limit": 50}, stream_mode="values"):
        final_state = step_state
        retry_count = step_state.get("retry_count", 0)
        if retry_count > prev_retry_count:
            history.append(step_state.get("retry_error_code") or "UNKNOWN")
            prev_retry_count = retry_count

    return final_state, history


def _outcome(final_state: dict) -> str:
    success = (
        final_state.get("row_count") is not None
        and not final_state.get("execution_error")
        and final_state.get("retry_error_code") is None
    )
    if success and final_state.get("retry_count", 0) == 0:
        return "first_try_success"
    if success:
        return "corrected_by_retry"
    return "still_failed"


def run(
    domain: DomainConfig,
    limit: int | None = None,
    on_case: Callable[[int, int, str, str], None] | None = None,
) -> dict:
    """benchmark_queries.json 전체를 graph.stream()으로 돌려 재시도 귀인을 집계한다.

    on_case(index, total, question, outcome)가 있으면 항목이 끝날 때마다 호출한다(1-based index).
    """
    if not domain.benchmark_queries_path.is_file():
        return {"skipped": True, "reason": "benchmark_queries_missing", "total": 0}

    queries = json.loads(domain.benchmark_queries_path.read_text())
    if limit:
        queries = queries[:limit]
    if not queries:
        return {"skipped": True, "reason": "benchmark_queries_empty", "total": 0}

    graph = build_graph(domain)
    total = len(queries)

    outcome_counts: Counter = Counter()
    corrected_by_first_error: Counter = Counter()
    still_failed_by_first_error: Counter = Counter()

    for i, q in enumerate(queries, start=1):
        run_id = str(uuid.uuid4())
        final_state, history = _run_with_history(graph, domain.name, q["question"], run_id)
        outcome = _outcome(final_state)
        outcome_counts[outcome] += 1
        first_error = history[0] if history else None

        if outcome == "corrected_by_retry" and first_error:
            corrected_by_first_error[first_error] += 1
        elif outcome == "still_failed" and first_error:
            still_failed_by_first_error[first_error] += 1

        run_logger.log(
            run_id=run_id,
            domain=domain.name,
            question=q["question"],
            status="success" if outcome != "still_failed" else "error",
            retries=final_state.get("retry_count", 0),
            sql=final_state.get("sql"),
            tags={
                "experiment": "self_correction_ablation",
                "outcome": outcome,
                "first_error_code": first_error,
                "error_history": history,
            },
        )

        if on_case:
            on_case(i, total, q["question"], outcome)

    return {
        "skipped": False,
        "reason": None,
        "total": total,
        "outcomes": dict(outcome_counts),
        "corrected_by_first_error": dict(corrected_by_first_error),
        "still_failed_by_first_error": dict(still_failed_by_first_error),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--limit", type=int, default=None, help="검사할 질문 수 제한(기본 전체)")
    args = parser.parse_args()

    domain = get_domain(args.domain)

    def on_case(i: int, total: int, question: str, outcome: str) -> None:
        print(f"  [{outcome}] ({i}/{total}) {question}")

    result = run(domain, limit=args.limit, on_case=on_case)

    if result["skipped"]:
        if result["reason"] == "benchmark_queries_missing":
            print(f"[{args.domain}] benchmark_queries.json 없음 ({domain.benchmark_queries_path}) — 스킵")
        else:
            print("benchmark_queries.json이 비어있습니다.")
        return

    total = result["total"]
    outcome_counts = result["outcomes"]
    corrected_by_first_error = result["corrected_by_first_error"]
    still_failed_by_first_error = result["still_failed_by_first_error"]

    print(f"\nSelf-Correction 귀인 (n={total}):")
    for outcome in ("first_try_success", "corrected_by_retry", "still_failed"):
        count = outcome_counts.get(outcome, 0)
        print(f"  {outcome}: {count}/{total} ({count / total:.1%})")

    if corrected_by_first_error:
        print("\n  재시도로 고쳐진 실패 유형별 건수:")
        for code, count in sorted(corrected_by_first_error.items(), key=lambda kv: -kv[1]):
            total_for_code = count + still_failed_by_first_error.get(code, 0)
            print(f"    {code}: {count}/{total_for_code} 교정됨")

    if still_failed_by_first_error:
        remaining = {c: n for c, n in still_failed_by_first_error.items() if c not in corrected_by_first_error}
        if remaining:
            print("\n  재시도로도 못 고친 실패 유형별 건수:")
            for code, count in remaining.items():
                print(f"    {code}: {count}건")


if __name__ == "__main__":
    main()
