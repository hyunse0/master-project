"""도메인 하나에 바인딩된 LangGraph 조립.

  START → intent → intent_clarification → schema_linking → schema_review → sql_generation
  intent_clarification --(review_config.intent 켜짐, needs_clarification, 재질의 미소진)--> intent(재분류)
  sql_generation --(VALUE_UNCONFIRMED, retry_count<max_retries)--> sql_generation
  sql_generation --(sql 확보)--> sql_review → validation
  validation --(review_config.sql 켜짐, 실패)--> sql_review
  validation --(review_config.sql 꺼짐, citation/anchor 실패, retry_count<max_retries)--> sql_generation
  validation --(review_config.sql 꺼짐, SqlValidator 실패 또는 재시도 소진)--> END
  validation --(전부 통과)--> execution
  execution --(review_config.sql 켜짐, 실패)--> sql_review
  execution --(review_config.sql 꺼짐, timeout/실행오류/zero-row, retry_count<max_retries)--> sql_generation
  execution --(review_config.sql 꺼짐, 성공 또는 재시도 소진)--> END

review_config.schema/sql이 켜져 있으면 schema_review/sql_review 노드가 interrupt()로
멈춘다(PostgresSaver 체크포인터 필요 — build_graph(checkpointer=...)). 꺼져 있으면
auto-pass로 지금까지와 동일하게 동작하며, 이 경로는 checkpointer=None으로도 문제없이
돌아간다(scripts/run_graph_cli.py, eval/token_cost_comparison.py가 이 경로).

review_config.sql이 켜져 있을 때 검증/실행 실패를 sql_generation이 아니라 sql_review로
되돌리는 이유: 사람이 이미 승인한 SQL을 자동 재생성으로 몰래 덮지 않기 위해서다(계획 문서
section 5.5) — retry_count 상한과 무관하게 사람이 직접 고치거나 재승인할 때까지 반복된다.

intent_clarification도 review_config.intent 게이트로 켜고 끈다(schema_review/sql_review와
같은 성격) — 꺼져 있으면(기본) intent가 모호하다고 판단해도 멈추지 않고 그대로 진행한다.
켜져 있고 실제로 모호하면 interrupt()로 멈춰 사용자 답변을 받고 intent로 되돌아가 재분류—
1회 상한(intent_clarification_node의 clarification_rounds)이라 무한 루프는 없다.
"""
import logging
import time

from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph

from app.domain.loader import DomainConfig
from app.embedding.embedder import EmbeddingEngine
from app.embedding.sparse_embedder import SparseEmbedder
from app.graph.nodes.execution import make_execution_node
from app.graph.nodes.intent import make_intent_node
from app.graph.nodes.intent_clarification import intent_clarification_node
from app.graph.nodes.schema_linking import make_schema_linking_node
from app.graph.nodes.schema_review import make_schema_review_node
from app.graph.nodes.sql_generation import make_sql_generation_node
from app.graph.nodes.sql_review import sql_review_node
from app.graph.nodes.validation import make_validation_node
from app.graph.state import GraphState
from app.knowledge.qdrant_connection import get_qdrant_client
from app.knowledge.qdrant_store import QdrantFewShotStore
from app.llm.azure_openai_client import AzureOpenAIChatClient
from app.llm.base import TokenCountingLLM
from app.llm.router import build_llm_router
from app.observability import run_progress
from app.sql.prompt_builder import (
    SqlPromptBuilder,
    load_general_notes,
    load_table_notes,
    render_table_notes_for_prompt,
)
from app.sql.retriever import SqlRetriever
from app.sql.schema_provider import SchemaProvider
from app.sql.validator import SqlValidator

logger = logging.getLogger(__name__)

_DEFAULT_MAX_RETRIES = 2


def _max_retries(state: GraphState) -> int:
    return (state.get("tags") or {}).get("max_retries", _DEFAULT_MAX_RETRIES)


def _route_after_sql_generation(state: GraphState) -> str:
    if state.get("retry_error_code") == "VALUE_UNCONFIRMED":
        if state.get("retry_count", 0) < _max_retries(state):
            return "sql_generation"
        return END
    return "sql_review"


def _sql_review_enabled(state: GraphState) -> bool:
    return bool((state.get("review_config") or {}).get("sql"))


def _route_after_intent_clarification(state: GraphState) -> str:
    if state.get("clarification_answer"):
        return "intent"
    return "schema_linking"


def _route_after_validation(state: GraphState) -> str:
    code = state.get("retry_error_code")
    if code is None:
        return "execution"
    if _sql_review_enabled(state):
        return "sql_review"
    if code == "SQL_VALIDATION_FAIL":
        return END
    if state.get("retry_count", 0) < _max_retries(state):
        return "sql_generation"
    return END


def _route_after_execution(state: GraphState) -> str:
    code = state.get("retry_error_code")
    if code is None:
        return END
    if _sql_review_enabled(state):
        return "sql_review"
    if state.get("retry_count", 0) < _max_retries(state):
        return "sql_generation"
    return END


# 질의 실행 탭의 실행 로그 패널에 그대로 노출되는 라벨 — client/src/components/queryRun/
# stages.ts의 NODE_LABEL과 표기를 맞춰서, 실행 중 스테이지 레일에 뜨는 이름과 로그 패널에
# 찍히는 이름이 같은 말을 쓰게 한다.
_NODE_LABEL_KO: dict[str, str] = {
    "intent": "의도 분류",
    "intent_clarification": "의도 확인",
    "schema_linking": "스키마 탐색",
    "schema_review": "스키마 검토",
    "sql_generation": "SQL 생성",
    "sql_review": "SQL 검토",
    "validation": "검증",
    "execution": "실행",
}


def _tracked(node_name: str, fn):
    """GET /runs/{id}/progress가 폴링해 읽을 수 있도록, 노드가 실제로 실행을 시작하는
    시점에 run_progress에 자기 이름을 기록한다(run_progress.py 참고). 그와 별개로 각 노드의
    시작/종료를 배너로 남겨, 실행 로그 패널만 보고도 지금 몇 번째 단계가 도는지·얼마나
    걸렸는지 한눈에 구분되게 한다 — 노드 각각의 내부 로그(예: "[sql_generation] SQL 생성
    완료")는 그대로 두고 이 배너 사이에 끼워 넣는 방식이라 노드 파일을 따로 고칠 필요가
    없다. review_config로 인터럽트되는 경우(interrupt()가 GraphInterrupt를 던짐)는
    "완료"가 아니라 "사람 검토 대기로 중단"으로 구분한다 — 재개 시 LangGraph가 노드를
    처음부터 재실행하므로 배너도 다시 한 번 찍힌다."""
    label = _NODE_LABEL_KO.get(node_name, node_name)

    def wrapper(state: GraphState):
        run_progress.set_current_node(state.get("run_id"), node_name)
        t0 = time.time()
        logger.info("▶ %s 시작", label)
        try:
            result = fn(state)
        except GraphInterrupt:
            logger.info("⏸ %s — 사람 검토 대기로 중단", label)
            raise
        except Exception as e:
            logger.info("✗ %s 실패 (%.2fs): %s", label, time.time() - t0, e)
            raise
        logger.info("✓ %s 완료 (%.2fs)", label, time.time() - t0)
        return result

    return wrapper


def build_graph(domain: DomainConfig, checkpointer=None):
    # intent는 difficulty를 아직 모르는 시점이라 항상 저비용 모델 고정 — 라우팅은
    # difficulty가 채워진 뒤의 노드(sql_generation, execution)에만 적용된다.
    intent_llm = TokenCountingLLM(AzureOpenAIChatClient())
    llm_router = build_llm_router()
    embedder = EmbeddingEngine()
    sparse_embedder = SparseEmbedder()
    qdrant_client = get_qdrant_client()
    schema_provider = SchemaProvider(domain.connection)

    retriever = SqlRetriever(QdrantFewShotStore(domain.qdrant_fewshot_collection))
    general_notes = load_general_notes(domain.prompt_fragments_path, domain.name)
    table_notes = load_table_notes(domain.prompt_fragments_path, domain.name)
    domain_notes = general_notes
    if table_notes:
        domain_notes += ("\n\n" if domain_notes else "") + "[테이블별 참고사항]\n" + render_table_notes_for_prompt(table_notes)
    prompt_builder = SqlPromptBuilder(domain_notes=domain_notes)

    allowed_tables = [t.split(".", 1)[1] for t in schema_provider.get_table_names()]
    sql_validator = SqlValidator(allowed_tables)

    graph = StateGraph(GraphState)
    graph.add_node("intent", _tracked("intent", make_intent_node(intent_llm)))
    graph.add_node("intent_clarification", _tracked("intent_clarification", intent_clarification_node))
    graph.add_node(
        "schema_linking",
        _tracked(
            "schema_linking",
            make_schema_linking_node(domain, embedder, qdrant_client, schema_provider, sparse_embedder),
        ),
    )
    graph.add_node(
        "schema_review",
        _tracked("schema_review", make_schema_review_node(intent_llm, schema_provider, embedder, domain_notes)),
    )
    graph.add_node(
        "sql_generation",
        _tracked("sql_generation", make_sql_generation_node(domain, llm_router, embedder, retriever, prompt_builder)),
    )
    graph.add_node("sql_review", _tracked("sql_review", sql_review_node))
    graph.add_node("validation", _tracked("validation", make_validation_node(domain, sql_validator)))
    graph.add_node("execution", _tracked("execution", make_execution_node(domain, llm_router)))

    graph.add_edge(START, "intent")
    graph.add_edge("intent", "intent_clarification")
    graph.add_conditional_edges(
        "intent_clarification",
        _route_after_intent_clarification,
        {"intent": "intent", "schema_linking": "schema_linking"},
    )
    graph.add_edge("schema_linking", "schema_review")
    graph.add_edge("schema_review", "sql_generation")
    graph.add_conditional_edges(
        "sql_generation",
        _route_after_sql_generation,
        {"sql_generation": "sql_generation", "sql_review": "sql_review", END: END},
    )
    graph.add_edge("sql_review", "validation")
    graph.add_conditional_edges(
        "validation",
        _route_after_validation,
        {"sql_generation": "sql_generation", "sql_review": "sql_review", "execution": "execution", END: END},
    )
    graph.add_conditional_edges(
        "execution",
        _route_after_execution,
        {"sql_generation": "sql_generation", "sql_review": "sql_review", END: END},
    )

    logger.info("LangGraph 조립 완료 (domain=%s)", domain.name)
    return graph.compile(checkpointer=checkpointer)
