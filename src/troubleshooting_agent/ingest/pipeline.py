"""Pipeline de ingesta del hito 1: catálogo → PDFs con texto → chunks.jsonl."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from troubleshooting_agent.catalog import Doc, documentos_a_indexar, metadata_para_pagina, resolver_archivos
from troubleshooting_agent.ingest.chunking import chunk_id, chunk_texto
from troubleshooting_agent.ingest.extract import extraer_paginas_pdf

METODOS_SOPORTADOS = {"texto"}


@dataclass
class ResultadoIngesta:
    procesados: list[str] = field(default_factory=list)
    saltados: dict[str, str] = field(default_factory=dict)  # doc_id -> motivo
    paginas: int = 0
    chunks: int = 0


def motivo_no_soportado(doc: Doc) -> str | None:
    extraccion = doc.get("extraccion") or {}
    metodo = extraccion.get("metodo", "texto")
    if extraccion.get("requiere_ocr") or metodo == "ocr":
        return "requiere OCR (no soportado en hito 1)"
    if metodo not in METODOS_SOPORTADOS:
        return f"método '{metodo}' no soportado en hito 1"
    return None


def chunks_de_documento(doc: Doc, archivos: list[tuple[Path, int]], size: int, overlap: int) -> Iterator[dict[str, Any]]:
    for path, offset in archivos:
        for pagina_local, texto in extraer_paginas_pdf(path):
            pagina = pagina_local + offset
            meta = metadata_para_pagina(doc, pagina)
            meta["archivo"] = path.name
            for n, trozo in enumerate(chunk_texto(texto, size, overlap)):
                yield {
                    "chunk_id": chunk_id(doc["doc_id"], pagina, n),
                    **meta,
                    "pagina_inicio": pagina,
                    "pagina_fin": pagina,
                    "fuente_texto": "texto",
                    "texto": trozo,
                }


def ingerir(
    catalog: dict[str, Any],
    corpus: str,
    raw_dir: Path,
    salida: Path,
    size: int,
    overlap: int,
) -> ResultadoIngesta:
    """Escribe `salida` (JSONL, se sobrescribe) y devuelve el resumen."""
    resultado = ResultadoIngesta()
    salida.parent.mkdir(parents=True, exist_ok=True)
    tmp = salida.with_suffix(salida.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for doc in documentos_a_indexar(catalog, corpus):
            doc_id = doc["doc_id"]
            motivo = motivo_no_soportado(doc)
            if motivo:
                resultado.saltados[doc_id] = motivo
                continue
            archivos = resolver_archivos(doc, raw_dir)
            if not archivos:
                resultado.saltados[doc_id] = f"archivo no encontrado en {raw_dir}"
                continue
            paginas_doc: set[int] = set()
            for chunk in chunks_de_documento(doc, archivos, size, overlap):
                f.write(json.dumps(chunk, ensure_ascii=False) + "\n")
                paginas_doc.add(chunk["pagina_inicio"])
                resultado.chunks += 1
            resultado.paginas += len(paginas_doc)
            resultado.procesados.append(doc_id)
    tmp.replace(salida)
    return resultado
