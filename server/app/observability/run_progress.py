"""실행 중인 run이 지금 어느 노드를 지나는지, 그리고 지금까지 찍힌 로그가 무엇인지
추적하는 인메모리 상태.

POST /runs·resume은 동기 호출이라(app/api/run_routes.py) 요청이 떠 있는 동안 클라이언트가
"지금 어느 노드인지", "지금까지 무슨 로그가 찍혔는지" 알 방법이 없었다 — 그래서
build_graph가 각 노드를 이 모듈로 감싸 실행 시작 시점의 노드 이름을 run_id별로 기록해두고,
run_routes.py는 capture_run_logs()가 만든 로그 버퍼(list, 실행 중에도 계속 append됨)의
참조를 그대로 등록해둔다. 프론트는 GET /runs/{id}/progress를 별도로 폴링해 이 값들을
읽는다 — 리스트는 그래프를 실행하는 스레드가 계속 append하는 같은 객체라 폴링 스레드가
읽는 시점의 스냅샷이 곧 "지금까지 실행된 만큼"의 로그가 된다. eval_routes.py의 job dict와
같은 전제로 락 없는 dict를 쓴다 — 재시작하면 날아가지만 진행 상황 표시일 뿐 정답 데이터가
아니므로 문제 없다.
"""
_CURRENT_NODE: dict[str, str] = {}
_LOG_BUFFERS: dict[str, list[dict]] = {}


def set_current_node(run_id: str | None, node_name: str) -> None:
    if run_id:
        _CURRENT_NODE[run_id] = node_name


def get_current_node(run_id: str) -> str | None:
    return _CURRENT_NODE.get(run_id)


def set_log_buffer(run_id: str, buffer: list[dict]) -> None:
    _LOG_BUFFERS[run_id] = buffer


def get_logs(run_id: str) -> list[dict]:
    return _LOG_BUFFERS.get(run_id, [])


def clear(run_id: str) -> None:
    _CURRENT_NODE.pop(run_id, None)
    _LOG_BUFFERS.pop(run_id, None)
