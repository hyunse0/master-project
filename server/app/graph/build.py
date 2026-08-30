"""도메인 하나에 바인딩된 LangGraph 조립.

  START → intent → schema_linking → schema_review → sql_generation
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
"""
import logging

from langgraph.graph import END, START, StateGraph

from app.domain.loader import DomainConfig
from app.embedding.embedder import EmbeddingEngine
from app.graph.nodes.execution import make_execution_node
from app.graph.nodes.intent import make_intent_node
from app.graph.nodes.schema_linking import make_schema_linking_node
from app.graph.nodes.schema_review import schema_review_node
from app.graph.nodes.sql_generation import make_sql_generation_node
from app.graph.nodes.sql_review import sql_review_node
from app.graph.nodes.validation import make_validation_node
from app.graph.state import GraphState
from app.knowledge.qdrant_connection import get_qdrant_client
from app.knowledge.qdrant_store import QdrantFewShotStore
from app.llm.azure_openai_client import AzureOpenAIChatClient
from app.llm.base import TokenCountingLLM
from app.llm.router import build_llm_router
from app.sql.prompt_builder import SqlPromptBuilder, load_prompt_fragments
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


def build_graph(domain: DomainConfig, checkpointer=None):
    # intent는 difficulty를 아직 모르는 시점이라 항상 저비용 모델 고정 — 라우팅은
    # difficulty가 채워진 뒤의 노드(sql_generation, execution)에만 적용된다.
    intent_llm = TokenCountingLLM(AzureOpenAIChatClient())
    llm_router = build_llm_router()
    embedder = EmbeddingEngine()
    qdrant_client = get_qdrant_client()
    schema_provider = SchemaProvider(domain.connection)

    retriever = SqlRetriever(QdrantFewShotStore(domain.qdrant_fewshot_collection))
    domain_notes = load_prompt_fragments(domain.prompt_fragments_path)
    prompt_builder = SqlPromptBuilder(domain_notes=domain_notes)

    allowed_tables = [t.split(".", 1)[1] for t in schema_provider.get_table_names()]
    sql_validator = SqlValidator(allowed_tables)

    graph = StateGraph(GraphState)
    graph.add_node("intent", make_intent_node(intent_llm))
    graph.add_node(
        "schema_linking",
        make_schema_linking_node(domain, embedder, qdrant_client, schema_provider),
    )
    graph.add_node("schema_review", schema_review_node)
    graph.add_node(
        "sql_generation",
        make_sql_generation_node(domain, llm_router, embedder, retriever, prompt_builder),
    )
    graph.add_node("sql_review", sql_review_node)
    graph.add_node("validation", make_validation_node(domain, sql_validator))
    graph.add_node("execution", make_execution_node(domain, llm_router))

    graph.add_edge(START, "intent")
    graph.add_edge("intent", "schema_linking")
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
