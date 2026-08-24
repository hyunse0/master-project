import logging
import re

import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)


def canonicalize(sql: str, dialect: str = "postgres") -> str:
    """SQL을 정규화하여 임베딩 품질을 높인다.

    - alias 제거 → table.column 명시
    - 키워드 대문자, 식별자 소문자
    - 불필요한 공백·개행 정리
    - 파싱 실패 시 원본 소문자 반환
    """
    try:
        parsed = sqlglot.parse_one(sql, dialect=dialect)
        normalized = _expand_aliases(parsed)
        result = normalized.sql(dialect=dialect, pretty=False)
        result = re.sub(r"\s+", " ", result).strip()
        logger.debug("canonicalize: %s → %s", sql[:60], result[:60])
        return result
    except Exception as e:
        logger.warning("SQL 정규화 실패 (원본 반환): %s", e)
        return re.sub(r"\s+", " ", sql).strip()


def _expand_aliases(tree: exp.Expression) -> exp.Expression:
    """FROM/JOIN 절의 테이블 alias를 실제 테이블명으로 치환한다."""
    alias_map: dict[str, str] = {}

    for table in tree.find_all(exp.Table):
        if table.alias:
            alias_map[table.alias] = table.name

    if not alias_map:
        return tree

    for col in tree.find_all(exp.Column):
        if col.table and col.table in alias_map:
            col.set("table", exp.to_identifier(alias_map[col.table]))

    for table in tree.find_all(exp.Table):
        if table.alias:
            table.set("alias", None)

    return tree


def build_embedding_text(
    question:   str,
    intent:     str,
    tables:     list[str],
    metrics:    list[str],
    domain:     str,
    task_type:  str       = "",
    dimensions: list[str] | None = None,
) -> str:
    """sql_knowledge 레코드를 임베딩할 텍스트를 구성한다."""
    parts = [
        f"question: {question}",
        f"intent: {intent}",
        f"tables: {' '.join(tables)}",
        f"metrics: {' '.join(metrics)}",
        f"domain: {domain}",
    ]
    if task_type:
        parts.append(f"task_type: {task_type}")
    if dimensions:
        parts.append(f"dimensions: {' '.join(dimensions)}")
    return "\n".join(parts)
