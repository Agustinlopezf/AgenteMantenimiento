"""CLI del agente.

    uv run python -m troubleshooting_agent.agent "el PowerFlex 700 paró por F5 OverVoltage"
    uv run python -m troubleshooting_agent.agent            # modo interactivo
    uv run python -m troubleshooting_agent.agent --pendientes
    uv run python -m troubleshooting_agent.agent --reanudar <thread_id>

El agente puede pausar dos veces:
- para pedir un dato que falta (respondés en la terminal);
- para que un responsable apruebe / modifique / rechace la propuesta de intervención.
  Si aprueba, se emite una orden de trabajo simulada en ORDENES_DIR.

Cada diagnóstico se guarda en STATE_DB (SQLite): si lo dejás pendiente (opción
"pausar" o Ctrl-D), se retoma después con --reanudar.
"""

from __future__ import annotations

import argparse
import sys

from troubleshooting_agent.agent.estado import listar_diagnosticos
from troubleshooting_agent.agent.fidelidad import resumen_fidelidad
from troubleshooting_agent.agent.graph import (
    crear_agente,
    crear_grafo_estado,
    estado_actual,
    iniciar,
    nuevo_thread_id,
    pendiente,
    reanudar,
)
from troubleshooting_agent.config import load_settings

_ORIGEN = {"llm": "LLM", "reglas": "reglas", "guarda": "guarda"}
_OPCIONES = {"a": "aprobar", "m": "modificar", "r": "rechazar", "p": "pausar"}


class Pausado(Exception):
    """El usuario dejó el diagnóstico pendiente."""


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
        elif tipo == "propuesta":
            print(f"  · propuesta v{t['version']} [{_ORIGEN.get(t['origen'], t['origen'])}]: {t['texto']}")
        elif tipo == "aprobacion":
            linea = f"  · responsable ({t.get('responsable')}): {t['decision']}"
            print(linea + (f" — {t['comentario']}" if t.get("comentario") else "")
                  + (f"  ⚑ {t['nota']}" if t.get("nota") else ""))
        elif tipo == "fidelidad":
            print(f"  · fidelidad por afirmación: {t['texto']}")
        elif tipo == "orden":
            print(f"  · orden de trabajo emitida: {t['texto']}")
    return len(traza)


def imprimir_diagnostico(resultado: dict, mostrar_contexto: bool) -> None:
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
    fid = resultado.get("fidelidad")
    if fid and fid["afirmaciones"]:
        print(f"\nFidelidad por afirmación: {resumen_fidelidad(fid)}")
        for a in fid["afirmaciones"]:
            if a["veredicto"] not in ("respaldada", "no_verificable"):
                print(f"  ✗ [{a['veredicto']}] {a['texto'][:90]}… {('faltan: ' + ', '.join(a['faltantes'])) if a['faltantes'] else a['motivo']}")
    t = resultado.get("tiempos") or {}
    print(f"\n(router {t.get('router_s', 0):.1f} s · retrieve {t.get('retrieve_s', 0):.2f} s · "
          f"LLM {t.get('llm_s', 0):.1f} s · propuesta {t.get('propuesta_s', 0):.1f} s)")


def imprimir_cierre(resultado: dict) -> None:
    cierre = resultado.get("cierre")
    if cierre == "aprobado":
        o = resultado["orden"]
        print(f"\n✔ Propuesta aprobada. Orden de trabajo simulada {o['ot_id']}:\n  {o['md']}\n  {o['json']}")
    elif cierre == "rechazado":
        a = resultado.get("aprobacion") or {}
        print(f"\n✘ Propuesta rechazada por {a.get('responsable')}" + (f": {a['comentario']}" if a.get("comentario") else "."))
    elif cierre == "sin_propuesta":
        print("\n(No hay propuesta de intervención para aprobar.)")


def _input(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise Pausado from None


def pedir_aprobacion(pausa: dict, responsable: str | None) -> dict[str, str]:
    print("\n══ PROPUESTA DE INTERVENCIÓN · pendiente de aprobación ══")
    print(pausa["texto"])
    opciones = "[a]probar / [m]odificar / [r]echazar / [p]ausar" if pausa["puede_modificar"] \
        else "[a]probar / [r]echazar / [p]ausar (ya no se puede modificar)"
    while True:
        eleccion = _OPCIONES.get(_input(f"\n{opciones} » ").lower()[:1])
        if eleccion == "modificar" and not pausa["puede_modificar"]:
            continue
        if eleccion:
            break
    if eleccion == "pausar":
        raise Pausado
    comentario = ""
    if eleccion == "modificar":
        while not comentario:
            comentario = _input("¿Qué hay que cambiar? » ")
    elif eleccion == "rechazar":
        comentario = _input("Motivo del rechazo » ")
    else:
        comentario = _input("Comentario (opcional) » ")
    quien = responsable or _input("Responsable que decide » ") or "(sin nombre)"
    return {"decision": eleccion, "comentario": comentario, "responsable": quien}


_RESPONSABLE: dict[str, str] = {}  # se pregunta una vez por sesión


def atender(grafo, thread_id: str, resultado: dict, args, mostradas: int = 0, diagnostico_visto: bool = False) -> int:
    """Muestra la traza y resuelve las pausas hasta terminar o hasta que el usuario pause."""
    mostradas = imprimir_traza(resultado.get("traza") or [], mostradas)
    try:
        while (pausa := pendiente(resultado)) is not None:
            if pausa["tipo"] == "pedir_datos":
                print(f"\n❓ {pausa['pregunta']}")
                valor: object = _input("» ")
            else:
                if not diagnostico_visto:
                    imprimir_diagnostico(resultado, args.contexto)
                    diagnostico_visto = True
                valor = pedir_aprobacion(pausa, args.responsable or _RESPONSABLE.get("nombre"))
                _RESPONSABLE["nombre"] = valor["responsable"]
            resultado = reanudar(grafo, valor, thread_id)
            mostradas = imprimir_traza(resultado.get("traza") or [], mostradas)
    except Pausado:
        print(f"⏸ Diagnóstico {thread_id} pendiente. Retomar con:\n"
              f"  uv run python -m troubleshooting_agent.agent --reanudar {thread_id}")
        return 0
    if not diagnostico_visto:
        imprimir_diagnostico(resultado, args.contexto)
    imprimir_cierre(resultado)
    return 0


def diagnosticar(grafo, pregunta: str, args) -> int:
    thread_id = nuevo_thread_id()
    print(f"\n── Diagnóstico {thread_id} ──")
    return atender(grafo, thread_id, iniciar(grafo, pregunta, thread_id, args.k), args)


def retomar(grafo, thread_id: str, args) -> int:
    valores = estado_actual(grafo, thread_id)
    if valores is None:
        print(f"No existe el diagnóstico {thread_id!r}. Ver --pendientes.", file=sys.stderr)
        return 1
    print(f"\n── Diagnóstico {thread_id} (retomado) ──\nConsulta: {valores.get('pregunta')}")
    if pendiente(valores) is None:
        print(f"Ya está cerrado ({valores.get('cierre') or 'respondido'}).")
        imprimir_diagnostico(valores, args.contexto)
        imprimir_cierre(valores)
        return 0
    return atender(grafo, thread_id, valores, args)


def listar(grafo, todos: bool) -> int:
    filas = listar_diagnosticos(grafo, grafo.checkpointer, solo_pendientes=not todos)
    if not filas:
        print("No hay diagnósticos " + ("guardados." if todos else "pendientes."))
        return 0
    espera = {"pedir_datos": "esperando datos", "aprobacion": "esperando aprobación"}
    for f in filas:
        estado = espera.get(f["espera"], f["cierre"] or "respondido")
        print(f"{f['thread_id']}  {f['creado'][:16]:16}  {estado:22}  {f['pregunta'][:60]}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m troubleshooting_agent.agent")
    ap.add_argument("pregunta", nargs="*", help="consulta del técnico (vacío = modo interactivo)")
    ap.add_argument("--k", type=int, help="cantidad de fragmentos de manual a recuperar")
    ap.add_argument("--contexto", action="store_true", help="mostrar la evidencia recuperada")
    ap.add_argument("--responsable", help="nombre de quien aprueba (si no, se pregunta)")
    ap.add_argument("--pendientes", action="store_true", help="listar diagnósticos pausados")
    ap.add_argument("--todos", action="store_true", help="con --pendientes: listar también los cerrados")
    ap.add_argument("--reanudar", metavar="THREAD_ID", help="retomar un diagnóstico guardado")
    args = ap.parse_args(argv)

    settings = load_settings()
    if args.pendientes:  # no hace falta cargar índice ni modelos
        return listar(crear_grafo_estado(settings), args.todos)

    grafo, avisos = crear_agente(settings)
    for aviso in avisos:
        print(f"⚠ {aviso}")

    if args.reanudar:
        return retomar(grafo, args.reanudar, args)
    if args.pregunta:
        return diagnosticar(grafo, " ".join(args.pregunta), args)

    print("Modo interactivo. Describí el síntoma (vacío o Ctrl-D para salir).")
    while True:
        try:
            pregunta = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not pregunta:
            return 0
        diagnosticar(grafo, pregunta, args)


if __name__ == "__main__":
    sys.exit(main())
