"""Extracción de texto de PDFs con PyMuPDF, por página física (base 1)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

import pymupdf

_ESPACIOS = re.compile(r"[ \t ]+")
_SALTOS = re.compile(r"\n{3,}")


def normalizar(texto: str) -> str:
    texto = _ESPACIOS.sub(" ", texto)
    texto = "\n".join(linea.strip() for linea in texto.splitlines())
    return _SALTOS.sub("\n\n", texto).strip()


def extraer_paginas_pdf(path: Path) -> Iterator[tuple[int, str]]:
    """Itera (pagina_base1, texto) omitiendo páginas sin texto."""
    with pymupdf.open(path) as pdf:
        for indice, pagina in enumerate(pdf):
            texto = normalizar(pagina.get_text("text"))
            if texto:
                yield indice + 1, texto
