"""스키마 후보 검토 노드.

review_config.schema가 꺼져 있으면(자동 모드) 검토 없이 schema_candidates를 그대로
확정한다. 켜져 있으면 interrupt()로 멈춘다 — schema_linking_node(작업, LLM/DB 호출)와
분리해둔 이유가 여기 있다: interrupt() 재개 시 이 노드만 재실행되고 비용이 큰
schema_linking은 재실행되지 않는다(계획 문서 section 5.1).

interrupt()에 넘기는 값은 최소 마커면 충분하다 — 검토 화면이 실제로 필요로 하는 데이터
(schema_candidates/schema_candidate_details)는 이미 GraphState에 있고, API 레이어가
graph.get_state()로 그 state를 직접 읽어 응답을 구성한다(중복 저장 안 함).
"""
from langgraph.types import interrupt

from app.graph.state import GraphState


def schema_review_node(state: GraphState) -> dict:
    if not (state.get("review_config") or {}).get("schema"):
        return {"confirmed_schema": state.get("schema_candidates", [])}

    confirmed = interrupt("review_schema")
    return {"confirmed_schema": confirmed}
