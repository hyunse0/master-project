"""질문에 관련된 테이블을 찾아 schema_text를 확정한다.

KPI 비교용 토글: tags["schema_rag_mode"] == "full_dump"이면 Qdrant 검색을 건너뛰고
전체 스키마를 그대로 덤프한다 — "스키마 RAG 검색 도입 전"을 코드로 재현 가능하게 유지하기
위한 것으로, eval/token_cost_comparison.py가 두 모드를 오가며 토큰 사용량을 비교한다.
"""
import logging

from qdrant_client import QdrantClient

from app.domain.loader import DomainConfig
from app.embedding.embedder import EmbeddingEngine
from app.graph.state import GraphState
from app.sql.schema_provider import SchemaProvider

logger = logging.getLogger(__name__)

_TOP_N_TABLES = 5


def make_schema_linking_node(
    domain: DomainConfig,
    embedder: EmbeddingEngine,
    qdrant_client: QdrantClient,
    schema_provider: SchemaProvider,
):
    def schema_linking_node(state: GraphState) -> dict:
        tags = state.get("tags") or {}
        mode = tags.get("schema_rag_mode", "rag")

        if mode == "full_dump":
            logger.info("  [schema_linking] full_dump 모드 — 전체 스키마 덤프")
            schema_text = schema_provider.get_schema_text(target_tables=None)
            return {"schema_candidates": [], "schema_text": schema_text}

        query_text = state["question"]
        if state.get("intent"):
            query_text = f'{state["question"]}\n의도: {state["intent"]}'
        embedding = embedder.embed(query_text)

        candidates: list[str] = []
        candidate_details: list[dict] = []
        if qdrant_client.collection_exists(domain.qdrant_schema_collection):
            result = qdrant_client.query_points(
                collection_name=domain.qdrant_schema_collection,
                query=embedding,
                limit=_TOP_N_TABLES,
                with_payload=True,
            )
            for p in result.points:
                if not p.payload:
                    continue
                candidates.append(p.payload["table"])
                candidate_details.append({
                    "table": p.payload["table"],
                    "comment": p.payload.get("comment"),
                    "score": round(float(p.score), 4),
                    "columns": p.payload.get("columns", []),
                    "text": p.payload.get("text", ""),
                })
        else:
            logger.warning(
                "  [schema_linking] 스키마 컬렉션(%s) 없음 — full_dump로 폴백",
                domain.qdrant_schema_collection,
            )

        target_tables = candidates or None
        schema_text = schema_provider.get_schema_text(target_tables=target_tables)
        logger.info("  [schema_linking] rag 모드 — 후보 테이블=%s", candidates)
        return {
            "schema_candidates": candidates,
            "schema_candidate_details": candidate_details,
            "schema_text": schema_text,
        }

    return schema_linking_node
