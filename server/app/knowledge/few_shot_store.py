"""domains/<domain>/few_shot.json 파일 자체의 CRUD — Qdrant 색인(qdrant_store.py)과는 별개다.

few_shot.json이 소스 오브 트루스이고 Qdrant sql_knowledge_{domain} 컬렉션은 거기서 파생된
검색 인덱스라는 전제(few_shot_seeder.py 참고)라서, 이 모듈은 순수하게 파일만 다루고
Qdrant를 건드리지 않는다 — "지금 화면에 반영된 상태인지"는 호출하는 쪽(API 라우트)이
qdrant_store.list_all()과 대조해서 판단한다.
"""
import json
import uuid
from datetime import datetime, timezone

from app.domain.loader import DomainConfig


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_entries(domain: DomainConfig) -> list[dict]:
    """few_shot.json을 읽는다. id가 없는 옛 항목(수동으로 작성된 초기 시드 등)은 여기서
    한 번만 id를 채워 파일에 다시 써준다 — 이후 모든 CRUD/반영상태 조회가 id 기준으로
    동작하려면 모든 항목에 id가 있어야 한다."""
    if not domain.few_shot_path.is_file():
        return []

    entries = json.loads(domain.few_shot_path.read_text())
    backfilled = False
    for e in entries:
        if not e.get("id"):
            e["id"] = str(uuid.uuid4())
            backfilled = True
        e.setdefault("source_run_id", None)
        e.setdefault("added_at", None)
        e.setdefault("sql_before_edit", None)
        e.setdefault("correction_reason", None)

    if backfilled:
        _write(domain, entries)

    return entries


def _write(domain: DomainConfig, entries: list[dict]) -> None:
    domain.few_shot_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2) + "\n")


def add_entry(domain: DomainConfig, *, question: str, intent: str, sql: str,
              tables: list[str], source_run_id: str | None,
              sql_before_edit: str | None = None, correction_reason: str | None = None) -> dict:
    entries = list_entries(domain)
    entry = {
        "id": str(uuid.uuid4()),
        "question": question,
        "intent": intent,
        "sql": sql,
        "tables": tables,
        "metrics": [],
        "domain": domain.name,
        "source_run_id": source_run_id,
        "sql_before_edit": sql_before_edit,
        "correction_reason": correction_reason,
        "added_at": _now_iso(),
    }
    entries.append(entry)
    _write(domain, entries)
    return entry


def delete_entry(domain: DomainConfig, entry_id: str) -> bool:
    entries = list_entries(domain)
    remaining = [e for e in entries if e["id"] != entry_id]
    if len(remaining) == len(entries):
        return False
    _write(domain, remaining)
    return True
