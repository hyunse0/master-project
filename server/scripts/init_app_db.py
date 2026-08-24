"""app-db에 스키마(schema.sql)를 적용한다. 여러 번 실행해도 안전(IF NOT EXISTS).
사용: python scripts/init_app_db.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.app_db import get_app_db_connection  # noqa: E402

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "app" / "db" / "schema.sql"


def main() -> None:
    sql = SCHEMA_PATH.read_text()
    conn = get_app_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(sql)
        print(f"app-db 스키마 적용 완료 ({SCHEMA_PATH})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
