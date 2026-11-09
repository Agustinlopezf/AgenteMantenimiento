"""CLI del agente.

    uv run python -m troubleshooting_agent.agent "el PowerFlex 700 paró por OverVoltage"
    uv run python -m troubleshooting_agent.agent            # modo interactivo
"""

from __future__ import annotations

import argparse
import sys

from troubleshooting_agent.agent.graph import crear_agente
from troubleshooting_agent.config import load_settings


def imprimir(resultado: dict, mostrar_contexto: bool) -> None:
    for aviso in resultado.get("avisos") or []:
        print(f"⚠ {aviso}")
    if mostrar_contexto:
        print("\n── Fragmentos recuperados ──")
        for h in resultado.get("hits") or []:
            p = h.payload
            print(f"  {h.score:.3f}  [{p['doc_id']}, p. {p['pagina_inicio']}]  {p.get('seccion') or ''}")
    print("\n" + resultado.get("respuesta", ""))
    fuentes = resultado.get("fuentes") or []
    if fuentes:
        print("\nFuentes:")
        for linea in fuentes:
            print(f"  - {linea}")
    t = resultado.get("tiempos") or {}
    print(f"\n(retrieve {t.get('retrieve_s', 0):.2f} s · LLM {t.get('llm_s', 0):.1f} s)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m troubleshooting_agent.agent")
    ap.add_argument("pregunta", nargs="*", help="consulta del técnico (vacío = modo interactivo)")
    ap.add_argument("--k", type=int, help="cantidad de fragmentos a recuperar")
    ap.add_argument("--contexto", action="store_true", help="mostrar los fragmentos recuperados")
    args = ap.parse_args(argv)

    settings = load_settings()
    grafo, avisos = crear_agente(settings)
    for aviso in avisos:
        print(f"⚠ {aviso}")

    def consultar(pregunta: str) -> None:
        entrada = {"pregunta": pregunta, "k": args.k or settings.retrieval_k, "avisos": [], "tiempos": {}}
        imprimir(grafo.invoke(entrada), args.contexto)

    if args.pregunta:
        consultar(" ".join(args.pregunta))
        return 0

    print("Modo interactivo. Describí el síntoma (vacío o Ctrl-D para salir).")
    while True:
        try:
            pregunta = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not pregunta:
            return 0
        consultar(pregunta)


if __name__ == "__main__":
    sys.exit(main())
