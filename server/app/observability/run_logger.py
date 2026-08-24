"""그래프 1회 실행(invoke)의 결과 요약을 app-db run_metrics 테이블에 기록한다.

노드마다 흩뿌리지 않고, 그래프 실행 진입점(CLI 스크립트/eval 스크립트, 나중엔 FastAPI 핸들러)
한 곳에서 graph.invoke() 리턴값으로 한 번만 호출한다.
"""
import json
import logging

from app.db.app_db import get_app_db_connection

logger = logging.getLogger(__name__)


def log(
    run_id:     str,
    domain:     str,
    question:   str,
    status:     str,
    *,
    error_code: str | None = None,
    retries:    int        = 0,
    row_count:  int | None = None,
    sql:        str | None = None,
    latency_ms: int | None = None,
    tags:       dict | None = None,
) -> None:
    conn = get_app_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO run_metrics
                    (run_id, domain, question, status, error_code, retries, row_count, sql, latency_ms, tags)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                """,
                (run_id, domain, question, status, error_code, retries, row_count, sql, latency_ms,
                 json.dumps(tags or {})),
            )
    except Exception as e:
        logger.warning("run_metrics 기록 실패: %s", e)
    finally:
        conn.close()
