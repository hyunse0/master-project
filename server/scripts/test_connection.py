"""DB 접속 + 스키마 introspection이 실제로 동작하는지 확인한다.
사용: python scripts/test_connection.py --domain <domain_name>
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import get_domain  # noqa: E402
from app.sql.schema_provider import SchemaProvider  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    domain = get_domain(args.domain)
    c = domain.connection
    print(f"[{domain.name}] {c.user}@{c.host}:{c.port}/{c.dbname}  schemas={c.allowed_schemas}")

    provider = SchemaProvider(c)
    print("연결 테스트:", "OK" if provider.test_connection() else "FAIL")

    tables = provider.get_table_names()
    print(f"테이블 {len(tables)}개: {tables}")

    if tables:
        schema, table = tables[0].split(".", 1)
        info = provider.get_table_info(schema, table)
        print(f"\n--- {info.full_name} introspection 결과 ---")
        print(provider.table_to_text(info))


if __name__ == "__main__":
    main()
