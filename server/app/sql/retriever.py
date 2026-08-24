import logging
from dataclasses import dataclass

from app.knowledge.qdrant_store import QdrantFewShotStore, SqlKnowledgeEntry

logger = logging.getLogger(__name__)

_W_SEMANTIC = 0.5
_W_TABLE    = 0.3
_W_DOMAIN   = 0.2


@dataclass
class RetrievedExample:
    entry:          SqlKnowledgeEntry
    score:          float
    semantic_score: float
    table_score:    float
    domain_score:   float


class SqlRetriever:
    """sql_knowledge에서 Few-shot 예제를 하이브리드 스코어로 검색한다.

    score = 0.5×semantic + 0.3×table_overlap + 0.2×domain_match
    """

    def __init__(self, store: QdrantFewShotStore, k_candidates: int = 20):
        self._store       = store
        self._k_candidates = k_candidates

    def retrieve(
        self,
        embedding:    list[float],
        query_tables: list[str],
        query_domain: str,
        top_k:        int = 3,
    ) -> list[RetrievedExample]:
        """하이브리드 스코어 상위 top_k 예제를 반환한다.

        Args:
            embedding:    build_embedding_text() 결과를 임베딩한 벡터
            query_tables: 질문에서 예상되는 테이블 목록
            query_domain: 질문 도메인 (연결된 도메인명)
            top_k:        반환할 예제 수
        """
        candidates = self._store.search_nearest(embedding, k=self._k_candidates)
        if not candidates:
            return []

        results: list[RetrievedExample] = []
        for entry, sem_score in candidates:
            tbl_score = _jaccard(query_tables, entry.tables)
            dom_score = 1.0 if entry.domain == query_domain else 0.0
            hybrid    = _W_SEMANTIC * sem_score + _W_TABLE * tbl_score + _W_DOMAIN * dom_score
            results.append(
                RetrievedExample(
                    entry=entry,
                    score=hybrid,
                    semantic_score=sem_score,
                    table_score=tbl_score,
                    domain_score=dom_score,
                )
            )

        results.sort(key=lambda r: r.score, reverse=True)
        logger.debug(
            "retrieve: top=%d  scores=%s",
            top_k,
            [(r.entry.question[:20], round(r.score, 3)) for r in results[:top_k]],
        )
        return results[:top_k]


def _jaccard(a: list[str], b: list[str]) -> float:
    """Jaccard 유사도. 둘 다 비어있으면 0."""
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 0.0
    union = sa | sb
    return len(sa & sb) / len(union) if union else 0.0
