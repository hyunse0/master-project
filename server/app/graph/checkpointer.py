"""LangGraph 체크포인터 — schema_review/sql_review의 interrupt()가 멈춘 상태를 영속화한다.

app-db(타겟 도메인 DB와 별개, 고정 운영 DB)에 연결. rag-practice/server/api/dependencies.py의
get_chat_checkpointer() 패턴을 그대로 이식 — psycopg(v3) ConnectionPool + PostgresSaver,
싱글턴으로 재사용한다. 체크포인트 테이블(checkpoints/checkpoint_writes/checkpoint_blobs)은
schema.sql에 포함하지 않고 setup()이 최초 호출 시 자동 생성한다.
"""
from typing import Optional

from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.db.app_db import get_app_db_conninfo

_checkpointer: Optional[PostgresSaver] = None


def get_checkpointer() -> PostgresSaver:
    global _checkpointer
    if _checkpointer is None:
        pool = ConnectionPool(
            conninfo=get_app_db_conninfo(),
            max_size=10,
            kwargs={"autocommit": True, "row_factory": dict_row},
            open=True,
        )
        _checkpointer = PostgresSaver(pool)
        _checkpointer.setup()
    return _checkpointer
