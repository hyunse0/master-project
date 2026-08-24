"""domains/<domain>/few_shot.json을 읽어 Qdrant sql_knowledge_{domain} 컬렉션에 색인한다.
사용: python scripts/seed_few_shot.py --domain <name>
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.domain.loader import get_domain  # noqa: E402
from app.embedding.embedder import EmbeddingEngine  # noqa: E402
from app.knowledge.qdrant_store import QdrantFewShotStore, SqlKnowledgeEntry  # noqa: E402
from app.sql.canonicalizer import build_embedding_text, canonicalize  # noqa: E402


def seed(domain_name: str) -> int:
    domain = get_domain(domain_name)
    if not domain.few_shot_path.is_file():
        print(f"[{domain_name}] few_shot.json 없음 ({domain.few_shot_path}) — 스킵")
        return 0

    items = json.loads(domain.few_shot_path.read_text())
    embedder = EmbeddingEngine()
    store = QdrantFewShotStore(domain.qdrant_fewshot_collection)

    count = 0
    for item in items:
        canonical_sql = canonicalize(item["sql"], dialect="postgres")
        embed_text = build_embedding_text(
            item["question"], item.get("intent", ""), item.get("tables", []),
            item.get("metrics", []), item.get("domain", domain_name),
        )
        embedding = embedder.embed(embed_text)
        entry = SqlKnowledgeEntry(
            question=item["question"],
            intent=item.get("intent", ""),
            canonical_sql=canonical_sql,
            tables=item.get("tables", []),
            metrics=item.get("metrics", []),
            domain=item.get("domain", domain_name),
        )
        store.add(entry, embedding)
        count += 1

    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    count = seed(args.domain)
    domain = get_domain(args.domain)
    print(f"[{args.domain}] {count}건을 few-shot 컬렉션({domain.qdrant_fewshot_collection})에 저장했습니다.")


if __name__ == "__main__":
    main()
