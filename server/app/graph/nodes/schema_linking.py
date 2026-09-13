"""질문에 관련된 테이블을 찾아 schema_text를 확정한다.

KPI 비교용 토글: tags["schema_rag_mode"] == "full_dump"이면 Qdrant 검색을 건너뛰고
전체 스키마를 그대로 덤프한다 — "스키마 RAG 검색 도입 전"을 코드로 재현 가능하게 유지하기
위한 것으로, eval/token_cost_comparison.py가 두 모드를 오가며 토큰 사용량을 비교한다.
"""
import logging

from qdrant_client import QdrantClient

from app.domain.loader import DomainConfig
from app.embedding.embedder import EmbeddingEngine
from app.graph.state import GraphState
from app.sql.column_relevance import build_column_details, classify_columns_for_tables, render_tiered_schema_block
from app.sql.schema_provider import SchemaProvider

logger = logging.getLogger(__name__)

_TOP_N_TABLES = 5


def _tier_candidates(
    candidate_details: list[dict],
    embedding: list[float],
    embedder: EmbeddingEngine,
    schema_provider: SchemaProvider,
) -> None:
    """candidate_details를 in-place로 컬럼 티어링 정보로 보강한다.

    스키마 변경 등으로 특정 후보의 introspection이 깨져도 전체 노드가 죽지 않도록,
    깨진 후보는 Qdrant에 이미 있던 이름만의 columns를 전부 other 티어로 폴백 렌더링한다.
    """
    tables = []
    ok_details = []
    for d in candidate_details:
        try:
            schema, name = d["table"].split(".", 1)
            tables.append(schema_provider.get_table_info(schema, name))
            ok_details.append(d)
        except Exception as e:
            logger.warning("  [schema_linking] 후보 %s introspection 실패 → other 티어 폴백: %s", d["table"], e)
            d["column_tiers"] = {"key": [], "relevant": [], "other": list(d.get("columns") or [])}
            d["column_details"] = {}
            d["foreign_keys"] = []

    if not tables:
        return

    tiers_by_table = classify_columns_for_tables(tables, embedding, embedder)
    for d, table in zip(ok_details, tables):
        tiers, scores = tiers_by_table[table.full_name]
        column_details = build_column_details(table, scores)
        foreign_keys = [
            {"column": fk.column, "ref_table": fk.ref_table, "ref_column": fk.ref_column}
            for fk in table.foreign_keys
        ]
        d["column_tiers"] = {"key": tiers.key, "relevant": tiers.relevant, "other": tiers.other}
        d["column_details"] = column_details
        d["foreign_keys"] = foreign_keys
        d["text"] = render_tiered_schema_block(
            table.full_name, table.comment, column_details, foreign_keys, tiers.key, tiers.relevant, tiers.other,
        )


def _carry_over_candidates(
    tables: list[str],
    embedding: list[float],
    embedder: EmbeddingEngine,
    schema_provider: SchemaProvider,
) -> list[dict]:
    """멀티턴(F단계) — Qdrant 검색 없이 주어진 테이블명만으로 candidate_details를 만든다.
    carry_schema=True 경로(전체 대체)에서 쓴다. 컬럼 티어링(key/relevant/other)은 새 질문
    임베딩 기준으로 다시 계산한다 — 테이블은 이어받아도 "이 질문에 어떤 컬럼이 필요한지"는
    매 턴 다를 수 있기 때문이다."""
    candidate_details: list[dict] = []
    for full_name in tables:
        try:
            schema, name = full_name.split(".", 1)
            info = schema_provider.get_table_info(schema, name)
        except Exception as e:
            logger.warning("  [schema_linking] 이전 턴 테이블 %s introspection 실패 — 후보에서 제외: %s", full_name, e)
            continue
        candidate_details.append({
            "table": full_name,
            "comment": info.comment,
            # 벡터 검색 스코어가 아니라 "직전 턴에서 이미 확정된 테이블"이라는 표시 — 검토 화면의
            # 점수 표시 의미가 vector-search와 달라지는 지점은 화면 작업(F단계 UI) 때 반영한다.
            "score": 1.0,
            "columns": [c.name for c in info.columns],
            "text": "",
        })
    _tier_candidates(candidate_details, embedding, embedder, schema_provider)
    return candidate_details


def make_schema_linking_node(
    domain: DomainConfig,
    embedder: EmbeddingEngine,
    qdrant_client: QdrantClient,
    schema_provider: SchemaProvider,
):
    def schema_linking_node(state: GraphState) -> dict:
        tags = state.get("tags") or {}
        mode = tags.get("schema_rag_mode", "rag")

        if mode == "full_dump":
            logger.info("  [schema_linking] full_dump 모드 — 전체 스키마 덤프")
            schema_text = schema_provider.get_schema_text(target_tables=None)
            return {"schema_candidates": [], "schema_text": schema_text}

        query_text = state["question"]
        if state.get("intent"):
            query_text = f'{state["question"]}\n의도: {state["intent"]}'
        embedding = embedder.embed(query_text)

        prior_turns = state.get("prior_turns") or []
        prior_tables = prior_turns[-1].get("confirmed_schema") or [] if prior_turns else []

        if state.get("carry_schema") and prior_tables:
            # carry_schema=True — 검색을 아예 생략하고 직전 턴 확정 테이블만 재사용.
            candidate_details = _carry_over_candidates(prior_tables, embedding, embedder, schema_provider)
            candidates = [d["table"] for d in candidate_details]
            logger.info("  [schema_linking] carry_schema 모드 — 직전 턴 확정 테이블 재사용=%s", candidates)
            if candidate_details:
                schema_text = "\n\n".join(d["text"] for d in candidate_details)
            else:
                schema_text = schema_provider.get_schema_text(target_tables=None)
            return {
                "schema_candidates": candidates,
                "schema_candidate_details": candidate_details,
                "schema_text": schema_text,
                "question_embedding": embedding,
            }

        candidates: list[str] = []
        candidate_details: list[dict] = []
        if qdrant_client.collection_exists(domain.qdrant_schema_collection):
            result = qdrant_client.query_points(
                collection_name=domain.qdrant_schema_collection,
                query=embedding,
                limit=_TOP_N_TABLES,
                with_payload=True,
            )
            for p in result.points:
                if not p.payload:
                    continue
                candidates.append(p.payload["table"])
                candidate_details.append({
                    "table": p.payload["table"],
                    "comment": p.payload.get("comment"),
                    "score": round(float(p.score), 4),
                    "columns": p.payload.get("columns", []),
                    "text": p.payload.get("text", ""),
                })
            _tier_candidates(candidate_details, embedding, embedder, schema_provider)

            # carry_schema=False일 때 직전 턴 확정 테이블을 합집합으로 강제 포함하는 안전망을
            # 시도했으나(EXP-010), Execution Accuracy가 오히려 하락해 폐기했다 — 불필요한 테이블이
            # 후보에 섞여 SQL 생성이 흔들리는 역효과가 스키마 매핑 recall 개선보다 컸다. 이제
            # prior_tables는 carry_schema=True 경로(위)에서만 쓰인다.
        else:
            logger.warning(
                "  [schema_linking] 스키마 컬렉션(%s) 없음 — full_dump로 폴백",
                domain.qdrant_schema_collection,
            )

        if candidate_details:
            schema_text = "\n\n".join(d["text"] for d in candidate_details)
        else:
            schema_text = schema_provider.get_schema_text(target_tables=None)
        logger.info("  [schema_linking] rag 모드 — 후보 테이블=%s", candidates)
        return {
            "schema_candidates": candidates,
            "schema_candidate_details": candidate_details,
            "schema_text": schema_text,
            "question_embedding": embedding,
        }

    return schema_linking_node
