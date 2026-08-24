import os

from qdrant_client import QdrantClient


def get_qdrant_client() -> QdrantClient:
    url = os.environ.get("QDRANT_URL", "http://localhost:6333")
    return QdrantClient(url=url)
