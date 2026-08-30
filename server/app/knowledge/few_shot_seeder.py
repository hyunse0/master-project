"""domains/<domain>/few_shot.json → Qdrant sql_knowledge_{domain} 색인.

scripts/seed_few_shot.py(CLI)와 app/api/fewshot_routes.py(화면의 "Qdrant에 반영" 버튼)가
같은 로직을 쓰도록 여기 한 곳에 모아둔다. 멱등 — 매번 컬렉션을 통째로 지우고 다시 채운다
(few_shot.json이 소스 오브 트루스이므로 add-only로 누적하면 재실행할 때마다 중복이 쌓인다).

각 항목의 Qdrant point id는 few_shot.json 항목의 id를 그대로 쓴다 — "이 파일 항목이 지금
Qdrant에 실제로 반영돼 있는가"를 화면에서 정확히 보여주려면(app/knowledge/few_shot_store.py
참고) 둘의 id가 일치해야 한다.
"""
from app.domain.loader import get_domain
from app.embedding.embedder import EmbeddingEngine
from app.knowledge import few_shot_store
from app.knowledge.qdrant_store import QdrantFewShotStore, SqlKnowledgeEntry
from app.sql.canonicalizer import build_embedding_text, canonicalize


def seed_domain(domain_name: str) -> int:
    domain = get_domain(domain_name)
    items = few_shot_store.list_entries(domain)
    if not items:
        return 0

    embedder = EmbeddingEngine()
    store = QdrantFewShotStore(domain.qdrant_fewshot_collection)
    store.clear()

    for item in items:
        canonical_sql = canonicalize(item["sql"], dialect="postgres")
        embed_text = build_embedding_text(
            item["question"], item.get("intent", ""), item.get("tables", []),
            item.get("metrics", []), item.get("domain", domain_name),
        )
        embedding = embedder.embed(embed_text)
        entry = SqlKnowledgeEntry(
            id=item.get("id"),
            question=item["question"],
            intent=item.get("intent", ""),
            canonical_sql=canonical_sql,
            tables=item.get("tables", []),
            metrics=item.get("metrics", []),
            domain=item.get("domain", domain_name),
        )
        store.add(entry, embedding)

    return len(items)
