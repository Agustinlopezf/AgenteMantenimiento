"""Grafo LangGraph del hito 2: el agente decide qué fuente consultar.

    START → identificar_equipo → decidir ─┬─ buscar_manual    ─┐
                 ▲                        ├─ buscar_historial ─┴→ decidir
                 └──── pedir_datos ◄──────┤   (pausa: interrupt → respuesta del técnico)
                                          └─ responder → END

`decidir` usa el LLM (salida JSON) con guardas y un router de reglas de respaldo
(ver router.py). `pedir_datos` pausa el grafo con `interrupt()`; se reanuda con
`Command(resume=texto)` sobre el mismo `thread_id` (requiere checkpointer).
"""

from __future__ import annotations

import operator
import time
import uuid
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from troubleshooting_agent.agent import router
from troubleshooting_agent.agent.citas import CitaAny, armar_fuentes, clasificar_citas, extraer_citas
from troubleshooting_agent.agent.equipo import Equipo, IdentificadorEquipo
from troubleshooting_agent.agent.llm import LLM, crear_llm
from troubleshooting_agent.agent.prompts import construir_mensaje_usuario, system_prompt
from troubleshooting_agent.agent.tools import buscar_historial, buscar_manual, unir_hits
from troubleshooting_agent.retrieval.retriever import IndiceIncompatible, IndiceNoDisponible, Retriever
from troubleshooting_agent.retrieval.store import Hit, abrir_store

if TYPE_CHECKING:
    from troubleshooting_agent.config import Settings

SIN_EVIDENCIA = (
    "No encontré evidencia en el corpus indexado para responder esta consulta, "
    "así que no puedo indicar causas ni procedimientos."
)
K_HISTORIAL = 4


def _sumar(a: dict[str, float], b: dict[str, float]) -> dict[str, float]:
    return {k: a.get(k, 0.0) + b.get(k, 0.0) for k in {*a, *b}}


class Estado(TypedDict, total=False):
    pregunta: str  # primera consulta del técnico
    turnos: Annotated[list[str], operator.add]  # todo lo que dijo el técnico
    k: int
    equipo: dict[str, Any]
    decision: dict[str, Any]
    consultas: Annotated[list[dict[str, Any]], operator.add]  # tools ejecutadas
    pedidos: int
    hits: list[Hit]  # manual
    casos: list[Hit]  # historial
    traza: Annotated[list[dict[str, Any]], operator.add]
    respuesta: str
    citas_validas: list[CitaAny]
    citas_invalidas: list[CitaAny]
    fuentes: list[str]
    avisos: Annotated[list[str], operator.add]
    tiempos: Annotated[dict[str, float], _sumar]


def _texto_tecnico(estado: Estado) -> str:
    return " ".join(t.strip() for t in (estado.get("turnos") or [estado.get("pregunta", "")]) if t and t.strip())


def _equipo(estado: Estado) -> Equipo:
    return Equipo(**estado["equipo"])


def construir_grafo(
    retriever: Retriever | None,
    llm: LLM,
    k_default: int = 6,
    *,
    retriever_historial: Retriever | None = None,
    identificador: IdentificadorEquipo | None = None,
    checkpointer: Any = None,
):
    identificador = identificador or IdentificadorEquipo({}, [])

    def identificar_equipo(estado: Estado) -> dict[str, Any]:
        eq = identificador.identificar(_texto_tecnico(estado))
        if not identificador.clases_en_corpus:  # sin catálogo (tests mínimos): no bloquear
            eq.en_corpus = True
        return {"equipo": eq.como_dict(), "traza": [{"tipo": "equipo", "texto": eq.resumen()}]}

    def decidir(estado: Estado) -> dict[str, Any]:
        t0 = time.perf_counter()
        ctx = router.Contexto(
            texto=_texto_tecnico(estado),
            equipo=_equipo(estado),
            consultas=estado.get("consultas") or [],
            pedidos=estado.get("pedidos") or 0,
            clases_en_corpus=identificador.clases_en_corpus,
        )
        d = router.decidir(llm, ctx)
        return {
            "decision": d.como_dict(),
            "traza": [{"tipo": "decision", "paso": ctx.pasos + 1, **d.como_dict()}],
            "tiempos": {"router_s": time.perf_counter() - t0},
        }

    def _tool(estado: Estado, nombre: str) -> dict[str, Any]:
        t0 = time.perf_counter()
        d, eq, k = estado["decision"], _equipo(estado), estado.get("k") or k_default
        if nombre == "buscar_manual":
            r = buscar_manual(retriever, d["consulta"], eq, k)
            clave = "hits"
        else:
            r = buscar_historial(retriever_historial, d["consulta"], eq, K_HISTORIAL)
            clave = "casos"
        resumen = r.resumen(eq.modelo)
        return {
            clave: unir_hits(estado.get(clave) or [], r.hits),
            "consultas": [{"accion": nombre, "consulta": d["consulta"], "resumen": resumen, "n": len(r.hits)}],
            "traza": [{"tipo": "resultado", "accion": nombre, "texto": resumen}],
            "avisos": r.avisos,
            "tiempos": {"retrieve_s": time.perf_counter() - t0},
        }

    def nodo_buscar_manual(estado: Estado) -> dict[str, Any]:
        return _tool(estado, "buscar_manual")

    def nodo_buscar_historial(estado: Estado) -> dict[str, Any]:
        return _tool(estado, "buscar_historial")

    def pedir_datos(estado: Estado) -> dict[str, Any]:
        pregunta = estado["decision"]["pregunta"]
        respuesta = interrupt({"tipo": "pedir_datos", "pregunta": pregunta})
        texto = str(respuesta or "").strip()
        return {
            "turnos": [texto] if texto else [],
            "pedidos": (estado.get("pedidos") or 0) + 1,
            "traza": [{"tipo": "respuesta_tecnico", "texto": texto or "(sin respuesta)"}],
        }

    def responder(estado: Estado) -> dict[str, Any]:
        hits, casos = estado.get("hits") or [], estado.get("casos") or []
        eq = _equipo(estado)
        if not hits and not casos:
            texto = SIN_EVIDENCIA
            if eq.clase_equipo and not eq.en_corpus:
                texto += f" No hay manuales indexados para la clase de equipo '{eq.clase_equipo}'."
            elif eq.clase_equipo is None:
                texto += " Tampoco pude identificar de qué equipo se trata."
            return {"respuesta": texto, "citas_validas": [], "citas_invalidas": [], "fuentes": []}

        t0 = time.perf_counter()
        pregunta = _texto_tecnico(estado)
        respuesta = llm.generar(system_prompt(), construir_mensaje_usuario(pregunta, hits, casos))
        todos = [*hits, *casos]
        validas, invalidas = clasificar_citas(extraer_citas(respuesta), todos)

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
            "fuentes": armar_fuentes(validas, todos),
            "avisos": avisos,
            "tiempos": {"llm_s": time.perf_counter() - t0},
        }

    def ruta(estado: Estado) -> str:
        return estado["decision"]["accion"]

    g = StateGraph(Estado)
    g.add_node("identificar_equipo", identificar_equipo)
    g.add_node("decidir", decidir)
    g.add_node("buscar_manual", nodo_buscar_manual)
    g.add_node("buscar_historial", nodo_buscar_historial)
    g.add_node("pedir_datos", pedir_datos)
    g.add_node("responder", responder)
    g.add_edge(START, "identificar_equipo")
    g.add_edge("identificar_equipo", "decidir")
    g.add_conditional_edges("decidir", ruta, {a: a for a in router.ACCIONES})
    g.add_edge("buscar_manual", "decidir")
    g.add_edge("buscar_historial", "decidir")
    g.add_edge("pedir_datos", "identificar_equipo")
    g.add_edge("responder", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


# ── ejecución por turnos ────────────────────────────────────


def nuevo_thread_id() -> str:
    return uuid.uuid4().hex[:12]


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}


def iniciar(grafo, pregunta: str, thread_id: str, k: int | None = None) -> dict[str, Any]:
    entrada: dict[str, Any] = {"pregunta": pregunta, "turnos": [pregunta], "avisos": [], "tiempos": {}}
    if k:
        entrada["k"] = k
    return grafo.invoke(entrada, _config(thread_id))


def reanudar(grafo, respuesta: str, thread_id: str) -> dict[str, Any]:
    return grafo.invoke(Command(resume=respuesta), _config(thread_id))


def pendiente(resultado: dict[str, Any]) -> dict[str, Any] | None:
    """Si el grafo quedó pausado, devuelve el payload del interrupt ({tipo, pregunta})."""
    interrupciones = resultado.get("__interrupt__") or []
    return interrupciones[0].value if interrupciones else None


# ── armado con settings ─────────────────────────────────────


def _abrir_retriever(store, coleccion: str, embedder) -> tuple[Retriever | None, list[str]]:
    try:
        return Retriever(store, embedder), []
    except (IndiceNoDisponible, IndiceIncompatible) as e:
        return None, [f"[{coleccion}] {e}"]


def crear_retriever(settings: Settings) -> tuple[Retriever | None, Retriever | None, list[str]]:
    """Abre manuales + historial con un solo embedder. Sin índice de manuales no carga el modelo."""
    store = abrir_store(settings)
    if store.meta() is None or store.count() == 0:
        return None, None, [str(IndiceNoDisponible(
            "No hay índice para CORPUS=" + settings.corpus + ". Correr: "
            "uv run python -m troubleshooting_agent.ingest && "
            "uv run python -m troubleshooting_agent.retrieval.index"
        ))]
    from troubleshooting_agent.retrieval.embeddings import crear_embedder

    embedder = crear_embedder(settings)
    # Qdrant local bloquea la carpeta: reusar el store ya abierto, no abrir otro cliente.
    manual, avisos = _abrir_retriever(store, "chunks", embedder)
    historial, avisos_h = _abrir_retriever(abrir_store(settings, coleccion="historial"), "historial", embedder)
    return manual, historial, avisos + avisos_h


def crear_agente(settings: Settings, checkpointer: Any = None):
    """Devuelve (grafo compilado, avisos de arranque)."""
    from troubleshooting_agent.catalog import load_catalog

    retriever, retriever_hist, avisos_r = crear_retriever(settings)
    llm, avisos_l = crear_llm(settings)
    identificador = IdentificadorEquipo.desde_catalogo(load_catalog(settings.catalog_path), settings.corpus)
    grafo = construir_grafo(
        retriever,
        llm,
        settings.retrieval_k,
        retriever_historial=retriever_hist,
        identificador=identificador,
        checkpointer=checkpointer,
    )
    return grafo, avisos_r + avisos_l
