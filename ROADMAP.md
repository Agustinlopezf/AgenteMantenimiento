# ROADMAP — Agente de troubleshooting

Entrega oficial: **21/12/2026**. Objetivo interno: **30/11/2026** (diciembre queda de colchón por la UBA).
Dedicación: ~10 h/semana.

**Principio:** desde la semana 1 existe un agente que responde de punta a punta. Cada semana mejora una capa **sin romper el camino completo**. Al cierre de cada semana el agente tiene que poder demostrarse.

Para Claude Code: trabajar solo sobre la etapa en curso. Al terminar una tarea, marcarla `[x]` y anotar desvíos en "Registro".

### Devolución del profesor (20/11) (archivo local `devolucion_profesor.txt`, no versionado)
Replanificación a partir de la semana 2. Prioridades:
1. **Parte agéntica primero:** el agente **decide** la acción (consultar manual, buscar historial de fallas, pedir datos al técnico). Dos tools diferenciadas + Skill de troubleshooting (procedimiento, chequeos de seguridad, criterios de escalamiento).
2. **HITL = aprobación humana de una acción preparada por el agente** (propuesta de intervención → aprobar / modificar / rechazar → OT simulada). Pedir datos faltantes es agéntico pero **no** cuenta como HITL. Estado persistente entre interacciones.
3. **RAG medido:** BM25 + RRF vs. denso con set de preguntas con doc + página esperados. Re-ranker **solo si la medición lo justifica**.
4. **Fidelidad:** una cita a una página recuperada no garantiza que la afirmación esté respaldada → chequeo por afirmación.
5. **Opcionales (solo si sobra tiempo):** OCR, búsqueda web, lectura de planos.

Objetivo de cierre: identificar equipo → decidir fuente → pedir datos si faltan → recomendación con evidencia → validación humana; con estado persistente, tests y demo reproducible.

---

## Semana 1 · 9–15 nov · Esqueleto de punta a punta + ingesta

### Hito 1 — jueves 12/11: el agente responde algo (ingenuo pero completo)
- [x] Base: `pyproject.toml` (uv), `config.py` (lee `.env`), pytest corriendo
- [x] `catalog.py` mínimo: carga el catálogo y filtra por `CORPUS` / `indexar`
- [x] Ingesta ingenua: PyMuPDF por página, chunks de tamaño fijo, **solo docs con texto del corpus demo**
- [x] Embeddings BGE-M3 + Qdrant local
- [x] Grafo LangGraph mínimo: `retrieve → answer` (respuesta en español con cita `doc_id` + página)
- [x] CLI: `uv run python -m troubleshooting_agent.agent "pregunta"`
- [ ] Probar 5 preguntas sobre PowerFlex y revisar a mano — corridas en `artifacts/hito1_respuestas.md`; **falta la revisión manual (Agustín)** y reemplazar las preguntas borrador de `eval/preguntas_hito1.json`

**Riesgos que valida el hito 1:**
- ¿Qwen 3.5 4B responde bien en español a partir de manuales en inglés y cita correctamente?
- ¿LLM + embeddings entran en 8 GB de VRAM?

**Punto de decisión (15/11):** si el 4B no cita bien o inventa → probar otro modelo que entre en 8 GB (cuantizado) o ajustar prompt/contexto. Se decide antes de seguir.

### Resto de la semana
- ~~Lanzar OCR (OCRmyPDF) de los 11 escaneados en segundo plano~~ → movido a diciembre (opcional, devolución 20/11)
- [ ] Correr `scripts/descargar_manuales_publicos.py` y confirmar URLs (sobre todo 20B-UM002 ES)
- [ ] `catalog.py validate` completo (taxonomía, archivos existentes) + tests
- [ ] **(Agustín)** Borrador de 10 preguntas de evaluación con doc + página esperados (≥ 5 respondibles con corpus demo)

---

## Semana 2 · 16–22 nov · Agente que decide (sobre el retrieval actual)

### Hito 2 — domingo 22/11: el agente elige qué fuente consultar
- [ ] Historial **sintético** `data/catalog/fallas_sinteticas.jsonl` (`distribucion: publico`, ~20–30 casos sobre equipos del corpus demo, mismo esquema que §4.6 de CLAUDE.md)
- [ ] Tool `buscar_manual(consulta, filtros)` — documentación del fabricante
- [ ] Tool `buscar_historial(consulta, clase_equipo)` — fallas resueltas (colección o filtro separado)
- [ ] Grafo con decisión: `identificar_equipo` (sinónimos de la taxonomía) → router (`pedir_datos` | `buscar_manual` | `buscar_historial` | ambas) → `chequeo_suficiencia` (puede volver a buscar o pedir datos) → `respuesta`
- [ ] Skill `troubleshooting` versionada (`src/troubleshooting_agent/agent/skills/troubleshooting.md`): procedimiento de diagnóstico, chequeos de seguridad (LOTO, presión, energía), criterios de escalamiento; se carga en router y respuesta
- [ ] Respuesta distingue manual del fabricante vs. caso del historial vs. norma; incluye advertencias de seguridad recuperadas
- [ ] El CLI y el camino de punta a punta siguen funcionando; tests sin red

---

## Semana 3 · 23–30 nov · HITL + retrieval medido + fidelidad + demo

### Hito 3 — lunes 30/11: entregable
- [ ] **HITL:** el agente arma una `propuesta_intervencion` (verificaciones, intervención, riesgos, citas) y pausa con `interrupt()`; el técnico responsable aprueba / modifica / rechaza; si aprueba → **orden de trabajo simulada** en `artifacts/ordenes/`
- [ ] **Estado persistente:** checkpointer SQLite con `thread_id` por caso; el CLI puede reanudar un diagnóstico pendiente
- [ ] BM25 + RRF + filtro por `modelos`
- [ ] **(Agustín)** Set de evaluación de 15–20 preguntas con doc + página esperados (≥ la mitad respondibles con corpus demo)
- [ ] hit@k / MRR denso vs. híbrido → `artifacts/eval_retrieval.json`; re-ranker **solo si la medición lo justifica**
- [ ] **Fidelidad por afirmación** (extender `agent/citas.py`: ¿la página recuperada respalda la frase? LLM juez o solapamiento de términos clave como códigos/parámetros) → `artifacts/eval_agente.json`
- [ ] Modo simulado sin Ollama
- [ ] Prueba desde clon limpio siguiendo el README (como el profesor), con guion de demo que incluya el circuito HITL
- [ ] README final: resultados, limitaciones

Si no entra en ~10 h: la fidelidad con LLM juez pasa a la primera semana de diciembre.

---

## Diciembre · colchón hasta 21/12 (solo si sobra)
- [ ] OCR de los 11 escaneados (OCRmyPDF) + completar `secciones` + indexar corpus completo
- [ ] DOCX por encabezados; XLSX → `fallas_sam_v2.jsonl` (historial real, no se versiona)
- [ ] Re-ranker (si no entró en semana 3)
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
- 09/11 · torch fijado al índice PyTorch `cu126` (`[tool.uv.sources]`) · el wheel de PyPI (cu132) no anda con el driver 575 (CUDA 12.9). Requisito para el profesor: driver NVIDIA ≥ 560.
- 09/11 · Índice demo: 3936 puntos BGE-M3 fp16 en Qdrant local, 129 s en GPU (+ ~6 min de descarga del modelo la primera vez). VRAM pico embeddings 1,5 GB.
- 09/11 · **Riesgo VRAM: OK.** Consulta con `qwen3.5:4b` (num_ctx 8192, think=false) + BGE-M3 cargados a la vez: pico 5,4 / 8 GB (nvidia-smi). LLM 5–16 s por respuesta.
- 09/11 · **Riesgo citas: a revisar.** 5 preguntas: responde en español y la mayoría de las citas son válidas, pero: (a) inventó un parámetro con cita válida ("parámetro 375 [Bus Reg Level]" que no está en el fragmento) → se endureció el prompt; el chequeo actual solo verifica doc/página, no el contenido; (b) h1-03 cita páginas no recuperadas (probablemente referencias "see page N" del texto) y h1-02 deforma un doc_id; ambas cosas las marca el chequeo como inválidas; (c) agrega consejos genéricos (LOTO) sin fuente. Ver `artifacts/hito1_respuestas.md`.
- 09/11 · **Cuello de botella principal: retrieval denso solo.** Para "Decel Inhibit del PowerFlex 700" no recuperó la p. 85 de `rok-20b-um001-en` (donde está), y mezcla manuales 750 con preguntas del 700 → semana 2 (BM25 para códigos/nombres de falla, filtro por `modelos`, re-ranker).
- 20/11 · Replanificación por devolución del profesor (`devolucion_profesor.txt`) · prioridad agéntica (router + 2 tools + skill) en semana 2; HITL de aprobación con OT simulada + checkpointer, retrieval medido y fidelidad en semana 3; OCR, DOCX/XLSX reales, web y planos pasan a diciembre (opcionales). Historial sintético público para demo y tests.
