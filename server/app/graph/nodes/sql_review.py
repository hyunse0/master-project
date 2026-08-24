"""SQL 검토 노드. B(자동 모드)에서는 검토 없이 생성된 SQL을 그대로 확정한다.

C(human-in-the-loop)에서 이 노드 본문을 interrupt()로 교체한다. resume 시점이 정확히
이 노드이므로, 사용자가 수정한 SQL은 sql_generation_node를 다시 타지 않고(=재작성으로
덮이지 않고) 곧바로 validation_node로 흘러 반드시 검증을 통과해야 한다(계획 문서 section 5.4).
"""
from app.graph.state import GraphState


def sql_review_node(state: GraphState) -> dict:
    return {}
