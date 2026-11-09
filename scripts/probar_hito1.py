"""Corre las preguntas de eval/preguntas_hito1.json contra el agente y deja un reporte
para revisión manual en artifacts/hito1_respuestas.md.

    uv run python scripts/probar_hito1.py [--preguntas eval/preguntas_hito1.json] [--k 6]

Solo usar con CORPUS=demo: el reporte incluye texto de los fragmentos recuperados y
se versiona (los documentos demo son públicos).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from troubleshooting_agent.agent.graph import crear_agente
from troubleshooting_agent.config import REPO_ROOT, load_settings


def vram_usada_mb() -> str:
    try:
        salida = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip().splitlines()[0]
        usada, total = (int(x) for x in salida.split(","))
        return f"{usada} / {total} MB"
    except Exception:
        return "n/d (sin nvidia-smi)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preguntas", type=Path, default=REPO_ROOT / "eval" / "preguntas_hito1.json")
    ap.add_argument("--salida", type=Path, default=REPO_ROOT / "artifacts" / "hito1_respuestas.md")
    ap.add_argument("--k", type=int)
    args = ap.parse_args()

    settings = load_settings()
    if settings.corpus != "demo":
        print("ERROR: este reporte se versiona; correrlo solo con CORPUS=demo.", file=sys.stderr)
        return 1
    k = args.k or settings.retrieval_k
    preguntas = json.loads(args.preguntas.read_text(encoding="utf-8"))["preguntas"]
    grafo, avisos = crear_agente(settings)

    md = [
        "# Hito 1 — respuestas para revisión manual",
        "",
        f"- Fecha: {datetime.now():%Y-%m-%d %H:%M}",
        f"- LLM: `{settings.llm_model}` (USE_REAL_LLM={settings.use_real_llm}, think={settings.llm_think}, "
        f"num_ctx={settings.llm_num_ctx}, temperature={settings.llm_temperature})",
        f"- Embeddings: `{settings.embedding_model}` · índice: {'Qdrant' if settings.use_qdrant else 'numpy'} · k={k}",
        f"- Avisos de arranque: {'; '.join(avisos) or 'ninguno'}",
        "",
        "Revisar por pregunta: ¿responde en español? ¿las citas apuntan a la página correcta? "
        "¿inventa algo que no está en los fragmentos? ¿incluye advertencias de seguridad?",
        "",
    ]
    resumen = []
    for q in preguntas:
        print(f"[{q['id']}] {q['pregunta']}")
        r = grafo.invoke({"pregunta": q["pregunta"], "k": k, "avisos": [], "tiempos": {}})
        vram = vram_usada_mb()
        t = r.get("tiempos", {})
        validas, invalidas = r.get("citas_validas", []), r.get("citas_invalidas", [])
        resumen.append((q["id"], len(validas), len(invalidas), t.get("llm_s", 0.0)))
        print(f"    citas válidas {len(validas)} · inválidas {len(invalidas)} · LLM {t.get('llm_s', 0):.1f} s · VRAM {vram}")

        md += [f"## {q['id']} — {q['pregunta']}", ""]
        for aviso in r.get("avisos") or []:
            md.append(f"> ⚠ {aviso}")
        md += [
            "",
            r.get("respuesta", ""),
            "",
            f"**Citas válidas:** {', '.join(map(str, validas)) or '—'}  ",
            f"**Citas inválidas:** {', '.join(map(str, invalidas)) or '—'}  ",
            f"**Tiempos:** retrieve {t.get('retrieve_s', 0):.2f} s · LLM {t.get('llm_s', 0):.1f} s · **VRAM (nvidia-smi):** {vram}",
            "",
            "<details><summary>Fragmentos recuperados</summary>",
            "",
            "| # | score | cita | sección |",
            "|---|---|---|---|",
        ]
        for i, h in enumerate(r.get("hits") or [], 1):
            p = h.payload
            md.append(f"| {i} | {h.score:.3f} | [{p['doc_id']}, p. {p['pagina_inicio']}] | {p.get('seccion') or ''} |")
        md += ["", "</details>", "", "**Revisión manual:** _(completar)_", ""]

    md += ["## Resumen", "", "| id | citas válidas | citas inválidas | LLM (s) |", "|---|---|---|---|"]
    md += [f"| {i} | {v} | {inv} | {s:.1f} |" for i, v, inv, s in resumen]
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"Reporte: {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
