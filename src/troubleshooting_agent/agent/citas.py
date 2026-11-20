"""Extracción y verificación de citas en la respuesta del LLM.

- Manual: [doc_id, p. N]
- Historial: [historial, caso ID]
"""

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
_CITA_CASO = re.compile(r"^\s*historial\s*,\s*caso\s+(?P<caso>[\w.\-]+)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Cita:
    doc_id: str
    pagina: int

    def __str__(self) -> str:
        return f"[{self.doc_id}, p. {self.pagina}]"


@dataclass(frozen=True)
class CitaCaso:
    caso_id: str

    def __str__(self) -> str:
        return f"[historial, caso {self.caso_id}]"


CitaAny = Cita | CitaCaso


def extraer_citas(texto: str) -> list[CitaAny]:
    """Citas en orden de aparición, sin repetir. Acepta varias en un corchete separadas por ';'.

    Un rango [doc, p. 5-6] se registra por su página inicial.
    """
    vistas: dict[CitaAny, None] = {}
    for contenido in _CORCHETES.findall(texto):
        for parte in contenido.split(";"):
            if m := _CITA_CASO.match(parte):
                vistas[CitaCaso(m["caso"])] = None
            elif m := _CITA.match(parte):
                vistas[Cita(m["doc"], int(m["ini"]))] = None
    return list(vistas)


def _clave(hit: Hit) -> CitaAny:
    p = hit.payload
    if "caso_id" in p:
        return CitaCaso(str(p["caso_id"]))
    return Cita(p["doc_id"], p["pagina_inicio"])


def clasificar_citas(citas: list[CitaAny], hits: list[Hit]) -> tuple[list[CitaAny], list[CitaAny]]:
    """(válidas, inválidas): válida = la página o el caso está entre los fragmentos recuperados."""
    recuperadas = {_clave(h) for h in hits}
    validas = [c for c in citas if c in recuperadas]
    invalidas = [c for c in citas if c not in recuperadas]
    return validas, invalidas


def armar_fuentes(citas: list[CitaAny], hits: list[Hit]) -> list[str]:
    """Líneas 'Fuentes' armadas desde el payload (no desde el texto del LLM)."""
    por_clave = {_clave(h): h.payload for h in hits}
    lineas = []
    for c in citas:
        p = por_clave.get(c)
        if p is None:
            continue
        if isinstance(c, CitaCaso):
            origen = "caso sintético" if p.get("sintetico") else "caso real"
            partes = [p.get("titulo"), p.get("pozo"), p.get("fecha"), origen]
        else:
            partes = [p.get("titulo"), p.get("seccion")]
        lineas.append(f"{c} " + " · ".join(str(x) for x in partes if x))
    return lineas
