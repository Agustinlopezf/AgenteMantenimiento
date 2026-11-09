# CLAUDE.md — Agente de troubleshooting de mantenimiento

Trabajo final del curso **AI Agent Developer (ITBA)**. Este archivo es la guía para Claude Code: qué es el proyecto, cómo está organizado y qué reglas seguir al tocar el código.

**Plan y etapa actual: ver [ROADMAP.md](ROADMAP.md).** Trabajar solo sobre la etapa en curso y no romper el camino de punta a punta (ingesta → retrieval → respuesta) que existe desde el hito 1.

## 1. Qué es el proyecto

Un agente que ayuda a técnicos de mantenimiento a diagnosticar fallas de equipos industriales (oil & gas) usando como fuente los **manuales de los fabricantes**, **instructivos internos** y el **historial de fallas resueltas**.

Flujo típico:
1. El técnico describe un síntoma en español ("el pozo para por F-22", "el compresor no levanta presión de aceite").
2. El agente identifica equipo / clase / conjunto (pregunta si falta información).
3. Recupera evidencia del corpus filtrando por metadatos (clase de equipo, fabricante, modelo, tipo de contenido).
4. Responde en español con causas probables, pasos de verificación y **citas** (`doc_id` + página).
5. Si el corpus no alcanza, puede buscar en la web **solo en dominios/páginas permitidas** (empezando por Rockwell Automation).

Requisitos no negociables:
- **Corre 100 % local** con modelos open source. Nada sale de la máquina por defecto.
- Debe poder correrlo el profesor (con GPU). El **modelo grande es opcional** y se elige por configuración; el default tiene que funcionar en hardware modesto.
- Hardware de desarrollo: Lenovo Legion 7, RTX 3070 Laptop (8 GB VRAM), 32 GB RAM, Ubuntu 24.04.
- Si no hay GPU / Ollama / índice, el sistema degrada con aviso explícito (modo simulado), nunca falla en silencio.

## 2. Stack

| Capa | Tecnología | Notas |
|---|---|---|
| Lenguaje / entorno | Python 3.12, `uv` | `uv sync`, `uv run ...` |
| LLM local | Ollama | Default `qwen3.5:4b` (modelo canónico del curso). Modelo grande opcional vía `LLM_MODEL`. |
| Orquestación del agente | LangGraph | Estado, checkpoints, human-in-the-loop (clase 11). |
| Embeddings | `sentence-transformers` — BGE-M3 (multilingüe) | Corpus mezcla EN/ES y las consultas son en ES: el modelo tiene que ser cross-lingual. Mismo modelo para indexar y consultar. |
| Vector store | Qdrant (local mode) | Payload = metadatos del catálogo (ver §4). Fallback in-memory con el mismo contrato. |
| Retrieval | Híbrido denso + BM25, fusión RRF, re-ranking | Clase 8. Filtros por payload antes del ranking. |
| Extracción PDF | PyMuPDF | Texto por página, conservando número de página física. |
| OCR | OCRmyPDF / Tesseract (`eng`, `spa`) | Solo docs con `requiere_ocr: true`. Se cachea el resultado. |
| DOCX / XLSX | python-docx / openpyxl | DOCX se segmenta por encabezados; XLSX → JSONL (un registro = un chunk). |
| Tools externas | MCP (opcional) | Búsqueda web restringida a allowlist de dominios (clase 13). |
| Evaluación | RAGAS / métricas propias | Faithfulness, context precision, hit@k sobre preguntas de troubleshooting. |
| Tests | pytest | Sin red ni GPU por defecto (providers y embeddings determinísticos). |

## 3. Estructura del repo

```
.
├── CLAUDE.md
├── pyproject.toml
├── data/
│   ├── raw/                      # PDFs/DOCX/XLSX originales (solo lectura, puede tener subcarpetas)
│   ├── catalog/
│   │   ├── catalogo_documentos.json   # FUENTE DE VERDAD de metadatos
│   │   └── fallas_sam_v2.jsonl        # historial de fallas (interno_pae: NO se versiona)
│   ├── ocr_cache/                # PDFs con capa de texto generada por OCR
│   └── chunks/                   # chunks.jsonl generados por la ingesta
├── artifacts/                    # índices, reportes de evaluación
├── src/troubleshooting_agent/
│   ├── catalog.py                # carga + validación del catálogo, herencia doc → sección → chunk
│   ├── ingest/                   # extracción, OCR, chunking
│   ├── retrieval/                # embeddings, Qdrant, BM25, RRF, reranker
│   ├── agent/                    # grafo LangGraph, prompts, tools
│   └── config.py                 # settings vía env vars
├── tests/
├── scripts/
│   └── descargar_manuales_publicos.py
└── notebooks/                    # experimentos (no es código productivo)
```

## 4. Catálogo de documentos y tags del RAG

`data/catalog/catalogo_documentos.json` define **qué** se indexa y **con qué metadatos**. Ningún documento entra al índice si no está en el catálogo. La estructura de carpetas en `data/raw/` no tiene significado para el RAG: la pertenencia a un equipo se expresa con `conjunto`.

### 4.1 Estructura

```
{
  "version", "fecha",
  "convenciones": {...},
  "taxonomia": {
    "clase_equipo", "componente", "conjunto",
    "contexto_operativo", "tipo_documento", "tipo_contenido"
  },
  "documentos": [ ...fichas... ],
  "faltantes_detectados": [ ... ]
}
```

### 4.2 Campos de la ficha de documento

| Campo | Tipo | Uso |
|---|---|---|
| `doc_id` | str | Identidad estable. Prefijo de todos los `chunk_id`. |
| `archivo` / `ruta_origen` | str \| null | Archivo en `data/raw/`. `null` si el doc es multiparte. |
| `partes` | list | Docs partidos en varios PDFs: cada parte con `archivo`, `paginas`, `ruta_origen`. Un solo `doc_id`. |
| `distribucion` | `publico` \| `propietario` \| `interno_pae` | Si el documento se puede distribuir. Solo `publico` entra con `CORPUS=demo`. No es un filtro de retrieval. |
| `fuente_publica` | obj | Solo para `publico`: `url` oficial del fabricante + `sha256` de la versión usada al catalogar. |
| `titulo` | str | Se muestra en las citas. |
| `tipo_documento` | enum | manual_usuario, manual_referencia, manual_programacion, manual_servicio, manual_iom, norma_practica_recomendada, plano_electrico, certificado, instructivo_interno, historial_fallas, lista_repuestos, secuencia_operacion |
| `clase_equipo` | enum | **Tag principal.** Ver taxonomía. |
| `clases_relacionadas` | list[enum] | Clases secundarias (ej. un tablero que contiene un VDF). |
| `componente` | str | Subsistema opcional (ESM, lubricacion_forzada, DNFT…). |
| `conjunto` | enum \| null | Paquete de equipo al que pertenece (motocompresor, equipo de perforación, pozo AIB). |
| `fabricante` | str | |
| `modelos` | list[str] | |
| `revision`, `serie`, `firmware` | str | Opcionales. |
| `idioma` | `es` \| `en` | |
| `contexto_operativo` | list[enum] | produccion_bombeo_mecanico, perforacion, medicion_fiscal_proceso, compresion_gas, general |
| `extraccion` | obj | `metodo` (texto, ocr, docx, xlsx), `requiere_ocr`, `nota`. |
| `indexar` | bool | `false` → no entra al vector store (duplicado, superado, sin valor técnico). Ver `motivo_exclusion`. |
| `prioridad` | alta \| media \| baja | Peso opcional en el ranking. |
| `secciones` | list | `titulo`, `paginas: [ini, fin]`, `tipo_contenido` y overrides opcionales (`clase_equipo`, `fabricante`, `modelos`, `componente`). |
| `relacionados` | list[doc_id] | Navegación entre documentos. |
| `notas` | str | Advertencias para el humano. No se indexan. |

### 4.3 Taxonomía (valores controlados)

- **clase_equipo:** variador_frecuencia, tablero_electrico, controlador_pozo, motor_electrico, top_drive, bop, caudalimetro, medidor_corte_agua, motor_gas, compresor_reciprocante, panel_control. Cada clase tiene `sinonimos` para mapear la consulta del usuario a la clase.
- **conjunto:** motocompresor_waukesha_ariel, equipo_perforacion_rapid_rig_17, pozo_aib_sam_v2.
- **tipo_contenido:** troubleshooting, codigos_falla, mantenimiento, parametros, instalacion, puesta_en_marcha, operacion, configuracion, repuestos, planos, seguridad, general.

Agregar un valor nuevo = agregarlo primero en `taxonomia` y después usarlo. `catalog.py` debe rechazar valores fuera de la taxonomía.

### 4.4 Herencia de metadatos al chunk

```
chunk.metadata = documento  ⊕  sección que contiene la página  ⊕  datos propios del chunk
```
- Las páginas son **físicas del PDF, base 1** (no la numeración impresa).
- Si una sección define `clase_equipo`, `fabricante`, `modelos` o `componente`, **pisa** al documento (ej. motores Reliance dentro del manual del Top Drive).
- Páginas fuera de toda sección → `tipo_contenido: "general"`.

### 4.5 Payload del chunk (lo que va a Qdrant)

```json
{
  "chunk_id": "nov-3om00200-r01::p0180::c02",
  "doc_id": "nov-3om00200-r01",
  "archivo": "3OM00200_-_Rev_01_-_3OM00200_-_FINAL_New_01.pdf",
  "pagina_inicio": 180, "pagina_fin": 180,
  "seccion": "SM01096 cap. 5 – Maintenance & Troubleshooting",
  "clase_equipo": "top_drive",
  "clases_relacionadas": [],
  "componente": null,
  "conjunto": "equipo_perforacion_rapid_rig_17",
  "fabricante": "National Oilwell Varco (NOV)",
  "modelos": ["TDS-10RR"],
  "tipo_documento": "manual_servicio",
  "tipo_contenido": "mantenimiento",
  "contexto_operativo": ["perforacion"],
  "idioma": "en",
  "prioridad": "media",
  "fuente_texto": "texto",
  "texto": "..."
}
```

Campos indexados como **filtro** en Qdrant: `clase_equipo`, `conjunto`, `fabricante`, `modelos`, `tipo_contenido`, `tipo_documento`, `idioma`, `componente`, `doc_id`.

`chunk_id = {doc_id}::p{pagina:04d}::c{n:02d}`: estable entre re-ingestas (reindexar no duplica).

### 4.6 Historial de fallas

`fallas_sam_v2.jsonl`: un registro por caso (`sintoma`, `causa`, `solucion`, `pozo`, `fecha`, `clase_equipo`, `clases_relacionadas`, `observaciones_calidad`). Se embebe `texto_para_embedding`. Se usa como evidencia de casos reales y como ejemplos few-shot; en la respuesta se distingue de lo que dice el manual del fabricante.

## 5. Reglas para Claude Code

- `data/raw/` es **solo lectura**. Nunca modificar ni renombrar originales.
- **Nunca versionar ni empaquetar** contenido de documentos `propietario` o `interno_pae`: ni los PDFs, ni chunks, ni índices, ni fixtures de tests con su texto. Los tests usan textos sintéticos o fragmentos de documentos `publico`.
- La ingesta respeta `CORPUS`: `demo` = solo `distribucion: publico`; `completo` = todo lo que tenga `indexar: true`.
- El catálogo es la fuente de verdad: no inferir metadatos del nombre del archivo ni de la carpeta en el código.
- No indexar documentos con `indexar: false`.
- Toda respuesta del agente cita `doc_id` + página. Si no hay evidencia suficiente, el agente lo dice; no inventa procedimientos ni valores de parámetros.
- Las normas (`norma_practica_recomendada`) se presentan como criterio general, no como instrucción del fabricante.
- Seguridad: si el procedimiento recuperado incluye advertencias (energía, presión, bloqueo/etiquetado), se incluyen en la respuesta.
- El modelo, la URL de Ollama, el modelo de embeddings, el corpus y el modo simulado se configuran con env vars (`LLM_MODEL`, `OLLAMA_BASE_URL`, `EMBEDDING_MODEL`, `USE_REAL_LLM`, `USE_QDRANT`, `CORPUS`). Nunca hardcodear.
- Respetar el límite de 8 GB de VRAM: LLM + embeddings + reranker no pueden exigir más en simultáneo con la config por defecto.
- Tests con `uv run pytest` deben pasar sin red, sin GPU y sin Ollama.
- Antes de escribir código nuevo, proponer el plan y esperar confirmación.

## 6. Comandos

```bash
uv sync
uv run python scripts/descargar_manuales_publicos.py         # corpus de demo → data/raw/
uv run python -m troubleshooting_agent.catalog validate      # valida catálogo vs taxonomía y archivos
uv run python -m troubleshooting_agent.ingest --ocr          # OCR + extracción + chunking → data/chunks/
uv run python -m troubleshooting_agent.retrieval.index       # embeddings + Qdrant
uv run python -m troubleshooting_agent.agent                 # CLI del agente
uv run pytest
```
(Los módulos todavía no existen; estos son los entrypoints previstos.)

## 7. Pendientes conocidos

- OCR de 11 documentos escaneados (BOP Shaffer, API RP 53, planos WEG, O&M Waukesha 6387-1 a–d, Murphy, planos S-08685-4) y completar rangos de `secciones` después del OCR.
- Faltan manuales: **WEG CFW900** (citado en el historial de fallas) y **Lufkin SAM Well Manager**.
- Confirmar que la secuencia Murphy Centurion Plus (Enerflex) corresponda al programa de las unidades Valerus V6624–V6628.
- Limpieza del historial SAM V2: fecha 2026-12-29 dudosa y una fila con columnas corridas.
- Definir el set de preguntas de evaluación (troubleshooting real por clase de equipo). Incluir un subset que se pueda responder solo con el corpus de demo.
- Verificar en la primera descarga la URL de `rok-pflex-um-es` (20B-UM002 en español), que se dedujo del patrón de Rockwell.
