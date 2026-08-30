"""SQL 검토 노드.

review_config.sql이 꺼져 있으면(자동 모드) 검토 없이 생성된 SQL을 그대로 확정한다.
켜져 있으면 interrupt()로 멈춘다. 재개 시점이 정확히 이 노드이므로, 사용자가 수정한
SQL은 sql_generation_node를 다시 타지 않고(=재작성으로 덮이지 않고) 곧바로
validation_node로 흘러 반드시 검증을 통과해야 한다(계획 문서 section 5.4).

validation/execution 실패 후에도(review_config.sql이 켜져 있으면 build.py의 라우팅이
sql_generation 대신 여기로 되돌린다) 같은 노드가 재진입되므로 별도 분기 없이
"최초 검토"와 "실패 후 재검토"를 동일하게 처리한다 — 둘 다 "지금 state의 sql을 보여주고
사람이 확정한 값을 받는다"는 점에서 같은 동작이기 때문이다.
"""
from langgraph.types import interrupt

from app.graph.state import GraphState


def sql_review_node(state: GraphState) -> dict:
    if not (state.get("review_config") or {}).get("sql"):
        return {}

    edited_sql = interrupt("review_sql")
    return {"sql": edited_sql}
