"""자연어 질문을 분류해 task_type/metric/dimensions/time_range/난이도/질의유형을 추출한다.

rag-practice/server/retrieval/router.py의 "pipeline: sql" 분기 JSON 스키마만 이식했다 —
이 앱은 SQL 전용이라 chat/rag/refuse 파이프라인 분기는 가져오지 않았다. difficulty 필드는
Tier1(토큰 이코노미·난이도별 모델 라우팅) 요구사항으로, query_type 필드는 Tier2(멀티에이전트
확장 — sql_generation의 유형별 서브에이전트 분기) 요구사항으로 추가됐다.
"""
import json
import logging
import re
import uuid

from app.graph.state import GraphState
from app.llm.base import TokenCountingLLM

logger = logging.getLogger(__name__)

_INTENT_PROMPT = """\
당신은 임상 데이터 조회 시스템의 질의 분류기입니다.
사용자 질문을 분석하여 아래 JSON 형식만 반환하세요. 설명이나 마크다운 없이 JSON만.

{{
  "intent": "질문 의도를 영어 키워드로 간략히 요약 (예: count patients by surgery method)",
  "task_type": "count" | "sum" | "avg" | "min" | "max" | "list" | "trend" | "distribution" | "comparison" | "unknown",
  "metric": "조회하려는 핵심 지표를 영어 snake_case로 작성 (예: patient_count, avg_psa). 없으면 빈 문자열",
  "dimensions": ["그룹핑 기준을 영어 snake_case로. 없으면 빈 배열"],
  "time_range": {{
    "from": "YYYY-MM-DD 또는 null",
    "to":   "YYYY-MM-DD 또는 null",
    "grain": "day" | "month" | "year" | "none"
  }},
  "difficulty": "질의 복잡도 — 자연어 질문 자체의 난이도가 아니라 예상되는 SQL 작성 복잡도 기준. 아래 기준으로 분류:
    easy   — 단일 테이블 단순 집계/조회 (예: 총 환자 수)
    medium — 그룹핑·필터가 있는 조회, 2개 이하 테이블 조인
    hard   — 3개 이상 테이블 조인, 서브쿼리, 코호트 정의, 복합 조건",
  "query_type": "질의 유형 — 아래 기준으로 분류:
    aggregate — 집계 함수/GROUP BY가 필요한 질문 (건수, 평균, 합계, 분포, 비율)
    list      — 조건에 맞는 개별 레코드를 나열/조회하는 질문
    cohort    — 여러 포함/제외 조건을 조합해 특정 대상군(예: 환자군)을 정의하는 질문"
}}

사용자 질문: {query}
"""


def make_intent_node(llm: TokenCountingLLM):
    def intent_node(state: GraphState) -> dict:
        run_id = state.get("run_id") or str(uuid.uuid4())
        tags = state.get("tags") or {}

        prompt = _INTENT_PROMPT.format(query=state["question"])
        try:
            raw = llm.generate(prompt, run_id=run_id, node="intent", tags=tags)
            data = _parse(raw)
            intent_status, intent_error = "success", None
        except Exception as e:
            logger.warning("[run=%s] intent 분류 실패 → 기본값 fallback: %s", run_id, e)
            data = {}
            intent_status, intent_error = "fallback", str(e)

        time_range = data.get("time_range") or {}
        time_range = (
            {k: v for k, v in time_range.items() if k in ("from", "to", "grain")}
            if (time_range.get("from") or time_range.get("to"))
            else {}
        )

        return {
            "run_id": run_id,
            "tags": tags,
            "intent": data.get("intent", "general"),
            "task_type": data.get("task_type", "unknown"),
            "metric": data.get("metric", ""),
            "dimensions": data.get("dimensions", []),
            "time_range": time_range,
            "difficulty": data.get("difficulty", "medium"),
            "query_type": data.get("query_type", "list"),
            "intent_status": intent_status,
            "intent_error": intent_error,
            "retry_count": 0,
        }

    return intent_node


def _parse(raw: str) -> dict:
    text = re.sub(r"```(?:json)?|```", "", raw).strip()
    return json.loads(text)
