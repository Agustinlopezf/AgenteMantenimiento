"""Evalúa el agente de punta a punta sobre el set de preguntas.

    uv run python scripts/evaluar_agente.py [--juez/--sin-juez] [--limite N]

Por pregunta corre el grafo real (router → tools → respuesta → propuesta) y se detiene
en la aprobación (no aprueba nada). Si el agente pide datos, se le responde vacío.
Mide:
- retrieval dentro del agente: ¿alguna página esperada quedó entre la evidencia?
- citas: válidas / inválidas, y si cita alguna página esperada;
- fidelidad por afirmación (léxica + juez LLM si --juez);
- propuesta: verificaciones aceptadas / descartadas;
- decisiones del router y tiempos.
Salida: artifacts/eval_agente.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from troubleshooting_agent.agent.citas import Cita
from troubleshooting_agent.agent.estado import serializador
from troubleshooting_agent.agent.graph import crear_agente, iniciar, pendiente, reanudar
from troubleshooting_agent.config import REPO_ROOT, load_settings

sys.path.insert(0, str(Path(__file__).parent))
from evaluar_retrieval import es_relevante, leer_preguntas  # noqa: E402


def cita_esperada(c, esperado: list[dict]) -> bool:
    return isinstance(c, Cita) and any(
        c.doc_id == e["doc_id"] and e["paginas"][0] <= c.pagina <= e["paginas"][1] for e in esperado)


def correr(grafo, q: dict) -> dict:
    t0 = time.perf_counter()
    tid = f"eval-{q['id']}"
    r = iniciar(grafo, q["pregunta"], tid)
    while (p := pendiente(r)) is not None and p["tipo"] == "pedir_datos":
        r = reanudar(grafo, "", tid)
    hits = r.get("hits") or []
    fid = r.get("fidelidad") or {"conteo": {}, "tasa_respaldada": None, "afirmaciones": []}
    prop = r.get("propuesta") or {}
    return {
        "id": q["id"],
        "pregunta": q["pregunta"],
        "decisiones": [f"{t['accion']}[{t['origen']}]" for t in r["traza"] if t["tipo"] == "decision"],
        "consultas": [{"accion": c["accion"], "consulta": c["consulta"]} for c in r.get("consultas") or []],
        "evidencia_relevante": any(es_relevante(h, q["esperado"]) for h in hits),
        "citas_validas": [str(c) for c in r.get("citas_validas") or []],
        "citas_invalidas": [str(c) for c in r.get("citas_invalidas") or []],
        "cita_pagina_esperada": any(cita_esperada(c, q["esperado"]) for c in r.get("citas_validas") or []),
        "fidelidad": fid["conteo"],
        "tasa_respaldada": fid["tasa_respaldada"],
        "afirmaciones_dudosas": [
            {k: a.get(k) for k in ("texto", "citas", "citas_originales", "veredicto", "faltantes", "motivo")}
            for a in fid["afirmaciones"] if a["veredicto"] in ("cita_corregida", "no_respaldada", "parcial", "cita_invalida")
        ],
        "propuesta": {"verificaciones": len(prop.get("verificaciones") or []),
                      "descartadas": len(prop.get("descartadas") or []), "origen": prop.get("origen")},
        "espera_aprobacion": (pendiente(r) or {}).get("tipo") == "aprobacion",
        "tiempos": {k: round(v, 2) for k, v in (r.get("tiempos") or {}).items()},
        "total_s": round(time.perf_counter() - t0, 1),
        "respuesta": r.get("respuesta", ""),
    }


def agregados(filas: list[dict]) -> dict:
    n = len(filas) or 1
    conteo: dict[str, int] = {}
    for f in filas:
        for k, v in f["fidelidad"].items():
            conteo[k] = conteo.get(k, 0) + v
    decididas = sum(conteo.get(k, 0) for k in ("respaldada", "cita_corregida", "parcial", "no_respaldada", "cita_invalida"))
    return {
        "evidencia_relevante": round(sum(f["evidencia_relevante"] for f in filas) / n, 3),
        "cita_pagina_esperada": round(sum(f["cita_pagina_esperada"] for f in filas) / n, 3),
        "respuestas_con_cita_invalida": sum(bool(f["citas_invalidas"]) for f in filas),
        "afirmaciones": conteo,
        "tasa_respaldada": round(conteo.get("respaldada", 0) / decididas, 3) if decididas else None,
        "tasa_tras_correccion": round((conteo.get("respaldada", 0) + conteo.get("cita_corregida", 0)) / decididas, 3)
        if decididas else None,
        "propuestas_para_aprobar": sum(f["espera_aprobacion"] for f in filas),
        "verificaciones_descartadas": sum(f["propuesta"]["descartadas"] for f in filas),
        "tiempo_medio_s": round(sum(f["total_s"] for f in filas) / n, 1),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preguntas", type=Path, default=REPO_ROOT / "data" / "eval" / "preguntas.jsonl")
    ap.add_argument("--salida", type=Path, default=REPO_ROOT / "artifacts" / "eval_agente.json")
    ap.add_argument("--juez", action=argparse.BooleanOptionalAction, default=True, help="juez LLM de fidelidad")
    ap.add_argument("--limite", type=int, help="evaluar solo las primeras N preguntas")
    ap.add_argument("--fusion", action=argparse.BooleanOptionalAction, default=True,
                    help="buscar_manual con consulta reescrita + pregunta original (RRF)")
    args = ap.parse_args(argv)

    settings = dataclasses.replace(load_settings(), fidelidad_llm=args.juez)
    grafo, avisos = crear_agente(settings, checkpointer=InMemorySaver(serde=serializador()),
                                 fusion_consulta=args.fusion)
    for a in avisos:
        print(f"⚠ {a}")
    preguntas = leer_preguntas(args.preguntas, settings.corpus)[: args.limite]

    filas = []
    for q in preguntas:
        f = correr(grafo, q)
        filas.append(f)
        c = f["fidelidad"]
        print(f"{q['id']}  evid={'✔' if f['evidencia_relevante'] else '✘'}  cita_esp={'✔' if f['cita_pagina_esperada'] else '✘'}"
              f"  inval={len(f['citas_invalidas'])}  fid={c.get('respaldada', 0)}/{sum(c.values())}"
              f" (corr {c.get('cita_corregida', 0)}, no_resp {c.get('no_respaldada', 0)}, parcial {c.get('parcial', 0)})"
              f"  prop={f['propuesta']['verificaciones']}-{f['propuesta']['descartadas']}  {f['total_s']} s"
              f"  {' → '.join(f['decisiones'])}", flush=True)

    resumen = agregados(filas)
    print("\n" + json.dumps(resumen, ensure_ascii=False, indent=1))
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps({
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": settings.corpus, "llm": settings.llm_model, "retrieval_mode": settings.retrieval_mode,
        "juez_llm": args.juez, "fusion_consulta": args.fusion, "n_preguntas": len(filas), "resumen": resumen, "detalle": filas,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"→ {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
