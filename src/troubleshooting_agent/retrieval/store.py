"""Vector store con un contrato único y dos backends: Qdrant local y numpy en disco.

Contrato:
    recrear(dim, meta)                -> borra y crea la colección vacía
    upsert(chunks, vectores)          -> inserta/actualiza por chunk_id (no duplica)
    buscar(vector, k, filtros=None)   -> list[Hit] ordenada por score desc
    meta() -> dict | None             -> metadatos del índice (modelo de embeddings, dim, ...)
    count() -> int

Filtros: {campo: valor} o {campo: [v1, v2]} (cualquiera). Si el campo del payload es
una lista (ej. `modelos`), matchea si algún elemento coincide.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import numpy as np

if TYPE_CHECKING:
    from troubleshooting_agent.config import Settings

Filtros = dict[str, Any]
_NAMESPACE = uuid.UUID("6f1d2c1e-6a51-4a1b-9a57-7c1f0e3b9d10")


@dataclass(frozen=True)
class Hit:
    score: float
    payload: dict[str, Any]


class VectorStore(Protocol):
    def recrear(self, dim: int, meta: dict[str, Any]) -> None: ...
    def upsert(self, chunks: list[dict[str, Any]], vectores: np.ndarray) -> None: ...
    def buscar(self, vector: np.ndarray, k: int, filtros: Filtros | None = None) -> list[Hit]: ...
    def meta(self) -> dict[str, Any] | None: ...
    def count(self) -> int: ...


def punto_id(chunk_id: str) -> str:
    """ID estable derivado del chunk_id: reindexar pisa el mismo punto."""
    return str(uuid.uuid5(_NAMESPACE, chunk_id))


def _como_lista(valor: Any) -> list[Any]:
    return list(valor) if isinstance(valor, (list, tuple, set)) else [valor]


# ── Qdrant ──────────────────────────────────────────────────


class QdrantStore:
    def __init__(self, path: Path | None, coleccion: str):
        """`path=None` → Qdrant en memoria (tests)."""
        from qdrant_client import QdrantClient

        self.coleccion = coleccion
        if path is None:
            self._cliente = QdrantClient(":memory:")
            self._meta_path = None
            self._meta_mem: dict[str, Any] | None = None
        else:
            path.mkdir(parents=True, exist_ok=True)
            self._cliente = QdrantClient(path=str(path))
            self._meta_path = path / f"{coleccion}.meta.json"

    def recrear(self, dim: int, meta: dict[str, Any]) -> None:
        from qdrant_client import models

        if self._cliente.collection_exists(self.coleccion):
            self._cliente.delete_collection(self.coleccion)
        self._cliente.create_collection(
            self.coleccion,
            vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
        )
        meta = {**meta, "dim": dim}
        if self._meta_path is None:
            self._meta_mem = meta
        else:
            self._meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def upsert(self, chunks: list[dict[str, Any]], vectores: np.ndarray, lote: int = 256) -> None:
        from qdrant_client import models

        for i in range(0, len(chunks), lote):
            puntos = [
                models.PointStruct(id=punto_id(c["chunk_id"]), vector=v.tolist(), payload=c)
                for c, v in zip(chunks[i : i + lote], vectores[i : i + lote])
            ]
            self._cliente.upsert(self.coleccion, points=puntos)

    def _filtro(self, filtros: Filtros | None):
        from qdrant_client import models

        if not filtros:
            return None
        condiciones = []
        for campo, valor in filtros.items():
            valores = _como_lista(valor)
            match = models.MatchValue(value=valores[0]) if len(valores) == 1 else models.MatchAny(any=valores)
            condiciones.append(models.FieldCondition(key=campo, match=match))
        return models.Filter(must=condiciones)

    def buscar(self, vector: np.ndarray, k: int, filtros: Filtros | None = None) -> list[Hit]:
        resultado = self._cliente.query_points(
            self.coleccion,
            query=np.asarray(vector, dtype=np.float32).tolist(),
            limit=k,
            query_filter=self._filtro(filtros),
            with_payload=True,
        )
        return [Hit(score=float(p.score), payload=dict(p.payload or {})) for p in resultado.points]

    def meta(self) -> dict[str, Any] | None:
        if not self._cliente.collection_exists(self.coleccion):
            return None
        if self._meta_path is None:
            return self._meta_mem
        if not self._meta_path.exists():
            return None
        return json.loads(self._meta_path.read_text(encoding="utf-8"))

    def count(self) -> int:
        if not self._cliente.collection_exists(self.coleccion):
            return 0
        return int(self._cliente.count(self.coleccion, exact=True).count)

    def cerrar(self) -> None:
        self._cliente.close()


# ── numpy (fallback USE_QDRANT=false) ───────────────────────


class NumpyStore:
    """Índice exacto en memoria, persistido en disco como .npy + .jsonl + meta.json."""

    def __init__(self, path: Path | None):
        self.path = path
        self._vectores = np.zeros((0, 0), dtype=np.float32)
        self._payloads: list[dict[str, Any]] = []
        self._meta: dict[str, Any] | None = None
        if path is not None and (path / "meta.json").exists():
            self._meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
            self._vectores = np.load(path / "vectores.npy")
            with (path / "payloads.jsonl").open(encoding="utf-8") as f:
                self._payloads = [json.loads(linea) for linea in f]

    def _guardar(self) -> None:
        if self.path is None:
            return
        self.path.mkdir(parents=True, exist_ok=True)
        np.save(self.path / "vectores.npy", self._vectores)
        with (self.path / "payloads.jsonl").open("w", encoding="utf-8") as f:
            for p in self._payloads:
                f.write(json.dumps(p, ensure_ascii=False) + "\n")
        (self.path / "meta.json").write_text(json.dumps(self._meta, ensure_ascii=False, indent=2), encoding="utf-8")

    def recrear(self, dim: int, meta: dict[str, Any]) -> None:
        self._vectores = np.zeros((0, dim), dtype=np.float32)
        self._payloads = []
        self._meta = {**meta, "dim": dim}
        self._guardar()

    def upsert(self, chunks: list[dict[str, Any]], vectores: np.ndarray) -> None:
        posicion = {p["chunk_id"]: i for i, p in enumerate(self._payloads)}
        nuevos_v, nuevos_p = [], []
        for chunk, vector in zip(chunks, np.asarray(vectores, dtype=np.float32)):
            i = posicion.get(chunk["chunk_id"])
            if i is None:
                nuevos_v.append(vector)
                nuevos_p.append(chunk)
            else:
                self._vectores[i] = vector
                self._payloads[i] = chunk
        if nuevos_v:
            self._vectores = np.vstack([self._vectores, np.stack(nuevos_v)])
            self._payloads.extend(nuevos_p)
        self._guardar()

    @staticmethod
    def _cumple(payload: dict[str, Any], filtros: Filtros) -> bool:
        for campo, valor in filtros.items():
            if not set(_como_lista(payload.get(campo))) & set(_como_lista(valor)):
                return False
        return True

    def buscar(self, vector: np.ndarray, k: int, filtros: Filtros | None = None) -> list[Hit]:
        if not self._payloads:
            return []
        indices = np.arange(len(self._payloads))
        if filtros:
            indices = np.array([i for i in indices if self._cumple(self._payloads[i], filtros)], dtype=int)
            if indices.size == 0:
                return []
        scores = self._vectores[indices] @ np.asarray(vector, dtype=np.float32)
        orden = np.argsort(-scores)[:k]
        return [Hit(score=float(scores[j]), payload=self._payloads[indices[j]]) for j in orden]

    def meta(self) -> dict[str, Any] | None:
        return self._meta

    def count(self) -> int:
        return len(self._payloads)


def abrir_store(settings: Settings, corpus: str | None = None) -> VectorStore:
    corpus = corpus or settings.corpus
    if settings.use_qdrant:
        return QdrantStore(settings.index_dir / "qdrant", coleccion=f"chunks_{corpus}")
    return NumpyStore(settings.index_dir / f"numpy_{corpus}")
