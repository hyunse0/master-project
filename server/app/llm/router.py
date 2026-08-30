"""난이도(difficulty)별 저비용/고성능 모델 분기.

intent 노드가 GraphState.difficulty(easy/medium/hard)를 채운 뒤에 오는 LLM 호출
(sql_generation, execution의 응답 요약)만 이 라우터를 거친다 — intent 자신은 아직
difficulty를 모르는 시점이라 항상 저비용 모델을 고정으로 쓴다(app/graph/build.py).

LLM_CHAT_DEPLOYMENT_HIGH를 아직 설정하지 않았다면 LOW와 동일한 배포로 폴백한다 —
라우팅 구조 자체는 동작하되 실제 모델 분기 효과는 없는 상태이며, 게이트웨이에
등록된 고성능 배포명이 정해지면 .env에 채우기만 하면 된다.
"""
import os

from app.llm.azure_openai_client import AzureOpenAIChatClient
from app.llm.base import TokenCountingLLM

# medium을 hard가 아니라 easy 쪽에 붙인 이유: 모델 티어가 2단계뿐이고 이 기능의 목적이
# 비용 절감이라, 극단값(hard)만 고성능으로 승격하고 나머지는 기본적으로 저비용 쪽에 둔다.
_TIER_BY_DIFFICULTY = {"easy": "low", "medium": "low", "hard": "high"}


def _low_deployment() -> str:
    return os.environ.get("LLM_CHAT_DEPLOYMENT_LOW", os.environ.get("LLM_CHAT_DEPLOYMENT", "gpt-4.1-mini"))


def _high_deployment() -> str:
    return os.environ.get("LLM_CHAT_DEPLOYMENT_HIGH", _low_deployment())


def build_llm_router() -> dict[str, TokenCountingLLM]:
    """difficulty 문자열로 바로 조회 가능한 {"easy": low_llm, "medium": low_llm, "hard": high_llm}."""
    low = TokenCountingLLM(AzureOpenAIChatClient(_low_deployment()))
    high = TokenCountingLLM(AzureOpenAIChatClient(_high_deployment()))
    tier_client = {"low": low, "high": high}
    return {difficulty: tier_client[tier] for difficulty, tier in _TIER_BY_DIFFICULTY.items()}


def select_llm(llm_router: dict[str, TokenCountingLLM], difficulty: str | None) -> TokenCountingLLM:
    return llm_router.get(difficulty or "medium", llm_router["medium"])
