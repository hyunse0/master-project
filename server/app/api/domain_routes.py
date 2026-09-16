from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from qdrant_client.models import FusionQuery, Prefetch, Fusion

from app.api.run_routes import clear_graph_cache
from app.domain import notes_store
from app.domain.loader import DomainConfig, get_domain
from app.embedding.embedder import EmbeddingEngine
from app.embedding.sparse_embedder import SparseEmbedder
from app.knowledge.qdrant_connection import get_qdrant_client
from app.knowledge.schema_indexer import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME, build_schema_index
from app.sql.schema_provider import SchemaProvider

router = APIRouter(prefix="/domain", tags=["domain"])

_embedder: EmbeddingEngine | None = None
_sparse_embedder: SparseEmbedder | None = None


def _get_embedder() -> EmbeddingEngine:
    global _embedder
    if _embedder is None:
        _embedder = EmbeddingEngine()
    return _embedder


def _get_sparse_embedder() -> SparseEmbedder:
    global _sparse_embedder
    if _sparse_embedder is None:
        _sparse_embedder = SparseEmbedder()
    return _sparse_embedder


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
    sparse_embedder = _get_sparse_embedder()
    client = get_qdrant_client()

    vector = embedder.embed(q)
    sparse_vector = sparse_embedder.embed_query(q)
    results = client.query_points(
        collection_name=domain.qdrant_schema_collection,
        prefetch=[
            Prefetch(query=vector, using=DENSE_VECTOR_NAME, limit=max(limit, 20)),
            Prefetch(query=sparse_vector, using=SPARSE_VECTOR_NAME, limit=max(limit, 20)),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=limit,
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


_NOTE_CATEGORIES = {"codeset", "join", "general"}


class DomainNoteCreate(BaseModel):
    table_name: str | None = None  # None이면 도메인 전체 공통 노트('join'은 항상 None)
    note: str
    category: str = "general"
    structured_data: dict | None = None  # 화면이 폼을 복원하기 위한 원본 구조 — codeset/join만 사용


class DomainNoteUpdate(BaseModel):
    note: str
    structured_data: dict | None = None


def _reindex_if_table_scoped(domain: DomainConfig, table_name: str | None) -> None:
    """테이블 전용 노트가 바뀌면 스키마 임베딩도 다시 만들어야 검색에 반영된다(EXP-017).
    일반 노트(table_name=None) — 'join'은 두 테이블에 걸쳐 있어 항상 여기 해당 — 는 임베딩과
    무관해 재색인이 필요 없다."""
    if table_name:
        build_schema_index(domain.name)


@router.get("/notes")
def list_domain_notes():
    domain = _active_domain()
    return notes_store.list_notes(domain.name)


@router.post("/notes")
def create_domain_note(body: DomainNoteCreate):
    domain = _active_domain()
    if not body.note.strip():
        raise HTTPException(400, "note는 비어 있을 수 없습니다.")
    if body.category not in _NOTE_CATEGORIES:
        raise HTTPException(400, f"알 수 없는 category: {body.category} (허용: {sorted(_NOTE_CATEGORIES)})")
    # join은 테이블 두 개에 걸친 관계라 table_name(단일 테이블) 컬럼과 결이 안 맞음 — 항상 None으로
    # 강제해 스키마 임베딩 재색인(테이블 하나에만 힌트를 붙이는 동작) 대상에서 빠지게 한다.
    table_name = None if body.category == "join" else body.table_name
    row = notes_store.create_note(domain.name, table_name, body.note.strip(), body.category, body.structured_data)
    _reindex_if_table_scoped(domain, table_name)
    clear_graph_cache()  # 다음 실행부터 새 노트가 프롬프트에 반영되도록 캐시된 그래프를 비운다
    return row


@router.put("/notes/{note_id}")
def update_domain_note(note_id: str, body: DomainNoteUpdate):
    domain = _active_domain()
    if not body.note.strip():
        raise HTTPException(400, "note는 비어 있을 수 없습니다.")
    row = notes_store.update_note(note_id, body.note.strip(), body.structured_data)
    if row is None:
        raise HTTPException(404, f"노트를 찾을 수 없습니다: {note_id}")
    _reindex_if_table_scoped(domain, row["table_name"])
    clear_graph_cache()
    return row


@router.delete("/notes/{note_id}")
def delete_domain_note(note_id: str):
    domain = _active_domain()
    existing = next((n for n in notes_store.list_notes(domain.name) if n["id"] == note_id), None)
    deleted = notes_store.delete_note(note_id)
    if not deleted:
        raise HTTPException(404, f"노트를 찾을 수 없습니다: {note_id}")
    if existing:
        _reindex_if_table_scoped(domain, existing["table_name"])
    clear_graph_cache()
    return {"deleted": True}
