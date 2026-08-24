import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extensions import connection as PgConnection

SERVER_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(SERVER_ROOT / ".env")


def get_app_db_connection() -> PgConnection:
    """앱 자체 운영 DB(run 레지스트리, LangGraph 체크포인트) 접속.

    타겟 도메인 DB(app/domain/loader.py가 다루는 접속 정보)와는 별개 —
    도메인이 바뀌거나 외부 DB로 교체돼도 이 접속 정보는 고정이다.
    """
    return psycopg2.connect(
        host=os.environ.get("APP_DB_HOST", "localhost"),
        port=int(os.environ.get("APP_DB_PORT", "5433")),
        dbname=os.environ.get("APP_DB_NAME", "nl2sql_app"),
        user=os.environ.get("APP_DB_USER", "postgres"),
        password=os.environ.get("APP_DB_PASSWORD", "postgres"),
    )
