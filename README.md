# Agente de troubleshooting de mantenimiento

Trabajo final — **AI Agent Developer (ITBA)**.

Agente que asiste en el diagnóstico de fallas de equipos industriales de oil & gas (variadores de frecuencia, controladores de pozo, motocompresores, top drive, BOP, instrumentación) a partir de manuales de fabricantes, instructivos internos e historial de fallas resueltas. Corre **100 % local** con modelos open source.

```
Técnico: "El variador de un pozo con AIB paró por falla de sobretensión en el bus DC"
Agente:  causas probables → verificaciones → acciones,
         con citas [doc_id, pág.] al manual y a casos previos similares
```

## Cómo funciona

1. **Catálogo** (`data/catalog/catalogo_documentos.json`): define qué documentos se indexan y con qué tags (clase de equipo, conjunto, fabricante, modelo, tipo de contenido, rangos de páginas por sección).
2. **Ingesta**: extracción de texto por página (OCR para escaneados), chunking por sección y herencia de metadatos documento → sección → chunk.
3. **Retrieval híbrido**: embeddings multilingües (BGE-M3) + BM25, fusión RRF y filtros por metadatos (clase, modelo y, si hay código de falla, prioridad a las secciones de troubleshooting). Medido con un set de preguntas con doc + página esperados.
4. **Agente (LangGraph)**: identifica el equipo y **decide** qué hacer en cada paso (buscar en el manual, buscar casos similares en el historial, pedir un dato al técnico o responder). Responde en español citando fuentes y chequea **por afirmación** que la página citada respalde lo que dice.
5. **Aprobación humana (HITL)**: arma una **propuesta de intervención** (seguridad, verificaciones con cita, intervención, escalamiento) y se detiene hasta que un responsable la **aprueba, modifica o rechaza**. Si se aprueba, emite una **orden de trabajo simulada**. El estado de cada diagnóstico persiste en SQLite: se puede dejar pendiente y retomar después.

```
identificar_equipo → decidir ─┬─ buscar_manual / buscar_historial ─→ decidir
        ▲                     ├─ pedir_datos (pausa: dato del técnico)
        └─────────────────────┤
                              └─ responder → proponer_intervencion → aprobacion (pausa: responsable)
                                                    ▲                    ├─ modificar ─┘
                                                    │                    ├─ rechazar → fin
                                                    │                    └─ aprobar  → orden de trabajo simulada
```

## Stack

Python 3.12 · uv · Ollama (Qwen 3.5) · LangGraph · sentence-transformers (BGE-M3) · Qdrant · PyMuPDF · OCRmyPDF/Tesseract · pytest

## Requisitos

- Linux (probado en Ubuntu 24.04)
- [uv](https://docs.astral.sh/uv/)
- [Ollama](https://ollama.com/)
- Tesseract + OCRmyPDF (solo para la ingesta de documentos escaneados):
  `sudo apt install tesseract-ocr tesseract-ocr-spa ocrmypdf`
- GPU NVIDIA recomendada, con driver **≥ 560** (CUDA 12.6+): en Linux `uv` instala torch `cu126` desde el índice de PyTorch. La configuración por defecto entra en **8 GB de VRAM**; sin GPU funciona más lento (embeddings en CPU) o en modo simulado.

## Instalación

```bash
git clone <repo>
cd <repo>
uv sync
ollama pull qwen3.5:4b
cp .env.example .env
```

## Configuración

Variables de entorno (en `.env`):

| Variable | Default | Descripción |
|---|---|---|
| `LLM_MODEL` | `qwen3.5:4b` | Modelo de Ollama. Se puede usar uno más grande si la GPU lo permite. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | |
| `USE_REAL_LLM` | `false` | `false` = provider simulado (sin Ollama). |
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Debe ser el mismo al indexar y al consultar. |
| `USE_QDRANT` | `true` | `false` = vector store en memoria. |
| `WEB_SEARCH_ALLOWLIST` | `rockwellautomation.com` | Dominios habilitados para la búsqueda web. |
| `CORPUS` | `demo` | `demo` = solo documentos públicos; `completo` = todo lo que tenga `indexar: true`. |
| `RETRIEVAL_MODE` | `hibrido` | `hibrido` (denso + BM25 con RRF), `denso` o `bm25`. |
| `STATE_DB` | `artifacts/estado/checkpoints.sqlite` | Estado persistente de los diagnósticos (checkpointer de LangGraph). |
| `ORDENES_DIR` | `artifacts/ordenes` | Órdenes de trabajo simuladas (`.json` + `.md`). |
| `FIDELIDAD_LLM` | `false` | `true` = además del chequeo léxico, un juez LLM revisa cada afirmación (más lento). |

## Datos

Los manuales **no están en el repositorio**. El catálogo (versionado) clasifica cada documento según si se puede distribuir:

| `distribucion` | Docs | Qué son | Cómo se obtienen |
|---|---|---|---|
| `publico` | 6 | Manuales PowerFlex (Rockwell) y FLEXIM FLUXUS F532WD | Descarga automática desde el sitio oficial del fabricante |
| `propietario` | 13 | NOV, Waukesha, Ariel, Agar, Murphy, API RP 53 | No se distribuyen (confidenciales o con copyright) |
| `interno_pae` | 3 | Instructivo SAM V2, historial de fallas, proyecto WEG | No se distribuyen (documentos de la empresa) |

### Corpus de demo (para reproducir)

```bash
uv run python scripts/descargar_manuales_publicos.py   # baja los 6 públicos a data/raw/
# en .env: CORPUS=demo
```

Con `CORPUS=demo` la ingesta usa solo los documentos `publico`: alcanza para probar el agente de punta a punta con preguntas sobre variadores de frecuencia y caudalímetros. El corpus completo (motocompresores, perforación, pozos con SAM V2) se muestra en una demo en vivo.

### Corpus completo

Copiar los archivos en `data/raw/` (se permiten subcarpetas), con los nombres del campo `archivo` del catálogo, y usar `CORPUS=completo`.

Validar en ambos casos: `uv run python -m troubleshooting_agent.catalog validate`

Campos y taxonomía del catálogo: ver `convenciones` y `taxonomia` en [catalogo_documentos.json](data/catalog/catalogo_documentos.json).

## Uso

```bash
uv run python -m troubleshooting_agent.catalog list         # qué documentos entran según CORPUS
uv run python -m troubleshooting_agent.ingest               # manuales → data/chunks/chunks.jsonl; historial → data/chunks/historial.jsonl
uv run python -m troubleshooting_agent.retrieval.index      # embeddings BGE-M3 + índices Qdrant local (manuales + historial)
uv run python -m troubleshooting_agent.agent "el PowerFlex 700 paró por F5 OverVoltage"   # una consulta
uv run python -m troubleshooting_agent.agent --contexto     # modo interactivo, mostrando la evidencia
uv run python -m troubleshooting_agent.agent --pendientes   # diagnósticos pausados (esperando datos o aprobación)
uv run python -m troubleshooting_agent.agent --reanudar <thread_id>   # retomar uno (aunque sea en otra sesión)
uv run python scripts/evaluar_retrieval.py                  # denso vs BM25 vs híbrido → artifacts/eval_retrieval.json
uv run python scripts/evaluar_agente.py                     # agente de punta a punta + fidelidad → artifacts/eval_agente.json
uv run pytest                                               # tests (sin red, GPU ni Ollama)
```

Para usar el LLM real: `USE_REAL_LLM=true` en `.env` y Ollama corriendo con el modelo de `LLM_MODEL`. Si Ollama no responde o falta el modelo, el agente avisa y responde en modo simulado (lista los fragmentos recuperados con su cita). La primera indexación descarga BGE-M3 (~2,3 GB) en la cache de Hugging Face.

### Guion de demo (circuito completo con aprobación humana)

Funciona también sin Ollama (`USE_REAL_LLM=false`): el router decide con reglas y la propuesta se arma con reglas.

```bash
# 1. Consulta incompleta: el agente pide el modelo, busca y arma la propuesta
uv run python -m troubleshooting_agent.agent "el variador del pozo para por sobretensión en el bus"
#    ❓ Para seguir necesito: el modelo exacto del equipo.
#    » PowerFlex 755, código F5
#    ... traza de decisiones, diagnóstico con citas, fidelidad por afirmación ...
#    ══ PROPUESTA DE INTERVENCIÓN · pendiente de aprobación ══
#    [a]probar / [m]odificar / [r]echazar / [p]ausar » m
#    ¿Qué hay que cambiar? » agregar medir la tensión de línea antes de tocar parámetros
#    Responsable que decide » J. Pérez
#    ... propuesta v2 con el cambio ...
#    [a]probar / [m]odificar / [r]echazar / [p]ausar » p        ← queda pendiente en SQLite

# 2. Otra sesión (o después de cerrar la terminal)
uv run python -m troubleshooting_agent.agent --pendientes
#    576e71132ca1  2026-11-21T11:53  esperando aprobación   el variador del pozo para por ...
uv run python -m troubleshooting_agent.agent --reanudar 576e71132ca1 --responsable "Supervisor"
#    » a
#    ✔ Propuesta aprobada. Orden de trabajo simulada OT-20261121-115512-576e7113:
#      artifacts/ordenes/OT-20261121-115512-576e7113.md
```

Pedir un dato faltante es parte del comportamiento del agente; la **aprobación** es la intervención humana: nada se "ejecuta" (no se emite la OT) sin que un responsable apruebe. Las verificaciones de la propuesta cuya cita no se recuperó, o cuyos códigos / parámetros / valores no aparecen en la página citada, se descartan antes de mostrarla.

El agente muestra su traza: qué equipo identificó y, en cada paso, qué acción decidió (`buscar_historial`, `buscar_manual`, `pedir_datos` o `responder`), quién la decidió (LLM, reglas o guarda) y por qué. Si falta un dato (por ejemplo, el modelo), pregunta en la terminal y continúa con la respuesta. En modo simulado decide con reglas. Ejemplos de corridas en [`artifacts/hito2_respuestas.md`](artifacts/hito2_respuestas.md).

Con `CORPUS=demo` el historial de fallas es **sintético** (`data/catalog/fallas_sinteticas.jsonl`, 24 casos sobre los equipos del corpus demo): no son eventos reales.

> Opcionales no implementados: OCR (`--ocr`), DOCX/XLSX reales, búsqueda web restringida y lectura de planos.

## Estructura

```
scripts/
  descargar_manuales_publicos.py
data/
  raw/          manuales originales (no versionado)
  catalog/      catálogo de documentos + historial de fallas
  ocr_cache/    PDFs con capa OCR (no versionado)
  chunks/       chunks generados (no versionado)
src/troubleshooting_agent/
  catalog.py    validación y herencia de metadatos
  ingest/       extracción, OCR, chunking
  retrieval/    embeddings, Qdrant, BM25, RRF, reranker
  agent/        grafo LangGraph, router, tools, identificación de equipo, citas,
                fidelidad por afirmación, propuesta + orden de trabajo, estado (SQLite)
    skills/     skill de troubleshooting (procedimiento, seguridad, escalamiento)
tests/
notebooks/
data/eval/       preguntas de evaluación con doc + página esperados
artifacts/      reportes de evaluación; estado/ y ordenes/ (locales, no versionados)
```

## Estado

- [x] Catálogo de documentos y taxonomía de tags
- [x] Historial de fallas SAM V2 en JSONL
- [x] Corpus de demo con manuales públicos (script de descarga)
- [x] Ingesta de PDFs con texto (OCR pendiente, opcional)
- [x] Historial de fallas sintético + tool de búsqueda separada
- [x] Agente LangGraph que decide qué fuente consultar y pide datos faltantes (hito 2)
- [x] Aprobación humana (HITL) con orden de trabajo simulada + estado persistente en SQLite (hito 3)
- [x] Índice híbrido (BM25 + RRF) medido contra denso; re-ranker no incorporado (ver Resultados)
- [x] Fidelidad por afirmación (chequeo léxico + juez LLM opcional)
- [x] Evaluación: 20 preguntas con doc + página esperados (borrador, pendiente de revisión)
- [ ] Búsqueda web restringida (opcional)
- [ ] OCR de escaneados y corpus completo (opcional)

## Resultados (corpus demo, 21/11)

Set de evaluación: 20 preguntas de troubleshooting sobre los manuales públicos (PowerFlex 700 / 750, FLUXUS F532WD) con documento y página esperados (`data/eval/preguntas.jsonl`, **borrador pendiente de revisión**).

**Retrieval** (`scripts/evaluar_retrieval.py` → `artifacts/eval_retrieval.json`; "+fallas" = si la consulta trae código de falla, primero se busca en las secciones de troubleshooting del catálogo):

| Variante | hit@1 | hit@3 | hit@10 | MRR@10 |
|---|---|---|---|---|
| denso (hito 1) | 0.30 | 0.35 | 0.55 | 0.35 |
| BM25 | 0.20 | 0.40 | 0.70 | 0.34 |
| híbrido (RRF) | 0.35 | 0.45 | 0.55 | 0.41 |
| **híbrido + fallas** (default) | **0.60** | **0.80** | **0.95** | **0.72** |

El filtro por metadatos del catálogo es lo que más mueve la aguja (las tablas de códigos de falla quedaban enterradas entre cientos de páginas que mencionan "OverVoltage"); BM25 aporta en códigos y nombres exactos. **Re-ranker: no se incorporó.** Con el híbrido + fallas, 16 de 20 preguntas tienen la página esperada en el top 3; un cross-encoder (bge-reranker-v2-m3, ~2 GB) sumado al LLM y a BGE-M3 excede los 8 GB de VRAM, y los fallos restantes son de cobertura (síntoma en español contra una tabla en inglés) más que de orden.

**Agente de punta a punta** (`scripts/evaluar_agente.py` → `artifacts/eval_agente.json`, qwen3.5:4b, juez LLM activado). Dos corridas: la segunda agrega al prompt la lista explícita de citas permitidas.

| Métrica | Corrida 1 | Corrida 2 (actual) |
|---|---|---|
| La evidencia recuperada incluye la página esperada | 80 % | 85 % |
| La respuesta cita la página esperada | 70 % | 65 % |
| Afirmaciones con cita respaldadas por la fuente | 68 % (167/246) | 67 % (151/225) |
| Afirmaciones no respaldadas / que citan una página no recuperada | 48 / 22 | 43 / 27 |
| Respuestas con al menos una cita inválida | 8 / 20 | 5 / 20 |
| Propuestas que llegan a aprobación / verificaciones descartadas | 20 / 16 | 19 / 13 |
| Tiempo medio por consulta (router + respuesta + propuesta + juez) | 41 s | 39 s |

Las diferencias entre corridas están dentro de la variación del modelo (20 preguntas). Lectura: el agente encuentra y cita la página correcta en la mayoría de los casos, pero **1 de cada 3 afirmaciones del modelo 4B no está respaldada por la página que cita** (mezcla páginas, agrega consejos genéricos, desplaza el número de página). Por eso el chequeo por afirmación se muestra al técnico y la propuesta que va a aprobación solo conserva verificaciones con respaldo.

## Limitaciones

- El agente asiste el diagnóstico; no reemplaza los procedimientos de seguridad ni el criterio del técnico.
- El modelo por defecto (4B) produce afirmaciones no respaldadas (~1/3 según el juez): el chequeo de fidelidad las marca, pero no las corrige. Un modelo más grande (`LLM_MODEL`) debería mejorar esto si la GPU lo permite.
- El chequeo léxico solo detecta términos clave inventados (códigos, parámetros, valores); las frases sin esos términos necesitan el juez LLM (`FIDELIDAD_LLM=true`), que suma latencia.
- Qdrant local no admite dos procesos a la vez: no se puede correr el agente mientras corre la evaluación (el agente lo avisa).
- El set de evaluación y el historial sintético los armó el asistente: falta la revisión de un técnico.
- La calidad depende de la cobertura del corpus: hoy faltan, por ejemplo, el manual del VDF WEG CFW900 y el del controlador Lufkin SAM.
