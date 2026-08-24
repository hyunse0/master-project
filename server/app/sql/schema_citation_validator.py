"""SQL에서 참조된 컬럼이 실제 DB 스키마에 존재하는지 검증한다."""
import logging
from dataclasses import dataclass, field

import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)


@dataclass
class CitationResult:
    ok:       bool
    missing:  list[str] = field(default_factory=list)  # "schema.table.column"
    feedback: str = ""


def validate_schema_citations(sql: str, conn) -> CitationResult:
    """SQL에 사용된 컬럼이 information_schema에 존재하는지 검증한다."""
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception as e:
        return CitationResult(ok=False, feedback=f"SQL 파싱 실패: {e}")

    cte_names = {cte.alias.lower() for cte in tree.find_all(exp.CTE)}
    alias_map = _build_alias_map(tree, cte_names)
    from_tables = [v for k, v in alias_map.items() if k == v[1]]  # alias==table
    select_aliases = _collect_select_aliases(tree)

    refs: set[tuple[str, str, str]] = set()
    for col in tree.find_all(exp.Column):
        col_name = col.name.lower()
        if not col_name or col_name == "*":
            continue
        tbl_ref = col.table.lower() if col.table else None
        if tbl_ref:
            if tbl_ref in cte_names:
                continue
            if tbl_ref in alias_map:
                schema, tbl = alias_map[tbl_ref]
                refs.add((schema, tbl, col_name))
        elif len(from_tables) == 1:
            if col_name in select_aliases:
                # ORDER BY/GROUP BY/HAVING이 SELECT 목록의 별칭을 참조하는 경우 —
                # 실제 테이블 컬럼이 아니라 information_schema에는 없는 게 정상이다.
                continue
            schema, tbl = from_tables[0]
            refs.add((schema, tbl, col_name))

    if not refs:
        return CitationResult(ok=True)

    missing = []
    try:
        with conn.cursor() as cur:
            for schema, tbl, col in refs:
                cur.execute(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s AND column_name = %s
                    LIMIT 1
                    """,
                    (schema, tbl, col),
                )
                if cur.fetchone() is None:
                    missing.append(f"{schema}.{tbl}.{col}")
    except Exception as e:
        logger.warning("schema citation 검증 중 오류: %s", e)
        try:
            conn.rollback()
        except Exception:
            pass
        return CitationResult(ok=True)  # 검증 실패 시 통과 (executor가 잡음)

    if missing:
        feedback = (
            "다음 컬럼이 스키마에 존재하지 않습니다. 올바른 컬럼명으로 재작성하세요:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
        logger.warning("schema citation 실패: %s", missing)
        return CitationResult(ok=False, missing=missing, feedback=feedback)

    return CitationResult(ok=True)


def _collect_select_aliases(tree: exp.Expression) -> set[str]:
    """SELECT 프로젝션 목록의 별칭(AS ...) 이름을 모은다.

    ORDER BY/GROUP BY가 테이블 컬럼이 아니라 이 별칭을 참조할 수 있어(예: ORDER BY
    patient_count), 그런 참조를 실제 컬럼 인용으로 오인해 거짓 실패를 내지 않기 위함.
    """
    aliases: set[str] = set()
    for select in tree.find_all(exp.Select):
        for proj in select.expressions:
            if isinstance(proj, exp.Alias):
                aliases.add(proj.alias.lower())
    return aliases


def _build_alias_map(
    tree: exp.Expression,
    cte_names: set[str],
) -> dict[str, tuple[str, str]]:
    """alias → (schema, table_name) 매핑."""
    alias_map: dict[str, tuple[str, str]] = {}
    for table in tree.find_all(exp.Table):
        tbl_name = table.name.lower()
        schema   = (table.db or "public").lower()
        alias    = (table.alias or tbl_name).lower()
        if tbl_name and tbl_name not in cte_names:
            alias_map[alias]    = (schema, tbl_name)
            alias_map[tbl_name] = (schema, tbl_name)
    return alias_map
