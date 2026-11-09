"""Extracción y verificación de citas [doc_id, p. N] en la respuesta del LLM."""

from __future__ import annotations

import re
from dataclasses import dataclass

from troubleshooting_agent.retrieval.store import Hit

_CORCHETES = re.compile(r"\[([^\[\]]+)\]")
_CITA = re.compile(
    r"^\s*(?P<doc>[A-Za-z0-9][\w.\-]*)\s*,\s*"
    r"(?:p(?:ág|ag|age)?s?\.?|página|pagina)\s*(?P<ini>\d+)(?:\s*[-–]\s*(?P<fin>\d+))?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Cita:
    doc_id: str
    pagina: int

    def __str__(self) -> str:
        return f"[{self.doc_id}, p. {self.pagina}]"


def extraer_citas(texto: str) -> list[Cita]:
    """Citas en orden de aparición, sin repetir. Acepta varias en un corchete separadas por ';'.

    Un rango [doc, p. 5-6] se registra por su página inicial.
    """
    vistas: dict[Cita, None] = {}
    for contenido in _CORCHETES.findall(texto):
        for parte in contenido.split(";"):
            m = _CITA.match(parte)
            if m:
                vistas[Cita(m["doc"], int(m["ini"]))] = None
    return list(vistas)


def clasificar_citas(citas: list[Cita], hits: list[Hit]) -> tuple[list[Cita], list[Cita]]:
    """(válidas, inválidas): válida = (doc_id, página) está entre los fragmentos recuperados."""
    recuperadas = {(h.payload["doc_id"], h.payload["pagina_inicio"]) for h in hits}
    validas = [c for c in citas if (c.doc_id, c.pagina) in recuperadas]
    invalidas = [c for c in citas if (c.doc_id, c.pagina) not in recuperadas]
    return validas, invalidas


def armar_fuentes(citas: list[Cita], hits: list[Hit]) -> list[str]:
    """Líneas 'Fuentes' armadas desde el payload (no desde el texto del LLM)."""
    por_clave = {(h.payload["doc_id"], h.payload["pagina_inicio"]): h.payload for h in hits}
    lineas = []
    for c in citas:
        p = por_clave.get((c.doc_id, c.pagina))
        if p is None:
            continue
        detalle = " · ".join(x for x in (p.get("titulo"), p.get("seccion")) if x)
        lineas.append(f"{c} {detalle}")
    return lineas
