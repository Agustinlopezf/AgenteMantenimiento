from pathlib import Path

import pytest

from troubleshooting_agent.config import REPO_ROOT, load_settings

VARIABLES = [
    "LLM_MODEL", "OLLAMA_BASE_URL", "USE_REAL_LLM", "EMBEDDING_MODEL", "USE_QDRANT",
    "CORPUS", "WEB_SEARCH_ALLOWLIST", "DATA_DIR", "CHUNK_SIZE", "CHUNK_OVERLAP",
    "EMBEDDING_DEVICE", "INDEX_DIR", "RETRIEVAL_K", "LLM_NUM_CTX", "LLM_TEMPERATURE", "LLM_THINK",
]


@pytest.fixture
def entorno_limpio(monkeypatch, tmp_path) -> Path:
    for var in VARIABLES:
        monkeypatch.delenv(var, raising=False)
    return tmp_path / "no_existe.env"  # evita leer el .env local del usuario


def test_defaults(entorno_limpio):
    s = load_settings(entorno_limpio)
    assert s.llm_model == "qwen3.5:4b"
    assert s.use_real_llm is False
    assert s.use_qdrant is True
    assert s.corpus == "demo"
    assert s.embedding_model == "BAAI/bge-m3"
    assert s.data_dir == REPO_ROOT / "data"
    assert s.catalog_path == REPO_ROOT / "data" / "catalog" / "catalogo_documentos.json"
    assert (s.chunk_size, s.chunk_overlap) == (1200, 200)
    assert s.index_dir == REPO_ROOT / "artifacts" / "index"
    assert (s.embedding_device, s.retrieval_k, s.llm_think) == ("auto", 6, False)


def test_rutas_relativas_desde_raiz_del_repo(entorno_limpio, monkeypatch):
    monkeypatch.setenv("INDEX_DIR", "otro/indice")
    assert load_settings(entorno_limpio).index_dir == REPO_ROOT / "otro" / "indice"


def test_override_por_env(entorno_limpio, monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODEL", "otro:7b")
    monkeypatch.setenv("USE_REAL_LLM", "true")
    monkeypatch.setenv("CORPUS", "completo")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("WEB_SEARCH_ALLOWLIST", "a.com, b.com")
    s = load_settings(entorno_limpio)
    assert s.llm_model == "otro:7b"
    assert s.use_real_llm is True
    assert s.corpus == "completo"
    assert s.raw_dir == tmp_path / "raw"
    assert s.web_search_allowlist == ("a.com", "b.com")


def test_dotenv_no_pisa_entorno(entorno_limpio, monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("CORPUS=completo\nLLM_MODEL=desde-dotenv\n")
    monkeypatch.setenv("CORPUS", "demo")
    s = load_settings(env_file)
    assert s.corpus == "demo"
    assert s.llm_model == "desde-dotenv"


def test_corpus_invalido(entorno_limpio, monkeypatch):
    monkeypatch.setenv("CORPUS", "todo")
    with pytest.raises(ValueError, match="CORPUS"):
        load_settings(entorno_limpio)


def test_chunking_invalido(entorno_limpio, monkeypatch):
    monkeypatch.setenv("CHUNK_SIZE", "100")
    monkeypatch.setenv("CHUNK_OVERLAP", "100")
    with pytest.raises(ValueError):
        load_settings(entorno_limpio)
