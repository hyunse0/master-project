import hashlib
import logging
import os
import time
from collections.abc import Iterator

from openai import AzureOpenAI

logger = logging.getLogger(__name__)

_LLM_CACHE_MAXSIZE = 128


class AzureOpenAIChatClient:
    """SK AI Talent Lab LLM 게이트웨이(Azure OpenAI 호환) 채팅 모델 클라이언트.

    generate_with_usage()가 app/llm/base.py의 TokenCountingLLM이 요구하는 인터페이스 —
    이 클라이언트를 다른 게이트웨이/vLLM으로 교체해도 그래프 노드는 손댈 필요 없다.
    """

    def __init__(self, deployment: str | None = None):
        self.model_name = deployment or os.environ.get("LLM_CHAT_DEPLOYMENT", "gpt-4.1-mini")
        self.client = AzureOpenAI(
            azure_endpoint=os.environ.get("LLM_GATEWAY_BASE_URL", ""),
            api_version=os.environ.get("LLM_GATEWAY_API_VERSION", "2024-12-01-preview"),
            api_key=os.environ.get("LLM_GATEWAY_API_KEY", ""),
        )
        self._cache: dict[str, tuple[str, int, int]] = {}  # md5(prompt) → (answer, input_tokens, output_tokens)
        logger.info("AzureOpenAIChatClient 초기화 완료 (model=%s, cache=%d)", self.model_name, _LLM_CACHE_MAXSIZE)

    def health(self) -> bool:
        return bool(os.environ.get("LLM_GATEWAY_API_KEY"))

    def _cache_key(self, prompt: str) -> str:
        return hashlib.md5(prompt.encode()).hexdigest()

    def _evict_and_store(self, key: str, value: tuple[str, int, int]) -> None:
        if len(self._cache) >= _LLM_CACHE_MAXSIZE:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = value

    def generate(self, prompt: str) -> str:
        return self.generate_with_usage(prompt)[0]

    def generate_with_usage(self, prompt: str) -> tuple[str, int, int]:
        """(answer, input_tokens, output_tokens)를 반환한다. 캐시 히트 시에도 원 호출의
        토큰 수를 그대로 반환 — 캐싱으로 인한 실비용 절감과 별개로, 이 프롬프트를 생성하는 데
        "설계상" 필요한 토큰 수를 KPI 비교에 일관되게 반영하기 위함."""
        cache_key = self._cache_key(prompt)

        if cache_key in self._cache:
            logger.info("LLM 캐시 히트 (key=%s...)", cache_key[:8])
            return self._cache[cache_key]

        logger.info("LLM 호출 시작 (model=%s, prompt_len=%d자)", self.model_name, len(prompt))
        t = time.time()
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as e:
            raise RuntimeError(f"LLM 게이트웨이 호출 실패 (model={self.model_name}): {e}") from e
        elapsed = time.time() - t

        answer = response.choices[0].message.content or ""
        usage = response.usage
        input_tokens = (usage.prompt_tokens or 0) if usage else 0
        output_tokens = (usage.completion_tokens or 0) if usage else 0
        logger.info(
            "LLM 호출 완료 (%.2fs, 응답 %d자, in=%d out=%d)",
            elapsed, len(answer), input_tokens, output_tokens,
        )

        result = (answer, input_tokens, output_tokens)
        self._evict_and_store(cache_key, result)
        return result

    def generate_stream(self, prompt: str) -> Iterator[str]:
        """청크 단위로 텍스트를 yield한다. 완료 후 캐시에 저장."""
        cache_key = self._cache_key(prompt)
        if cache_key in self._cache:
            logger.info("LLM 캐시 히트 (stream) (key=%s...)", cache_key[:8])
            yield self._cache[cache_key][0]
            return

        logger.info("LLM 스트리밍 시작 (model=%s, prompt_len=%d자)", self.model_name, len(prompt))
        t = time.time()
        chunks: list[str] = []
        input_tokens = output_tokens = 0
        try:
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
                stream_options={"include_usage": True},
            )
            for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    chunks.append(text)
                    yield text
                if getattr(chunk, "usage", None):
                    input_tokens = chunk.usage.prompt_tokens or 0
                    output_tokens = chunk.usage.completion_tokens or 0
        except Exception as e:
            raise RuntimeError(f"LLM 게이트웨이 스트리밍 호출 실패 (model={self.model_name}): {e}") from e

        assembled = "".join(chunks)
        elapsed = time.time() - t
        logger.info("LLM 스트리밍 완료 (%.2fs, 응답 %d자)", elapsed, len(assembled))
        self._evict_and_store(cache_key, (assembled, input_tokens, output_tokens))

    def cache_info(self) -> dict:
        return {"size": len(self._cache), "maxsize": _LLM_CACHE_MAXSIZE}
