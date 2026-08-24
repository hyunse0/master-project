"""LLM 클라이언트 공통 인터페이스 + 토큰 계측 래퍼.

그래프 노드는 이 모듈의 TokenCountingLLM만 사용한다 — 어떤 원시 클라이언트를 감쌌는지
(gemini_client.GeminiClient 등)는 신경 쓰지 않고, run_id/node/tags만 넘기면 호출마다
자동으로 app/observability/cost_tracker.py에 토큰 사용량이 기록된다.
"""
import logging
from collections.abc import Iterator
from typing import Protocol

from app.observability import cost_tracker

logger = logging.getLogger(__name__)


class RawLLMClient(Protocol):
    model_name: str

    def generate_with_usage(self, prompt: str) -> tuple[str, int, int]: ...
    def generate_stream(self, prompt: str) -> Iterator[str]: ...


class TokenCountingLLM:
    """RawLLMClient를 감싸 호출마다 토큰 사용량을 기록한다.

    run_id가 없으면(예: 아직 run 개념이 없는 CLI 임시 실행) 계측을 건너뛰고 그냥 통과한다.
    """

    def __init__(self, raw: RawLLMClient):
        self._raw = raw

    def generate(
        self,
        prompt: str,
        *,
        run_id: str | None = None,
        node:   str | None = None,
        tags:   dict | None = None,
    ) -> str:
        answer, input_tokens, output_tokens = self._raw.generate_with_usage(prompt)
        if run_id:
            cost_tracker.record(
                run_id=run_id,
                node=node or "unknown",
                model=self._raw.model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                tags=tags,
            )
        return answer

    def generate_stream(self, prompt: str) -> Iterator[str]:
        yield from self._raw.generate_stream(prompt)
