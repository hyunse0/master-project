"""의도 분류가 모호할 때 사용자에게 되묻는 노드(F단계, review_config.intent 게이트).

schema_review/sql_review와 같은 성격의 human-in-the-loop다 — review_config.intent가 꺼져
있으면(기본값) intent_node가 needs_clarification=True를 냈어도 멈추지 않고 그대로 통과한다
(schema_review/sql_review의 off-path와 동일: 자동으로 최선을 다해 진행). eval/CLI 경로가
review_config={"schema": False, "sql": False}만 넘기던 기존 관례를 그대로 따르면 이 게이트도
자동으로 꺼진 채 동작하므로, checkpointer=None인 eval/CLI 실행이 interrupt() 때문에 깨지는
일이 없다.

게이트가 켜져 있고 needs_clarification=True면 interrupt()로 멈춰 사용자 답변을 받고,
`intent_node`로 되돌아가 답변을 반영해 재분류한다(build.py의 조건부 엣지). 무한 재질의를
막기 위해 clarification_rounds로 1회만 허용 — 상한에 도달하면 이 노드도 그냥 통과시켜
intent_node가 마지막으로 낸 분류 결과 그대로 진행한다(다른 재시도 로직들과 같은 fail-safe
철학: 사람이 안 도와줘도 파이프라인이 멈추지 않는다).
"""
from langgraph.types import interrupt

from app.graph.state import GraphState

_MAX_CLARIFICATION_ROUNDS = 1


def intent_clarification_node(state: GraphState) -> dict:
    if not (state.get("review_config") or {}).get("intent"):
        return {}
    if not state.get("needs_clarification"):
        return {}
    if state.get("clarification_rounds", 0) >= _MAX_CLARIFICATION_ROUNDS:
        return {}

    answer = interrupt(state.get("clarification_question") or "추가 정보가 필요합니다.")
    return {
        "clarification_answer": answer,
        "clarification_rounds": state.get("clarification_rounds", 0) + 1,
    }
