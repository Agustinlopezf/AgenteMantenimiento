"""CLI del agente.

    uv run python -m troubleshooting_agent.agent "el PowerFlex 700 paró por F5 OverVoltage"
    uv run python -m troubleshooting_agent.agent            # modo interactivo

Si el agente necesita un dato, pregunta y espera la respuesta en la terminal
(el grafo queda pausado y se reanuda con lo que escribas).
"""

from __future__ import annotations

import argparse
import sys

from troubleshooting_agent.agent.graph import crear_agente, iniciar, nuevo_thread_id, pendiente, reanudar
from troubleshooting_agent.config import load_settings

_ORIGEN = {"llm": "LLM", "reglas": "reglas", "guarda": "guarda"}


def imprimir_traza(traza: list[dict], desde: int = 0) -> int:
    for t in traza[desde:]:
        tipo = t.get("tipo")
        if tipo == "equipo":
            print(f"  · equipo: {t['texto']}")
        elif tipo == "decision":
            extra = t.get("consulta") or t.get("pregunta") or ""
            print(f"  {t['paso']}. decide {t['accion']} [{_ORIGEN.get(t['origen'], t['origen'])}]: {t['motivo']}"
                  + (f"  «{extra}»" if extra else ""))
            for nota in t.get("notas") or []:
                print(f"     ⚑ {nota}")
        elif tipo == "resultado":
            print(f"     → {t['texto']}")
        elif tipo == "respuesta_tecnico":
            print(f"  · técnico: {t['texto']}")
    return len(traza)


def imprimir_final(resultado: dict, mostrar_contexto: bool) -> None:
    for aviso in resultado.get("avisos") or []:
        print(f"⚠ {aviso}")
    if mostrar_contexto:
        print("\n── Evidencia recuperada ──")
        for h in resultado.get("hits") or []:
            p = h.payload
            print(f"  {h.score:.3f}  [{p['doc_id']}, p. {p['pagina_inicio']}]  {p.get('seccion') or ''}")
        for h in resultado.get("casos") or []:
            p = h.payload
            print(f"  {h.score:.3f}  [historial, caso {p['caso_id']}]  {p.get('sintoma', '')[:70]}")
    print("\n" + resultado.get("respuesta", ""))
    fuentes = resultado.get("fuentes") or []
    if fuentes:
        print("\nFuentes:")
        for linea in fuentes:
            print(f"  - {linea}")
    t = resultado.get("tiempos") or {}
    print(f"\n(router {t.get('router_s', 0):.1f} s · retrieve {t.get('retrieve_s', 0):.2f} s · LLM {t.get('llm_s', 0):.1f} s)")


def diagnosticar(grafo, pregunta: str, k: int | None, mostrar_contexto: bool) -> int:
    thread_id = nuevo_thread_id()
    print(f"\n── Diagnóstico {thread_id} ──")
    resultado = iniciar(grafo, pregunta, thread_id, k)
    mostradas = imprimir_traza(resultado.get("traza") or [])
    while (pausa := pendiente(resultado)) is not None:
        print(f"\n❓ {pausa['pregunta']}")
        try:
            respuesta = input("» ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n(diagnóstico interrumpido sin respuesta)")
            return 1
        resultado = reanudar(grafo, respuesta, thread_id)
        mostradas = imprimir_traza(resultado.get("traza") or [], mostradas)
    imprimir_final(resultado, mostrar_contexto)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m troubleshooting_agent.agent")
    ap.add_argument("pregunta", nargs="*", help="consulta del técnico (vacío = modo interactivo)")
    ap.add_argument("--k", type=int, help="cantidad de fragmentos de manual a recuperar")
    ap.add_argument("--contexto", action="store_true", help="mostrar la evidencia recuperada")
    args = ap.parse_args(argv)

    settings = load_settings()
    grafo, avisos = crear_agente(settings)
    for aviso in avisos:
        print(f"⚠ {aviso}")

    if args.pregunta:
        return diagnosticar(grafo, " ".join(args.pregunta), args.k, args.contexto)

    print("Modo interactivo. Describí el síntoma (vacío o Ctrl-D para salir).")
    while True:
        try:
            pregunta = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not pregunta:
            return 0
        diagnosticar(grafo, pregunta, args.k, args.contexto)


if __name__ == "__main__":
    sys.exit(main())
