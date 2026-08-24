"""도메인 접속정보를 domain_connections 테이블에 등록(또는 갱신)한다.
비밀번호는 저장 전 app/db/encryption.py로 암호화된다.

사용:
  python scripts/register_domain.py --name poc_prostate --host localhost --port 5432 \\
      --dbname poc_prostate --user postgres --password postgres --schemas poc [--activate]

--activate를 주면 이 도메인을 활성 도메인으로 만들고(다른 행은 자동으로 비활성화),
에이전트는 항상 활성 도메인 하나만 사용한다.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.db.app_db import get_app_db_connection  # noqa: E402
from app.db.encryption import encrypt_secret  # noqa: E402
from app.domain.loader import DOMAINS_ROOT  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--dbname", required=True)
    parser.add_argument("--user", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--schemas", default="public", help="콤마 구분, 예: poc,poc_mart")
    parser.add_argument("--activate", action="store_true", default=True)
    args = parser.parse_args()

    schemas = [s.strip() for s in args.schemas.split(",") if s.strip()]
    password_enc = encrypt_secret(args.password)

    conn = get_app_db_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                if args.activate:
                    cur.execute("UPDATE domain_connections SET is_active = false WHERE name != %s", (args.name,))
                cur.execute(
                    """
                    INSERT INTO domain_connections (name, db_host, db_port, db_name, db_user, db_password_enc, db_schemas, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        db_host = EXCLUDED.db_host,
                        db_port = EXCLUDED.db_port,
                        db_name = EXCLUDED.db_name,
                        db_user = EXCLUDED.db_user,
                        db_password_enc = EXCLUDED.db_password_enc,
                        db_schemas = EXCLUDED.db_schemas,
                        is_active = EXCLUDED.is_active,
                        updated_at = now()
                    """,
                    (args.name, args.host, args.port, args.dbname, args.user, password_enc, schemas, args.activate),
                )
        pack_dir = DOMAINS_ROOT / args.name
        pack_dir.mkdir(parents=True, exist_ok=True)
        print(f"등록 완료: {args.name} ({'활성' if args.activate else '비활성'}), 도메인 팩: {pack_dir}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
