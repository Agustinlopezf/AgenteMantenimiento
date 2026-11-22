"""Estado persistente de los diagnósticos: checkpointer SQLite de LangGraph.

Cada diagnóstico es un `thread_id`. Si el grafo queda pausado (pedido de datos o
aprobación pendiente), el estado queda en `STATE_DB` y se puede retomar desde otro
proceso con `--reanudar <thread_id>`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

# Tipos propios que viajan en el estado y el checkpointer puede deserializar.
TIPOS_ESTADO = [
    ("troubleshooting_agent.retrieval.store", "Hit"),
    ("troubleshooting_agent.agent.citas", "Cita"),
    ("troubleshooting_agent.agent.citas", "CitaCaso"),
]


def serializador() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=TIPOS_ESTADO)


def abrir_checkpointer(path: Path) -> SqliteSaver:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(conn, serde=serializador())
    saver.setup()
    return saver


def thread_ids(checkpointer: SqliteSaver) -> list[str]:
    """Diagnósticos guardados, del más reciente al más viejo."""
    filas = checkpointer.conn.execute(
        "SELECT thread_id, MAX(checkpoint_id) AS ultimo FROM checkpoints GROUP BY thread_id ORDER BY ultimo DESC"
    ).fetchall()
    return [f[0] for f in filas]


def listar_diagnosticos(grafo, checkpointer: SqliteSaver, solo_pendientes: bool = True) -> list[dict[str, Any]]:
    from troubleshooting_agent.agent.graph import estado_actual, pendiente

    salida = []
    for tid in thread_ids(checkpointer):
        valores = estado_actual(grafo, tid)
        if valores is None:
            continue
        pausa = pendiente(valores)
        if solo_pendientes and pausa is None:
            continue
        salida.append({
            "thread_id": tid,
            "creado": valores.get("creado", ""),
            "pregunta": valores.get("pregunta", ""),
            "espera": pausa["tipo"] if pausa else None,
            "cierre": valores.get("cierre"),
        })
    return salida
