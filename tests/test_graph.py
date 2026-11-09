"""Grafo de punta a punta sin red, GPU ni Ollama (HashEmbedder + LLM simulado / fake)."""

import pytest

from troubleshooting_agent.agent import llm as llm_mod
from troubleshooting_agent.agent.graph import SIN_EVIDENCIA, construir_grafo, crear_retriever
from troubleshooting_agent.agent.llm import LLMSimulado, OllamaLLM, crear_llm
from troubleshooting_agent.config import load_settings
from troubleshooting_agent.retrieval.embeddings import HashEmbedder
from troubleshooting_agent.retrieval.index import indexar
from troubleshooting_agent.retrieval.retriever import IndiceIncompatible, IndiceNoDisponible, Retriever
from troubleshooting_agent.retrieval.store import NumpyStore

CHUNKS = [
    {"chunk_id": "demo::p0081::c00", "doc_id": "demo", "pagina_inicio": 81, "pagina_fin": 81,
     "titulo": "Manual demo", "seccion": "Troubleshooting", "texto": "Falla OverVoltage: la tensión del bus DC superó el límite. Verificar la línea."},
    {"chunk_id": "demo::p0020::c00", "doc_id": "demo", "pagina_inicio": 20, "pagina_fin": 20,
     "titulo": "Manual demo", "seccion": "Instalación", "texto": "Montaje del gabinete y cableado de control."},
]


@pytest.fixture
def retriever():
    store, emb = NumpyStore(None), HashEmbedder(dim=128)
    indexar(CHUNKS, store, emb, corpus="demo")
    return Retriever(store, emb)


class LLMFijo:
    nombre, simulado = "fijo", False

    def __init__(self, respuesta):
        self.respuesta = respuesta
        self.llamadas = 0

    def generar(self, system, user):
        self.llamadas += 1
        assert "[demo, p. 81]" in user  # el contexto lleva el encabezado de cita
        return self.respuesta


def _invocar(grafo, pregunta="OverVoltage en el bus DC", k=2):
    return grafo.invoke({"pregunta": pregunta, "k": k, "avisos": [], "tiempos": {}})


def test_retriever_errores():
    with pytest.raises(IndiceNoDisponible):
        Retriever(NumpyStore(None), HashEmbedder())
    store = NumpyStore(None)
    indexar(CHUNKS, store, HashEmbedder(dim=64), corpus="demo")
    with pytest.raises(IndiceIncompatible):
        Retriever(store, HashEmbedder(dim=64, nombre="otro-modelo"))


def test_grafo_simulado(retriever):
    r = _invocar(construir_grafo(retriever, LLMSimulado()))
    assert r["hits"][0].payload["chunk_id"] == "demo::p0081::c00"
    assert r["respuesta"].startswith("[MODO SIMULADO]")
    assert "[demo, p. 81]" in r["respuesta"]
    assert r["citas_invalidas"] == []
    assert "retrieve_s" in r["tiempos"] and "llm_s" in r["tiempos"]


def test_grafo_cita_valida(retriever):
    llm = LLMFijo("**Causas probables**\n- Tensión de línea alta [demo, p. 81].")
    r = _invocar(construir_grafo(retriever, llm))
    assert [str(c) for c in r["citas_validas"]] == ["[demo, p. 81]"]
    assert r["fuentes"] == ["[demo, p. 81] Manual demo · Troubleshooting"]
    assert r["avisos"] == []


def test_grafo_cita_inventada_genera_aviso(retriever):
    r = _invocar(construir_grafo(retriever, LLMFijo("Cambiar el fusible F3 [demo, p. 999].")))
    assert [str(c) for c in r["citas_invalidas"]] == ["[demo, p. 999]"]
    assert any("NO están entre los fragmentos" in a for a in r["avisos"])
    assert any("ninguna cita verificable" in a for a in r["avisos"])


def test_grafo_sin_indice_no_llama_al_llm():
    llm = LLMFijo("no debería usarse")
    r = _invocar(construir_grafo(None, llm))
    assert r["respuesta"] == SIN_EVIDENCIA
    assert llm.llamadas == 0


@pytest.fixture
def settings(monkeypatch, tmp_path):
    for var in ("LLM_MODEL", "USE_QDRANT", "CORPUS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("USE_REAL_LLM", "true")
    return load_settings(tmp_path / "no.env")


def test_crear_retriever_sin_indice_avisa(settings):
    retriever, avisos = crear_retriever(settings)
    assert retriever is None
    assert "No hay índice" in avisos[0]


def test_crear_llm_sin_ollama_cae_a_simulado(settings, monkeypatch):
    class ClienteCaido:
        def __init__(self, *a, **kw): ...
        def list(self):
            raise ConnectionError("connection refused")

    import ollama
    monkeypatch.setattr(ollama, "Client", ClienteCaido)
    llm, avisos = crear_llm(settings)
    assert isinstance(llm, LLMSimulado)
    assert "No se pudo conectar a Ollama" in avisos[0]


def test_crear_llm_modelo_faltante_y_ok(settings, monkeypatch):
    class Modelo:
        def __init__(self, nombre): self.model = nombre

    class Cliente:
        modelos = ["otro:7b"]
        def __init__(self, *a, **kw): ...
        def list(self):
            return type("R", (), {"models": [Modelo(m) for m in Cliente.modelos]})()

    import ollama
    monkeypatch.setattr(ollama, "Client", Cliente)
    llm, avisos = crear_llm(settings)
    assert isinstance(llm, LLMSimulado) and "ollama pull qwen3.5:4b" in avisos[0]

    Cliente.modelos = ["qwen3.5:4b"]
    llm, avisos = crear_llm(settings)
    assert isinstance(llm, OllamaLLM) and avisos == []


def test_use_real_llm_false(settings, monkeypatch):
    monkeypatch.setenv("USE_REAL_LLM", "false")
    llm, avisos = llm_mod.crear_llm(load_settings())
    assert llm.simulado and "simulado" in avisos[0]
