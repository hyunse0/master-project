"""run 레지스트리 — run_id 존재 여부 확인 + 최신 상태 스냅샷 캐시.

진실은 PostgresSaver 체크포인트(app/graph/checkpointer.py)에 있고, 이 테이블은
① "존재하지 않는 run"과 "빈 상태"를 구분하고 ② GET /runs/{id}가 체크포인터를 다시
읽지 않고 빠르게 마지막 응답을 돌려줄 수 있도록 캐싱하는 역할이다
(data-access-copilot-plan.md section 5 3번 항목).
"""
import json
import logging

from app.db.app_db import get_app_db_connection

logger = logging.getLogger(__name__)


def create_conversation(domain: str) -> str:
    """새 대화(멀티턴 스레드)를 하나 발급한다 — "새 대화" 버튼 클릭 시 또는 conversation_id
    없이 POST /runs가 들어왔을 때(=대화의 첫 턴) 호출된다."""
    conn = get_app_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO conversations (domain) VALUES (%s) RETURNING conversation_id",
                (domain,),
            )
            return str(cur.fetchone()[0])
    finally:
        conn.close()


def create(
    run_id: str,
    domain: str,
    question: str,
    review_config: dict,
    *,
    conversation_id: str | None = None,
    turn_no: int = 1,
    parent_run_id: str | None = None,
) -> None:
    conn = get_app_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO runs (run_id, domain, question, review_config, status,
                                   conversation_id, turn_no, parent_run_id)
                VALUES (%s, %s, %s, %s::jsonb, 'running', %s, %s, %s)
                """,
                (run_id, domain, question, json.dumps(review_config), conversation_id, turn_no, parent_run_id),
            )
    finally:
        conn.close()


def save_snapshot(run_id: str, status: str, snapshot: dict) -> None:
    conn = get_app_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE runs SET status = %s, state_snapshot = %s::jsonb, updated_at = now()
                WHERE run_id = %s
                """,
                (status, json.dumps(snapshot), run_id),
            )
    finally:
        conn.close()


def get(run_id: str) -> dict | None:
    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status, domain, question, review_config, state_snapshot,
                       conversation_id, turn_no, parent_run_id
                FROM runs WHERE run_id = %s
                """,
                (run_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    status, domain, question, review_config, state_snapshot, conversation_id, turn_no, parent_run_id = row
    return {
        "status": status,
        "domain": domain,
        "question": question,
        "review_config": review_config,
        "state_snapshot": state_snapshot,
        "conversation_id": str(conversation_id) if conversation_id else None,
        "turn_no": turn_no,
        "parent_run_id": str(parent_run_id) if parent_run_id else None,
    }


def get_last_turn(conversation_id: str) -> dict | None:
    """대화의 가장 최근 턴(run) 하나를 turn_no 기준으로 가져온다 — 다음 턴을 만들 때
    prior_turns(직전 턴 컨텍스트)를 구성하는 데 쓰인다. 진행 중/검토 대기 중인 턴은
    아직 이어받을 확정 결과가 없으므로 호출부가 status를 보고 판단한다."""
    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, status, question, review_config, state_snapshot, turn_no
                FROM runs
                WHERE conversation_id = %s
                ORDER BY turn_no DESC
                LIMIT 1
                """,
                (conversation_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    run_id, status, question, review_config, state_snapshot, turn_no = row
    return {
        "run_id": str(run_id),
        "status": status,
        "question": question,
        "review_config": review_config,
        "state_snapshot": state_snapshot,
        "turn_no": turn_no,
    }


def list_conversation_turns(conversation_id: str) -> list[dict]:
    """대화 상세 화면(GET /conversations/{id})용 — 턴 순서대로 요약 필드만 반환한다.
    상세는 지금처럼 GET /runs/{id}로 턴 하나씩 따로 조회한다(list_runs와 같은 설계)."""
    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT run_id, turn_no, question, status, created_at, state_snapshot
                FROM runs
                WHERE conversation_id = %s
                ORDER BY turn_no ASC
                """,
                (conversation_id,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "run_id": str(run_id),
            "turn_no": turn_no,
            "question": question,
            "status": status,
            "created_at": created_at.isoformat(),
            "row_count": (state_snapshot or {}).get("row_count"),
            "latency_ms": (state_snapshot or {}).get("latency_ms"),
        }
        for run_id, turn_no, question, status, created_at, state_snapshot in rows
    ]


def list_runs(
    *,
    domain: str | None = None,
    status: str | None = None,
    q: str | None = None,
    limit: int = 20,
    before: str | None = None,
) -> dict:
    """실행 히스토리 목록. state_snapshot 전체가 아니라 목록에 필요한 필드만 뽑아서 돌려준다 —
    상세는 클릭 시 GET /runs/{id}로 따로 조회한다."""
    clauses: list[str] = []
    params: list = []
    if domain:
        clauses.append("domain = %s")
        params.append(domain)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if q:
        clauses.append("question ILIKE %s")
        params.append(f"%{q}%")
    if before:
        clauses.append("created_at < %s")
        params.append(before)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT run_id, domain, question, status, created_at, state_snapshot,
                       conversation_id, turn_no
                FROM runs
                {where}
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (*params, limit + 1),
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    has_more = len(rows) > limit
    rows = rows[:limit]
    runs = [
        {
            "run_id": str(run_id),
            "domain": domain_,
            "question": question,
            "status": status_,
            "created_at": created_at.isoformat(),
            "retries": (state_snapshot or {}).get("retries", 0),
            "row_count": (state_snapshot or {}).get("row_count"),
            "latency_ms": (state_snapshot or {}).get("latency_ms"),
            "conversation_id": str(conversation_id) if conversation_id else None,
            "turn_no": turn_no,
        }
        for run_id, domain_, question, status_, created_at, state_snapshot, conversation_id, turn_no in rows
    ]
    return {"runs": runs, "has_more": has_more}


def list_edited_sql_runs(domain: str | None = None) -> list[dict]:
    """사람이 SQL을 직접 고쳐서 승인한 run만 뽑는다 — scripts/curate_few_shot_from_history.py
    전용. sql_edited는 resume_run이 라운드마다 갱신하므로, 여기 나오는 건 항상 "최종적으로
    사람이 손댄 SQL"이지 재시도 도중 있었던 중간 수정까지 다 모으진 않는다."""
    clauses = ["state_snapshot->>'sql_edited' = 'true'"]
    params: list = []
    if domain:
        clauses.append("domain = %s")
        params.append(domain)
    where = f"WHERE {' AND '.join(clauses)}"

    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT run_id, domain, question, created_at, state_snapshot
                FROM runs
                {where}
                ORDER BY created_at DESC
                """,
                params,
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        {
            "run_id": str(run_id),
            "domain": domain_,
            "question": question,
            "created_at": created_at.isoformat(),
            "sql_before_edit": (state_snapshot or {}).get("sql_before_edit"),
            "sql": (state_snapshot or {}).get("sql"),
            "correction_reason": (state_snapshot or {}).get("correction_reason"),
            "confirmed_schema": (state_snapshot or {}).get("confirmed_schema") or [],
            "task_type": (state_snapshot or {}).get("task_type"),
        }
        for run_id, domain_, question, created_at, state_snapshot in rows
    ]
