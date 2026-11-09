# ROADMAP — Agente de troubleshooting

Entrega oficial: **21/12/2026**. Objetivo interno: **30/11/2026** (diciembre queda de colchón por la UBA).
Dedicación: ~10 h/semana.

**Principio:** desde la semana 1 existe un agente que responde de punta a punta. Cada semana mejora una capa **sin romper el camino completo**. Al cierre de cada semana el agente tiene que poder demostrarse.

Para Claude Code: trabajar solo sobre la etapa en curso. Al terminar una tarea, marcarla `[x]` y anotar desvíos en "Registro".

---

## Semana 1 · 9–15 nov · Esqueleto de punta a punta + ingesta

### Hito 1 — jueves 12/11: el agente responde algo (ingenuo pero completo)
- [x] Base: `pyproject.toml` (uv), `config.py` (lee `.env`), pytest corriendo
- [x] `catalog.py` mínimo: carga el catálogo y filtra por `CORPUS` / `indexar`
- [x] Ingesta ingenua: PyMuPDF por página, chunks de tamaño fijo, **solo docs con texto del corpus demo**
- [ ] Embeddings BGE-M3 + Qdrant local
- [ ] Grafo LangGraph mínimo: `retrieve → answer` (respuesta en español con cita `doc_id` + página)
- [ ] CLI: `uv run python -m troubleshooting_agent.agent "pregunta"`
- [ ] Probar 5 preguntas sobre PowerFlex y revisar a mano

**Riesgos que valida el hito 1:**
- ¿Qwen 3.5 4B responde bien en español a partir de manuales en inglés y cita correctamente?
- ¿LLM + embeddings entran en 8 GB de VRAM?

**Punto de decisión (15/11):** si el 4B no cita bien o inventa → probar otro modelo que entre en 8 GB (cuantizado) o ajustar prompt/contexto. Se decide antes de seguir.

### Resto de la semana
- [ ] Lanzar OCR (OCRmyPDF) de los 11 escaneados en segundo plano
- [ ] Correr `scripts/descargar_manuales_publicos.py` y confirmar URLs (sobre todo 20B-UM002 ES)
- [ ] `catalog.py validate` completo (taxonomía, archivos existentes) + tests
- [ ] **(Agustín)** Borrador de 10 preguntas de evaluación con doc + página esperados (≥ 5 respondibles con corpus demo)

---

## Semana 2 · 16–22 nov · Ingesta completa + retrieval medido

### Hito 2 — domingo 22/11: retrieval evaluado con números, corpus completo indexado
- [ ] Chunking por sección con herencia doc → sección → chunk; `chunk_id` estable
- [ ] DOCX por encabezados; XLSX → `fallas_sam_v2.jsonl`
- [ ] Indexar docs con OCR; completar rangos de `secciones` pendientes en el catálogo
- [ ] Filtros por payload (clase_equipo, conjunto, tipo_contenido…)
- [ ] BM25 + RRF + re-ranker
- [ ] **(Agustín)** Set de evaluación a 20–30 preguntas
- [ ] Métricas hit@k / MRR: denso vs. híbrido, con vs. sin filtros → `artifacts/eval_retrieval.json`
- [ ] El agente del hito 1 sigue funcionando con el retrieval nuevo

**Punto de decisión (22/11):** si hit@5 es bajo (orientativo < 0,7) → revisar chunking/OCR antes de sumar lógica al agente.

---

## Semana 3 · 23–30 nov · Agente completo + cierre

### Hito 3 — lunes 30/11: entregable
- [ ] Grafo: identificar equipo (sinónimos de la taxonomía) → pedir datos faltantes (HITL) → retrieve con filtros → chequeo de suficiencia → respuesta con citas
- [ ] Respuesta distingue manual del fabricante vs. caso del historial vs. norma; incluye advertencias de seguridad recuperadas
- [ ] Modo simulado sin Ollama
- [ ] Evaluación end-to-end (faithfulness, citas correctas) → `artifacts/eval_agente.json`
- [ ] Prueba desde clon limpio siguiendo el README (como el profesor)
- [ ] README final: resultados, limitaciones

---

## Diciembre · colchón hasta 21/12 (solo si sobra)
- [ ] Búsqueda web restringida a allowlist (MCP)
- [ ] Modelo grande opcional + comparación vs. 4B
- [ ] Descripción de planos con VLM
- [ ] Preparar demo en vivo con corpus completo

---

## Registro
<!-- fecha · qué cambió respecto del plan · por qué -->
- 09/11 · `pflex-rm001_-en-e 1.pdf` renombrado a mano a `pflex-rm001_-en-e_1.pdf` en `data/raw/` · coincidir con `archivo` del catálogo (no se infieren nombres en el código).
- 09/11 · Herencia doc → sección (incl. overrides) adelantada al hito 1 en `catalog.metadata_para_pagina` · costo mínimo y el payload queda completo desde el inicio. El chunking *por sección* sigue en semana 2.
- 09/11 · `ingest --ocr` se acepta pero no hace nada (avisa); docs OCR/DOCX/XLSX se saltean con aviso · OCR es tarea del resto de la semana.
- 09/11 · Ingesta demo: 6 docs, 1763 páginas con texto, 3936 chunks (1200 car., overlap 200), ~3 s.
