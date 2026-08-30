"""Few-shot 예제 관리 화면 전용 엔드포인트.

세 가지 상태를 오간다 — ① 후보(히스토리에서 사람이 SQL을 고쳐 승인했지만 아직 채택 안 함)
② 저장됨(few_shot.json엔 있지만 Qdrant엔 아직 미반영) ③ 반영됨(Qdrant에도 실제로 있어
지금 sql_generation이 참고 중). ①→②는 POST /fewshot/entries, ②→③은 POST /fewshot/seed다.

반영 여부는 별도 상태를 저장해두지 않고, 요청마다 Qdrant를 직접 조회해 few_shot.json
항목의 id가 거기 있는지로 판단한다 — 진실은 항상 Qdrant 쪽에 있고 이 라우트는 그걸
그대로 보여줄 뿐이다(app/knowledge/few_shot_seeder.py가 파일 id를 Qdrant point id로
그대로 쓰기 때문에 가능하다).
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.domain.loader import DomainConfig, get_domain
from app.knowledge import few_shot_store
from app.knowledge.few_shot_seeder import seed_domain
from app.knowledge.qdrant_store import QdrantFewShotStore
from app.runs import run_manager

router = APIRouter(prefix="/fewshot", tags=["fewshot"])


def _resolve_domain(domain_name: str | None) -> DomainConfig:
    try:
        return get_domain(domain_name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/candidates")
def list_candidates(domain: str | None = None) -> list[dict]:
    resolved = _resolve_domain(domain)
    already_added = {
        e["source_run_id"] for e in few_shot_store.list_entries(resolved) if e.get("source_run_id")
    }
    return [c for c in run_manager.list_edited_sql_runs(resolved.name) if c["run_id"] not in already_added]


@router.get("/entries")
def list_entries(domain: str | None = None) -> list[dict]:
    resolved = _resolve_domain(domain)
    entries = few_shot_store.list_entries(resolved)
    live_ids = {e.id for e in QdrantFewShotStore(resolved.qdrant_fewshot_collection).list_all(resolved.name)}
    return [{**e, "reflected": e["id"] in live_ids} for e in entries]


class AddEntryRequest(BaseModel):
    domain: str
    run_id: str


@router.post("/entries")
def add_entry(body: AddEntryRequest) -> dict:
    resolved = _resolve_domain(body.domain)
    row = run_manager.get(body.run_id)
    if row is None:
        raise HTTPException(404, "run을 찾을 수 없습니다")

    snapshot = row["state_snapshot"]
    if not snapshot.get("sql_edited"):
        raise HTTPException(400, "사람이 SQL을 직접 고쳐 승인한 run만 few-shot으로 채택할 수 있습니다")

    return few_shot_store.add_entry(
        resolved,
        question=row["question"],
        intent=snapshot.get("task_type") or "",
        sql=snapshot["sql"],
        tables=snapshot.get("confirmed_schema") or [],
        source_run_id=body.run_id,
        sql_before_edit=snapshot.get("sql_before_edit"),
        correction_reason=snapshot.get("correction_reason"),
    )


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, domain: str) -> dict:
    resolved = _resolve_domain(domain)
    if not few_shot_store.delete_entry(resolved, entry_id):
        raise HTTPException(404, "해당 id의 항목을 찾을 수 없습니다")
    return {"deleted": entry_id}


@router.post("/seed")
def seed(domain: str) -> dict:
    resolved = _resolve_domain(domain)
    count = seed_domain(resolved.name)
    return {"domain": resolved.name, "count": count}
