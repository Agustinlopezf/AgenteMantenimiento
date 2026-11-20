"""Skills del agente: guías en Markdown versionadas, divididas por sección `##`."""

from __future__ import annotations

from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent


@cache
def cargar_skill(nombre: str) -> dict[str, str]:
    """{titulo_seccion_en_minusculas: cuerpo}. El texto antes del primer `##` se descarta."""
    texto = (_DIR / f"{nombre}.md").read_text(encoding="utf-8")
    secciones: dict[str, str] = {}
    for bloque in texto.split("\n## ")[1:]:
        titulo, _, cuerpo = bloque.partition("\n")
        secciones[titulo.strip().lower()] = cuerpo.strip()
    return secciones


def seccion(nombre: str, titulo: str) -> str:
    return cargar_skill(nombre)[titulo.lower()]
