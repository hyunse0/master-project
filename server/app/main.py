from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.domain_routes import router as domain_router

app = FastAPI(title="Data Access Copilot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(domain_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
