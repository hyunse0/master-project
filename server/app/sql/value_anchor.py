"""WHERE절 리터럴 값이 실제 DB 컬럼에 존재하는지 검증한다."""
import logging
from dataclasses import dataclass, field

import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)


@dataclass
class ValueAnchor:
    table_full:    str        # "schema.table"
    column:        str
    value:         str
    found:         bool
    actual_values: list[str] = field(default_factory=list)


@dataclass
class AnchorResult:
    ok:       bool
    anchors:  list[ValueAnchor] = field(default_factory=list)
    feedback: str = ""


def check_value_anchors(sql: str, conn) -> AnchorResult:
    """WHERE절 리터럴 값이 DB에 실제로 존재하는지 확인한다.

    존재하지 않으면 실제 DISTINCT 값을 조회해 피드백에 포함한다.
    """
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return AnchorResult(ok=True)  # 파싱 실패는 validator에서 처리

    cte_names  = {cte.alias.lower() for cte in tree.find_all(exp.CTE)}
    alias_map  = _build_alias_map(tree, cte_names)
    from_tables = [v for k, v in alias_map.items() if k == v[1]]

    filters = _extract_value_filters(tree, alias_map, cte_names, from_tables)
    if not filters:
        return AnchorResult(ok=True)

    anchors: list[ValueAnchor] = []
    with conn.cursor() as cur:
        for table_full, col, val in filters:
            found, actual = _probe_value(cur, table_full, col, val)
            anchors.append(ValueAnchor(
                table_full=table_full, column=col, value=val,
                found=found, actual_values=actual,
            ))

    failed = [a for a in anchors if not a.found]
    if not failed:
        return AnchorResult(ok=True, anchors=anchors)

    lines = ["WHERE절의 값이 실제 DB에 없습니다. 아래 실제 값으로 SQL을 재작성하세요:"]
    for a in failed:
        vals = ", ".join(f"'{v}'" for v in a.actual_values) if a.actual_values else "값 없음"
        lines.append(f"  - {a.table_full}.{a.column} = '{a.value}' → 실제 값: [{vals}]")

    logger.warning("value anchor 실패: %s", [(a.table_full, a.column, a.value) for a in failed])
    return AnchorResult(ok=False, anchors=anchors, feedback="\n".join(lines))


def has_value_filters(sql: str) -> bool:
    """SQL에 리터럴 값 필터(= '...' 또는 LIKE/ILIKE)가 있는지 확인한다."""
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return False
    for eq in tree.find_all(exp.EQ):
        if isinstance(eq.right, exp.Literal) and eq.right.is_string:
            return True
    for like in tree.find_all((exp.Like, exp.ILike)):
        if isinstance(like.expression, exp.Literal):
            return True
    return False


# 코드/명칭 컬럼 suffix — 잘못된 값이 박혔을 가능성이 높은 컬럼 패턴
_CODE_COLUMN_SUFFIXES = (
    "_cd", "_nm", "_kor_nm", "_eng_nm",
)
_CODE_COLUMN_EXACTS = frozenset(["dtl_cd_nm", "erp_dtl_cd"])


def _is_code_column(col_name: str) -> bool:
    col = col_name.lower()
    return col in _CODE_COLUMN_EXACTS or any(col.endswith(s) for s in _CODE_COLUMN_SUFFIXES)


def extract_code_column_filters(sql: str) -> list[dict]:
    """코드/명칭 컬럼(예: _cd, _nm, dtl_cd_nm)의 WHERE 리터럴 필터를 추출한다.

    Returns: [{"table": "schema.table", "column": "col", "value": "val"}, ...]
    ZERO_ROWS_WITH_VALUE_FILTER 판단 및 suspect_filter 구성에 사용.
    """
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return []

    cte_names   = {cte.alias.lower() for cte in tree.find_all(exp.CTE)}
    alias_map   = _build_alias_map(tree, cte_names)
    from_tables = [v for k, v in alias_map.items() if k == v[1]]
    filters     = _extract_value_filters(tree, alias_map, cte_names, from_tables)

    return [
        {"table": tbl, "column": col, "value": val}
        for tbl, col, val in filters
        if _is_code_column(col)
    ]


# ── internals ──────────────────────────────────────────────────


def _probe_value(
    cur,
    table_full: str,
    col: str,
    val: str,
) -> tuple[bool, list[str]]:
    """값 존재 여부 확인. 없으면 실제 DISTINCT 값 반환."""
    try:
        cur.execute(
            f'SELECT COUNT(*) FROM {table_full} WHERE "{col}" = %s',
            (val,),
        )
        found = cur.fetchone()[0] > 0
    except Exception as e:
        logger.debug("value probe 쿼리 실패 (%s.%s=%r): %s", table_full, col, val, e)
        try:
            cur.connection.rollback()
        except Exception:
            pass
        return True, []  # 쿼리 실패 시 통과

    if found:
        return True, []

    try:
        cur.execute(
            f'SELECT DISTINCT "{col}" FROM {table_full} WHERE "{col}" IS NOT NULL LIMIT 30',
        )
        actual = [str(r[0]) for r in cur.fetchall()]
    except Exception:
        try:
            cur.connection.rollback()
        except Exception:
            pass
        actual = []

    return False, actual


def _extract_value_filters(
    tree:        exp.Expression,
    alias_map:   dict,
    cte_names:   set[str],
    from_tables: list[tuple[str, str]],
) -> list[tuple[str, str, str]]:
    """(table_full, column, value) 트리플 추출."""
    results: list[tuple[str, str, str]] = []

    def _resolve(col_node: exp.Column) -> tuple[str, str] | None:
        col_name = col_node.name.lower()
        tbl_ref  = col_node.table.lower() if col_node.table else None
        if tbl_ref:
            if tbl_ref in cte_names:
                return None
            if tbl_ref in alias_map:
                schema, tbl = alias_map[tbl_ref]
                return f"{schema}.{tbl}", col_name
        elif len(from_tables) == 1:
            schema, tbl = from_tables[0]
            return f"{schema}.{tbl}", col_name
        return None

    for eq in tree.find_all(exp.EQ):
        col = eq.left  if isinstance(eq.left,  exp.Column)  else None
        lit = eq.right if isinstance(eq.right, exp.Literal) else None
        if col and lit and lit.is_string:
            resolved = _resolve(col)
            if resolved:
                results.append((resolved[0], resolved[1], lit.this))

    for like in tree.find_all((exp.Like, exp.ILike)):
        col = like.this       if isinstance(like.this,       exp.Column)  else None
        lit = like.expression if isinstance(like.expression, exp.Literal) else None
        if col and lit:
            raw_val = lit.this.strip("%")
            resolved = _resolve(col)
            if resolved and raw_val:
                results.append((resolved[0], resolved[1], raw_val))

    return results


def _build_alias_map(
    tree:      exp.Expression,
    cte_names: set[str],
) -> dict[str, tuple[str, str]]:
    alias_map: dict[str, tuple[str, str]] = {}
    for table in tree.find_all(exp.Table):
        tbl_name = table.name.lower()
        schema   = (table.db or "public").lower()
        alias    = (table.alias or tbl_name).lower()
        if tbl_name and tbl_name not in cte_names:
            alias_map[alias]    = (schema, tbl_name)
            alias_map[tbl_name] = (schema, tbl_name)
    return alias_map
