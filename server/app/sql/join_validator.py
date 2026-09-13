"""SQL의 JOIN 구조가 카티션 곱(cartesian product)을 유발하지 않는지 정적으로 검증한다.

schema_citation_validator.py와 같은 성격(sqlglot AST만 사용, DB 조회 불필요)의 저비용
게이트 — "기술적 깊이가 아쉽다(join 시 성능 보장이 중요)" 피드백에 대한 1단계 대응이다.
join 성능 자체(실행계획 비용)는 대상 DB의 EXPLAIN이 필요해 별도 실험으로 분리했고, 여기서는
그보다 먼저 잡을 수 있는 "조인 조건 자체가 빠진" 구조적 버그만 잡는다 — 조건 없는 콤마 조인이나
ON/USING 없는 JOIN은 의도치 않은 카티션 곱으로 이어져 결과가 폭발적으로 부풀거나(성능) 완전히
틀린 행 조합을 만들기(정확도) 때문에 두 문제의 교집합이다.
"""
import logging
from dataclasses import dataclass, field

import sqlglot
import sqlglot.expressions as exp

logger = logging.getLogger(__name__)


@dataclass
class JoinValidationResult:
    ok:           bool
    disconnected: list[str] = field(default_factory=list)  # 조건 없이 붕 떠 있는 테이블/별칭
    feedback:     str = ""


def validate_joins(sql: str) -> JoinValidationResult:
    """SELECT 스코프(서브쿼리·CTE 각각 자기 FROM/JOIN만 본다)마다 카티션 조인 여부를 검사한다.

    파싱 자체가 실패하면 여기서 실패시키지 않는다 — schema_citation_validator가 먼저
    돌며 같은 파싱 실패를 이미 더 적합한 메시지로 잡아준다(이중 실패 메시지 방지).
    """
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except Exception:
        return JoinValidationResult(ok=True)

    disconnected: list[str] = []
    for select in tree.find_all(exp.Select):
        disconnected.extend(_disconnected_tables(select))

    if not disconnected:
        return JoinValidationResult(ok=True)

    ordered = sorted(set(disconnected))
    feedback = (
        "다음 테이블이 다른 테이블과 JOIN 조건(ON/USING) 없이 나열되어 있어 카티션 곱"
        "(예상보다 훨씬 많은 행 조합)이 발생할 수 있습니다. 의도한 조인이라면 JOIN ... ON"
        " 조건이나 WHERE 등가조건으로 다른 테이블과의 연결관계를 명시하세요:\n"
        + "\n".join(f"  - {t}" for t in ordered)
    )
    logger.warning("join 검증 실패: %s", ordered)
    return JoinValidationResult(ok=False, disconnected=ordered, feedback=feedback)


def _disconnected_tables(select: exp.Select) -> list[str]:
    from_ = select.args.get("from_")
    if from_ is None:
        return []

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    nodes: list[str] = []
    cross_nodes: set[str] = set()

    def node_id(table_expr: exp.Expression) -> str | None:
        alias = table_expr.alias
        if alias:
            return alias.lower()
        if isinstance(table_expr, exp.Table) and table_expr.name:
            return table_expr.name.lower()
        return None

    primary_id = node_id(from_.this)
    if primary_id:
        nodes.append(primary_id)
        parent[primary_id] = primary_id

    for j in select.args.get("joins") or []:
        jid = node_id(j.this)
        if not jid:
            continue
        parent.setdefault(jid, jid)
        nodes.append(jid)

        kind = (j.args.get("kind") or "").upper()
        if kind == "CROSS":
            cross_nodes.add(jid)  # 명시적 CROSS JOIN은 의도된 것으로 보고 연결 요구 대상에서 제외
            continue

        cond = j.args.get("on")
        has_condition = cond is not None or j.args.get("using") is not None
        if not has_condition:
            continue  # 조건 없음 — 아래 WHERE 등가조건 검사에서 구제될 여지만 남기고 그대로 둠

        referenced = _table_refs(cond) if cond else set()
        referenced.discard(jid)
        connected_to = [r for r in referenced if r in parent]
        if connected_to:
            for r in connected_to:
                union(jid, r)
        else:
            union(jid, primary_id or jid)

    # 콤마 조인(구식) 스타일은 WHERE의 최상위 AND 등가조건으로 연결될 수 있다
    where = select.args.get("where")
    if where is not None:
        for eq in _flatten_and(where.this):
            if not isinstance(eq, exp.EQ):
                continue
            refs = [r for r in _table_refs(eq) if r in parent]
            for r in refs[1:]:
                union(refs[0], r)

    real_nodes = [n for n in nodes if n not in cross_nodes]
    if len(real_nodes) <= 1:
        return []
    root = find(real_nodes[0])
    return [n for n in real_nodes[1:] if find(n) != root]


def _flatten_and(expr: exp.Expression):
    if isinstance(expr, exp.And):
        yield from _flatten_and(expr.left)
        yield from _flatten_and(expr.right)
    else:
        yield expr


def _table_refs(expr: exp.Expression) -> set[str]:
    return {col.table.lower() for col in expr.find_all(exp.Column) if col.table}
