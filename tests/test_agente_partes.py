"""Identificación de equipo, router (reglas, LLM, guardas), tools, skill e historial."""

import json

import pytest

from troubleshooting_agent.agent import router
from troubleshooting_agent.agent.citas import Cita, CitaCaso, extraer_citas
from troubleshooting_agent.agent.equipo import Equipo, IdentificadorEquipo
from troubleshooting_agent.agent.llm import LLMSimulado
from troubleshooting_agent.agent.skills import cargar_skill
from troubleshooting_agent.agent.tools import buscar_manual
from troubleshooting_agent.catalog import load_catalog
from troubleshooting_agent.config import REPO_ROOT
from troubleshooting_agent.ingest.historial import chunks_historial
from troubleshooting_agent.retrieval.embeddings import HashEmbedder
from troubleshooting_agent.retrieval.index import indexar
from troubleshooting_agent.retrieval.retriever import Retriever
from troubleshooting_agent.retrieval.store import NumpyStore

CATALOGO = load_catalog(REPO_ROOT / "data" / "catalog" / "catalogo_documentos.json")


@pytest.fixture(scope="module")
def ide():
    return IdentificadorEquipo.desde_catalogo(CATALOGO, "demo")


# ── equipo ──────────────────────────────────────────────────

@pytest.mark.parametrize("texto, clase, modelo, codigo", [
    ("el PowerFlex 700 paró por F5 OverVoltage", "variador_frecuencia", "PowerFlex 700", "F5"),
    ("el pf755 tira F-12", "variador_frecuencia", "PowerFlex 755", "F12"),
    ("PowerFlex 70 con falla 4", "variador_frecuencia", "PowerFlex 70", "F4"),
    ("el F532WD no tiene señal", "caudalimetro", "FLUXUS F532WD", None),
    ("el caudalímetro marca un signo de pregunta", "caudalimetro", None, None),
    ("el FLUXUS de la batería sin señal", "caudalimetro", "FLUXUS F532WD", None),
])
def test_identificar(ide, texto, clase, modelo, codigo):
    eq = ide.identificar(texto)
    assert (eq.clase_equipo, eq.modelo, eq.codigo_falla) == (clase, modelo, codigo)
    assert eq.en_corpus


def test_identificar_faltantes(ide):
    assert ide.identificar("el variador para por sobretensión").faltantes == ["modelo"]
    assert ide.identificar("el caudalímetro marca un signo de pregunta").faltantes == []  # código opcional
    assert ide.identificar("el PowerFlex anda mal").modelo is None  # familia ambigua: no adivina
    ambiguo = ide.identificar("el motor no arranca")
    assert ambiguo.clase_equipo is None and "equipo_ambiguo" in ambiguo.faltantes
    assert set(ambiguo.clases_candidatas) == {"motor_electrico", "motor_gas"}
    nada = ide.identificar("no anda")
    assert "equipo" in nada.faltantes
    compresor = ide.identificar("el compresor no levanta presión")
    assert compresor.clase_equipo == "compresor_reciprocante" and not compresor.en_corpus


def test_historial_no_contamina_modelos(ide):
    # el doc del historial lista FLUXUS con clase variador: no debe usarse para mapear modelos
    assert ide.identificar("FLUXUS F532WD").clase_equipo == "caudalimetro"


# ── router ──────────────────────────────────────────────────

def _ctx(eq, consultas=(), pedidos=0, texto="PowerFlex 700 F5"):
    return router.Contexto(texto, eq, list(consultas), pedidos, ["variador_frecuencia", "caudalimetro"])


EQ_OK = Equipo("variador_frecuencia", ["variador_frecuencia"], "Rockwell", "PowerFlex 700", "F5", [], True)
HECHO_HIST = {"accion": "buscar_historial", "consulta": "PowerFlex 700 F5", "resumen": "2 resultados", "n": 2}
HECHO_MAN = {"accion": "buscar_manual", "consulta": "PowerFlex 700 F5", "resumen": "6 resultados", "n": 6}


def test_reglas_secuencia():
    assert router.decidir_reglas(_ctx(EQ_OK)).accion == "buscar_historial"
    assert router.decidir_reglas(_ctx(EQ_OK, [HECHO_HIST])).accion == "buscar_manual"
    assert router.decidir_reglas(_ctx(EQ_OK, [HECHO_HIST, HECHO_MAN])).accion == "responder"
    sin_equipo = Equipo(faltantes=["equipo"])
    d = router.decidir_reglas(_ctx(sin_equipo, texto="no anda"))
    assert d.accion == "pedir_datos" and "qué equipo es" in d.pregunta
    assert router.decidir_reglas(_ctx(sin_equipo, pedidos=2, texto="no anda")).accion == "buscar_historial"


class LLMGuion:
    nombre, simulado = "guion", False

    def __init__(self, salida):
        self.salida = salida

    def generar_json(self, system, user, schema):
        if isinstance(self.salida, Exception):
            raise self.salida
        return self.salida


def test_router_llm_valido():
    d = router.decidir(LLMGuion({"accion": "buscar_manual", "motivo": "hay código", "consulta": "F5 OverVoltage"}), _ctx(EQ_OK))
    assert (d.accion, d.origen, d.consulta) == ("buscar_manual", "llm", "F5 OverVoltage")


@pytest.mark.parametrize("salida", [{"accion": "borrar_todo", "motivo": "x"}, ValueError("JSON inválido"), ConnectionError("caído")])
def test_router_llm_invalido_cae_a_reglas(salida):
    d = router.decidir(LLMGuion(salida), _ctx(EQ_OK))
    assert d.accion == "buscar_historial" and d.origen == "reglas"
    assert d.notas and "router LLM falló" in d.notas[0]


def test_guardas():
    repetida = router.decidir(LLMGuion({"accion": "buscar_historial", "motivo": "x", "consulta": "PowerFlex 700 F5"}),
                              _ctx(EQ_OK, [HECHO_HIST]))
    assert repetida.accion == "buscar_manual" and repetida.origen == "guarda"
    assert "repetida" in repetida.notas[0]

    sin_buscar = router.decidir(LLMGuion({"accion": "responder", "motivo": "ya sé"}), _ctx(EQ_OK))
    assert sin_buscar.accion == "buscar_historial" and sin_buscar.origen == "guarda"

    tope = [HECHO_HIST, HECHO_MAN, {**HECHO_MAN, "consulta": "otra"}, {**HECHO_MAN, "consulta": "otra más"}]
    d = router.decidir(LLMGuion({"accion": "buscar_manual", "motivo": "x", "consulta": "nueva"}), _ctx(EQ_OK, tope))
    assert d.accion == "responder" and d.origen == "guarda"


def test_guarda_clase_sin_documentacion():
    compresor = Equipo("compresor_reciprocante", ["compresor_reciprocante"], en_corpus=False)
    d = router.decidir(LLMGuion({"accion": "pedir_datos", "motivo": "falta código", "pregunta": "¿Código?"}), _ctx(compresor))
    assert d.accion == "responder" and d.origen == "guarda"


def test_router_simulado_usa_reglas():
    assert router.decidir(LLMSimulado(), _ctx(EQ_OK)).origen == "reglas"


def test_prompt_router_incluye_procedimiento_de_la_skill():
    class Espia(LLMGuion):
        def generar_json(self, system, user, schema):
            self.system, self.user = system, user
            return {"accion": "responder", "motivo": "x"}

    espia = Espia(None)
    router.decidir(espia, _ctx(EQ_OK, [HECHO_HIST]))
    assert "Identificar el equipo" in espia.system
    assert "buscar_historial('PowerFlex 700 F5') → 2 resultados" in espia.user


# ── tools ───────────────────────────────────────────────────

def test_buscar_manual_cae_a_clase_si_no_hay_modelo():
    chunks = [{"chunk_id": "a::p0001::c00", "doc_id": "a", "pagina_inicio": 1, "clase_equipo": "variador_frecuencia",
               "modelos": ["PowerFlex 755"], "texto": "OverVoltage bus DC"}]
    store, emb = NumpyStore(None), HashEmbedder(dim=64)
    indexar(chunks, store, emb, corpus="demo")
    r = buscar_manual(Retriever(store, emb), "OverVoltage", EQ_OK, k=3)
    assert len(r.hits) == 1 and "modelos" not in r.filtros
    assert "PowerFlex 700" in r.avisos[0]


# ── skill y citas ───────────────────────────────────────────

def test_skill_tiene_las_tres_secciones():
    assert set(cargar_skill("troubleshooting")) == {"procedimiento", "seguridad", "escalamiento"}


def test_extraer_cita_de_caso():
    texto = "Ver [historial, caso S-003] y [rok-20b-um001-en, p. 87; historial, caso S-010]."
    assert extraer_citas(texto) == [CitaCaso("S-003"), Cita("rok-20b-um001-en", 87), CitaCaso("S-010")]


# ── historial ───────────────────────────────────────────────

def test_historial_sintetico_demo():
    casos, saltados = chunks_historial(CATALOGO, "demo", REPO_ROOT / "data" / "catalog")
    assert saltados == {}
    assert len(casos) >= 20
    assert all(c["sintetico"] and c["doc_id"] == "hist-sintetico-demo" for c in casos)
    assert len({c["chunk_id"] for c in casos}) == len(casos)
    clases = {c["clase_equipo"] for c in casos}
    assert clases <= set(CATALOGO["taxonomia"]["clase_equipo"])
    assert {"variador_frecuencia", "caudalimetro"} <= clases


def test_historial_respeta_corpus(tmp_path):
    catalogo = {"documentos": [
        {"doc_id": "pub", "distribucion": "publico", "indexar": True, "tipo_documento": "historial_fallas",
         "titulo": "Pub", "clase_equipo": "bop", "extraccion": {"registros": "pub.jsonl"}},
        {"doc_id": "int", "distribucion": "interno_pae", "indexar": True, "tipo_documento": "historial_fallas",
         "titulo": "Int", "clase_equipo": "bop", "extraccion": {"registros": "int.jsonl"}},
    ]}
    for nombre in ("pub", "int"):
        (tmp_path / f"{nombre}.jsonl").write_text(
            json.dumps({"id": f"{nombre}-1", "sintoma": "s", "causa": "c", "solucion": "x"}) + "\n", encoding="utf-8")
    demo, _ = chunks_historial(catalogo, "demo", tmp_path)
    completo, _ = chunks_historial(catalogo, "completo", tmp_path)
    assert [c["caso_id"] for c in demo] == ["pub-1"]
    assert sorted(c["caso_id"] for c in completo) == ["int-1", "pub-1"]
    assert demo[0]["clase_equipo"] == "bop"  # hereda del documento si el registro no trae
