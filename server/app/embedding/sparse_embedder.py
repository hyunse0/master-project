"""로컬 BM25 스파스 벡터 생성기 — Qdrant 하이브리드(dense+sparse) 검색의 sparse 축.

OpenAI 게이트웨이를 쓰는 EmbeddingEngine(dense)과 달리 네트워크 호출이 없다 — fastembed의
Qdrant/bm25는 룰 기반 용어 빈도 계산이라(신경망 아님) 로컬에서 즉시 계산된다. 첫 호출 시
토크나이저/불용어 리소스를 HuggingFace Hub에서 한 번 내려받아 로컬에 캐시한다.

색인 시엔 embed()(문서 가중치 포함), 검색 시엔 query_embed()(가중치 없는 순수 용어 빈도)를
쓴다 — IDF는 Qdrant 컬렉션의 SparseVectorParams(modifier=Modifier.IDF)가 색인된 데이터
통계로 서버 사이드에서 계산하므로, 클라이언트가 IDF 통계를 따로 저장/동기화할 필요가 없다.
"""
import logging

from fastembed import SparseTextEmbedding
from qdrant_client.models import SparseVector

logger = logging.getLogger(__name__)

MODEL_NAME = "Qdrant/bm25"


class SparseEmbedder:
    def __init__(self):
        self._model = SparseTextEmbedding(model_name=MODEL_NAME)
        logger.info("SparseEmbedder 초기화 완료 (model=%s)", MODEL_NAME)

    def embed_documents(self, texts: list[str]) -> list[SparseVector]:
        if not texts:
            return []
        return [
            SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
            for e in self._model.embed(texts)
        ]

    def embed_query(self, text: str) -> SparseVector:
        e = next(self._model.query_embed([text]))
        return SparseVector(indices=e.indices.tolist(), values=e.values.tolist())
