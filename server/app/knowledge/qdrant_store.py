"""few-shot(sql_knowledge) 저장소 — rag-practice의 psycopg2+pgvector 구현을 Qdrant로 교체.

SqlKnowledgeEntry 데이터클래스와 add()/search_nearest() 시그니처는 원본과 동일하게 유지해
app/sql/retriever.py를 손대지 않고 그대로 재사용할 수 있게 한다.
"""
import logging
import uuid
from dataclasses import dataclass, field

from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from app.knowledge.qdrant_connection import get_qdrant_client

logger = logging.getLogger(__name__)


@dataclass
class SqlKnowledgeEntry:
    question: str
    intent: str
    canonical_sql: str
    tables: list[str] = field(default_factory=list)
    metrics: list[str] = field(default_factory=list)
    domain: str = "general"
    embedding: list[float] | None = None
    id: str | None = None


class QdrantFewShotStore:
    """sql_knowledge_{domain} 컬렉션의 CRUD 및 벡터 검색을 담당한다."""

    def __init__(self, collection_name: str):
        self._collection = collection_name
        self._client = get_qdrant_client()

    def _ensure_collection(self, vector_size: int) -> None:
        if self._client.collection_exists(self._collection):
            existing_size = self._client.get_collection(self._collection).config.params.vectors.size
            if existing_size == vector_size:
                return
            logger.warning(
                "  [qdrant_store] %s 차원 불일치(기존=%d, 신규=%d) — 임베딩 모델이 바뀐 것으로 보고 "
                "컬렉션을 재생성합니다(기존 데이터는 사라짐, 재시딩 필요)",
                self._collection, existing_size, vector_size,
            )
            self._client.delete_collection(self._collection)

        self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )

    def add(self, entry: SqlKnowledgeEntry, embedding: list[float]) -> str:
        """항목을 저장하고 생성된 UUID를 반환한다."""
        self._ensure_collection(len(embedding))
        entry_id = entry.id or str(uuid.uuid4())
        point = PointStruct(
            id=entry_id,
            vector=embedding,
            payload={
                "question": entry.question,
                "intent": entry.intent,
                "canonical_sql": entry.canonical_sql,
                "tables": entry.tables,
                "metrics": entry.metrics,
                "domain": entry.domain,
            },
        )
        self._client.upsert(collection_name=self._collection, points=[point])
        logger.debug("sql_knowledge added: collection=%s id=%s", self._collection, entry_id)
        return entry_id

    def delete(self, entry_id: str) -> bool:
        if not self._client.collection_exists(self._collection):
            return False
        self._client.delete(collection_name=self._collection, points_selector=[entry_id])
        return True

    def list_all(self, domain: str | None = None) -> list[SqlKnowledgeEntry]:
        if not self._client.collection_exists(self._collection):
            return []
        query_filter = (
            Filter(must=[FieldCondition(key="domain", match=MatchValue(value=domain))])
            if domain else None
        )
        points, _ = self._client.scroll(
            collection_name=self._collection, scroll_filter=query_filter, limit=1000,
        )
        return [_point_to_entry(p.id, p.payload) for p in points]

    def search_nearest(
        self,
        embedding: list[float],
        k: int = 10,
    ) -> list[tuple[SqlKnowledgeEntry, float]]:
        """벡터 코사인 유사도 기준 상위 k개를 반환한다.

        반환값: [(entry, cosine_similarity)] — 유사도 높은 순 정렬.
        컬렉션이 아직 없으면(시딩 전) 빈 리스트를 반환한다 — retriever.py가 이를 신경 쓰지
        않아도 되도록 여기서 흡수한다.
        """
        if not self._client.collection_exists(self._collection):
            return []

        result = self._client.query_points(
            collection_name=self._collection,
            query=embedding,
            limit=k,
            with_payload=True,
        )
        return [(_point_to_entry(p.id, p.payload), float(p.score)) for p in result.points]


def _point_to_entry(point_id, payload: dict) -> SqlKnowledgeEntry:
    return SqlKnowledgeEntry(
        id=str(point_id),
        question=payload.get("question", ""),
        intent=payload.get("intent", ""),
        canonical_sql=payload.get("canonical_sql", ""),
        tables=payload.get("tables") or [],
        metrics=payload.get("metrics") or [],
        domain=payload.get("domain", "general"),
        embedding=None,
    )
