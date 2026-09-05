"""스키마 후보 검토 노드.

review_config.schema가 꺼져 있으면(자동 모드) LLM이 schema_candidates 중 질문에 실제
필요한 테이블만 골라 confirmed_schema로 확정한다(EXP-005/EXP-006 — 실패 시 전체 후보를
그대로 유지하는 fail-safe). 켜져 있으면 interrupt()로 멈춘다 — schema_linking_node(작업,
LLM/DB 호출)와 분리해둔 이유가 여기 있다: interrupt() 재개 시 이 노드만 재실행되고
비용이 큰 schema_linking은 재실행되지 않는다(계획 문서 section 5.1).

두 경로 모두 최종 선택 결과로 schema_text를 다시 만들어 되돌린다 — 원래는 schema_linking이
만든 schema_text(원본 후보 전체)가 그대로 sql_generation까지 흘러가 confirmed_schema가
좁혀져도(사람이 검토했든 LLM이 골랐든) SQL 생성 프롬프트에는 반영되지 않는 공백이 있었다
(EXP-005에서 발견/수정). schema_text 재조립은 DB를 다시 조회하지 않고
schema_candidate_details[].text(schema_linking이 Qdrant payload에서 이미 가져온 테이블
렌더링, schema_indexer.py가 색인 시점에 만들어둔 값)를 그대로 이어붙인다 — schema_linking
단계에서 이미 introspect한 걸 여기서 또 DB에 물어보는 중복 조회(EXP-005 때는 매번
schema_provider.get_schema_text()를 다시 호출해 테이블당 3개씩 쿼리를 반복했다)를
없애기 위해서다. 선택된 테이블이 후보 캐시에 없는 예외적인 경우(예: 사람이 후보 밖 테이블을
직접 추가)에만 schema_provider로 폴백한다.

interrupt()에 넘기는 값은 최소 마커면 충분하다 — 검토 화면이 실제로 필요로 하는 데이터
(schema_candidates/schema_candidate_details)는 이미 GraphState에 있고, API 레이어가
graph.get_state()로 그 state를 직접 읽어 응답을 구성한다(중복 저장 안 함).
"""
import json
import logging
import re

from langgraph.types import interrupt

from app.graph.state import GraphState
from app.llm.base import TokenCountingLLM
from app.sql.schema_provider import SchemaProvider

logger = logging.getLogger(__name__)

_SELECT_PROMPT = """\
당신은 SQL 생성을 돕기 위해, 아래 후보 테이블 중 이 질문에 답하는 SQL을 작성하는 데
실제로 필요한 테이블만 골라내는 역할입니다. 후보 목록에 없는 테이블은 절대 새로 만들어내지 마세요.

각 후보를 고를지 판단할 때는 테이블 이름이나 코멘트가 질문과 표면적으로 비슷해 보이는지가
아니라, 그 테이블의 컬럼 중 실제로 질문이 요구하는 값을 담고 있는 컬럼이 있는지를 근거로
판단하세요. 예를 들어 질문에 "처방코드"가 나온다고 해서 이름에 "처방"이 들어간 테이블을
바로 고르지 말고, 실제로 처방코드 값을 담은 컬럼이 있는 테이블을 고르세요.

조인에 필요한 연결 테이블(예: 환자 식별자를 가진 테이블)은 질문에 직접 언급되지 않아도
필요하면 포함하세요. 포함할지 애매한 후보는 제외하지 말고 포함하세요 — 불필요한 테이블을
하나 더 포함하는 것보다 필요한 테이블을 빠뜨리는 게 더 나쁩니다.

질문: {question}
질문 의도: {intent}

후보 테이블:
{candidates}

각 후보에 대해 포함 여부와 근거(어떤 컬럼이 질문의 어떤 요구사항과 맞는지)를 한 줄씩
간단히 적은 뒤, 마지막 줄에 설명이나 마크다운 없이 아래 JSON 형식만 반환하세요:
{{"selected_tables": ["table1", "table2"]}}
"""


def _format_candidates(details: list[dict], candidates: list[str]) -> str:
    if not details:
        return "\n".join(f"- {c}" for c in candidates)
    blocks = []
    for d in details:
        text = d.get("text")
        if text:
            blocks.append(text)
        else:
            cols = ", ".join(d.get("columns") or [])
            comment = d.get("comment") or ""
            blocks.append(f"- {d['table']}: {comment} (columns: {cols})")
    return "\n\n".join(blocks)


def _parse_selected_tables(raw: str) -> list[str] | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    data = json.loads(match.group(0))
    return data.get("selected_tables")


def _select_tables(
    llm: TokenCountingLLM, state: GraphState, candidates: list[str], details: list[dict]
) -> list[str]:
    run_id = state.get("run_id", "")
    tags = state.get("tags") or {}
    prompt = _SELECT_PROMPT.format(
        question=state["question"],
        intent=state.get("intent", ""),
        candidates=_format_candidates(details, candidates),
    )
    try:
        raw = llm.generate(prompt, run_id=run_id, node="schema_review", tags=tags)
        parsed = _parse_selected_tables(raw)
        selected = [t for t in (parsed or []) if t in candidates]
        if selected:
            return selected
        logger.warning("[run=%s] schema 재선정 결과 비어있음 → 전체 후보 유지", run_id)
    except Exception as e:
        logger.warning("[run=%s] schema 재선정 실패 → 전체 후보 유지: %s", run_id, e)
    return candidates


def _assemble_from_cache(selected: list[str], details: list[dict]) -> str | None:
    text_by_table = {d["table"]: d.get("text") for d in details if d.get("text")}
    texts = [text_by_table[t] for t in selected if t in text_by_table]
    if len(texts) != len(selected):
        return None
    return "\n\n".join(texts)


def make_schema_review_node(llm: TokenCountingLLM, schema_provider: SchemaProvider):
    def schema_review_node(state: GraphState) -> dict:
        candidates = state.get("schema_candidates") or []
        details = state.get("schema_candidate_details") or []
        review_on = bool((state.get("review_config") or {}).get("schema"))

        if review_on:
            selected = interrupt("review_schema")
        elif not candidates:
            return {"confirmed_schema": []}
        else:
            selected = _select_tables(llm, state, candidates, details)

        if not candidates:
            return {"confirmed_schema": selected}

        if not selected:
            schema_text = schema_provider.get_schema_text(target_tables=None)
        else:
            schema_text = _assemble_from_cache(selected, details)
            if schema_text is None:
                schema_text = schema_provider.get_schema_text(target_tables=selected)

        return {"confirmed_schema": selected, "schema_text": schema_text}

    return schema_review_node
