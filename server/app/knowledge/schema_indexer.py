"""schema_provider의 introspection 결과를 임베딩해 Qdrant schema_{domain} 컬렉션에 색인한다.
"접속 정보만 주면 스키마를 읽어 RAG를 구축한다"의 나머지 절반.
사용: python app/knowledge/schema_indexer.py --domain <name>
"""
import argparse
import logging
import sys
from pathlib import Path

from qdrant_client.models import Distance, PointStruct, VectorParams

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.domain.loader import get_domain  # noqa: E402
from app.embedding.embedder import EmbeddingEngine  # noqa: E402
from app.knowledge.qdrant_connection import get_qdrant_client  # noqa: E402
from app.sql.schema_provider import SchemaProvider  # noqa: E402

logger = logging.getLogger(__name__)


def build_schema_index(domain_name: str) -> int:
    domain = get_domain(domain_name)
    provider = SchemaProvider(domain.connection)
    embedder = EmbeddingEngine()
    client = get_qdrant_client()

    tables = provider.get_all_tables()
    if not tables:
        logger.warning("색인할 테이블이 없습니다 (domain=%s)", domain_name)
        return 0

    texts = [provider.table_to_text(t) for t in tables]
    vectors = embedder.embed_batch(texts)

    collection = domain.qdrant_schema_collection
    if client.collection_exists(collection):
        client.delete_collection(collection)
    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=len(vectors[0]), distance=Distance.COSINE),
    )

    points = [
        PointStruct(
            id=i,
            vector=vectors[i],
            payload={
                "table": tables[i].full_name,
                "schema": tables[i].schema,
                "name": tables[i].name,
                "comment": tables[i].comment,
                "text": texts[i],
                "columns": [c.name for c in tables[i].columns],
            },
        )
        for i in range(len(tables))
    ]
    client.upsert(collection_name=collection, points=points)
    logger.info("스키마 인덱싱 완료: domain=%s collection=%s tables=%d", domain_name, collection, len(points))
    return len(points)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    count = build_schema_index(args.domain)
    print(f"[{args.domain}] {count}개 테이블을 스키마 인덱스({get_domain(args.domain).qdrant_schema_collection})에 저장했습니다.")


if __name__ == "__main__":
    main()
