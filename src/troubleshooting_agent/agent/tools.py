"""Tools del agente: dos fuentes bien diferenciadas.

- `buscar_manual`: documentación del fabricante (colección `chunks_*`).
- `buscar_historial`: casos de fallas resueltas (colección `historial_*`).

Ambas filtran por el equipo identificado. Si el filtro por modelo deja sin
resultados, `buscar_manual` reintenta solo con la clase y lo avisa. Si hay código de
falla, `buscar_manual` busca primero en las secciones de troubleshooting / códigos de
falla (tipo_contenido del catálogo) y completa con el resto del manual.

El router reescribe la consulta (p. ej. agrega el nombre de la falla en inglés). Eso
ayuda con manuales en inglés, pero a veces recupera peor que la pregunta original del
técnico: si se pasa `consulta_original`, `buscar_manual` busca con las dos y las fusiona
por RRF (un fragmento que aparece arriba en cualquiera de las dos queda arriba).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from troubleshooting_agent.agent.equipo import Equipo
from troubleshooting_agent.retrieval.retriever import Retriever, rrf
from troubleshooting_agent.retrieval.store import Filtros, Hit


TIPOS_FALLAS = ["troubleshooting", "codigos_falla"]


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


def buscar_manual(
    retriever: Retriever | None, consulta: str, equipo: Equipo, k: int, *, priorizar_fallas: bool = True,
    consulta_original: str | None = None,
) -> ResultadoBusqueda:
    if retriever is None:
        return ResultadoBusqueda([], avisos=["No hay índice de manuales: buscar_manual no devolvió nada."])
    filtros: Filtros = {}
    if equipo.clase_equipo:
        filtros["clase_equipo"] = equipo.clase_equipo
    if equipo.modelo:
        filtros["modelos"] = equipo.modelo
    priorizar = priorizar_fallas and bool(equipo.codigo_falla)

    consultas = [consulta]
    if consulta_original and " ".join(consulta_original.split()).lower() != " ".join(consulta.split()).lower():
        consultas.append(consulta_original)

    def _una(q: str, f: Filtros) -> list[Hit]:
        hits = retriever.buscar(q, k, {**f, "tipo_contenido": TIPOS_FALLAS}) if priorizar else []
        if len(hits) < k:  # completar con el resto del manual
            vistos = {h.payload["chunk_id"] for h in hits}
            hits += [h for h in retriever.buscar(q, k, f or None) if h.payload["chunk_id"] not in vistos]
        return hits[:k]

    def _buscar(f: Filtros) -> list[Hit]:
        listas = [_una(q, f) for q in consultas]
        return listas[0] if len(listas) == 1 else rrf(listas, k)

    avisos: list[str] = []
    hits = _buscar(filtros)
    if not hits and "modelos" in filtros:
        avisos.append(
            f"No hay fragmentos indexados del modelo {equipo.modelo}; se usan manuales de otros modelos "
            f"de la misma clase ({equipo.clase_equipo})."
        )
        filtros.pop("modelos")
        hits = _buscar(filtros)
    if priorizar:
        filtros = {**filtros, "prioridad": "secciones de fallas"}
    if len(consultas) > 1:
        filtros = {**filtros, "fusion": "consulta + pregunta original"}
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
