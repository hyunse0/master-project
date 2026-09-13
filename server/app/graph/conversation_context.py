"""턴 사이 대화 맥락 조립 — app/api/run_routes.py와 eval/execution_accuracy.py가 공유한다.

멀티턴 설계의 핵심 결정: LangGraph 체크포인터의 thread_id는 지금처럼 턴(run)마다 새로
발급하고(interrupt/resume 로직 무변경), "직전 턴에서 무엇을 이어받을지"는 체크포인트 이월이
아니라 직전 턴의 완료 상태에서 다음 턴의 GraphState 입력으로 명시 주입한다.

extract_prior_turn()이 "완료된 턴에서 어떤 필드를 뽑아 다음 턴에 넘기는가"라는 핵심 로직이고,
API/eval 두 갈래가 반드시 이 함수 하나를 공유해야 한다 — 각자 구현하면 eval이 실서비스와
다른 걸 재게 된다. 두 갈래가 이 함수에 넘기는 "완료된 턴" 표현만 다르다: API는
run_manager에 영속화된 state_snapshot(build_prior_turns)을, eval은 graph.invoke()가 방금
반환한 GraphState를 메모리에서 그대로 쓴다(골든셋 실행마다 runs/conversations 테이블에
가짜 기록을 남기지 않기 위해) — 두 표현 모두 confirmed_schema/sql/summary/task_type 등
같은 키 이름을 쓰므로(GraphState 필드 == API 응답 필드) extract_prior_turn()은 어느 쪽을
받아도 동일하게 동작한다.
"""
from app.runs import run_manager


def extract_prior_turn(question: str, snapshot: dict) -> dict:
    """완료된 턴 하나(question + GraphState 또는 그와 동일한 shape의 dict)에서 다음 턴
    프롬프트에 필요한 최소 정보만 뽑는다."""
    return {
        "question": question,
        "confirmed_schema": snapshot.get("confirmed_schema") or [],
        "confirmed_columns": snapshot.get("confirmed_columns") or {},
        "sql": snapshot.get("sql"),
        "summary": snapshot.get("summary"),
        "task_type": snapshot.get("task_type"),
    }


def build_prior_turns(conversation_id: str | None) -> list[dict]:
    """API 전용 — run_manager에 영속화된 직전 1턴을 읽어 extract_prior_turn()으로 변환한다.
    직전 턴이 없거나 success로 끝나지 않았으면(검토 대기·실패·진행 중) 이어받을 확정 결과가
    없으므로 빈 리스트를 반환한다."""
    if not conversation_id:
        return []
    last = run_manager.get_last_turn(conversation_id)
    if not last or last["status"] != "success":
        return []
    return [extract_prior_turn(last["question"], last["state_snapshot"] or {})]


def next_turn_meta(conversation_id: str | None) -> tuple[int, str | None]:
    """(turn_no, parent_run_id)를 계산한다. 직전 턴이 미완료 상태여도 턴 번호는 이어간다 —
    "몇 번째 시도인가"가 아니라 "몇 번째 질문인가"를 세는 것이기 때문이다."""
    if not conversation_id:
        return 1, None
    last = run_manager.get_last_turn(conversation_id)
    if not last:
        return 1, None
    return last["turn_no"] + 1, last["run_id"]
