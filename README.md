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
3. **Retrieval híbrido**: embeddings multilingües (BGE-M3) + BM25, fusión RRF, re-ranking y filtros por metadatos en Qdrant.
4. **Agente (LangGraph)**: identifica el equipo, pide datos faltantes, recupera evidencia, responde en español citando fuentes y, opcionalmente, busca en la web dentro de una lista de dominios permitidos.

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

Detalle de campos y taxonomía del catálogo: [CLAUDE.md](CLAUDE.md) §4.

## Uso

```bash
uv run python -m troubleshooting_agent.catalog list         # qué documentos entran según CORPUS
uv run python -m troubleshooting_agent.ingest               # manuales → data/chunks/chunks.jsonl; historial → data/chunks/historial.jsonl
uv run python -m troubleshooting_agent.retrieval.index      # embeddings BGE-M3 + índices Qdrant local (manuales + historial)
uv run python -m troubleshooting_agent.agent "el PowerFlex 700 paró por F5 OverVoltage"   # una consulta
uv run python -m troubleshooting_agent.agent --contexto     # modo interactivo, mostrando la evidencia
uv run python scripts/probar_hito1.py                       # preguntas de prueba → artifacts/hito1_respuestas.md
uv run pytest                                               # tests (sin red, GPU ni Ollama)
```

Para usar el LLM real: `USE_REAL_LLM=true` en `.env` y Ollama corriendo con el modelo de `LLM_MODEL`. Si Ollama no responde o falta el modelo, el agente avisa y responde en modo simulado (lista los fragmentos recuperados con su cita). La primera indexación descarga BGE-M3 (~2,3 GB) en la cache de Hugging Face.

El agente muestra su traza: qué equipo identificó y, en cada paso, qué acción decidió (`buscar_historial`, `buscar_manual`, `pedir_datos` o `responder`), quién la decidió (LLM, reglas o guarda) y por qué. Si falta un dato (por ejemplo, el modelo), pregunta en la terminal y continúa con la respuesta. En modo simulado decide con reglas. Ejemplos de corridas en [`artifacts/hito2_respuestas.md`](artifacts/hito2_respuestas.md).

Con `CORPUS=demo` el historial de fallas es **sintético** (`data/catalog/fallas_sinteticas.jsonl`, 24 casos sobre los equipos del corpus demo): no son eventos reales.

> Todavía no implementado: aprobación humana de la propuesta de intervención (HITL), estado persistente en SQLite, retrieval híbrido (BM25 + RRF) y chequeo de fidelidad por afirmación (hito 3); OCR (`--ocr`) y DOCX/XLSX (opcionales).

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
  agent/        grafo LangGraph, router, tools, identificación de equipo, citas
    skills/     skill de troubleshooting (procedimiento, seguridad, escalamiento)
tests/
notebooks/
artifacts/      reportes de evaluación
```

## Estado

- [x] Catálogo de documentos y taxonomía de tags
- [x] Historial de fallas SAM V2 en JSONL
- [x] Corpus de demo con manuales públicos (script de descarga)
- [x] Ingesta de PDFs con texto (OCR pendiente, opcional)
- [x] Historial de fallas sintético + tool de búsqueda separada
- [x] Agente LangGraph que decide qué fuente consultar y pide datos faltantes (hito 2)
- [ ] Aprobación humana (HITL) + estado persistente (hito 3)
- [ ] Índice híbrido (BM25 + RRF); re-ranker solo si la evaluación lo justifica
- [ ] Búsqueda web restringida
- [ ] Evaluación (set de preguntas de troubleshooting)

## Limitaciones

- El agente asiste el diagnóstico; no reemplaza los procedimientos de seguridad ni el criterio del técnico.
- La calidad depende de la cobertura del corpus: hoy faltan, por ejemplo, el manual del VDF WEG CFW900 y el del controlador Lufkin SAM.
