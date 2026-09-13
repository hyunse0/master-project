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
    cohort    — 여러 포함/제외 조건을 조합해 특정 대상군(예: 환자군)을 정의하는 질문",
  "needs_clarification": "질문 자체가 여러 방식으로 해석 가능하거나 핵심 조건(기준 시점, 비교 대상,
    지표 정의 등)이 빠져 있어 사람마다 다른 SQL을 만들 수 있을 때만 true. 최대한 합리적인 기본값을
    스스로 가정하고, 위 [이전 턴]으로 해소되는 생략 표현은 모호하다고 보지 마세요. 정말 필요할 때만 true",
  "clarification_question": "needs_clarification이 true일 때만 채움 — 사용자에게 되물을 한국어 질문
    한 문장. false면 빈 문자열"
}}

{context_block}사용자 질문: {query}
"""


def _build_context_block(prior_turns: list[dict] | None) -> str:
    """멀티턴(F단계) — 직전 턴 정보를 프롬프트에 얹는다. "그중", "거기에" 같은 생략·대용
    표현은 직전 턴 맥락 없이는 분류 자체가 불가능하므로, prior_turns가 있을 때만 이 블록을
    채운다(없으면 빈 문자열이라 기존 싱글턴 동작과 완전히 동일)."""
    if not prior_turns:
        return ""
    prev = prior_turns[-1]
    lines = [f"- 이전 질문: {prev['question']}"]
    if prev.get("confirmed_schema"):
        lines.append(f"- 이전에 사용한 테이블: {', '.join(prev['confirmed_schema'])}")
    if prev.get("summary"):
        lines.append(f"- 이전 결과 요약: {prev['summary']}")
    body = "\n".join(lines)
    return (
        "[이전 턴 — 지금 질문이 여기 이어지는 후속 질문일 수 있습니다. "
        '"그중"/"거기에"/"그 환자들" 같은 표현은 아래 이전 턴을 기준으로 해석하세요]\n'
        f"{body}\n\n"
    )


def make_intent_node(llm: TokenCountingLLM):
    def intent_node(state: GraphState) -> dict:
        run_id = state.get("run_id") or str(uuid.uuid4())
        tags = state.get("tags") or {}

        # intent_clarification_node가 재개시킨 재분류 패스 — 사용자 답변을 질문에 합쳐서
        # 다시 분류한다. 아래 return에서 clarification_answer를 명시적으로 None으로 되돌려야
        # (LangGraph는 반환에 없는 키는 이전 값을 유지) intent_clarification_node가 이번
        # 패스를 "이미 처리됨"으로 보고 schema_linking으로 그대로 흘려보낸다.
        question = state["question"]
        clarification_answer = state.get("clarification_answer")
        if clarification_answer:
            question = f"{question}\n[추가 답변] {clarification_answer}"

        context_block = _build_context_block(state.get("prior_turns"))
        prompt = _INTENT_PROMPT.format(query=question, context_block=context_block)
        try:
            raw = llm.generate(prompt, run_id=run_id, node="intent", tags=tags)
            data = _parse(raw)
            intent_status, intent_error = "success", None
            logger.info(
                "질의 분류 완료 · difficulty=%s query_type=%s task_type=%s",
                data.get("difficulty"), data.get("query_type"), data.get("task_type"),
            )
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
            "question": question,
            "intent": data.get("intent", "general"),
            "task_type": data.get("task_type", "unknown"),
            "metric": data.get("metric", ""),
            "dimensions": data.get("dimensions", []),
            "time_range": time_range,
            "difficulty": data.get("difficulty", "medium"),
            "query_type": data.get("query_type", "list"),
            "intent_status": intent_status,
            "intent_error": intent_error,
            "needs_clarification": bool(data.get("needs_clarification")),
            "clarification_question": data.get("clarification_question") or None,
            "clarification_answer": None,
            "retry_count": 0,
        }

    return intent_node


def _parse(raw: str) -> dict:
    text = re.sub(r"```(?:json)?|```", "", raw).strip()
    return json.loads(text)
