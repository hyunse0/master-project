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
schema_candidate_details[]에 schema_linking이 이미 계산해둔 컬럼 티어링(column_tiers/
column_details/foreign_keys, column_relevance.py)을 그대로 재사용해 조립한다 —
schema_linking 단계에서 이미 introspect한 걸 여기서 또 DB에 물어보는 중복 조회(EXP-005
때는 매번 schema_provider.get_schema_text()를 다시 호출해 테이블당 3개씩 쿼리를
반복했다)를 없애기 위해서다. 선택된 테이블이 후보 캐시에 없는 예외적인 경우(예: 사람이
후보 밖 테이블을 직접 추가)에만 그 테이블 하나만 즉석 introspect+티어링하거나
(question_embedding이 있으면), 그마저 안 되면 schema_provider의 완전 비압축 렌더링으로
폴백한다.

사람 검토 경로(interrupt)의 재개 값은 `{"tables": [...], "columns": {table: [col, ...]}}`
형태다 — tables는 확정 테이블 목록(기존과 동일), columns는 테이블별로 사람이 상세 노출을
선택한 non-key 컬럼의 "완전 대체 목록"(부분 델타 아님, key 컬럼은 항상 강제 포함이라
포함할 필요 없음). 진행 중이던 체크포인트가 옛 shape(평평한 list[str])로 멈춰 있을 수
있어 두 shape을 모두 방어적으로 처리한다.
"""
import json
import logging
import re

from langgraph.types import interrupt

from app.embedding.embedder import EmbeddingEngine
from app.graph.state import GraphState
from app.llm.base import TokenCountingLLM
from app.sql.column_relevance import build_column_details, classify_columns_for_tables, render_tiered_schema_block
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
{domain_notes_section}
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
    llm: TokenCountingLLM, state: GraphState, candidates: list[str], details: list[dict], domain_notes: str = ""
) -> list[str]:
    run_id = state.get("run_id", "")
    tags = state.get("tags") or {}
    domain_notes_section = f"\n[도메인 참고사항]\n{domain_notes}\n" if domain_notes else ""
    prompt = _SELECT_PROMPT.format(
        question=state["question"],
        intent=state.get("intent", ""),
        candidates=_format_candidates(details, candidates),
        domain_notes_section=domain_notes_section,
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


def _tier_out_of_cache_table(
    table: str,
    question_embedding: list[float] | None,
    embedder: EmbeddingEngine | None,
    schema_provider: SchemaProvider,
) -> str | None:
    """후보 캐시에 없는 테이블(사람이 후보 밖 테이블을 직접 추가) 하나만 즉석 티어링한다.

    question_embedding/embedder가 없으면(예: full_dump 모드) 압축 없이 완전한 렌더링으로
    폴백한다 — 실패 시 None을 돌려줘 호출부가 schema_provider의 최종 폴백을 타게 한다.
    """
    try:
        schema, name = table.split(".", 1)
        info = schema_provider.get_table_info(schema, name)
    except Exception as e:
        logger.warning("후보 밖 테이블 %s introspection 실패: %s", table, e)
        return None
    if question_embedding is None or embedder is None:
        return SchemaProvider.table_to_text(info)
    tiers, scores = classify_columns_for_tables([info], question_embedding, embedder)[info.full_name]
    column_details = build_column_details(info, scores)
    foreign_keys = [
        {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column} for fk in info.foreign_keys
    ]
    return render_tiered_schema_block(
        info.full_name, info.comment, column_details, foreign_keys, tiers.key, tiers.relevant, tiers.other,
    )


def _assemble_schema_text(
    selected: list[str],
    details: list[dict],
    confirmed_columns: dict[str, list[str]] | None,
    question_embedding: list[float] | None,
    embedder: EmbeddingEngine | None,
    schema_provider: SchemaProvider,
) -> str:
    """선택된 테이블들의 schema_text를 컬럼 티어링을 반영해 재조립한다.

    사람의 confirmed_columns 오버라이드가 있으면 그 테이블의 relevant 티어 대신 사용하고,
    key 티어는 오버라이드 여부와 무관하게 항상 강제 포함한다(조인 컬럼을 사람이 실수로
    빼도 SQL 생성이 막히지 않도록). 캐시에 없는 테이블은 즉석 티어링 또는 완전 비압축
    렌더링으로 개별 폴백한다.
    """
    by_table = {d["table"]: d for d in details}
    blocks = []
    for table in selected:
        d = by_table.get(table)
        if d is None:
            text = _tier_out_of_cache_table(table, question_embedding, embedder, schema_provider)
            blocks.append(text if text is not None else schema_provider.get_schema_text(target_tables=[table]))
            continue
        key = d["column_tiers"]["key"]
        override = (confirmed_columns or {}).get(table)
        relevant = override if override is not None else d["column_tiers"]["relevant"]
        all_columns = key + d["column_tiers"]["relevant"] + d["column_tiers"]["other"]
        other = [c for c in all_columns if c not in key and c not in relevant]
        blocks.append(render_tiered_schema_block(
            d["table"], d.get("comment"), d["column_details"], d["foreign_keys"], key, relevant, other,
        ))
    return "\n\n".join(blocks)


def make_schema_review_node(
    llm: TokenCountingLLM, schema_provider: SchemaProvider, embedder: EmbeddingEngine, domain_notes: str = ""
):
    def schema_review_node(state: GraphState) -> dict:
        candidates = state.get("schema_candidates") or []
        details = state.get("schema_candidate_details") or []
        question_embedding = state.get("question_embedding")

        if bool((state.get("review_config") or {}).get("schema")):
            resumed = interrupt("review_schema")
            if isinstance(resumed, list):  # 옛 shape(list[str]) — 진행 중이던 체크포인트 호환
                selected, confirmed_columns = resumed, None
            else:
                selected = resumed.get("tables") or []
                confirmed_columns = resumed.get("columns") or None
        elif not candidates:
            logger.info("  [schema_review] 후보 없음 — 빈 스키마로 진행")
            return {"confirmed_schema": []}
        else:
            selected = _select_tables(llm, state, candidates, details, domain_notes)
            confirmed_columns = None

        source = "사람 검토" if bool((state.get("review_config") or {}).get("schema")) else "자동 확정"
        logger.info("  [schema_review] %s — 확정 테이블 %d개: %s", source, len(selected), selected)

        if not candidates:
            return {"confirmed_schema": selected, "confirmed_columns": confirmed_columns}

        if not selected:
            schema_text = schema_provider.get_schema_text(target_tables=None)
        else:
            schema_text = _assemble_schema_text(
                selected, details, confirmed_columns, question_embedding, embedder, schema_provider,
            )

        return {"confirmed_schema": selected, "confirmed_columns": confirmed_columns, "schema_text": schema_text}

    return schema_review_node
