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


def create(run_id: str, domain: str, question: str, review_config: dict) -> None:
    conn = get_app_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO runs (run_id, domain, question, review_config, status)
                VALUES (%s, %s, %s, %s::jsonb, 'running')
                """,
                (run_id, domain, question, json.dumps(review_config)),
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
                "SELECT status, domain, question, review_config, state_snapshot FROM runs WHERE run_id = %s",
                (run_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()

    if row is None:
        return None
    status, domain, question, review_config, state_snapshot = row
    return {
        "status": status,
        "domain": domain,
        "question": question,
        "review_config": review_config,
        "state_snapshot": state_snapshot,
    }
