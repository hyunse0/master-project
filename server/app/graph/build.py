"""도메인 하나에 바인딩된 LangGraph 조립.

  START → intent → schema_linking → schema_review → sql_generation
  sql_generation --(VALUE_UNCONFIRMED, retry_count<max_retries)--> sql_generation
  sql_generation --(sql 확보)--> sql_review → validation
  validation --(citation/anchor 실패, retry_count<max_retries)--> sql_generation
  validation --(SqlValidator 실패)--> END
  validation --(전부 통과)--> execution
  execution --(timeout/실행오류/zero-row, retry_count<max_retries)--> sql_generation
  execution --(성공 또는 재시도 소진)--> END

체크포인터 없이 compile() — PostgresSaver는 C(HITL 6단계)에서 추가한다.
schema_review/sql_review가 지금은 auto-pass 얇은 노드로 존재하는 것도 C에서 interrupt()로
교체하기 위한 자리다(계획 문서 section 5.1 — 작업 노드와 검토 노드 분리 원칙).
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


def _route_after_validation(state: GraphState) -> str:
    code = state.get("retry_error_code")
    if code == "SQL_VALIDATION_FAIL":
        return END
    if code in ("SCHEMA_CITATION_FAIL", "VALUE_ANCHOR_FAIL"):
        if state.get("retry_count", 0) < _max_retries(state):
            return "sql_generation"
        return END
    return "execution"


def _route_after_execution(state: GraphState) -> str:
    code = state.get("retry_error_code")
    if code in ("TIMEOUT", "UNSAFE_SQL", "ZERO_ROWS_WITH_VALUE_FILTER"):
        if state.get("retry_count", 0) < _max_retries(state):
            return "sql_generation"
        return END
    return END


def build_graph(domain: DomainConfig):
    llm = TokenCountingLLM(AzureOpenAIChatClient())
    embedder = EmbeddingEngine()
    qdrant_client = get_qdrant_client()
    schema_provider = SchemaProvider(domain.connection)

    retriever = SqlRetriever(QdrantFewShotStore(domain.qdrant_fewshot_collection))
    domain_notes = load_prompt_fragments(domain.prompt_fragments_path)
    prompt_builder = SqlPromptBuilder(domain_notes=domain_notes)

    allowed_tables = [t.split(".", 1)[1] for t in schema_provider.get_table_names()]
    sql_validator = SqlValidator(allowed_tables)

    graph = StateGraph(GraphState)
    graph.add_node("intent", make_intent_node(llm))
    graph.add_node(
        "schema_linking",
        make_schema_linking_node(domain, embedder, qdrant_client, schema_provider),
    )
    graph.add_node("schema_review", schema_review_node)
    graph.add_node(
        "sql_generation",
        make_sql_generation_node(domain, llm, embedder, retriever, prompt_builder),
    )
    graph.add_node("sql_review", sql_review_node)
    graph.add_node("validation", make_validation_node(domain, sql_validator))
    graph.add_node("execution", make_execution_node(domain, llm))

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
        {"sql_generation": "sql_generation", "execution": "execution", END: END},
    )
    graph.add_conditional_edges(
        "execution",
        _route_after_execution,
        {"sql_generation": "sql_generation", END: END},
    )

    logger.info("LangGraph 조립 완료 (domain=%s)", domain.name)
    return graph.compile()
