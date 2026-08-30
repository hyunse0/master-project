"""graph.invoke()를 CLI에서 직접 호출해 자동 모드 파이프라인을 확인한다.
사용: python scripts/run_graph_cli.py --domain poc_prostate --question "전립선암 환자는 총 몇 명인가요?"
      [--schema-rag-mode rag|full_dump] [--routing-mode on|off] [--max-retries 2] [--experiment <태그>]
"""
import argparse
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import get_domain  # noqa: E402
from app.graph.build import build_graph  # noqa: E402
from app.observability import run_logger  # noqa: E402


def run_once(domain_name: str, question: str, tags: dict, graph=None):
    domain = get_domain(domain_name)
    if graph is None:
        graph = build_graph(domain)

    run_id = str(uuid.uuid4())
    initial_state = {
        "question": question,
        "domain": domain.name,
        "run_id": run_id,
        "tags": tags,
        "review_config": {"schema": False, "sql": False},
    }

    t0 = time.time()
    final_state = graph.invoke(initial_state, config={"recursion_limit": 50})
    latency_ms = int((time.time() - t0) * 1000)

    error_code = final_state.get("retry_error_code")
    execution_error = final_state.get("execution_error")
    status = (
        "success"
        if (final_state.get("row_count") is not None and not execution_error and error_code is None)
        else "error"
    )

    run_logger.log(
        run_id=run_id,
        domain=domain.name,
        question=question,
        status=status,
        error_code=error_code,
        retries=final_state.get("retry_count", 0),
        row_count=final_state.get("row_count"),
        sql=final_state.get("sql"),
        latency_ms=latency_ms,
        tags=tags,
    )

    return final_state, status, latency_ms


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--schema-rag-mode", default="rag", choices=["rag", "full_dump"])
    parser.add_argument("--routing-mode", default="on", choices=["on", "off"])
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--experiment", default="cli")
    args = parser.parse_args()

    tags = {
        "schema_rag_mode": args.schema_rag_mode,
        "routing_mode": args.routing_mode,
        "max_retries": args.max_retries,
        "experiment": args.experiment,
    }
    final_state, status, latency_ms = run_once(args.domain, args.question, tags)

    print(f"\n=== status={status}  latency={latency_ms}ms  retries={final_state.get('retry_count', 0)} ===")
    print(f"difficulty={final_state.get('difficulty')}  query_type={final_state.get('query_type')}  task_type={final_state.get('task_type')}")
    print(f"schema_candidates={final_state.get('schema_candidates')}")
    print(f"\nSQL:\n{final_state.get('sql')}")
    if final_state.get("execution_error"):
        print(f"\nERROR: {final_state['execution_error']}")
    if final_state.get("retry_error_code"):
        print(f"\nretry_error_code={final_state['retry_error_code']}")
        print(f"retry_feedback={final_state.get('retry_feedback')}")
    print(f"\nrow_count={final_state.get('row_count')}")
    print(f"\n{final_state.get('summary', '')}")


if __name__ == "__main__":
    main()
