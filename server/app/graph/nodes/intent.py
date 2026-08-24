"""자연어 질문을 분류해 task_type/metric/dimensions/time_range/난이도를 추출한다.

rag-practice/server/retrieval/router.py의 "pipeline: sql" 분기 JSON 스키마만 이식했다 —
이 앱은 SQL 전용이라 chat/rag/refuse 파이프라인 분기는 가져오지 않았다. difficulty 필드는
Tier1(토큰 이코노미·난이도별 모델 라우팅) 요구사항으로 새로 추가됐다.
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
  "table_hints": ["질문에 명시적으로 언급된 테이블/도메인 유사 표현. 없으면 빈 배열"],
  "difficulty": "질의 복잡도 — 아래 기준으로 분류:
    easy   — 단일 테이블 단순 집계/조회 (예: 총 환자 수)
    medium — 그룹핑·필터가 있는 조회, 2개 이하 테이블 조인
    hard   — 3개 이상 테이블 조인, 서브쿼리, 코호트 정의, 복합 조건"
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
        except Exception as e:
            logger.warning("intent 분류 실패 → 기본값 fallback: %s", e)
            data = {}

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
            "table_hints": data.get("table_hints", []),
            "difficulty": data.get("difficulty", "medium"),
            "retry_count": 0,
        }

    return intent_node


def _parse(raw: str) -> dict:
    text = re.sub(r"```(?:json)?|```", "", raw).strip()
    return json.loads(text)
