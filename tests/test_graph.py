"""Grafo de punta a punta sin red, GPU ni Ollama (HashEmbedder + LLM simulado / fake)."""

import pytest

from troubleshooting_agent.agent import llm as llm_mod
from troubleshooting_agent.agent.equipo import IdentificadorEquipo
from troubleshooting_agent.agent.graph import (
    SIN_EVIDENCIA,
    construir_grafo,
    crear_retriever,
    iniciar,
    pendiente,
    reanudar,
)
from troubleshooting_agent.agent.llm import LLMSimulado, OllamaLLM, crear_llm
from troubleshooting_agent.agent.propuesta import SCHEMA_PROPUESTA
from troubleshooting_agent.config import load_settings
from troubleshooting_agent.retrieval.embeddings import HashEmbedder
from troubleshooting_agent.retrieval.index import indexar
from troubleshooting_agent.retrieval.retriever import IndiceIncompatible, IndiceNoDisponible, Retriever
from troubleshooting_agent.retrieval.store import NumpyStore

_BASE = {"titulo": "Manual demo", "clase_equipo": "variador_frecuencia", "modelos": ["Drive 100"]}
CHUNKS = [
    {**_BASE, "chunk_id": "demo::p0081::c00", "doc_id": "demo", "pagina_inicio": 81, "pagina_fin": 81,
     "seccion": "Troubleshooting", "texto": "Falla F5 OverVoltage: la tensión del bus DC superó el límite. Verificar la línea."},
    {**_BASE, "chunk_id": "demo::p0020::c00", "doc_id": "demo", "pagina_inicio": 20, "pagina_fin": 20,
     "seccion": "Instalación", "texto": "Montaje del gabinete y cableado de control."},
]
CASOS = [
    {"chunk_id": "hist::caso::S-001", "doc_id": "hist", "caso_id": "S-001", "titulo": "Historial demo",
     "clase_equipo": "variador_frecuencia", "modelos": ["Drive 100"], "sintetico": True,
     "sintoma": "Para por F5 OverVoltage al bajar.", "causa": "Regeneración.", "solucion": "Extender desaceleración.",
     "texto": "Drive 100 F5 OverVoltage regeneración extender desaceleración"},
]
TAXONOMIA = {"clase_equipo": {
    "variador_frecuencia": {"sinonimos": ["variador", "drive"]},
    "motor_electrico": {"sinonimos": ["motor"]},
    "motor_gas": {"sinonimos": ["motor", "engine"]},
}}
DOCS = [{"doc_id": "demo", "clase_equipo": "variador_frecuencia", "fabricante": "Demo SA", "modelos": ["Drive 100", "Drive 200"]}]


def _retriever(chunks):
    store, emb = NumpyStore(None), HashEmbedder(dim=128)
    indexar(chunks, store, emb, corpus="demo")
    return Retriever(store, emb)


@pytest.fixture
def retriever():
    return _retriever(CHUNKS)


@pytest.fixture
def retriever_hist():
    return _retriever(CASOS)


@pytest.fixture
def identificador():
    return IdentificadorEquipo(TAXONOMIA, DOCS)


class LLMFijo:
    """Respuesta fija; el router decide con las decisiones guionadas (o reglas si no hay)."""

    nombre, simulado = "fijo", False

    def __init__(self, respuesta, decisiones=None, propuestas=None):
        self.respuesta = respuesta
        self.decisiones = list(decisiones or [])
        self.propuestas = list(propuestas or [])
        self.llamadas = 0
        self.prompts_router = []
        self.prompts_propuesta = []

    def generar(self, system, user):
        self.llamadas += 1
        assert "[demo, p. 81]" in user  # el contexto lleva el encabezado de cita
        return self.respuesta

    def generar_json(self, system, user, schema):
        if schema is SCHEMA_PROPUESTA:
            self.prompts_propuesta.append(user)
            if not self.propuestas:
                raise ValueError("sin guion de propuesta")
            return self.propuestas.pop(0)
        self.prompts_router.append(user)
        if not self.decisiones:
            raise ValueError("sin guion")
        return self.decisiones.pop(0)


def _correr(grafo, pregunta="El Drive 100 paró por F5 OverVoltage", respuestas=()):
    """Corre y responde las pausas en orden; sin más respuestas, devuelve el estado pausado."""
    r = iniciar(grafo, pregunta, "t1", k=2)
    respuestas = list(respuestas)
    while pendiente(r) is not None and respuestas:
        r = reanudar(grafo, respuestas.pop(0), "t1")
    return r


def _acciones(r):
    return [t["accion"] for t in r["traza"] if t["tipo"] == "decision"]


def test_retriever_errores():
    with pytest.raises(IndiceNoDisponible):
        Retriever(NumpyStore(None), HashEmbedder())
    store = NumpyStore(None)
    indexar(CHUNKS, store, HashEmbedder(dim=64), corpus="demo")
    with pytest.raises(IndiceIncompatible):
        Retriever(store, HashEmbedder(dim=64, nombre="otro-modelo"))


def test_grafo_simulado_consulta_historial_y_manual(retriever, retriever_hist, identificador):
    grafo = construir_grafo(retriever, LLMSimulado(), retriever_historial=retriever_hist, identificador=identificador)
    r = _correr(grafo)
    assert _acciones(r) == ["buscar_historial", "buscar_manual", "responder"]
    assert r["hits"][0].payload["chunk_id"] == "demo::p0081::c00"
    assert r["casos"][0].payload["caso_id"] == "S-001"
    assert r["respuesta"].startswith("[MODO SIMULADO]")
    assert "[demo, p. 81]" in r["respuesta"] and "[historial, caso S-001]" in r["respuesta"]
    assert r["citas_invalidas"] == []
    assert {"retrieve_s", "llm_s", "router_s"} <= set(r["tiempos"])


def test_grafo_llm_decide_ir_directo_al_manual(retriever, retriever_hist, identificador):
    llm = LLMFijo("Tensión de línea alta [demo, p. 81]. Antecedente [historial, caso S-001].", decisiones=[
        {"accion": "buscar_manual", "motivo": "hay código de falla", "consulta": "F5 OverVoltage Drive 100"},
        {"accion": "responder", "motivo": "el manual describe la falla"},
    ])
    r = _correr(construir_grafo(retriever, llm, retriever_historial=retriever_hist, identificador=identificador))
    assert _acciones(r) == ["buscar_manual", "responder"]
    assert all(t["origen"] == "llm" for t in r["traza"] if t["tipo"] == "decision")
    assert "casos" not in r or not r["casos"]
    # la cita al caso no recuperado se marca inválida
    assert [str(c) for c in r["citas_validas"]] == ["[demo, p. 81]"]
    assert [str(c) for c in r["citas_invalidas"]] == ["[historial, caso S-001]"]
    assert "ACCIONES YA HECHAS" in llm.prompts_router[1] and "buscar_manual" in llm.prompts_router[1]


def test_grafo_cita_valida_y_fuentes(retriever, retriever_hist, identificador):
    llm = LLMFijo("Causa: tensión alta [demo, p. 81]. Caso [historial, caso S-001].")
    r = _correr(construir_grafo(retriever, llm, retriever_historial=retriever_hist, identificador=identificador))
    assert r["fuentes"] == [
        "[demo, p. 81] Manual demo · Troubleshooting",
        "[historial, caso S-001] Historial demo · caso sintético",
    ]
    assert not any("cita" in a for a in r["avisos"])


def test_grafo_cita_inventada_genera_aviso(retriever, identificador):
    r = _correr(construir_grafo(retriever, LLMFijo("Cambiar el fusible F3 [demo, p. 999]."), identificador=identificador))
    assert [str(c) for c in r["citas_invalidas"]] == ["[demo, p. 999]"]
    assert any("NO están entre los fragmentos" in a for a in r["avisos"])
    assert any("ninguna cita verificable" in a for a in r["avisos"])


def test_grafo_pide_datos_pausa_y_reanuda(retriever, retriever_hist, identificador):
    grafo = construir_grafo(retriever, LLMSimulado(), retriever_historial=retriever_hist, identificador=identificador)
    r = iniciar(grafo, "el motor no arranca", "t-pausa")
    pausa = pendiente(r)
    assert pausa is not None and pausa["tipo"] == "pedir_datos"
    assert "qué equipo es" in pausa["pregunta"]
    assert "respuesta" not in r

    r = reanudar(grafo, "es el variador Drive 100, muestra F5", "t-pausa")
    assert pendiente(r)["tipo"] == "aprobacion"  # pedir datos no es el HITL: la pausa de aprobación sigue
    assert r["equipo"]["modelo"] == "Drive 100" and r["equipo"]["codigo_falla"] == "F5"
    assert r["pedidos"] == 1
    assert _acciones(r) == ["pedir_datos", "buscar_historial", "buscar_manual", "responder"]
    assert r["respuesta"].startswith("[MODO SIMULADO]")


def test_grafo_limita_pedidos_de_datos(retriever, identificador):
    pedir = {"accion": "pedir_datos", "motivo": "falta info", "pregunta": "¿Qué equipo?"}
    llm = LLMFijo("x [demo, p. 81]", decisiones=[pedir, pedir, pedir, pedir])
    r = _correr(construir_grafo(retriever, llm, identificador=identificador), "no anda", ["no sé", "tampoco"])
    assert r["pedidos"] == 2
    acciones = _acciones(r)
    assert acciones[:2] == ["pedir_datos", "pedir_datos"]
    assert acciones[-1] == "responder"
    assert any(t.get("origen") == "guarda" for t in r["traza"] if t["tipo"] == "decision")


def test_grafo_sin_indice_no_llama_al_llm(identificador):
    llm = LLMFijo("no debería usarse")
    r = _correr(construir_grafo(None, llm, identificador=identificador))
    assert r["respuesta"].startswith(SIN_EVIDENCIA)
    assert llm.llamadas == 0
    assert any("No hay índice de manuales" in a for a in r["avisos"])


def test_grafo_clase_sin_documentacion(retriever, identificador):
    llm = LLMFijo("no debería usarse")
    r = _correr(construir_grafo(retriever, llm, identificador=identificador), "el engine a gas pierde potencia")
    assert "motor_gas" in r["respuesta"]
    assert llm.llamadas == 0


@pytest.fixture
def settings(monkeypatch, tmp_path):
    for var in ("LLM_MODEL", "USE_QDRANT", "CORPUS"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("INDEX_DIR", str(tmp_path / "index"))
    monkeypatch.setenv("USE_REAL_LLM", "true")
    return load_settings(tmp_path / "no.env")


def test_crear_retriever_sin_indice_avisa(settings):
    manual, historial, avisos = crear_retriever(settings)
    assert manual is None and historial is None
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


def test_crear_retriever_indice_bloqueado_avisa(settings, monkeypatch):
    from troubleshooting_agent.retrieval.store import abrir_store

    monkeypatch.setenv("USE_QDRANT", "true")
    s = load_settings()
    otro_proceso = abrir_store(s)  # Qdrant local bloquea la carpeta
    manual, historial, avisos = crear_retriever(s)
    assert manual is None and historial is None
    assert "abierto por otro proceso" in avisos[0]
    otro_proceso.cerrar()
