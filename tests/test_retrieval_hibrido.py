"""BM25, RRF, retriever híbrido, prioridad a secciones de fallas y métricas de evaluación."""

import importlib.util
import json

import pytest

from troubleshooting_agent.agent.equipo import Equipo
from troubleshooting_agent.agent.tools import buscar_manual
from troubleshooting_agent.config import REPO_ROOT
from troubleshooting_agent.retrieval.bm25 import BM25, tokenizar
from troubleshooting_agent.retrieval.embeddings import HashEmbedder
from troubleshooting_agent.retrieval.index import indexar
from troubleshooting_agent.retrieval.retriever import Retriever, RetrieverHibrido, rrf
from troubleshooting_agent.retrieval.store import Hit, NumpyStore


def _c(cid, pagina, texto, tipo="general", modelos=("Drive 100",)):
    return {"chunk_id": cid, "doc_id": "demo", "pagina_inicio": pagina, "clase_equipo": "variador_frecuencia",
            "modelos": list(modelos), "tipo_contenido": tipo, "texto": texto}


CHUNKS = [
    _c("a", 10, "Bus regulation limits the DC bus voltage during deceleration."),
    _c("b", 87, "OverVoltage 5 DC bus voltage exceeded maximum value. Extend the decel time.", "troubleshooting"),
    _c("c", 120, "Parameter 161 Bus Reg Mode selects the regulation method."),
    _c("d", 200, "Motor nameplate data and autotune.", modelos=("Drive 200",)),
]


def test_tokenizar_codigos_y_tildes():
    assert tokenizar("Falla F-12 en la tensión") == ["f12", "12", "falla", "tension"]
    assert tokenizar("F 5 OverVoltage") == ["f5", "5", "overvoltage"]


def test_bm25_rankea_por_terminos_exactos_y_filtra():
    bm = BM25(CHUNKS)
    hits = bm.buscar("F5 OverVoltage", 3)
    assert hits[0].payload["chunk_id"] == "b"
    assert bm.buscar("autotune", 3, {"modelos": "Drive 100"}) == []
    assert bm.buscar("término inexistente", 3) == []


def test_rrf_premia_lo_que_aparece_en_ambas_listas():
    h = {c["chunk_id"]: Hit(1.0, c) for c in CHUNKS}
    fusion = rrf([[h["a"], h["b"], h["c"]], [h["b"], h["d"]]], k=3)
    assert [x.payload["chunk_id"] for x in fusion][0] == "b"
    assert len(fusion) == 3


@pytest.fixture
def denso():
    store, emb = NumpyStore(None), HashEmbedder(dim=64)
    indexar(CHUNKS, store, emb, corpus="demo")
    return Retriever(store, emb), store


@pytest.mark.parametrize("modo", ["hibrido", "denso", "bm25"])
def test_hibrido_respeta_contrato_y_filtros(denso, modo):
    retr, store = denso
    r = RetrieverHibrido(retr, BM25(store.payloads()), modo)
    hits = r.buscar("OverVoltage bus", 2, {"modelos": "Drive 100"})
    assert 0 < len(hits) <= 2
    assert all("Drive 100" in h.payload["modelos"] for h in hits)


def test_modo_invalido(denso):
    with pytest.raises(ValueError):
        RetrieverHibrido(denso[0], BM25([]), "magia")


def test_buscar_manual_prioriza_secciones_de_fallas_si_hay_codigo(denso):
    retr, store = denso
    r = RetrieverHibrido(retr, BM25(store.payloads()), "hibrido")
    eq = Equipo("variador_frecuencia", ["variador_frecuencia"], "Demo", "Drive 100", "F5", [], True)
    res = buscar_manual(r, "bus voltage", eq, k=3)
    assert res.hits[0].payload["tipo_contenido"] == "troubleshooting"
    assert len(res.hits) == 3  # completa con el resto del manual
    assert res.filtros["prioridad"] == "secciones de fallas"
    sin = buscar_manual(r, "bus voltage", eq, k=3, priorizar_fallas=False)
    assert "prioridad" not in sin.filtros


def _cargar_script(nombre):
    spec = importlib.util.spec_from_file_location(nombre, REPO_ROOT / "scripts" / f"{nombre}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_metricas_de_evaluacion():
    ev = _cargar_script("evaluar_retrieval")
    esperado = [{"doc_id": "demo", "paginas": [86, 88]}]
    hits = [Hit(1, CHUNKS[0]), Hit(1, CHUNKS[1])]
    assert ev.rango_primer_relevante(hits, esperado) == 2
    m = ev.metricas([1, 2, None, 11])
    assert m["hit@1"] == 0.25 and m["hit@3"] == 0.5 and m["hit@10"] == 0.5
    assert m["mrr@10"] == round((1 + 0.5) / 4, 3)


def test_set_de_evaluacion_bien_formado():
    """Solo documentos públicos del catálogo; páginas como rango [ini, fin]."""
    catalogo = json.loads((REPO_ROOT / "data" / "catalog" / "catalogo_documentos.json").read_text(encoding="utf-8"))
    publicos = {d["doc_id"] for d in catalogo["documentos"] if d["distribucion"] == "publico"}
    lineas = (REPO_ROOT / "data" / "eval" / "preguntas.jsonl").read_text(encoding="utf-8").splitlines()
    preguntas = [json.loads(x) for x in lineas if x.strip()]
    assert len(preguntas) >= 15
    assert len({q["id"] for q in preguntas}) == len(preguntas)
    for q in preguntas:
        assert q["pregunta"] and q["esperado"]
        for e in q["esperado"]:
            assert e["doc_id"] in publicos
            assert e["paginas"][0] <= e["paginas"][1]
