from dataclasses import dataclass
from pathlib import Path

from app.db.app_db import get_app_db_connection
from app.db.encryption import decrypt_secret

SERVER_ROOT = Path(__file__).resolve().parents[2]
DOMAINS_ROOT = SERVER_ROOT / "domains"


@dataclass
class PostgresConnection:
    host: str
    port: int
    dbname: str
    user: str
    password: str
    allowed_schemas: list[str]


@dataclass
class DomainConfig:
    name: str
    root: Path
    connection: PostgresConnection
    qdrant_schema_collection: str
    qdrant_fewshot_collection: str

    @property
    def ddl_path(self) -> Path:
        return self.root / "ddl.sql"

    @property
    def synthetic_data_path(self) -> Path:
        return self.root / "synthetic_data.py"

    @property
    def few_shot_path(self) -> Path:
        return self.root / "few_shot.json"

    @property
    def golden_set_path(self) -> Path:
        return self.root / "golden_set.json"

    @property
    def prompt_fragments_path(self) -> Path:
        return self.root / "prompt_fragments.yaml"


def _fetch_connection_row(name: str | None) -> dict | None:
    """domain_connections에서 접속정보를 읽는다. name이 없으면 활성 도메인(is_active) 하나를 찾는다.

    실서비스 접속정보는 사용자가 화면으로 입력해 이 테이블에 저장되는 값이라 .env로 관리하지 않는다
    (scripts/register_domain.py로 등록/교체).
    """
    conn = get_app_db_connection()
    try:
        with conn.cursor() as cur:
            if name:
                cur.execute(
                    "SELECT name, db_host, db_port, db_name, db_user, db_password_enc, db_schemas "
                    "FROM domain_connections WHERE name = %s",
                    (name,),
                )
            else:
                cur.execute(
                    "SELECT name, db_host, db_port, db_name, db_user, db_password_enc, db_schemas "
                    "FROM domain_connections WHERE is_active LIMIT 1"
                )
            row = cur.fetchone()
            if row is None:
                return None
            columns = [d[0] for d in cur.description]
            return dict(zip(columns, row))
    finally:
        conn.close()


def get_domain(name: str | None = None) -> DomainConfig:
    """접속정보로 domain_connections에서, 도메인 팩 경로는 domains/<name>/ 에서 찾는다.

    name을 안 주면 활성 도메인(domain_connections.is_active) 하나를 사용한다 — 에이전트가
    동시에 쓰는 도메인은 항상 최대 1개(DB 유니크 제약으로 보장).
    스키마 자체는 여기서 읽지 않는다 — 실제 introspection은 schema_provider.py가
    이 접속 정보를 받아 연결 시점에 수행한다.
    """
    row = _fetch_connection_row(name)
    if row is None:
        if name:
            raise ValueError(f"등록된 도메인이 없습니다: {name} — scripts/register_domain.py로 먼저 등록하세요.")
        raise ValueError("활성화된 도메인이 없습니다 — scripts/register_domain.py로 도메인을 등록하고 활성화하세요.")

    domain = row["name"]
    root = DOMAINS_ROOT / domain
    if not root.is_dir():
        available = [p.name for p in DOMAINS_ROOT.iterdir() if p.is_dir()] if DOMAINS_ROOT.is_dir() else []
        raise ValueError(
            f"도메인 팩을 찾을 수 없습니다: {root} (사용 가능한 도메인: {available})"
        )

    connection = PostgresConnection(
        host=row["db_host"],
        port=row["db_port"],
        dbname=row["db_name"],
        user=row["db_user"],
        password=decrypt_secret(row["db_password_enc"]),
        allowed_schemas=list(row["db_schemas"]),
    )

    return DomainConfig(
        name=domain,
        root=root,
        connection=connection,
        qdrant_schema_collection=f"schema_{domain}",
        qdrant_fewshot_collection=f"sql_knowledge_{domain}",
    )
