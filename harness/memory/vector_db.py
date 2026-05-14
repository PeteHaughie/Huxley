from __future__ import annotations
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.config import Settings


class VectorMemory:
    def __init__(self, path: Path, collection_name: str = "interlink"):
        self.path = path
        self.path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.path),
            settings=Settings(anonymized_telemetry=False),
        )
        self._col = self._client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def store(self, key: str, text: str, metadata: Optional[dict] = None):
        self._col.add(
            documents=[text],
            metadatas=[metadata or {}],
            ids=[key],
        )

    def recall(self, query: str, n: int = 5) -> list[dict]:
        results = self._col.query(
            query_texts=[query],
            n_results=n,
        )
        out = []
        for i, doc in enumerate(results["documents"][0]):
            out.append({
                "text": doc,
                "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                "distance": results["distances"][0][i] if results["distances"] else 0.0,
            })
        return out

    def count(self) -> int:
        return self._col.count()
