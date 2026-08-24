"""자동 모드(interrupt 없음) 동기 실행 엔드포인트.

C(human-in-the-loop)의 실제 POST /runs(비동기 + PostgresSaver 체크포인트 + resume)가
구현되기 전까지의 임시 엔드포인트 — scripts/run_graph_cli.py와 같은 로직을 HTTP로 감싼 것.
스키마/SQL 검토 인터럽트는 아직 없어 review_config는 항상 무시하고 끝까지 실행한다.
"""
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.domain.loader import get_domain
from app.graph.build import build_graph
from app.observability import run_logger

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])

_graph_cache: dict[str, object] = {}


def _get_graph(domain_name: str):
    if domain_name not in _graph_cache:
        domain = get_domain(domain_name)
        _graph_cache[domain_name] = build_graph(domain)
    return _graph_cache[domain_name]


class RunRequest(BaseModel):
    question: str
    domain: str | None = None


@router.post("")
def create_run(body: RunRequest) -> dict:
    try:
        domain = get_domain(body.domain)
    except ValueError as e:
        raise HTTPException(400, str(e))

    try:
        graph = _get_graph(domain.name)
    except Exception as e:
        raise HTTPException(502, f"그래프 초기화 실패: {e}")

    run_id = str(uuid.uuid4())
    tags = {"schema_rag_mode": "rag", "max_retries": 2, "experiment": "ui"}

    t0 = time.time()
    try:
        final_state = graph.invoke(
            {
                "question": body.question,
                "domain": domain.name,
                "run_id": run_id,
                "tags": tags,
                "review_config": {"schema": False, "sql": False},
            },
            config={"recursion_limit": 50},
        )
    except Exception as e:
        logger.exception("run 실행 실패")
        raise HTTPException(502, f"파이프라인 실행 실패: {e}")
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
        question=body.question,
        status=status,
        error_code=error_code,
        retries=final_state.get("retry_count", 0),
        row_count=final_state.get("row_count"),
        sql=final_state.get("sql"),
        latency_ms=latency_ms,
        tags=tags,
    )

    return {
        "run_id": run_id,
        "status": status,
        "domain": domain.name,
        "question": body.question,
        "difficulty": final_state.get("difficulty"),
        "task_type": final_state.get("task_type"),
        "schema_candidates": final_state.get("schema_candidates") or [],
        "schema_candidate_details": final_state.get("schema_candidate_details") or [],
        "confirmed_schema": final_state.get("confirmed_schema") or [],
        "sql": final_state.get("sql"),
        "columns": final_state.get("columns") or [],
        "rows": final_state.get("rows") or [],
        "row_count": final_state.get("row_count"),
        "summary": final_state.get("summary"),
        "execution_error": execution_error,
        "retry_error_code": error_code,
        "retry_feedback": final_state.get("retry_feedback"),
        "retries": final_state.get("retry_count", 0),
        "max_retries": tags["max_retries"],
        "latency_ms": latency_ms,
    }
