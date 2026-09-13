"""난이도(difficulty)별 저비용/고성능 모델 분기.

intent 노드가 GraphState.difficulty(easy/medium/hard)를 채운 뒤에 오는 LLM 호출
(sql_generation, execution의 응답 요약)만 이 라우터를 거친다 — intent 자신은 아직
difficulty를 모르는 시점이라 항상 저비용 모델을 고정으로 쓴다(app/graph/build.py).

LLM_CHAT_DEPLOYMENT_HIGH를 아직 설정하지 않았다면 LOW와 동일한 배포로 폴백한다 —
라우팅 구조 자체는 동작하되 실제 모델 분기 효과는 없는 상태이며, 게이트웨이에
등록된 고성능 배포명이 정해지면 .env에 채우기만 하면 된다.

배포명은 app-db `model_config`(비용 대시보드 화면에서 사용자가 선택)가 있으면 그 값을
우선하고, 없으면 .env 기본값으로 폴백한다 — domain_connections와 같은 "런타임에
사용자가 바꾸는 값은 DB, 정적 인프라 값은 .env" 원칙.
"""
import os

from app.llm.azure_openai_client import AzureOpenAIChatClient
from app.llm.base import TokenCountingLLM
from app.llm.model_config import get_model_config

# medium을 hard가 아니라 easy 쪽에 붙인 이유: 모델 티어가 2단계뿐이고 이 기능의 목적이
# 비용 절감이라, 극단값(hard)만 고성능으로 승격하고 나머지는 기본적으로 저비용 쪽에 둔다.
_TIER_BY_DIFFICULTY = {"easy": "low", "medium": "low", "hard": "high"}


def _low_deployment() -> str:
    configured = get_model_config()["chat_low"]
    return configured or os.environ.get("LLM_CHAT_DEPLOYMENT_LOW", os.environ.get("LLM_CHAT_DEPLOYMENT", "gpt-4.1-mini"))


def _high_deployment() -> str:
    configured = get_model_config()["chat_high"]
    return configured or os.environ.get("LLM_CHAT_DEPLOYMENT_HIGH", _low_deployment())


def build_llm_router() -> dict[str, TokenCountingLLM]:
    """difficulty 문자열로 바로 조회 가능한 {"easy": low_llm, "medium": low_llm, "hard": high_llm}."""
    low = TokenCountingLLM(AzureOpenAIChatClient(_low_deployment()))
    high = TokenCountingLLM(AzureOpenAIChatClient(_high_deployment()))
    tier_client = {"low": low, "high": high}
    return {difficulty: tier_client[tier] for difficulty, tier in _TIER_BY_DIFFICULTY.items()}


def build_judge_llm() -> TokenCountingLLM:
    """eval judge(LLM-as-a-judge) 전용 클라이언트. LOW/HIGH 생성 모델과 항상 다른 배포를
    써야 한다 — 같은 모델이 자기 결과를 채점하면 판정이 후해진다는 게 관찰된 문제라
    (docs/kpi-experiment-log.md 참고), 생성 티어와 분리된 배포를 둔다."""
    configured = get_model_config()["chat_judge"]
    deployment = configured or os.environ.get("LLM_JUDGE_DEPLOYMENT", "gpt-4o-mini")
    return TokenCountingLLM(AzureOpenAIChatClient(deployment))


def select_llm(
    llm_router:   dict[str, TokenCountingLLM],
    difficulty:   str | None,
    routing_mode: str = "on",
) -> TokenCountingLLM:
    """routing_mode="off"면 난이도 무관하게 저비용 모델(medium 티어)로 고정한다 —
    eval/token_cost_comparison.py --compare routing_mode=on,off로 라우팅 자체의
    비용-정확도 효과를 측정하기 위한 토글(계획 문서 H단계)."""
    if routing_mode == "off":
        return llm_router["medium"]
    return llm_router.get(difficulty or "medium", llm_router["medium"])
