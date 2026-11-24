"""Evalúa el retrieval de manuales: denso vs. BM25 vs. híbrido (RRF).

    uv run python scripts/evaluar_retrieval.py [--preguntas data/eval/preguntas.jsonl]

Para cada pregunta usa el mismo camino que el agente: identifica el equipo y llama a
`buscar_manual` (filtro por clase + modelo, con fallback a clase). Un resultado es
relevante si coincide el doc_id y la página cae en el rango esperado.

Con --consultas-router <eval_agente.json> agrega dos variantes (híbrido + fallas) con
la consulta que escribió el router en esa corrida del agente: "router" sola y
"router+pregunta" (fusión RRF con la pregunta original, como hace el agente). Así se
mide la fusión sin el ruido del LLM: las consultas quedan fijas.

Métricas: hit@k (hay al menos un relevante en el top k) y MRR@10.
Salida: artifacts/eval_retrieval.json (+ tabla en la terminal).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from troubleshooting_agent.agent.equipo import IdentificadorEquipo
from troubleshooting_agent.agent.tools import buscar_manual
from troubleshooting_agent.catalog import load_catalog
from troubleshooting_agent.config import REPO_ROOT, load_settings
from troubleshooting_agent.retrieval.bm25 import BM25
from troubleshooting_agent.retrieval.embeddings import crear_embedder
from troubleshooting_agent.retrieval.retriever import MODOS, Retriever, RetrieverHibrido
from troubleshooting_agent.retrieval.store import Hit, abrir_store

KS = (1, 3, 6, 10)


def leer_preguntas(path: Path, corpus: str) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        preguntas = [json.loads(linea) for linea in f if linea.strip()]
    # con CORPUS=demo solo se evalúan las preguntas respondibles con documentos públicos
    return [p for p in preguntas if corpus == "completo" or p.get("corpus", "demo") == "demo"]


def es_relevante(hit: Hit, esperado: list[dict]) -> bool:
    p = hit.payload
    return any(p.get("doc_id") == e["doc_id"] and e["paginas"][0] <= p.get("pagina_inicio", -1) <= e["paginas"][1]
               for e in esperado)


def rango_primer_relevante(hits: list[Hit], esperado: list[dict]) -> int | None:
    return next((i for i, h in enumerate(hits, start=1) if es_relevante(h, esperado)), None)


def metricas(rangos: list[int | None]) -> dict[str, float]:
    n = len(rangos) or 1
    salida = {f"hit@{k}": sum(r is not None and r <= k for r in rangos) / n for k in KS}
    salida["mrr@10"] = sum(1 / r for r in rangos if r is not None and r <= 10) / n
    return {k: round(v, 3) for k, v in salida.items()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preguntas", type=Path, default=REPO_ROOT / "data" / "eval" / "preguntas.jsonl")
    ap.add_argument("--salida", type=Path, default=REPO_ROOT / "artifacts" / "eval_retrieval.json")
    ap.add_argument("--consultas-router", type=Path, help="eval_agente.json con las consultas del router")
    args = ap.parse_args(argv)
    consultas_router: dict[str, str] = {}
    if args.consultas_router:
        for d in json.loads(args.consultas_router.read_text(encoding="utf-8"))["detalle"]:
            manual = [c["consulta"] for c in d.get("consultas") or [] if c["accion"] == "buscar_manual"]
            if manual:
                consultas_router[d["id"]] = manual[0]

    settings = load_settings()
    preguntas = leer_preguntas(args.preguntas, settings.corpus)
    store = abrir_store(settings)
    if store.count() == 0:
        print("ERROR: no hay índice; correr ingest + retrieval.index", file=sys.stderr)
        return 1
    embedder = crear_embedder(settings)
    denso = Retriever(store, embedder)
    t0 = time.perf_counter()
    bm25 = BM25(store.payloads())
    print(f"BM25 sobre {len(bm25)} chunks · {time.perf_counter() - t0:.1f} s")
    ide = IdentificadorEquipo.desde_catalogo(load_catalog(settings.catalog_path), settings.corpus)

    resultados: dict[str, dict] = {}
    detalle: list[dict] = []
    # variante: modo de retrieval × priorizar secciones de fallas cuando hay código
    variantes = [(m, p, None) for m in MODOS for p in (False, True)]
    if consultas_router:
        variantes += [("hibrido", True, "router"), ("hibrido", True, "router+pregunta")]
    for modo, priorizar, router in variantes:
        nombre = router or modo + ("+fallas" if priorizar else "")
        r = RetrieverHibrido(denso, bm25, modo)
        rangos = []
        for q in preguntas:
            eq = ide.identificar(q["pregunta"])
            consulta = consultas_router.get(q["id"], q["pregunta"]) if router else q["pregunta"]
            original = q["pregunta"] if router == "router+pregunta" else None
            hits = buscar_manual(r, consulta, eq, max(KS), priorizar_fallas=priorizar, consulta_original=original).hits
            rango = rango_primer_relevante(hits, q["esperado"])
            rangos.append(rango)
            detalle.append({"id": q["id"], "variante": nombre, "rango": rango,
                            "top3": [f"{h.payload['doc_id']} p{h.payload['pagina_inicio']}" for h in hits[:3]]})
        resultados[nombre] = metricas(rangos)

    print(f"\n{len(preguntas)} preguntas (CORPUS={settings.corpus})\n")
    cols = [*(f"hit@{k}" for k in KS), "mrr@10"]
    print(f"{'variante':16}" + "".join(f"{c:>9}" for c in cols))
    for nombre, m in resultados.items():
        print(f"{nombre:16}" + "".join(f"{m[c]:>9.2f}" for c in cols))

    print("\nRango del primer relevante por pregunta (— = no está en el top 10):")
    print(f"{'id':6}" + "".join(f"{n:>16}" for n in resultados))
    for q in preguntas:
        fila = {d["variante"]: d["rango"] for d in detalle if d["id"] == q["id"]}
        print(f"{q['id']:6}" + "".join(f"{fila[n] if fila[n] else '—':>16}" for n in resultados))

    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(json.dumps({
        "fecha": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "corpus": settings.corpus,
        "embedding_model": embedder.nombre,
        "n_preguntas": len(preguntas),
        "preguntas_revisadas": sum(bool(q.get("revisado")) for q in preguntas),
        "metricas": resultados,
        "detalle": detalle,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n→ {args.salida}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
