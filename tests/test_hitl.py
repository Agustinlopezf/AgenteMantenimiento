"""HITL: propuesta de intervención → aprobar / modificar / rechazar → OT simulada, con estado en SQLite."""

import json

import pytest

from troubleshooting_agent.agent.equipo import IdentificadorEquipo
from troubleshooting_agent.agent.estado import abrir_checkpointer, listar_diagnosticos
from troubleshooting_agent.agent.graph import construir_grafo, estado_actual, iniciar, pendiente, reanudar
from troubleshooting_agent.agent.llm import LLMSimulado
from troubleshooting_agent.agent.propuesta import (
    MAX_MODIFICACIONES,
    SCHEMA_PROPUESTA,
    normalizar_aprobacion,
    validar_propuesta,
)
from troubleshooting_agent.retrieval.embeddings import HashEmbedder
from troubleshooting_agent.retrieval.index import indexar
from troubleshooting_agent.retrieval.retriever import Retriever
from troubleshooting_agent.retrieval.store import Hit, NumpyStore

CHUNKS = [
    {"chunk_id": "demo::p0081::c00", "doc_id": "demo", "pagina_inicio": 81, "pagina_fin": 81, "titulo": "Manual demo",
     "seccion": "Troubleshooting", "tipo_contenido": "troubleshooting", "clase_equipo": "variador_frecuencia",
     "modelos": ["Drive 100"], "texto": "F5 OverVoltage: tensión del bus DC alta. Extender el tiempo de desaceleración."},
]
CASOS = [
    {"chunk_id": "hist::caso::S-001", "doc_id": "hist", "caso_id": "S-001", "titulo": "Historial demo",
     "clase_equipo": "variador_frecuencia", "modelos": ["Drive 100"], "sintetico": True,
     "sintoma": "F5 al bajar", "causa": "Regeneración", "solucion": "Extender desaceleración",
     "texto": "Drive 100 F5 OverVoltage regeneración"},
]
TAXONOMIA = {"clase_equipo": {"variador_frecuencia": {"sinonimos": ["variador", "drive"]}}}
DOCS = [{"doc_id": "demo", "clase_equipo": "variador_frecuencia", "fabricante": "Demo SA", "modelos": ["Drive 100"]}]
PREGUNTA = "El Drive 100 paró por F5 OverVoltage"

PROPUESTA_OK = {
    "resumen": "Sobretensión por regeneración", "prioridad": "alta", "escalar": False, "motivo_escalamiento": "",
    "seguridad": ["LOTO y esperar descarga del bus DC"],
    "verificaciones": [
        {"accion": "Revisar el caso similar", "cita": "[historial, caso S-001]"},
        {"accion": "Verificar tensión del bus", "cita": "[demo, p. 81]"},
        {"accion": "Paso inventado", "cita": "[demo, p. 999]"},
    ],
    "intervencion": "Extender el tiempo de desaceleración",
}


def _retriever(chunks):
    store, emb = NumpyStore(None), HashEmbedder(dim=128)
    indexar(chunks, store, emb, corpus="demo")
    return Retriever(store, emb)


class LLMGuion:
    nombre, simulado = "guion", False

    def __init__(self, propuestas):
        self.propuestas = list(propuestas)
        self.prompts_propuesta = []

    def generar(self, system, user):
        return "Sobretensión del bus [demo, p. 81]. Antecedente [historial, caso S-001]."

    def generar_json(self, system, user, schema):
        if schema is not SCHEMA_PROPUESTA:
            raise ValueError("router: usar reglas")
        self.prompts_propuesta.append(user)
        return self.propuestas.pop(0)


def _grafo(llm, tmp_path, checkpointer=None):
    return construir_grafo(
        _retriever(CHUNKS), llm, retriever_historial=_retriever(CASOS),
        identificador=IdentificadorEquipo(TAXONOMIA, DOCS), checkpointer=checkpointer, dir_ordenes=tmp_path / "ordenes",
    )


def test_propuesta_pausa_y_aprobar_emite_orden(tmp_path):
    grafo = _grafo(LLMGuion([dict(PROPUESTA_OK)]), tmp_path)
    r = iniciar(grafo, PREGUNTA, "t-ok")
    pausa = pendiente(r)
    assert pausa["tipo"] == "aprobacion" and pausa["puede_modificar"]
    p = pausa["propuesta"]
    assert [v["cita"] for v in p["verificaciones"]] == ["[historial, caso S-001]", "[demo, p. 81]"]
    assert p["descartadas"][0]["cita"] == "[demo, p. 999]"  # cita no recuperada → afuera
    assert "orden" not in r  # nada se ejecuta sin aprobación

    r = reanudar(grafo, {"decision": "aprobar", "responsable": "J. Pérez", "comentario": "ok"}, "t-ok")
    assert pendiente(r) is None and r["cierre"] == "aprobado"
    ot = json.loads(open(r["orden"]["json"], encoding="utf-8").read())
    assert ot["simulada"] and ot["aprobada_por"] == "J. Pérez" and ot["prioridad"] == "alta"
    assert ot["equipo"]["modelo"] == "Drive 100" and ot["equipo"]["codigo_falla"] == "F5"
    assert [d["accion"] for d in ot["decisiones_agente"]] == ["buscar_historial", "buscar_manual", "responder"]
    assert "(SIMULADA)" in open(r["orden"]["md"], encoding="utf-8").read()


def test_modificar_regenera_con_indicaciones_y_rechazar(tmp_path):
    revisada = {**PROPUESTA_OK, "intervencion": "Instalar resistencia de frenado"}
    llm = LLMGuion([dict(PROPUESTA_OK), revisada])
    grafo = _grafo(llm, tmp_path)
    iniciar(grafo, PREGUNTA, "t-mod")
    r = reanudar(grafo, "modificar: proponer resistencia de frenado", "t-mod")
    pausa = pendiente(r)
    assert pausa["tipo"] == "aprobacion" and pausa["propuesta"]["version"] == 2
    assert pausa["propuesta"]["intervencion"] == "Instalar resistencia de frenado"
    assert "proponer resistencia de frenado" in llm.prompts_propuesta[1]
    assert "PROPUESTA ANTERIOR" in llm.prompts_propuesta[1]

    r = reanudar(grafo, {"decision": "rechazar", "comentario": "falta repuesto"}, "t-mod")
    assert r["cierre"] == "rechazado" and "orden" not in r
    assert not list((tmp_path / "ordenes").glob("*.json"))


def test_limite_de_modificaciones_y_decision_invalida(tmp_path):
    grafo = _grafo(LLMSimulado(), tmp_path)
    iniciar(grafo, PREGUNTA, "t-lim")
    for i in range(MAX_MODIFICACIONES):
        r = reanudar(grafo, f"modificar: cambio {i}", "t-lim")
    assert pendiente(r)["puede_modificar"] is False
    assert "Indicación del responsable: cambio 1" in pendiente(r)["texto"]  # simulado: la agrega como paso
    r = reanudar(grafo, "modificar: otro más", "t-lim")
    assert pendiente(r)["tipo"] == "aprobacion" and r["modificaciones"] == MAX_MODIFICACIONES
    r = reanudar(grafo, "cualquier cosa", "t-lim")
    assert pendiente(r)["tipo"] == "aprobacion"
    notas = [t.get("nota", "") for t in r["traza"] if t["tipo"] == "aprobacion"]
    assert any("ya se modificó" in n for n in notas) and any("no reconocida" in n for n in notas)


def test_sin_verificaciones_validas_no_pide_aprobacion(tmp_path):
    inventada = {**PROPUESTA_OK, "verificaciones": [{"accion": "x", "cita": "[otro, p. 1]"}]}
    r = iniciar(_grafo(LLMGuion([inventada]), tmp_path), PREGUNTA, "t-vacia")
    assert pendiente(r) is None and r["cierre"] == "sin_propuesta"
    assert any("propuesta" in a for a in r["avisos"])


def test_propuesta_llm_falla_cae_a_reglas(tmp_path):
    class Roto(LLMGuion):
        def generar_json(self, system, user, schema):
            raise ValueError("JSON inválido")

    r = iniciar(_grafo(Roto([]), tmp_path), PREGUNTA, "t-roto")
    p = pendiente(r)["propuesta"]
    assert p["origen"] == "reglas" and p["verificaciones"]
    assert any("La propuesta del LLM falló" in a for a in r["avisos"])


def test_estado_persiste_en_sqlite_entre_procesos(tmp_path):
    db = tmp_path / "estado" / "checkpoints.sqlite"
    grafo1 = _grafo(LLMSimulado(), tmp_path, abrir_checkpointer(db))
    iniciar(grafo1, PREGUNTA, "t-persist")
    iniciar(grafo1, "no anda", "t-datos")  # queda esperando datos
    del grafo1

    # "otro proceso": nuevo checkpointer y nuevo grafo sobre el mismo archivo
    cp = abrir_checkpointer(db)
    grafo2 = _grafo(LLMSimulado(), tmp_path, cp)
    pendientes = {d["thread_id"]: d["espera"] for d in listar_diagnosticos(grafo2, cp)}
    assert pendientes == {"t-persist": "aprobacion", "t-datos": "pedir_datos"}
    guardado = estado_actual(grafo2, "t-persist")
    assert guardado["hits"][0].payload["chunk_id"] == "demo::p0081::c00"  # Hit deserializado

    r = reanudar(grafo2, {"decision": "aprobar", "responsable": "supervisor"}, "t-persist")
    assert r["cierre"] == "aprobado" and (tmp_path / "ordenes").exists()
    assert {d["thread_id"] for d in listar_diagnosticos(grafo2, cp)} == {"t-datos"}
    assert estado_actual(grafo2, "no-existe") is None


@pytest.mark.parametrize("valor, decision, comentario", [
    ("aprobar", "aprobar", ""),
    ("a", "aprobar", ""),
    ("r: sin repuesto", "rechazar", "sin repuesto"),
    ({"decision": "Modificar", "comentario": "agregar X"}, "modificar", "agregar X"),
    ("quizás", "invalida", ""),
])
def test_normalizar_aprobacion(valor, decision, comentario):
    a = normalizar_aprobacion(valor)
    assert (a["decision"], a["comentario"]) == (decision, comentario)


def test_validar_propuesta_normaliza():
    hit = Hit(1.0, CHUNKS[0])
    p = validar_propuesta({"verificaciones": [{"accion": "a", "cita": "[demo, p. 81]"}, {"accion": "", "cita": "x"}],
                           "prioridad": "URGENTE"}, [hit], [])
    assert p["prioridad"] == "media" and len(p["verificaciones"]) == 1 and p["seguridad"] == []


def test_grafo_estado_lista_sin_indice_ni_llm(tmp_path, monkeypatch):
    from troubleshooting_agent.agent.graph import crear_grafo_estado
    from troubleshooting_agent.config import load_settings

    monkeypatch.setenv("STATE_DB", str(tmp_path / "e.sqlite"))
    grafo = _grafo(LLMSimulado(), tmp_path, abrir_checkpointer(tmp_path / "e.sqlite"))
    iniciar(grafo, PREGUNTA, "t-lista")
    liviano = crear_grafo_estado(load_settings(tmp_path / "no.env"))
    assert [d["thread_id"] for d in listar_diagnosticos(liviano, liviano.checkpointer)] == ["t-lista"]


def test_respuesta_con_cita_corrida_sale_corregida_y_avisada(tmp_path):
    class CitaCorrida(LLMGuion):
        def generar(self, system, user):
            return "- El F5 OverVoltage indica sobretensión del bus [demo, p. 18]."

    r = iniciar(_grafo(CitaCorrida([dict(PROPUESTA_OK)]), tmp_path), PREGUNTA, "t-corr")
    assert "[demo, p. 81]" in r["respuesta"] and "p. 18]" not in r["respuesta"]
    assert [str(c) for c in r["citas_validas"]] == ["[demo, p. 81]"] and r["citas_invalidas"] == []
    assert any("Se corrigieron 1 cita(s)" in a and "[demo, p. 18] → [demo, p. 81]" in a for a in r["avisos"])
    assert r["fidelidad"]["conteo"]["cita_corregida"] == 1
