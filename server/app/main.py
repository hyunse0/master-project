from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.cost_routes import router as cost_router
from app.api.domain_routes import router as domain_router
from app.api.eval_routes import router as eval_router
from app.api.fewshot_routes import router as fewshot_router
from app.api.mcp import mcp_server
from app.api.model_config_routes import router as model_config_router
from app.api.run_routes import conversation_router, router as run_router

# streamable_http_path="/" + app.mount("/mcp", ...) 조합으로 최종 엔드포인트가 /mcp가
# 되도록 한다(기본값 그대로 마운트하면 /mcp/mcp로 이중 중첩된다).
_mcp_app = mcp_server.streamable_http_app(streamable_http_path="/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # _mcp_app(Starlette)은 session_manager.run()을 도는 자체 lifespan을 갖고 있는데,
    # FastAPI는 app.mount()로 붙인 하위 앱의 lifespan을 자동으로 실행해주지 않는다 —
    # 여기서 명시적으로 같이 걸어주지 않으면 /mcp 요청이 응답 없이 걸려있게 된다.
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(_mcp_app.router.lifespan_context(_mcp_app))
        yield


app = FastAPI(title="Data Access Copilot API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(domain_router)
app.include_router(fewshot_router)
app.include_router(run_router)
app.include_router(conversation_router)
app.include_router(cost_router)
app.include_router(eval_router)
app.include_router(model_config_router)
app.mount("/mcp", _mcp_app)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
