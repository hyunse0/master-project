import logging
from functools import lru_cache

import torch
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)


class EmbeddingEngine:
    """한국어 지원 다국어 임베딩 모델 래퍼. 도메인/DB 엔진과 무관 — 그대로 재사용."""

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model = SentenceTransformer(model_name, device=device)
        self._cached_encode = lru_cache(maxsize=512)(self._raw_encode)
        logger.info("EmbeddingEngine 초기화 완료 (model=%s, device=%s, cache=512)", model_name, device)

    def _raw_encode(self, text: str) -> tuple[float, ...]:
        return tuple(self.model.encode(text, normalize_embeddings=True).tolist())

    def embed(self, text: str) -> list[float]:
        return list(self._cached_encode(text))

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self.model.encode(texts, normalize_embeddings=True, batch_size=128).tolist()

    def cache_info(self) -> str:
        info = self._cached_encode.cache_info()
        return f"hits={info.hits} misses={info.misses} size={info.currsize}/{info.maxsize}"
