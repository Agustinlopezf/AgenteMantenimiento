"""Retriever denso del hito 1: embebe la pregunta y busca en el vector store."""

from __future__ import annotations

from troubleshooting_agent.retrieval.embeddings import Embedder
from troubleshooting_agent.retrieval.store import Filtros, Hit, VectorStore


class IndiceNoDisponible(RuntimeError):
    """No hay índice construido (o está vacío) para el corpus actual."""


class IndiceIncompatible(RuntimeError):
    """El índice se construyó con otro modelo de embeddings."""


class Retriever:
    def __init__(self, store: VectorStore, embedder: Embedder):
        meta = store.meta()
        if meta is None or store.count() == 0:
            raise IndiceNoDisponible(
                "No hay índice para este corpus. Correr: "
                "uv run python -m troubleshooting_agent.ingest && "
                "uv run python -m troubleshooting_agent.retrieval.index"
            )
        if meta.get("embedding_model") != embedder.nombre or meta.get("dim") != embedder.dim:
            raise IndiceIncompatible(
                f"El índice se construyó con {meta.get('embedding_model')!r} (dim {meta.get('dim')}) "
                f"y EMBEDDING_MODEL es {embedder.nombre!r} (dim {embedder.dim}). "
                "Reindexar: uv run python -m troubleshooting_agent.retrieval.index"
            )
        self.store = store
        self.embedder = embedder

    def buscar(self, pregunta: str, k: int, filtros: Filtros | None = None) -> list[Hit]:
        vector = self.embedder.encode([pregunta])[0]
        return self.store.buscar(vector, k, filtros)
