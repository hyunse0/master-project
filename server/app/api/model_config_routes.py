"""모델 배포 선택 조회/저장. 비용 대시보드 화면의 "모델 설정" 패널이 쓴다.

저장 즉시 그래프 캐시(app/api/run_routes.py)를 비워, 앱 재시작 없이 다음 실행부터
새 배포명이 반영되게 한다.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.run_routes import clear_graph_cache
from app.llm.model_config import CHAT_OPTIONS, EMBEDDING_OPTIONS, get_model_config, set_model_config

router = APIRouter(tags=["model-config"])


class ModelConfigUpdate(BaseModel):
    chat_low:   str | None = None
    chat_high:  str | None = None
    chat_judge: str | None = None
    embedding:  str | None = None


@router.get("/model-config")
def read_model_config() -> dict:
    return {
        "options": {"chat": CHAT_OPTIONS, "embedding": EMBEDDING_OPTIONS},
        "current": get_model_config(),
    }


@router.put("/model-config")
def update_model_config(body: ModelConfigUpdate) -> dict:
    try:
        current = set_model_config(**body.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    clear_graph_cache()
    return {"options": {"chat": CHAT_OPTIONS, "embedding": EMBEDDING_OPTIONS}, "current": current}
