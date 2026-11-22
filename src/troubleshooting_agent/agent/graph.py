"""Grafo LangGraph: el agente decide qué fuente consultar y un responsable aprueba la intervención.

    START → identificar_equipo → decidir ─┬─ buscar_manual    ─┐
                 ▲                        ├─ buscar_historial ─┴→ decidir
                 └──── pedir_datos ◄──────┤   (pausa: interrupt → respuesta del técnico)
                                          └─ responder ─→ proponer_intervencion ─→ aprobacion (pausa)
                                                 │                 ▲                 │
                                                 ▼ (sin evidencia) └── modificar ────┤
                                                END ◄── rechazar ────────────────────┤
                                                    ◄── emitir_orden ◄── aprobar ────┘

`decidir` usa el LLM (salida JSON) con guardas y un router de reglas de respaldo
(ver router.py). `pedir_datos` y `aprobacion` pausan el grafo con `interrupt()`; se
reanuda con `Command(resume=...)` sobre el mismo `thread_id`. Con el checkpointer
SQLite (ver estado.py) el diagnóstico pendiente sobrevive al cierre del proceso.

Pedir datos es comportamiento agéntico; el HITL es `aprobacion`: el responsable
aprueba / modifica / rechaza la propuesta y, si aprueba, se emite una orden de
trabajo simulada (propuesta.py).
"""

from __future__ import annotations

import operator
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from troubleshooting_agent.agent import router
from troubleshooting_agent.agent.citas import CitaAny, armar_fuentes, clasificar_citas, extraer_citas
from troubleshooting_agent.agent.equipo import Equipo, IdentificadorEquipo
from troubleshooting_agent.agent.estado import abrir_checkpointer, serializador
from troubleshooting_agent.agent.fidelidad import evaluar_fidelidad, resumen_fidelidad
from troubleshooting_agent.agent.llm import LLM, crear_llm
from troubleshooting_agent.agent.prompts import construir_mensaje_usuario, system_prompt
from troubleshooting_agent.agent.propuesta import (
    MAX_MODIFICACIONES,
    emitir_orden,
    formatear_propuesta,
    generar_propuesta,
    normalizar_aprobacion,
)
from troubleshooting_agent.agent.tools import buscar_historial, buscar_manual, unir_hits
from troubleshooting_agent.config import REPO_ROOT
from troubleshooting_agent.retrieval.bm25 import BM25
from troubleshooting_agent.retrieval.retriever import IndiceIncompatible, IndiceNoDisponible, Retriever, RetrieverHibrido
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
    fidelidad: dict[str, Any]  # chequeo por afirmación (fidelidad.py)
    avisos: Annotated[list[str], operator.add]
    tiempos: Annotated[dict[str, float], _sumar]
    # ── aprobación humana (HITL) ──
    thread_id: str
    creado: str
    propuesta: dict[str, Any]
    indicaciones: Annotated[list[str], operator.add]  # cambios pedidos por el responsable
    modificaciones: int
    aprobacion: dict[str, str]
    orden: dict[str, Any]
    cierre: str  # sin_evidencia | sin_propuesta | aprobado | rechazado


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
    dir_ordenes: Path | None = None,
    juez_fidelidad: bool = False,
):
    identificador = identificador or IdentificadorEquipo({}, [])
    dir_ordenes = dir_ordenes or REPO_ROOT / "artifacts" / "ordenes"

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
            return {"respuesta": texto, "citas_validas": [], "citas_invalidas": [], "fuentes": [],
                    "cierre": "sin_evidencia"}

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
        t_fid = time.perf_counter()
        fidelidad = evaluar_fidelidad(respuesta, todos, llm if juez_fidelidad else None)
        dudosas = [a for a in fidelidad["afirmaciones"] if a["veredicto"] in ("no_respaldada", "parcial")]
        if dudosas:
            avisos.append(
                f"{len(dudosas)} afirmación(es) con datos que no están en la fuente citada: "
                + "; ".join(f"«{a['texto'][:70]}…» ({', '.join(a['faltantes']) or a['motivo']})" for a in dudosas[:3])
            )

        return {
            "respuesta": respuesta,
            "citas_validas": validas,
            "citas_invalidas": invalidas,
            "fuentes": armar_fuentes(validas, todos),
            "fidelidad": fidelidad,
            "avisos": avisos,
            "traza": [{"tipo": "fidelidad", "texto": resumen_fidelidad(fidelidad)}],
            "tiempos": {"llm_s": t_fid - t0, "fidelidad_s": time.perf_counter() - t_fid},
        }

    def proponer_intervencion(estado: Estado) -> dict[str, Any]:
        t0 = time.perf_counter()
        n = estado.get("modificaciones") or 0
        p = generar_propuesta(
            llm, _texto_tecnico(estado), _equipo(estado).resumen(), estado.get("respuesta", ""),
            estado.get("hits") or [], estado.get("casos") or [],
            previa=estado.get("propuesta") if n else None, indicaciones=estado.get("indicaciones") or [],
        )
        p["version"] = n + 1
        salida: dict[str, Any] = {
            "propuesta": p,
            "traza": [{"tipo": "propuesta", "version": n + 1, "origen": p["origen"],
                       "texto": f"{len(p['verificaciones'])} verificaciones · prioridad {p['prioridad']}"
                                + (f" · {len(p['descartadas'])} descartadas (cita no verificable)" if p["descartadas"] else "")}],
            "tiempos": {"propuesta_s": time.perf_counter() - t0},
            "avisos": [p["nota"]] if p.get("nota") else [],
        }
        if not p["verificaciones"]:
            salida["cierre"] = "sin_propuesta"
            salida["avisos"] = [*salida["avisos"], "No se pudo armar una propuesta de intervención con citas verificables."]
        return salida

    def aprobacion(estado: Estado) -> dict[str, Any]:
        p, n = estado["propuesta"], estado.get("modificaciones") or 0
        valor = interrupt({
            "tipo": "aprobacion",
            "propuesta": p,
            "texto": formatear_propuesta(p),
            "modificaciones": n,
            "puede_modificar": n < MAX_MODIFICACIONES,
        })
        a = normalizar_aprobacion(valor)
        nota = ""
        if a["decision"] == "modificar" and n >= MAX_MODIFICACIONES:
            a["decision"], nota = "invalida", f"ya se modificó {MAX_MODIFICACIONES} veces: aprobar o rechazar"
        elif a["decision"] == "modificar" and not a["comentario"]:
            a["decision"], nota = "invalida", "para modificar hay que indicar qué cambiar"
        elif a["decision"] == "invalida":
            nota = "decisión no reconocida (aprobar / modificar / rechazar)"
        salida: dict[str, Any] = {
            "aprobacion": a,
            "traza": [{"tipo": "aprobacion", **a, **({"nota": nota} if nota else {})}],
        }
        if a["decision"] == "modificar":
            salida |= {"indicaciones": [a["comentario"]], "modificaciones": n + 1}
        elif a["decision"] == "rechazar":
            salida["cierre"] = "rechazado"
        return salida

    def nodo_emitir_orden(estado: Estado) -> dict[str, Any]:
        orden = emitir_orden(
            dir_ordenes, estado.get("thread_id") or "sin-thread", estado["equipo"], _texto_tecnico(estado),
            estado["propuesta"], estado["aprobacion"], estado.get("traza") or [],
        )
        return {"orden": orden, "cierre": "aprobado", "traza": [{"tipo": "orden", "texto": orden["ot_id"]}]}

    def ruta(estado: Estado) -> str:
        return estado["decision"]["accion"]

    def ruta_respuesta(estado: Estado) -> str:
        return END if estado.get("cierre") == "sin_evidencia" else "proponer_intervencion"

    def ruta_propuesta(estado: Estado) -> str:
        return END if estado.get("cierre") == "sin_propuesta" else "aprobacion"

    def ruta_aprobacion(estado: Estado) -> str:
        return {"aprobar": "emitir_orden", "rechazar": END, "modificar": "proponer_intervencion"}.get(
            estado["aprobacion"]["decision"], "aprobacion")

    g = StateGraph(Estado)
    g.add_node("identificar_equipo", identificar_equipo)
    g.add_node("decidir", decidir)
    g.add_node("buscar_manual", nodo_buscar_manual)
    g.add_node("buscar_historial", nodo_buscar_historial)
    g.add_node("pedir_datos", pedir_datos)
    g.add_node("responder", responder)
    g.add_node("proponer_intervencion", proponer_intervencion)
    g.add_node("aprobacion", aprobacion)
    g.add_node("emitir_orden", nodo_emitir_orden)
    g.add_edge(START, "identificar_equipo")
    g.add_edge("identificar_equipo", "decidir")
    g.add_conditional_edges("decidir", ruta, {a: a for a in router.ACCIONES})
    g.add_edge("buscar_manual", "decidir")
    g.add_edge("buscar_historial", "decidir")
    g.add_edge("pedir_datos", "identificar_equipo")
    g.add_conditional_edges("responder", ruta_respuesta, ["proponer_intervencion", END])
    g.add_conditional_edges("proponer_intervencion", ruta_propuesta, ["aprobacion", END])
    g.add_conditional_edges("aprobacion", ruta_aprobacion, ["emitir_orden", "proponer_intervencion", "aprobacion", END])
    g.add_edge("emitir_orden", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver(serde=serializador()))


# ── ejecución por turnos ────────────────────────────────────


def nuevo_thread_id() -> str:
    return uuid.uuid4().hex[:12]


def _config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}, "recursion_limit": 40}


def iniciar(grafo, pregunta: str, thread_id: str, k: int | None = None) -> dict[str, Any]:
    entrada: dict[str, Any] = {"pregunta": pregunta, "turnos": [pregunta], "avisos": [], "tiempos": {},
                               "thread_id": thread_id, "creado": datetime.now().isoformat(timespec="seconds")}
    if k:
        entrada["k"] = k
    return grafo.invoke(entrada, _config(thread_id))


def reanudar(grafo, respuesta: Any, thread_id: str) -> dict[str, Any]:
    """`respuesta`: texto (pedir_datos) o {"decision", "comentario", "responsable"} (aprobacion)."""
    return grafo.invoke(Command(resume=respuesta), _config(thread_id))


def estado_actual(grafo, thread_id: str) -> dict[str, Any] | None:
    """Valores guardados de un diagnóstico (+ `__interrupt__` si está pausado), o None si no existe."""
    snap = grafo.get_state(_config(thread_id))
    if not snap.values:
        return None
    return {**snap.values, "__interrupt__": list(snap.interrupts)}


def pendiente(resultado: dict[str, Any]) -> dict[str, Any] | None:
    """Si el grafo quedó pausado, devuelve el payload del interrupt (tipo pedir_datos | aprobacion)."""
    interrupciones = resultado.get("__interrupt__") or []
    return interrupciones[0].value if interrupciones else None


# ── armado con settings ─────────────────────────────────────


def _abrir_retriever(store, coleccion: str, embedder, modo: str = "hibrido") -> tuple[Any, list[str]]:
    try:
        denso = Retriever(store, embedder)
    except (IndiceNoDisponible, IndiceIncompatible) as e:
        return None, [f"[{coleccion}] {e}"]
    if modo == "denso":
        return denso, []
    return RetrieverHibrido(denso, BM25(store.payloads()), modo), []


def crear_retriever(settings: Settings) -> tuple[Retriever | None, Retriever | None, list[str]]:
    """Abre manuales + historial con un solo embedder. Sin índice de manuales no carga el modelo."""
    try:
        store = abrir_store(settings)
    except RuntimeError as e:  # Qdrant local: la carpeta del índice la tiene abierta otro proceso
        if "already accessed" not in str(e):
            raise
        return None, None, [
            "El índice Qdrant está abierto por otro proceso (Qdrant local no admite acceso concurrente). "
            "Cerrar la otra sesión del agente o la evaluación y volver a intentar."
        ]
    if store.meta() is None or store.count() == 0:
        return None, None, [str(IndiceNoDisponible(
            "No hay índice para CORPUS=" + settings.corpus + ". Correr: "
            "uv run python -m troubleshooting_agent.ingest && "
            "uv run python -m troubleshooting_agent.retrieval.index"
        ))]
    from troubleshooting_agent.retrieval.embeddings import crear_embedder

    embedder = crear_embedder(settings)
    # Qdrant local bloquea la carpeta: reusar el store ya abierto, no abrir otro cliente.
    modo = settings.retrieval_mode
    manual, avisos = _abrir_retriever(store, "chunks", embedder, modo)
    historial, avisos_h = _abrir_retriever(abrir_store(settings, coleccion="historial"), "historial", embedder, modo)
    return manual, historial, avisos + avisos_h


def crear_grafo_estado(settings: Settings):
    """Grafo sin índice ni LLM: alcanza para listar / leer diagnósticos guardados (rápido)."""
    from troubleshooting_agent.agent.llm import LLMSimulado

    return construir_grafo(None, LLMSimulado(), checkpointer=abrir_checkpointer(settings.state_db))


def crear_agente(settings: Settings, checkpointer: Any = None):
    """Devuelve (grafo compilado, avisos de arranque). Por defecto, estado persistente en STATE_DB."""
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
        checkpointer=checkpointer or abrir_checkpointer(settings.state_db),
        dir_ordenes=settings.ordenes_dir,
        juez_fidelidad=settings.fidelidad_llm,
    )
    return grafo, avisos_r + avisos_l
