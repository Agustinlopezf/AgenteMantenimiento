"""CLI de ingesta.

    uv run python -m troubleshooting_agent.ingest [--corpus demo|completo] [--ocr]
"""

from __future__ import annotations

import argparse
import sys

from troubleshooting_agent.catalog import load_catalog
from troubleshooting_agent.config import load_settings
from troubleshooting_agent.ingest.pipeline import ingerir


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m troubleshooting_agent.ingest")
    ap.add_argument("--corpus", choices=["demo", "completo"], help="pisa CORPUS del entorno")
    ap.add_argument("--ocr", action="store_true", help="aplicar OCR a los escaneados (todavía no implementado)")
    args = ap.parse_args(argv)

    settings = load_settings()
    corpus = args.corpus or settings.corpus
    if args.ocr:
        print("AVISO: --ocr todavía no está implementado; los documentos escaneados se saltean.")

    resultado = ingerir(
        catalog=load_catalog(settings.catalog_path),
        corpus=corpus,
        raw_dir=settings.raw_dir,
        salida=settings.chunks_path,
        size=settings.chunk_size,
        overlap=settings.chunk_overlap,
    )

    print(f"CORPUS={corpus} · chunk_size={settings.chunk_size} · overlap={settings.chunk_overlap}")
    print(f"Procesados ({len(resultado.procesados)}): {', '.join(resultado.procesados) or '-'}")
    for doc_id, motivo in resultado.saltados.items():
        print(f"AVISO: salteado {doc_id}: {motivo}")
    print(f"Páginas con texto: {resultado.paginas} · chunks: {resultado.chunks} → {settings.chunks_path}")
    if not resultado.procesados:
        print("ERROR: no se procesó ningún documento.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
