"""Tools del agente: dos fuentes bien diferenciadas.

- `buscar_manual`: documentación del fabricante (colección `chunks_*`).
- `buscar_historial`: casos de fallas resueltas (colección `historial_*`).

Ambas filtran por el equipo identificado. Si el filtro por modelo deja sin
resultados, `buscar_manual` reintenta solo con la clase y lo avisa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from troubleshooting_agent.agent.equipo import Equipo
from troubleshooting_agent.retrieval.retriever import Retriever
from troubleshooting_agent.retrieval.store import Filtros, Hit


@dataclass
class ResultadoBusqueda:
    hits: list[Hit]
    filtros: Filtros = field(default_factory=dict)
    avisos: list[str] = field(default_factory=list)

    def resumen(self, modelo: str | None = None) -> str:
        if not self.hits:
            return "0 resultados"
        partes = [f"{len(self.hits)} resultados", f"mejor score {self.hits[0].score:.2f}"]
        if modelo:
            del_modelo = sum(modelo in (h.payload.get("modelos") or []) for h in self.hits)
            partes.append(f"{del_modelo} del modelo {modelo}")
        if self.filtros:
            partes.append("filtros " + ", ".join(f"{k}={v}" for k, v in self.filtros.items()))
        return " · ".join(partes)


def buscar_manual(retriever: Retriever | None, consulta: str, equipo: Equipo, k: int) -> ResultadoBusqueda:
    if retriever is None:
        return ResultadoBusqueda([], avisos=["No hay índice de manuales: buscar_manual no devolvió nada."])
    filtros: Filtros = {}
    if equipo.clase_equipo:
        filtros["clase_equipo"] = equipo.clase_equipo
    if equipo.modelo:
        filtros["modelos"] = equipo.modelo
    hits = retriever.buscar(consulta, k, filtros or None)
    avisos: list[str] = []
    if not hits and "modelos" in filtros:
        avisos.append(
            f"No hay fragmentos indexados del modelo {equipo.modelo}; se usan manuales de otros modelos "
            f"de la misma clase ({equipo.clase_equipo})."
        )
        filtros.pop("modelos")
        hits = retriever.buscar(consulta, k, filtros or None)
    return ResultadoBusqueda(hits, filtros, avisos)


def buscar_historial(retriever: Retriever | None, consulta: str, equipo: Equipo, k: int) -> ResultadoBusqueda:
    if retriever is None:
        return ResultadoBusqueda([], avisos=["No hay índice del historial de fallas: buscar_historial no devolvió nada."])
    filtros: Filtros = {"clase_equipo": equipo.clase_equipo} if equipo.clase_equipo else {}
    return ResultadoBusqueda(retriever.buscar(consulta, k, filtros or None), filtros)


def unir_hits(previos: list[Hit], nuevos: list[Hit]) -> list[Hit]:
    """Une sin duplicar por chunk_id (se queda con el mayor score), ordenado por score."""
    por_id: dict[str, Hit] = {}
    for h in [*previos, *nuevos]:
        cid = h.payload["chunk_id"]
        if cid not in por_id or h.score > por_id[cid].score:
            por_id[cid] = h
    return sorted(por_id.values(), key=lambda h: -h.score)
