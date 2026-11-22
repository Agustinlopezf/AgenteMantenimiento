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


# ── híbrido: denso + BM25 con Reciprocal Rank Fusion ────────

MODOS = ("hibrido", "denso", "bm25")


def rrf(listas: list[list[Hit]], k: int, k_rrf: int = 60) -> list[Hit]:
    """Fusión por rango: score = Σ 1/(k_rrf + rango). Ignora la escala de cada score."""
    scores: dict[str, float] = {}
    payloads: dict[str, dict] = {}
    for hits in listas:
        for rango, h in enumerate(hits, start=1):
            cid = h.payload["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k_rrf + rango)
            payloads.setdefault(cid, h.payload)
    orden = sorted(scores, key=lambda c: -scores[c])[:k]
    return [Hit(score=scores[c], payload=payloads[c]) for c in orden]


class RetrieverHibrido:
    """Mismo contrato que `Retriever.buscar`. `modo`: hibrido | denso | bm25.

    Cada rama trae `candidatos` resultados (con los mismos filtros) y RRF los combina.
    """

    def __init__(self, denso: Retriever, bm25, modo: str = "hibrido", candidatos: int = 30, k_rrf: int = 60):
        if modo not in MODOS:
            raise ValueError(f"modo={modo!r} no es válido; usar uno de {MODOS}")
        self.denso, self.bm25, self.modo = denso, bm25, modo
        self.candidatos, self.k_rrf = candidatos, k_rrf

    def buscar(self, pregunta: str, k: int, filtros: Filtros | None = None) -> list[Hit]:
        if self.modo == "denso":
            return self.denso.buscar(pregunta, k, filtros)
        if self.modo == "bm25":
            return self.bm25.buscar(pregunta, k, filtros)
        n = max(k, self.candidatos)
        return rrf([self.denso.buscar(pregunta, n, filtros), self.bm25.buscar(pregunta, n, filtros)], k, self.k_rrf)
