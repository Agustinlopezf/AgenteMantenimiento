"""Embeddings: BGE-M3 (sentence-transformers) y un embedder determinístico para tests.

`sentence_transformers` / `torch` se importan recién al instanciar `BgeM3Embedder`,
así los tests y el modo simulado no los cargan.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING, Protocol

import numpy as np

if TYPE_CHECKING:
    from troubleshooting_agent.config import Settings


class Embedder(Protocol):
    nombre: str
    dim: int
    device: str

    def encode(self, textos: list[str], mostrar_progreso: bool = False) -> np.ndarray:
        """Matriz (n, dim) float32 con filas normalizadas (norma L2 = 1)."""
        ...


def _normalizar(m: np.ndarray) -> np.ndarray:
    normas = np.linalg.norm(m, axis=1, keepdims=True)
    normas[normas == 0] = 1.0
    return (m / normas).astype(np.float32)


class BgeM3Embedder:
    """BGE-M3 denso (1024 dim). Sin prefijo de instrucción: BGE-M3 no lo requiere."""

    def __init__(self, nombre: str, device: str = "auto", max_seq_length: int = 512, batch_size: int = 32):
        import torch
        from sentence_transformers import SentenceTransformer

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        kwargs = {"model_kwargs": {"torch_dtype": torch.float16}} if device == "cuda" else {}
        self._modelo = SentenceTransformer(nombre, device=device, **kwargs)
        self._modelo.max_seq_length = max_seq_length
        self.nombre = nombre
        self.device = device
        self.batch_size = batch_size
        obtener_dim = getattr(self._modelo, "get_embedding_dimension", None) or self._modelo.get_sentence_embedding_dimension
        self.dim = int(obtener_dim())

    def encode(self, textos: list[str], mostrar_progreso: bool = False) -> np.ndarray:
        vectores = self._modelo.encode(
            textos,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=mostrar_progreso,
        )
        return np.asarray(vectores, dtype=np.float32)


class HashEmbedder:
    """Embedder determinístico (bolsa de tokens hasheados). Solo para tests / sin modelo."""

    _TOKEN = re.compile(r"\w+", re.UNICODE)

    def __init__(self, dim: int = 256, nombre: str = "hash-embedder"):
        self.nombre = nombre
        self.dim = dim
        self.device = "cpu"

    def encode(self, textos: list[str], mostrar_progreso: bool = False) -> np.ndarray:
        m = np.zeros((len(textos), self.dim), dtype=np.float32)
        for i, texto in enumerate(textos):
            for token in self._TOKEN.findall(texto.lower()):
                h = int.from_bytes(hashlib.blake2b(token.encode(), digest_size=8).digest(), "little")
                m[i, h % self.dim] += 1.0 if (h >> 63) == 0 else -1.0
        return _normalizar(m)


def crear_embedder(settings: Settings) -> Embedder:
    return BgeM3Embedder(settings.embedding_model, device=settings.embedding_device)
