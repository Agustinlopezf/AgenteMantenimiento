"""Grafo LangGraph mínimo del hito 1: retrieve → answer."""

from __future__ import annotations

import operator
import time
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from troubleshooting_agent.agent.citas import Cita, armar_fuentes, clasificar_citas, extraer_citas
from troubleshooting_agent.agent.llm import LLM, crear_llm
from troubleshooting_agent.agent.prompts import SYSTEM_PROMPT, construir_mensaje_usuario
from troubleshooting_agent.retrieval.retriever import IndiceIncompatible, IndiceNoDisponible, Retriever
from troubleshooting_agent.retrieval.store import Hit, abrir_store

if TYPE_CHECKING:
    from troubleshooting_agent.config import Settings

SIN_EVIDENCIA = (
    "No encontré evidencia en el corpus indexado para responder esta consulta, "
    "así que no puedo indicar causas ni procedimientos."
)


class Estado(TypedDict, total=False):
    pregunta: str
    k: int
    hits: list[Hit]
    respuesta: str
    citas_validas: list[Cita]
    citas_invalidas: list[Cita]
    fuentes: list[str]
    avisos: Annotated[list[str], operator.add]
    tiempos: Annotated[dict[str, float], operator.or_]


def construir_grafo(retriever: Retriever | None, llm: LLM, k_default: int = 6):
    def retrieve(estado: Estado) -> dict[str, Any]:
        t0 = time.perf_counter()
        if retriever is None:
            return {"hits": [], "tiempos": {"retrieve_s": 0.0}}
        hits = retriever.buscar(estado["pregunta"], estado.get("k") or k_default)
        return {"hits": hits, "tiempos": {"retrieve_s": time.perf_counter() - t0}}

    def answer(estado: Estado) -> dict[str, Any]:
        hits = estado.get("hits") or []
        if not hits:
            return {"respuesta": SIN_EVIDENCIA, "citas_validas": [], "citas_invalidas": [], "fuentes": []}

        t0 = time.perf_counter()
        respuesta = llm.generar(SYSTEM_PROMPT, construir_mensaje_usuario(estado["pregunta"], hits))
        validas, invalidas = clasificar_citas(extraer_citas(respuesta), hits)

        avisos = []
        if invalidas:
            avisos.append(
                "La respuesta cita fuentes que NO están entre los fragmentos recuperados: "
                + ", ".join(map(str, invalidas))
            )
        if not validas and not llm.simulado:
            avisos.append("La respuesta no incluye ninguna cita verificable: tratarla con cautela.")

        return {
            "respuesta": respuesta,
            "citas_validas": validas,
            "citas_invalidas": invalidas,
            "fuentes": armar_fuentes(validas, hits),
            "avisos": avisos,
            "tiempos": {"llm_s": time.perf_counter() - t0},
        }

    g = StateGraph(Estado)
    g.add_node("retrieve", retrieve)
    g.add_node("answer", answer)
    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "answer")
    g.add_edge("answer", END)
    return g.compile()


def crear_retriever(settings: Settings) -> tuple[Retriever | None, list[str]]:
    """Abre índice + embedder. Si no hay índice, devuelve (None, [aviso]) sin cargar el modelo."""
    store = abrir_store(settings)
    if store.meta() is None or store.count() == 0:
        return None, [str(IndiceNoDisponible(
            "No hay índice para CORPUS=" + settings.corpus + ". Correr: "
            "uv run python -m troubleshooting_agent.ingest && "
            "uv run python -m troubleshooting_agent.retrieval.index"
        ))]
    from troubleshooting_agent.retrieval.embeddings import crear_embedder

    try:
        return Retriever(store, crear_embedder(settings)), []
    except (IndiceNoDisponible, IndiceIncompatible) as e:
        return None, [str(e)]


def crear_agente(settings: Settings):
    """Devuelve (grafo compilado, avisos de arranque)."""
    retriever, avisos_r = crear_retriever(settings)
    llm, avisos_l = crear_llm(settings)
    return construir_grafo(retriever, llm, settings.retrieval_k), avisos_r + avisos_l
