"""Construye el índice vectorial a partir de data/chunks/chunks.jsonl.

    uv run python -m troubleshooting_agent.retrieval.index [--corpus demo|completo]

Recrea la colección en cada corrida (idempotente). Los IDs de punto derivan del
chunk_id, así que el índice nunca duplica chunks.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from troubleshooting_agent.config import load_settings
from troubleshooting_agent.retrieval.embeddings import Embedder, crear_embedder
from troubleshooting_agent.retrieval.store import VectorStore, abrir_store


def leer_chunks(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(linea) for linea in f if linea.strip()]


def indexar(chunks: list[dict[str, Any]], store: VectorStore, embedder: Embedder, corpus: str, progreso: bool = False) -> None:
    vectores = embedder.encode([c["texto"] for c in chunks], mostrar_progreso=progreso)
    store.recrear(
        embedder.dim,
        {
            "embedding_model": embedder.nombre,
            "corpus": corpus,
            "n_chunks": len(chunks),
            "creado": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    store.upsert(chunks, vectores)


def _vram_pico_mb() -> float | None:
    try:
        import torch

        if torch.cuda.is_available():
            return torch.cuda.max_memory_allocated() / 2**20
    except ImportError:
        pass
    return None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m troubleshooting_agent.retrieval.index")
    ap.add_argument("--corpus", choices=["demo", "completo"], help="pisa CORPUS del entorno")
    args = ap.parse_args(argv)

    settings = load_settings()
    corpus = args.corpus or settings.corpus
    if not settings.chunks_path.exists():
        print(
            f"ERROR: no existe {settings.chunks_path}. Correr antes: "
            "uv run python -m troubleshooting_agent.ingest",
            file=sys.stderr,
        )
        return 1

    chunks = leer_chunks(settings.chunks_path)
    print(f"{len(chunks)} chunks de {len({c['doc_id'] for c in chunks})} documentos")
    for doc_id, n in sorted(Counter(c["doc_id"] for c in chunks).items()):
        print(f"  {doc_id:28} {n}")

    t0 = time.perf_counter()
    embedder = crear_embedder(settings)
    print(f"Embeddings: {embedder.nombre} en {embedder.device} (dim {embedder.dim}) · carga {time.perf_counter() - t0:.1f} s")

    store = abrir_store(settings, corpus)
    t1 = time.perf_counter()
    indexar(chunks, store, embedder, corpus, progreso=True)
    backend = "Qdrant local" if settings.use_qdrant else "numpy"
    print(f"Indexados {store.count()} puntos en {backend} ({settings.index_dir}) · {time.perf_counter() - t1:.1f} s")

    vram = _vram_pico_mb()
    if vram is not None:
        print(f"VRAM pico (torch, embeddings): {vram:.0f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
