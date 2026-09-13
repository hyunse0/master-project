"""게이트웨이 배포명 선택을 app-db `model_config`(싱글톤 행)에서 읽고 쓴다.

router.py/embedder.py가 클라이언트를 만들 때마다 조회한다 — 그래프는 도메인당 한 번
빌드돼 캐싱되므로(app/api/run_routes.py `_graph_cache`), 값을 바꾼 뒤 반영하려면
그 캐시를 비워야 한다(set_model_config가 호출자에게 그 책임을 위임한다).
"""
from app.db.app_db import get_app_db_connection

CHAT_OPTIONS = ["gpt-4.1", "gpt-4.1-mini", "gpt-4o", "gpt-4o-mini", "gpt-5", "gpt-5-mini", "gpt-5.4", "gpt-5.6-luna"]
EMBEDDING_OPTIONS = ["text-embedding-3-large", "text-embedding-3-small", "text-embedding-ada-002"]

_FIELDS = ("chat_low", "chat_high", "chat_judge", "embedding")


def get_model_config() -> dict[str, str | None]:
    """DB에 저장된 값만 반환(없으면 전부 None) — .env 폴백은 호출자(router.py 등)가 담당."""
    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f"SELECT {', '.join(_FIELDS)} FROM model_config WHERE id = 1")
            row = cur.fetchone()
            if not row:
                return dict.fromkeys(_FIELDS)
            return dict(zip(_FIELDS, row))
    finally:
        conn.close()


def set_model_config(**fields: str | None) -> dict[str, str | None]:
    """넘어온 필드만 갱신(부분 업데이트) — 나머지는 기존 값 유지. 유효하지 않은 배포명은 거부."""
    unknown = set(fields) - set(_FIELDS)
    if unknown:
        raise ValueError(f"알 수 없는 필드: {unknown}")
    for key, value in fields.items():
        if value is None:
            continue
        options = EMBEDDING_OPTIONS if key == "embedding" else CHAT_OPTIONS
        if value not in options:
            raise ValueError(f"{key}에 허용되지 않는 값: {value} (허용: {options})")

    conn = get_app_db_connection()
    try:
        with conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_config (id, chat_low, chat_high, chat_judge, embedding)
                VALUES (1, %(chat_low)s, %(chat_high)s, %(chat_judge)s, %(embedding)s)
                ON CONFLICT (id) DO UPDATE SET
                    chat_low   = COALESCE(EXCLUDED.chat_low,   model_config.chat_low),
                    chat_high  = COALESCE(EXCLUDED.chat_high,  model_config.chat_high),
                    chat_judge = COALESCE(EXCLUDED.chat_judge, model_config.chat_judge),
                    embedding  = COALESCE(EXCLUDED.embedding,  model_config.embedding),
                    updated_at = now()
                """,
                {f: fields.get(f) for f in _FIELDS},
            )
    finally:
        conn.close()
    return get_model_config()
