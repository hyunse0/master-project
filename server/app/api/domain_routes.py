from fastapi import APIRouter, HTTPException

from app.domain.loader import DomainConfig, get_domain
from app.embedding.embedder import EmbeddingEngine
from app.knowledge.qdrant_connection import get_qdrant_client
from app.sql.schema_provider import SchemaProvider

router = APIRouter(prefix="/domain", tags=["domain"])

_embedder: EmbeddingEngine | None = None


def _get_embedder() -> EmbeddingEngine:
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingEngine()
    return _embedder


def _active_domain() -> DomainConfig:
    """활성 도메인(domain_connections.is_active)을 가져온다. 등록된 게 없으면 400."""
    try:
        return get_domain()
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/status")
def domain_status():
    domain = _active_domain()
    provider = SchemaProvider(domain.connection)
    try:
        connected = provider.test_connection()
        error = None
    except Exception as e:
        connected = False
        error = str(e)
    return {
        "domain": domain.name,
        "connected": connected,
        "error": error,
        "host": domain.connection.host,
        "port": domain.connection.port,
        "dbname": domain.connection.dbname,
        "schemas": domain.connection.allowed_schemas,
    }


@router.get("/tables")
def list_tables():
    domain = _active_domain()
    provider = SchemaProvider(domain.connection)
    tables = provider.get_all_tables()
    return [
        {
            "table": t.full_name,
            "schema": t.schema,
            "name": t.name,
            "comment": t.comment,
            "column_count": len(t.columns),
        }
        for t in tables
    ]


@router.get("/tables/{table_name:path}")
def table_detail(table_name: str):
    domain = _active_domain()
    provider = SchemaProvider(domain.connection)

    if "." in table_name:
        schema, name = table_name.split(".", 1)
    else:
        schema = domain.connection.allowed_schemas[0] if domain.connection.allowed_schemas else "public"
        name = table_name

    info = provider.get_table_info(schema, name)
    if not info.columns:
        raise HTTPException(404, f"테이블을 찾을 수 없습니다: {schema}.{name}")

    return {
        "table": info.full_name,
        "comment": info.comment,
        "columns": [
            {"name": c.name, "type": c.data_type, "comment": c.comment, "is_primary_key": c.is_primary_key}
            for c in info.columns
        ],
        "foreign_keys": [
            {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column}
            for fk in info.foreign_keys
        ],
    }


@router.get("/schema-search")
def schema_search(q: str, limit: int = 5):
    domain = _active_domain()
    embedder = _get_embedder()
    client = get_qdrant_client()

    vector = embedder.embed(q)
    results = client.query_points(
        collection_name=domain.qdrant_schema_collection, query=vector, limit=limit
    ).points

    return [
        {
            "table": r.payload["table"],
            "comment": r.payload.get("comment"),
            "score": r.score,
            "columns": r.payload.get("columns", []),
        }
        for r in results
    ]
