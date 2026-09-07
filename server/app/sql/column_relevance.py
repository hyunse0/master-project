"""컬럼 단위 관련도 분류 — 테이블 전체 컬럼 중 질문과 관련된 컬럼만 상세 노출하고
나머지는 이름만 압축해서 보여주기 위한 티어링.

PK/FK(key)는 조인이 끊기면 SQL 자체가 불가능해지므로 관련도와 무관하게 항상 상세
노출한다. 나머지 컬럼은 질문 임베딩과의 코사인 유사도로 상위 N개(relevant)만 상세
노출하고, 그 외(other)는 이름만 남긴다 — 완전히 숨기지는 않는다: SQL 생성 LLM이
필요하면 여전히 참조할 수 있고, schema_citation_validator가 사후에 존재 여부를
검증해준다.

schema_linking_node(테이블 후보 전체)와 schema_review_node(후보 밖 테이블 폴백)가
이 모듈을 공유한다 — 별도 Qdrant 컬렉션이나 재색인 없이, 이미 확보된 질문 임베딩과
EmbeddingEngine.embed_batch()만으로 즉석에서 계산한다(레포에 numpy 의존성이 없고
컬럼 수가 적어 순수 파이썬 코사인 계산으로 충분하다).
"""
from dataclasses import dataclass, field

from app.embedding.embedder import EmbeddingEngine
from app.sql.schema_provider import ColumnInfo, TableInfo

_TOP_N_RELEVANT_COLUMNS = 8
_RELEVANCE_FLOOR_SCORE = 0.15

_OTHER_TIER_NOTE = "이름만 제공 — 타입/설명 없음, 실제 사용 전 존재 여부를 확인하세요"


@dataclass
class ColumnTiers:
    key: list[str] = field(default_factory=list)
    relevant: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _column_embed_text(col: ColumnInfo) -> str:
    return f"{col.name}: {col.comment}" if col.comment else col.name


def _key_column_names(table: TableInfo) -> set[str]:
    return {c.name for c in table.columns if c.is_primary_key} | {fk.column for fk in table.foreign_keys}


def classify_columns_for_tables(
    tables: list[TableInfo],
    question_embedding: list[float],
    embedder: EmbeddingEngine,
) -> dict[str, tuple[ColumnTiers, dict[str, float]]]:
    """테이블별 컬럼을 key/relevant/other로 분류한다.

    non-key 컬럼 임베딩은 테이블 경계와 무관하게 한 번에 모아 embed_batch()로 배치
    처리한다 — 테이블 수만큼 임베딩 호출을 반복하지 않기 위해서다. 반환값의 score
    맵에는 relevant/other 구분 없이 모든 non-key 컬럼의 점수가 담긴다 — 검토 화면이
    "기타" 컬럼을 펼쳤을 때도 점수 힌트를 보여줄 수 있도록.
    """
    non_key_by_table: dict[str, list[ColumnInfo]] = {}
    flat_cols: list[ColumnInfo] = []
    for table in tables:
        key_names = _key_column_names(table)
        non_key = [c for c in table.columns if c.name not in key_names]
        non_key_by_table[table.full_name] = non_key
        flat_cols.extend(non_key)

    vectors = embedder.embed_batch([_column_embed_text(c) for c in flat_cols]) if flat_cols else []
    score_by_id = {id(c): _cosine(question_embedding, v) for c, v in zip(flat_cols, vectors)}

    result: dict[str, tuple[ColumnTiers, dict[str, float]]] = {}
    for table in tables:
        key = [c.name for c in table.columns if c.name in _key_column_names(table)]
        non_key = non_key_by_table[table.full_name]
        scored = sorted(((c.name, score_by_id[id(c)]) for c in non_key), key=lambda x: x[1], reverse=True)
        top_names = {name for name, score in scored[:_TOP_N_RELEVANT_COLUMNS] if score >= _RELEVANCE_FLOOR_SCORE}
        relevant = [c.name for c in non_key if c.name in top_names]
        other = [c.name for c in non_key if c.name not in top_names]
        result[table.full_name] = (
            ColumnTiers(key=key, relevant=relevant, other=other),
            dict(scored),
        )
    return result


def build_column_details(table: TableInfo, scores: dict[str, float]) -> dict[str, dict]:
    """schema_candidate_details[i]["column_details"] — 모든 컬럼(key 포함)의 상세.

    key 컬럼은 관련도 점수를 계산하지 않으므로 score는 None.
    """
    fk_columns = {fk.column for fk in table.foreign_keys}
    return {
        col.name: {
            "data_type": col.data_type,
            "comment": col.comment,
            "is_primary_key": col.is_primary_key,
            "is_foreign_key": col.name in fk_columns,
            "score": scores.get(col.name),
        }
        for col in table.columns
    }


def render_tiered_schema_block(
    table_name: str,
    comment: str | None,
    column_details: dict[str, dict],
    foreign_keys: list[dict],
    key_names: list[str],
    relevant_names: list[str],
    other_names: list[str],
) -> str:
    """key/relevant는 상세 라인, other는 이름만 압축한 한 줄로 렌더링한다.

    dict 기반 입력만 받는다 — schema_linking_node(방금 introspect한 TableInfo에서
    build_column_details()로 만든 dict)와 schema_review_node(Qdrant/state 캐시에
    이미 dict로 들어있는 값을 재조립 시점에 그대로 재사용) 양쪽 모두 매번 TableInfo를
    재구성하지 않고 이 렌더러를 공유할 수 있게 하기 위해서다. "설명 없음" 경고를
    텍스트 자체에 박아두는 이유는, 테이블 선정 프롬프트(_SELECT_PROMPT)가
    prompt_builder.py의 시스템 프롬프트 경고를 거치지 않기 때문이다.
    """
    fk_by_column = {fk["column"]: fk for fk in foreign_keys}

    def _detail_line(name: str) -> str:
        col = column_details[name]
        markers = []
        if col["is_primary_key"]:
            markers.append("PK")
        fk = fk_by_column.get(name)
        if fk:
            markers.append(f"FK -> {fk['ref_table']}.{fk['ref_column']}")
        marker = f" [{', '.join(markers)}]" if markers else ""
        comment_part = f" — {col['comment']}" if col["comment"] else ""
        return f"  {name}: {col['data_type']}{marker}{comment_part}"

    lines = [f"테이블: {table_name}" + (f" — {comment}" if comment else "")]
    lines.extend(_detail_line(name) for name in key_names)
    lines.extend(_detail_line(name) for name in relevant_names)
    if other_names:
        lines.append(f"  ({_OTHER_TIER_NOTE}: {', '.join(other_names)})")
    return "\n".join(lines)
