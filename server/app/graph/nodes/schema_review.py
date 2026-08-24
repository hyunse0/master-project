"""스키마 후보 검토 노드.

B(자동 모드)에서는 검토 없이 schema_candidates를 그대로 확정한다. C(human-in-the-loop)에서
이 노드 본문을 interrupt() 호출로 교체한다 — schema_linking_node(작업, LLM/DB 호출)와
분리해둔 이유가 여기 있다: interrupt() 재개 시 이 노드만 재실행되고 비용이 큰 schema_linking은
재실행되지 않는다(계획 문서 section 5.1).
"""
from app.graph.state import GraphState


def schema_review_node(state: GraphState) -> dict:
    return {"confirmed_schema": state.get("schema_candidates", [])}
