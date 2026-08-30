"""human-in-the-loop 실행 엔드포인트.

POST /runs와 POST /runs/{id}/resume은 동기 호출이다 — graph.invoke()가 다음 interrupt
지점 또는 그래프 종료까지 블로킹하고, 그 시점의 상태를 그대로 응답으로 돌려준다(계획 문서
section 5.7 — SSE 스트리밍은 보류된 설계 결정). review_config.schema/sql이 둘 다 꺼져
있으면 interrupt를 한 번도 타지 않으므로 기존 자동 모드와 동일하게 한 번의 POST /runs
호출로 끝까지 실행된다.

GET /runs/{id}는 LangGraph 체크포인터를 다시 읽지 않고 run_manager가 캐싱해둔 마지막
응답(state_snapshot)만 반환한다 — 새로고침/재접속 시 현재 run 상태를 다시 읽기 위한 것.

GET /runs(목록)도 같은 이유로 체크포인터 대신 runs 레지스트리만 읽는다 — 실행 히스토리
화면의 목록/필터/검색용이며, 상세는 클릭 시 GET /runs/{id}로 별도 조회한다.
"""
import logging
import time
import uuid

from fastapi import APIRouter, HTTPException
from langgraph.types import Command
from pydantic import BaseModel

from app.domain.loader import get_domain
from app.graph.build import build_graph
from app.graph.checkpointer import get_checkpointer
from app.observability import run_logger
from app.runs import run_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])

_graph_cache: dict[str, object] = {}

_DEFAULT_TAGS = {"schema_rag_mode": "rag", "max_retries": 2, "experiment": "ui"}
_DEFAULT_REVIEW_CONFIG = {"schema": False, "sql": False}


def _get_graph(domain_name: str):
    if domain_name not in _graph_cache:
        domain = get_domain(domain_name)
        _graph_cache[domain_name] = build_graph(domain, checkpointer=get_checkpointer())
    return _graph_cache[domain_name]


def _thread_config(run_id: str) -> dict:
    return {"configurable": {"thread_id": f"nl2sql-{run_id}"}, "recursion_limit": 50}


def _mark_crashed(run_id: str, domain_name: str, question: str, review_config: dict, error: Exception) -> None:
    """graph.invoke()가 예외로 죽었을 때 registry가 'running'에 영원히 멈춰있지 않도록
    최소한의 error 스냅샷을 남긴다 — GET /runs/{id}가 그대로 실패 사실을 보여줄 수 있게."""
    run_manager.save_snapshot(
        run_id,
        "error",
        {
            "run_id": run_id, "status": "error", "domain": domain_name, "question": question,
            "review_config": review_config,
            "difficulty": None, "task_type": None,
            "schema_candidates": [], "schema_candidate_details": [], "confirmed_schema": [],
            "sql": None, "columns": [], "rows": [], "row_count": None, "summary": None,
            "execution_error": str(error),
            "retry_error_code": None, "retry_feedback": None,
            "retries": 0, "max_retries": _DEFAULT_TAGS["max_retries"], "latency_ms": None,
            "sql_edited": False, "sql_before_edit": None, "correction_reason": None,
        },
    )


def _finalize(
    graph,
    run_id: str,
    domain_name: str,
    question: str,
    review_config: dict,
    tags: dict,
    latency_ms: int,
    sql_edited: bool = False,
    sql_before_edit: str | None = None,
    correction_reason: str | None = None,
) -> dict:
    snapshot = graph.get_state(_thread_config(run_id))
    values = snapshot.values

    if snapshot.next:
        next_node = snapshot.next[0]
        status = "interrupted_schema" if next_node == "schema_review" else "interrupted_sql"
    else:
        error_code = values.get("retry_error_code")
        execution_error = values.get("execution_error")
        status = (
            "success"
            if (values.get("row_count") is not None and not execution_error and error_code is None)
            else "error"
        )
        run_logger.log(
            run_id=run_id,
            domain=domain_name,
            question=question,
            status=status,
            error_code=error_code,
            retries=values.get("retry_count", 0),
            row_count=values.get("row_count"),
            sql=values.get("sql"),
            latency_ms=latency_ms,
            tags=tags,
        )

    response = {
        "run_id": run_id,
        "status": status,
        "domain": domain_name,
        "question": question,
        "review_config": review_config,
        "difficulty": values.get("difficulty"),
        "task_type": values.get("task_type"),
        "schema_candidates": values.get("schema_candidates") or [],
        "schema_candidate_details": values.get("schema_candidate_details") or [],
        "confirmed_schema": values.get("confirmed_schema") or [],
        "sql": values.get("sql"),
        "columns": values.get("columns") or [],
        "rows": values.get("rows") or [],
        "row_count": values.get("row_count"),
        "summary": values.get("summary"),
        "execution_error": values.get("execution_error"),
        "retry_error_code": values.get("retry_error_code"),
        "retry_feedback": values.get("retry_feedback"),
        "retries": values.get("retry_count", 0),
        "max_retries": tags["max_retries"],
        "latency_ms": latency_ms,
        "sql_edited": sql_edited,
        "sql_before_edit": sql_before_edit,
        "correction_reason": correction_reason,
    }
    run_manager.save_snapshot(run_id, status, response)
    return response


class RunRequest(BaseModel):
    question: str
    domain: str | None = None
    review_config: dict | None = None


class ResumeRequest(BaseModel):
    confirmed_schema: list[str] | None = None
    sql: str | None = None
    # sql_review에서 사람이 SQL을 직접 고쳤을 때만 의미가 있다 — 왜 고쳤는지는 diff만으로는
    # 알 수 없는 도메인 지식이라 사람이 직접 남겨야 나중에 few-shot 큐레이션에 쓸모가 있다.
    correction_reason: str | None = None


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
    review_config = body.review_config or _DEFAULT_REVIEW_CONFIG
    tags = _DEFAULT_TAGS

    run_manager.create(run_id, domain.name, body.question, review_config)

    t0 = time.time()
    try:
        graph.invoke(
            {
                "question": body.question,
                "domain": domain.name,
                "run_id": run_id,
                "tags": tags,
                "review_config": review_config,
            },
            config=_thread_config(run_id),
        )
    except Exception as e:
        logger.exception("run 실행 실패")
        _mark_crashed(run_id, domain.name, body.question, review_config, e)
        raise HTTPException(502, f"파이프라인 실행 실패: {e}")
    latency_ms = int((time.time() - t0) * 1000)

    return _finalize(graph, run_id, domain.name, body.question, review_config, tags, latency_ms)


@router.get("")
def list_runs(
    domain: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 20,
    before: str | None = None,
) -> dict:
    return run_manager.list_runs(domain=domain, status=status, q=q, limit=limit, before=before)


@router.get("/{run_id}")
def get_run(run_id: str) -> dict:
    row = run_manager.get(run_id)
    if row is None:
        raise HTTPException(404, "run을 찾을 수 없습니다")
    return row["state_snapshot"]


@router.post("/{run_id}/resume")
def resume_run(run_id: str, body: ResumeRequest) -> dict:
    row = run_manager.get(run_id)
    if row is None:
        raise HTTPException(404, "run을 찾을 수 없습니다")
    if row["status"] not in ("interrupted_schema", "interrupted_sql"):
        raise HTTPException(409, f"run이 검토 대기 상태가 아닙니다 (status={row['status']})")

    try:
        domain = get_domain(row["domain"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    graph = _get_graph(domain.name)

    sql_edited = False
    sql_before_edit = None
    if row["status"] == "interrupted_schema":
        if body.confirmed_schema is None:
            raise HTTPException(400, "confirmed_schema가 필요합니다")
        resume_value = body.confirmed_schema
    else:
        if body.sql is None:
            raise HTTPException(400, "sql이 필요합니다")
        resume_value = body.sql
        # 검토 화면에 떠 있던 SQL(생성 직후 스냅샷)과 실제로 제출된 SQL이 다르면 사람이 직접
        # 고친 것 — 원본은 이 라운드가 끝나면 최종 sql에 덮어써져 사라지므로 여기서 따로
        # 보존해둔다(few-shot 큐레이션에서 "AI가 뭐라고 짰었는지" before/after로 봐야 하므로).
        sql_before_edit = row["state_snapshot"].get("sql")
        sql_edited = body.sql != sql_before_edit

    t0 = time.time()
    try:
        graph.invoke(Command(resume=resume_value), config=_thread_config(run_id))
    except Exception as e:
        logger.exception("run resume 실패")
        _mark_crashed(run_id, row["domain"], row["question"], row["review_config"], e)
        raise HTTPException(502, f"resume 실패: {e}")
    latency_ms = int((time.time() - t0) * 1000)

    return _finalize(
        graph, run_id, row["domain"], row["question"], row["review_config"], _DEFAULT_TAGS, latency_ms,
        sql_edited=sql_edited,
        sql_before_edit=sql_before_edit if sql_edited else None,
        correction_reason=body.correction_reason if sql_edited else None,
    )


@router.get("/{run_id}/trace")
def get_run_trace(run_id: str) -> dict:
    row = run_manager.get(run_id)
    if row is None:
        raise HTTPException(404, "run을 찾을 수 없습니다")

    try:
        domain = get_domain(row["domain"])
        graph = _get_graph(domain.name)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # get_state_history()는 최신순으로 반환한다. 각 스냅샷의 tasks는 "이 체크포인트에서
    # 다음에 실행될 노드"이므로(langgraph 1.2 기준 metadata에 writes가 없음), 시간순으로
    # 정렬한 뒤 next_node로 노출한다 — "이 스냅샷을 만든 노드"가 아니라 "이 스냅샷 다음에
    # 실행된/될 노드"라는 의미를 정확히 반영한 이름이다.
    history = list(graph.get_state_history(_thread_config(run_id)))
    steps = [
        {
            "step": snap.metadata.get("step"),
            "next_node": snap.tasks[0].name if snap.tasks else None,
            "retry_count": snap.values.get("retry_count", 0),
            "retry_error_code": snap.values.get("retry_error_code"),
            "created_at": snap.created_at,
        }
        for snap in reversed(history)
    ]
    return {"run_id": run_id, "steps": steps}
