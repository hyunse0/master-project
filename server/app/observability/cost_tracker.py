"""노드별 LLM 호출 토큰 사용량을 app-db token_usage 테이블에 기록한다.

trace(계획 문서 section 5.6)와 같은 이유로 GraphState 밖에서 추적한다 — 다만 trace는
프로세스 인메모리 버퍼로 충분하지만, 토큰/비용은 "이 기능을 추가했더니 좋아졌다"는 KPI
자료의 원천이라 프로세스 재시작 후에도 남아야 해서 처음부터 DB에 쓴다.

tags가 비교의 핵심 — 예: {"schema_rag_mode": "rag"} vs {"schema_rag_mode": "full_dump"}로
같은 질의를 태깅해 실행하면, GROUP BY tags->>'schema_rag_mode'로 바로 전/후 비교가 된다.
"""
import json
import logging

from app.db.app_db import get_app_db_connection

logger = logging.getLogger(__name__)


def record(
    run_id:        str,
    node:          str,
    model:         str,
    input_tokens:  int,
    output_tokens: int,
    tags:          dict | None = None,
) -> None:
    conn = get_app_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO token_usage (run_id, node, model, input_tokens, output_tokens, tags)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (run_id, node, model, input_tokens, output_tokens, json.dumps(tags or {})),
            )
    except Exception as e:
        # 계측 실패로 파이프라인 자체가 죽으면 안 됨 — 로그만 남기고 계속 진행
        logger.warning("token_usage 기록 실패: %s", e)
    finally:
        conn.close()


def get_run_usage(run_id: str) -> list[dict]:
    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT node, model, input_tokens, output_tokens, tags, created_at
                FROM token_usage WHERE run_id = %s ORDER BY created_at
                """,
                (run_id,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()
