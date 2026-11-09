"""Catálogo de documentos: carga, selección según CORPUS y herencia de metadatos.

El catálogo (`data/catalog/catalogo_documentos.json`) es la fuente de verdad: no se
infiere nada del nombre del archivo ni de la carpeta.

Uso:
    uv run python -m troubleshooting_agent.catalog list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from troubleshooting_agent.config import load_settings

Doc = dict[str, Any]

# Campos que una sección puede pisar respecto del documento (CLAUDE.md §4.4).
CAMPOS_OVERRIDE_SECCION = ("clase_equipo", "fabricante", "modelos", "componente", "tipo_contenido")


def load_catalog(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def documentos_a_indexar(catalog: dict[str, Any], corpus: str) -> list[Doc]:
    """`indexar: true` y, con CORPUS=demo, solo `distribucion: publico`."""
    docs = [d for d in catalog["documentos"] if d.get("indexar") is True]
    if corpus == "demo":
        docs = [d for d in docs if d.get("distribucion") == "publico"]
    return docs


def _buscar(raw_dir: Path, ruta_origen: str | None, archivo: str | None) -> Path | None:
    if ruta_origen and (raw_dir / ruta_origen).is_file():
        return raw_dir / ruta_origen
    if archivo:
        if (raw_dir / archivo).is_file():
            return raw_dir / archivo
        for candidato in sorted(raw_dir.rglob(archivo)):
            if candidato.is_file():
                return candidato
    return None


def resolver_archivos(doc: Doc, raw_dir: Path) -> list[tuple[Path, int]]:
    """Devuelve [(path, offset_de_pagina)] por cada PDF del documento.

    Para docs multiparte, el offset es la suma de páginas de las partes anteriores,
    así la página física queda continua en todo el `doc_id`. Si falta algún archivo
    devuelve lista vacía (el documento no se puede ingerir completo).
    """
    raw_dir = Path(raw_dir)
    if doc.get("partes"):
        resultado: list[tuple[Path, int]] = []
        offset = 0
        for parte in doc["partes"]:
            path = _buscar(raw_dir, parte.get("ruta_origen"), parte.get("archivo"))
            if path is None:
                return []
            resultado.append((path, offset))
            offset += int(parte.get("paginas") or 0)
        return resultado
    path = _buscar(raw_dir, doc.get("ruta_origen"), doc.get("archivo"))
    return [(path, 0)] if path else []


def seccion_de_pagina(doc: Doc, pagina: int) -> dict[str, Any] | None:
    for seccion in doc.get("secciones") or []:
        ini, fin = seccion["paginas"]
        if ini <= pagina <= fin:
            return seccion
    return None


def metadata_para_pagina(doc: Doc, pagina: int) -> dict[str, Any]:
    """Metadatos del chunk = documento ⊕ sección que contiene la página (base 1)."""
    meta: dict[str, Any] = {
        "doc_id": doc["doc_id"],
        "archivo": doc.get("archivo"),
        "titulo": doc.get("titulo"),
        "seccion": None,
        "clase_equipo": doc.get("clase_equipo"),
        "clases_relacionadas": list(doc.get("clases_relacionadas") or []),
        "componente": doc.get("componente"),
        "conjunto": doc.get("conjunto"),
        "fabricante": doc.get("fabricante"),
        "modelos": list(doc.get("modelos") or []),
        "tipo_documento": doc.get("tipo_documento"),
        "tipo_contenido": "general",
        "contexto_operativo": list(doc.get("contexto_operativo") or []),
        "idioma": doc.get("idioma"),
        "prioridad": doc.get("prioridad"),
    }
    seccion = seccion_de_pagina(doc, pagina)
    if seccion is not None:
        meta["seccion"] = seccion.get("titulo")
        for campo in CAMPOS_OVERRIDE_SECCION:
            if seccion.get(campo) is not None:
                meta[campo] = seccion[campo]
    return meta


def _cmd_list(corpus: str | None) -> int:
    settings = load_settings()
    corpus = corpus or settings.corpus
    catalog = load_catalog(settings.catalog_path)
    docs = documentos_a_indexar(catalog, corpus)
    faltantes = 0
    print(f"CORPUS={corpus}: {len(docs)} documentos a indexar")
    for doc in docs:
        archivos = resolver_archivos(doc, settings.raw_dir)
        estado = "ok" if archivos else "FALTA ARCHIVO"
        faltantes += not archivos
        metodo = (doc.get("extraccion") or {}).get("metodo", "?")
        print(f"  [{estado:13}] {doc['doc_id']:28} metodo={metodo:6} {doc.get('titulo', '')}")
    if faltantes:
        print(f"AVISO: {faltantes} documento(s) sin archivo en {settings.raw_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m troubleshooting_agent.catalog")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="documentos que entran al índice según CORPUS")
    p_list.add_argument("--corpus", choices=["demo", "completo"])
    args = ap.parse_args(argv)
    if args.cmd == "list":
        return _cmd_list(args.corpus)
    return 1


if __name__ == "__main__":
    sys.exit(main())
