"""터미널에 실제로 찍히는 로그 레코드를 run 단위로 캡처해 실행 로그 패널에 노출한다.

root 로거는 이미 (mcp/fastmcp 의존성이 임포트 시점에 붙여둔) RichHandler로 INFO 이상을
stderr에 찍고 있다 — app.* 노드 로그뿐 아니라 httpx의 "HTTP Request: ..." 같은 실제
LLM/Qdrant 호출 로그도 여기 포함된다. 그 구성을 건드리지 않고 root에 캡처 전용 핸들러를
하나 더 얹어서 "터미널에 보이는 것과 동일한 레코드"를 그대로 가로챈다 — 별도 포맷터나
propagate=False 같은 걸 걸면 터미널 출력 자체가 달라져 버리므로 하지 않는다.

graph.invoke()가 동기 호출이고 FastAPI가 각 sync 핸들러를 스레드풀의 개별 스레드에서
돌리므로(Starlette가 contextvars.copy_context()로 컨텍스트를 그대로 넘겨줌), 전역 핸들러
하나를 root 로거에 항상 붙여두고 ContextVar로 "지금 이 스레드가 어느 run의 버퍼에 쓰고
있는지"만 구분한다 — 동시에 여러 run이 돌아도 로그가 섞이지 않는다.
"""
import contextlib
import contextvars
import datetime
import logging

_LEVEL_MAP = {"WARNING": "warn", "CRITICAL": "error"}

_current_buffer: contextvars.ContextVar[list[dict] | None] = contextvars.ContextVar(
    "run_log_buffer", default=None,
)


class _RunLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        buffer = _current_buffer.get()
        if buffer is None:
            return
        buffer.append({
            "ts": datetime.datetime.fromtimestamp(record.created).strftime("%H:%M:%S.%f")[:-3],
            "level": _LEVEL_MAP.get(record.levelname, record.levelname.lower()),
            "msg": record.getMessage(),
        })


_installed = False


def _install_capture_handler() -> None:
    """root에 캡처 핸들러를 붙인다 — 모듈 임포트 시점이 아니라 capture_run_logs()가 처음
    쓰일 때(=요청이 들어온 뒤, 곧 서버 startup이 끝난 뒤) 지연 설치한다. mcp 패키지가
    MCPServer(...) 생성 시점에 logging.basicConfig(handlers=[RichHandler()])를 호출하는데,
    basicConfig는 "root에 핸들러가 이미 있으면 아무것도 안 하는" 동작이라 우리가 먼저
    붙어버리면 그 RichHandler 설치 자체를 막아 터미널 출력이 통째로 사라진다 — 그래서 앱
    초기화가 다 끝난 뒤에만 안전하게 추가한다."""
    global _installed
    if _installed:
        return
    _installed = True

    root_logger = logging.getLogger()
    # 이 앱에서는 mcp 의존성이 이미 root를 INFO로 맞춰두지만, 그 부수효과에만 기대지 않도록
    # 더 낮은(예: 기본 WARNING) 상태라면 여기서도 명시적으로 올려둔다 — DEBUG처럼 누군가
    # 의도적으로 더 상세히 켜둔 경우는 그대로 존중한다.
    if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
        root_logger.setLevel(logging.INFO)
    root_logger.addHandler(_RunLogHandler(level=logging.INFO))


@contextlib.contextmanager
def capture_run_logs():
    """with 블록 동안 (터미널에 찍히는 것과 동일한) 로그 레코드를 리스트 하나에 모아 yield한다."""
    _install_capture_handler()
    buffer: list[dict] = []
    token = _current_buffer.set(buffer)
    try:
        yield buffer
    finally:
        _current_buffer.reset(token)
