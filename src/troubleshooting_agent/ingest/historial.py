"""Historial de fallas: registros JSONL del catálogo → chunks (un caso = un chunk).

Fuentes (definidas en el catálogo con `tipo_documento: historial_fallas` y
`extraccion.registros`):
- `fallas_sinteticas.jsonl` (publico): demo y tests.
- `fallas_sam_v2.jsonl` (interno_pae): solo con CORPUS=completo; no se versiona.

Cada registro trae su propia `clase_equipo` / `modelo`, que pisan los del documento.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from troubleshooting_agent.catalog import Doc, documentos_a_indexar

TIPO_HISTORIAL = "historial_fallas"


def es_historial(doc: Doc) -> bool:
    return doc.get("tipo_documento") == TIPO_HISTORIAL


def chunk_id_caso(doc_id: str, caso_id: str) -> str:
    return f"{doc_id}::caso::{caso_id}"


def chunk_de_registro(doc: Doc, registro: dict[str, Any]) -> dict[str, Any]:
    caso_id = str(registro["id"])
    modelo = registro.get("modelo")
    return {
        "chunk_id": chunk_id_caso(doc["doc_id"], caso_id),
        "doc_id": doc["doc_id"],
        "caso_id": caso_id,
        "titulo": doc.get("titulo"),
        "clase_equipo": registro.get("clase_equipo") or doc.get("clase_equipo"),
        "clases_relacionadas": list(registro.get("clases_relacionadas") or []),
        "fabricante": registro.get("fabricante") or doc.get("fabricante"),
        "modelos": [modelo] if modelo else list(doc.get("modelos") or []),
        "conjunto": doc.get("conjunto"),
        "tipo_documento": TIPO_HISTORIAL,
        "tipo_contenido": "troubleshooting",
        "idioma": registro.get("idioma") or doc.get("idioma"),
        "distribucion": doc.get("distribucion"),
        "sintetico": bool(registro.get("sintetico", False)),
        "fecha": registro.get("fecha"),
        "pozo": registro.get("pozo"),
        "codigo_falla": registro.get("codigo_falla"),
        "sintoma": registro.get("sintoma"),
        "causa": registro.get("causa"),
        "solucion": registro.get("solucion"),
        "texto": registro.get("texto_para_embedding")
        or f"Síntoma: {registro.get('sintoma')}. Causa: {registro.get('causa')}. Solución: {registro.get('solucion')}",
    }


def chunks_historial(catalog: dict[str, Any], corpus: str, catalog_dir: Path) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Devuelve (chunks, saltados {doc_id: motivo})."""
    chunks: list[dict[str, Any]] = []
    saltados: dict[str, str] = {}
    for doc in documentos_a_indexar(catalog, corpus):
        if not es_historial(doc):
            continue
        registros = (doc.get("extraccion") or {}).get("registros")
        path = Path(catalog_dir) / registros if registros else None
        if path is None or not path.is_file():
            saltados[doc["doc_id"]] = f"no se encontró el archivo de registros {path or '(sin extraccion.registros)'}"
            continue
        with path.open(encoding="utf-8") as f:
            for linea in f:
                if linea.strip():
                    chunks.append(chunk_de_registro(doc, json.loads(linea)))
    return chunks, saltados


def escribir_jsonl(chunks: list[dict[str, Any]], salida: Path) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    tmp = salida.with_suffix(salida.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    tmp.replace(salida)
