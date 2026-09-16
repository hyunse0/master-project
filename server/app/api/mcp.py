"""MCP 서버 노출 — 기존 FastAPI 도구 함수를 MCP tool로 얇게 래핑한다.

app.main에서 이 모듈의 `mcp_server`를 /mcp에 서브마운트한다(계획 문서 section 6, F그룹).
별도 프로세스 없이 기존 uvicorn 프로세스 안에서 도메인 접속/그래프/embedder 싱글톤을 그대로
재사용한다.

노출한 tool은 전부 읽기(스키마 조회/검색)이거나, 이미 검증 게이트(SqlValidator/schema
citation/value anchor)를 통과해야만 실행되는 경로(run_nl2sql_query)뿐이다 — raw SQL을
직접 실행하는 tool은 의도적으로 두지 않았다. 그 게이트를 우회하는 구멍을 만들지 않기 위해서다.
run_nl2sql_query는 review_config을 항상 {"schema": False, "sql": False}로 고정한다 —
단발 tool 호출로는 interrupt/resume을 받을 수 없어 human-in-the-loop 우회가 아니라 애초에
자동 모드만 지원한다.
"""
from mcp.server.mcpserver import MCPServer
from qdrant_client.models import FusionQuery, Prefetch, Fusion

from app.api import run_routes
from app.domain.loader import get_domain
from app.embedding.embedder import EmbeddingEngine
from app.embedding.sparse_embedder import SparseEmbedder
from app.knowledge.qdrant_connection import get_qdrant_client
from app.knowledge.qdrant_store import QdrantFewShotStore
from app.knowledge.schema_indexer import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME
from app.sql.retriever import SqlRetriever
from app.sql.schema_provider import SchemaProvider

mcp_server = MCPServer("data-access-copilot")

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


@mcp_server.tool()
def get_domain_status() -> dict:
    """현재 활성 도메인(domain_connections.is_active)의 접속 상태를 확인한다."""
    domain = get_domain()
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


@mcp_server.tool()
def list_tables() -> list[dict]:
    """활성 도메인의 전체 테이블 목록(이름/코멘트/컬럼 수)을 반환한다."""
    domain = get_domain()
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


@mcp_server.tool()
def get_table_detail(table_name: str) -> dict:
    """테이블 하나의 컬럼/PK/FK 상세 정보를 반환한다. table_name은 "schema.table" 또는 "table"."""
    domain = get_domain()
    provider = SchemaProvider(domain.connection)

    if "." in table_name:
        schema, name = table_name.split(".", 1)
    else:
        schema = domain.connection.allowed_schemas[0] if domain.connection.allowed_schemas else "public"
        name = table_name

    info = provider.get_table_info(schema, name)
    if not info.columns:
        raise ValueError(f"테이블을 찾을 수 없습니다: {schema}.{name}")

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


@mcp_server.tool()
def search_schema(query: str, limit: int = 5) -> list[dict]:
    """자연어 질의와 의미적으로 가까운 테이블을 스키마 인덱스(Qdrant schema_{domain})에서 검색한다."""
    domain = get_domain()
    embedder = _get_embedder()
    sparse_embedder = _get_sparse_embedder()
    client = get_qdrant_client()

    vector = embedder.embed(query)
    sparse_vector = sparse_embedder.embed_query(query)
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


@mcp_server.tool()
def search_few_shot_examples(question: str, top_k: int = 3, domain: str | None = None) -> list[dict]:
    """질문과 유사한 few-shot(질문→SQL) 예제를 검색한다. 참고 테이블 목록 없이 호출하므로
    하이브리드 스코어 중 semantic+domain 항만 반영되고 table_overlap 항은 0으로 처리된다."""
    resolved = get_domain(domain)
    embedder = _get_embedder()
    retriever = SqlRetriever(QdrantFewShotStore(resolved.qdrant_fewshot_collection))

    vector = embedder.embed(question)
    results = retriever.retrieve(vector, query_tables=[], query_domain=resolved.name, top_k=top_k)

    return [
        {
            "question": r.entry.question,
            "sql": r.entry.canonical_sql,
            "tables": r.entry.tables,
            "score": r.score,
        }
        for r in results
    ]


@mcp_server.tool()
def run_nl2sql_query(question: str, domain: str | None = None) -> dict:
    """자연어 질문을 SQL로 변환·검증·실행해 결과를 반환한다 — 자동 모드 고정(검토 인터럽트 없이
    한 번에 끝까지 실행). 내부적으로 스키마링킹→SQL생성→검증(SqlValidator/schema citation/
    value anchor)→실행을 전부 거치므로, MCP를 통한 SQL 실행 경로는 이 tool 하나뿐이다."""
    result = run_routes.execute_run(question, domain, {"schema": False, "sql": False})
    return {
        "run_id": result["run_id"],
        "status": result["status"],
        "domain": result["domain"],
        "sql": result["sql"],
        "columns": result["columns"],
        "rows": result["rows"],
        "row_count": result["row_count"],
        "summary": result["summary"],
        "execution_error": result["execution_error"],
    }
