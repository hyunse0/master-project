import hashlib
import logging
import os

from openai import AzureOpenAI

logger = logging.getLogger(__name__)

_CACHE_MAXSIZE = 512


class EmbeddingEngine:
    """SK AI Talent Lab LLM 게이트웨이(Azure OpenAI 호환)의 임베딩 모델 래퍼.

    도메인/DB 엔진과 무관 — schema_indexer, retriever, schema_linking_node가 공통으로 쓴다.
    이전엔 로컬 BAAI/bge-m3(sentence-transformers)였으나 게이트웨이의 text-embedding-3-small로
    교체됐다(1024차원 → 1536차원, 기존 Qdrant 컬렉션은 재색인 필요).
    """

    def __init__(self, deployment: str | None = None):
        self.model_name = deployment or os.environ.get("LLM_EMBEDDING_DEPLOYMENT", "text-embedding-3-small")
        self.client = AzureOpenAI(
            azure_endpoint=os.environ.get("LLM_GATEWAY_BASE_URL", ""),
            api_version=os.environ.get("LLM_GATEWAY_API_VERSION", "2024-12-01-preview"),
            api_key=os.environ.get("LLM_GATEWAY_API_KEY", ""),
        )
        self._cache: dict[str, tuple[float, ...]] = {}
        logger.info("EmbeddingEngine 초기화 완료 (model=%s, cache=%d)", self.model_name, _CACHE_MAXSIZE)

    def _cache_key(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def _evict_and_store(self, key: str, vector: tuple[float, ...]) -> None:
        if len(self._cache) >= _CACHE_MAXSIZE:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = vector

    def embed(self, text: str) -> list[float]:
        key = self._cache_key(text)
        if key in self._cache:
            return list(self._cache[key])

        try:
            response = self.client.embeddings.create(model=self.model_name, input=text)
        except Exception as e:
            raise RuntimeError(f"임베딩 게이트웨이 호출 실패 (model={self.model_name}): {e}") from e

        vector = tuple(response.data[0].embedding)
        self._evict_and_store(key, vector)
        return list(vector)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self.client.embeddings.create(model=self.model_name, input=texts)
        except Exception as e:
            raise RuntimeError(f"임베딩 게이트웨이 호출 실패 (model={self.model_name}): {e}") from e

        vectors = [d.embedding for d in response.data]
        for text, vector in zip(texts, vectors):
            self._evict_and_store(self._cache_key(text), tuple(vector))
        return vectors

    def cache_info(self) -> str:
        return f"size={len(self._cache)}/{_CACHE_MAXSIZE}"
