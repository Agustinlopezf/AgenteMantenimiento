"""Configuración vía variables de entorno (y `.env` en la raíz del repo).

Las variables ya definidas en el entorno tienen prioridad sobre el `.env`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
CORPUS_VALIDOS = ("demo", "completo")


def _bool(valor: str) -> bool:
    return valor.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}


@dataclass(frozen=True)
class Settings:
    llm_model: str
    ollama_base_url: str
    use_real_llm: bool
    embedding_model: str
    use_qdrant: bool
    corpus: str
    web_search_allowlist: tuple[str, ...]
    data_dir: Path
    chunk_size: int
    chunk_overlap: int

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def catalog_path(self) -> Path:
        return self.data_dir / "catalog" / "catalogo_documentos.json"

    @property
    def chunks_dir(self) -> Path:
        return self.data_dir / "chunks"

    @property
    def chunks_path(self) -> Path:
        return self.chunks_dir / "chunks.jsonl"

    @property
    def ocr_cache_dir(self) -> Path:
        return self.data_dir / "ocr_cache"


def load_settings(env_file: Path | None = None) -> Settings:
    load_dotenv(env_file or REPO_ROOT / ".env", override=False)
    env = os.environ.get

    corpus = env("CORPUS", "demo").strip().lower()
    if corpus not in CORPUS_VALIDOS:
        raise ValueError(f"CORPUS={corpus!r} no es válido; usar uno de {CORPUS_VALIDOS}")

    chunk_size = int(env("CHUNK_SIZE", "1200"))
    chunk_overlap = int(env("CHUNK_OVERLAP", "200"))
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("Se requiere CHUNK_SIZE > 0 y 0 <= CHUNK_OVERLAP < CHUNK_SIZE")

    allowlist = tuple(
        d.strip() for d in env("WEB_SEARCH_ALLOWLIST", "rockwellautomation.com").split(",") if d.strip()
    )

    return Settings(
        llm_model=env("LLM_MODEL", "qwen3.5:4b"),
        ollama_base_url=env("OLLAMA_BASE_URL", "http://localhost:11434"),
        use_real_llm=_bool(env("USE_REAL_LLM", "false")),
        embedding_model=env("EMBEDDING_MODEL", "BAAI/bge-m3"),
        use_qdrant=_bool(env("USE_QDRANT", "true")),
        corpus=corpus,
        web_search_allowlist=allowlist,
        data_dir=Path(env("DATA_DIR", str(REPO_ROOT / "data"))),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )
