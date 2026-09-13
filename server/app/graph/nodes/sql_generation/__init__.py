"""SQL 생성 노드 — LLM 호출 1회 + VALUE_UNCONFIRMED 처리만 담당한다.

SchemaCitation/ValueAnchor/SqlValidator 검증과 실행은 validation_node/execution_node로
분리돼 있다(rag-practice SqlGenPipeline._generation_loop를 노드 단위로 쪼갠 것).

질의유형(aggregate/list/cohort)별 전문 프롬프트 조각은 이 패키지의 형제 모듈
(aggregate.py/list.py/cohort.py)에서 GUIDANCE 상수로 가져와 prompt_builder에 주입한다 —
few-shot 검색·LLM 호출·retry 처리 같은 오케스트레이션은 유형과 무관하게 이 파일에서
공유한다(그래프 노드는 sql_generation 하나로 유지, 계획 문서 E그룹 "그래프 골격 재사용").
"""
import logging
import re

from app.db.postgres_client import get_domain_connection
from app.domain.loader import DomainConfig
from app.embedding.embedder import EmbeddingEngine
from app.graph.state import GraphState
from app.llm.base import TokenCountingLLM
from app.llm.router import select_llm
from app.sql.canonicalizer import build_embedding_text
from app.sql.prompt_builder import SqlPromptBuilder
from app.sql.retriever import RetrievedExample, SqlRetriever

from . import aggregate, cohort, list_type

logger = logging.getLogger(__name__)

_GUIDANCE_BY_QUERY_TYPE: dict[str, str] = {
    "aggregate": aggregate.GUIDANCE,
    "list": list_type.GUIDANCE,
    "cohort": cohort.GUIDANCE,
}
_DEFAULT_QUERY_TYPE = "list"


def make_sql_generation_node(
    domain: DomainConfig,
    llm_router: dict[str, TokenCountingLLM],
    embedder: EmbeddingEngine,
    retriever: SqlRetriever,
    prompt_builder: SqlPromptBuilder,
):
    def sql_generation_node(state: GraphState) -> dict:
        run_id = state["run_id"]
        difficulty = state.get("difficulty")
        query_type = state.get("query_type") or _DEFAULT_QUERY_TYPE
        tags = {**(state.get("tags") or {}), "difficulty": difficulty, "query_type": query_type}
        llm = select_llm(llm_router, difficulty, tags.get("routing_mode", "on"))
        is_first_attempt = state.get("retry_count", 0) == 0

        if is_first_attempt:
            few_shot_examples = _retrieve_few_shot(state, domain, embedder, retriever)
        else:
            few_shot_examples = state.get("few_shot_examples") or []

        prompt = prompt_builder.build(
            state["question"],
            state.get("schema_text", ""),
            few_shot_examples,
            feedback=state.get("retry_feedback"),
            error_code=state.get("retry_error_code"),
            task_type=state.get("task_type", ""),
            metric=state.get("metric", ""),
            dimensions=state.get("dimensions") or [],
            time_range=state.get("time_range") or {},
            type_guidance=_GUIDANCE_BY_QUERY_TYPE.get(query_type, list_type.GUIDANCE),
            prior_turn_context=_build_prior_turn_context(state.get("prior_turns")),
        )
        logger.info(
            "  [sql_generation] query_type=%s · few-shot 예제 %d건 · 확정 스키마 %d테이블",
            query_type, len(few_shot_examples), len(state.get("confirmed_schema") or []),
        )
        raw = llm.generate(prompt, run_id=run_id, node="sql_generation", tags=tags)

        if "## VALUE_UNCONFIRMED" in raw:
            logger.info("  [sql_generation] VALUE_UNCONFIRMED 감지 — 값 재탐색")
            feedback = _resolve_value_unconfirmed(raw, domain)
            return {
                "few_shot_examples": few_shot_examples,
                "sql_prompt": prompt,
                "sql_raw": raw,
                "retry_count": state.get("retry_count", 0) + 1,
                "retry_feedback": feedback,
                "retry_error_code": "VALUE_UNCONFIRMED",
            }

        sql = _extract_sql(raw)
        logger.info("  [sql_generation] SQL 생성 완료 (%d자)", len(sql))
        return {
            "few_shot_examples": few_shot_examples,
            "sql": sql,
            "sql_prompt": prompt,
            "sql_raw": raw,
            "retry_feedback": None,
            "retry_error_code": None,
        }

    return sql_generation_node


def _build_prior_turn_context(prior_turns: list[dict] | None) -> str | None:
    """멀티턴(F단계) — 직전 턴의 질문/SQL/요약을 프롬프트에 얹어 "이어서 수정"을 유도한다.
    prior_turns가 없으면 None(기존 싱글턴 동작과 동일하게 [이전 턴] 블록 자체가 생략됨)."""
    if not prior_turns:
        return None
    prev = prior_turns[-1]
    lines = [f"이전 질문: {prev['question']}"]
    if prev.get("sql"):
        lines.append(f"이전 SQL:\n{prev['sql']}")
    if prev.get("summary"):
        lines.append(f"이전 결과 요약: {prev['summary']}")
    return "\n".join(lines)


def _retrieve_few_shot(
    state: GraphState,
    domain: DomainConfig,
    embedder: EmbeddingEngine,
    retriever: SqlRetriever,
) -> list[dict]:
    table_hints = state.get("confirmed_schema") or []
    embed_text = build_embedding_text(
        state["question"],
        state.get("intent", ""),
        table_hints,
        [state["metric"]] if state.get("metric") else [],
        domain.name,
        task_type=state.get("task_type", ""),
        dimensions=state.get("dimensions") or [],
    )
    embedding = embedder.embed(embed_text)
    retrieved = retriever.retrieve(
        embedding, query_tables=table_hints, query_domain=domain.name, top_k=3,
    )
    return _serialize_examples(retrieved)


def _serialize_examples(examples: list[RetrievedExample]) -> list[dict]:
    return [
        {
            "question": ex.entry.question,
            "intent": ex.entry.intent,
            "canonical_sql": ex.entry.canonical_sql,
            "tables": ex.entry.tables,
            "domain": ex.entry.domain,
            "score": round(ex.score, 4),
        }
        for ex in examples
    ]


def _extract_sql(text: str) -> str:
    match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return text.strip()


def _resolve_value_unconfirmed(raw_answer: str, domain: DomainConfig) -> str:
    """LLM이 값을 확신 못할 때 실제 DB 값을 조회해 피드백을 만든다.

    prompt_builder._SYSTEM_PROMPT가 요구하는 출력 형식(`- 값: "..."` / `- 후보 컬럼: [...]`)에
    맞춰 파싱한다 — 여러 블록이 와도 첫 번째 값/후보 컬럼만 처리(다음 재시도에서 나머지 처리).
    """
    value_match = re.search(r'값:\s*"([^"]*)"', raw_answer)
    candidates_match = re.search(r"후보\s*컬럼:\s*\[([^\]]*)\]", raw_answer)
    if not value_match:
        return "VALUE_UNCONFIRMED: 값 정보를 파싱할 수 없습니다."

    candidate = value_match.group(1).strip()
    candidate_cols = (
        [c.strip() for c in candidates_match.group(1).split(",") if c.strip()]
        if candidates_match else []
    )

    if not candidate_cols:
        return (
            f'"{candidate}"에 해당하는 컬럼을 스키마에서 찾을 수 없습니다. '
            f"[스키마]에 없는 정보라면 SELECT하지 말고, 있다면 정확한 컬럼명을 다시 확인하세요."
        )

    full_col = candidate_cols[0]  # "schema.table.column"
    parts = full_col.rsplit(".", 2)
    if len(parts) < 2:
        return f"VALUE_UNCONFIRMED: 컬럼 형식이 잘못됐습니다: {full_col}"

    if len(parts) == 3:
        schema, tbl, col = parts
    else:
        schema, tbl, col = "public", parts[0], parts[1]

    table_full = f"{schema}.{tbl}"
    conn = get_domain_connection(domain.connection)
    actual: list[str] = []
    try:
        with conn.cursor() as cur:
            if candidate:
                cur.execute(
                    f'SELECT DISTINCT "{col}" FROM {table_full} '
                    f'WHERE "{col}"::text ILIKE %s LIMIT 20',
                    (f"%{candidate}%",),
                )
                actual = [str(r[0]) for r in cur.fetchall()]
            if not actual:
                cur.execute(
                    f'SELECT DISTINCT "{col}" FROM {table_full} WHERE "{col}" IS NOT NULL LIMIT 30',
                )
                actual = [str(r[0]) for r in cur.fetchall()]
    except Exception as e:
        logger.warning("VALUE_UNCONFIRMED 조회 오류: %s", e)
        return f"{full_col} 값 조회 실패: {e}"
    finally:
        conn.close()

    vals = ", ".join(f"'{v}'" for v in actual) if actual else "값 없음"
    return (
        f"{table_full}.{col} 컬럼의 실제 값 목록: [{vals}]\n"
        f"위 실제 값 중 하나를 사용해 SQL을 작성하세요."
    )
