"""Catálogo de documentos: carga, selección según CORPUS y herencia de metadatos.

El catálogo (`data/catalog/catalogo_documentos.json`) es la fuente de verdad: no se
infiere nada del nombre del archivo ni de la carpeta.

Uso:
    uv run python -m troubleshooting_agent.catalog list
    uv run python -m troubleshooting_agent.catalog validate
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from troubleshooting_agent.config import load_settings

Doc = dict[str, Any]

# Campos que una sección puede pisar respecto del documento (herencia doc → sección → chunk).
CAMPOS_OVERRIDE_SECCION = ("clase_equipo", "fabricante", "modelos", "componente", "tipo_contenido")


def load_catalog(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def documentos_a_indexar(catalog: dict[str, Any], corpus: str) -> list[Doc]:
    """`indexar: true` y, con CORPUS=demo, solo `distribucion: publico`."""
    docs = [d for d in catalog["documentos"] if d.get("indexar") is True]
    if corpus == "demo":
        docs = [d for d in docs if d.get("distribucion") == "publico"]
    return docs


def _buscar(raw_dir: Path, ruta_origen: str | None, archivo: str | None) -> Path | None:
    if ruta_origen and (raw_dir / ruta_origen).is_file():
        return raw_dir / ruta_origen
    if archivo:
        if (raw_dir / archivo).is_file():
            return raw_dir / archivo
        for candidato in sorted(raw_dir.rglob(archivo)):
            if candidato.is_file():
                return candidato
    return None


def resolver_archivos(doc: Doc, raw_dir: Path) -> list[tuple[Path, int]]:
    """Devuelve [(path, offset_de_pagina)] por cada PDF del documento.

    Para docs multiparte, el offset es la suma de páginas de las partes anteriores,
    así la página física queda continua en todo el `doc_id`. Si falta algún archivo
    devuelve lista vacía (el documento no se puede ingerir completo).
    """
    raw_dir = Path(raw_dir)
    if doc.get("partes"):
        resultado: list[tuple[Path, int]] = []
        offset = 0
        for parte in doc["partes"]:
            path = _buscar(raw_dir, parte.get("ruta_origen"), parte.get("archivo"))
            if path is None:
                return []
            resultado.append((path, offset))
            offset += int(parte.get("paginas") or 0)
        return resultado
    path = _buscar(raw_dir, doc.get("ruta_origen"), doc.get("archivo"))
    return [(path, 0)] if path else []


def seccion_de_pagina(doc: Doc, pagina: int) -> dict[str, Any] | None:
    for seccion in doc.get("secciones") or []:
        ini, fin = seccion["paginas"]
        if ini <= pagina <= fin:
            return seccion
    return None


def metadata_para_pagina(doc: Doc, pagina: int) -> dict[str, Any]:
    """Metadatos del chunk = documento ⊕ sección que contiene la página (base 1)."""
    meta: dict[str, Any] = {
        "doc_id": doc["doc_id"],
        "archivo": doc.get("archivo"),
        "titulo": doc.get("titulo"),
        "seccion": None,
        "clase_equipo": doc.get("clase_equipo"),
        "clases_relacionadas": list(doc.get("clases_relacionadas") or []),
        "componente": doc.get("componente"),
        "conjunto": doc.get("conjunto"),
        "fabricante": doc.get("fabricante"),
        "modelos": list(doc.get("modelos") or []),
        "tipo_documento": doc.get("tipo_documento"),
        "tipo_contenido": "general",
        "contexto_operativo": list(doc.get("contexto_operativo") or []),
        "idioma": doc.get("idioma"),
        "prioridad": doc.get("prioridad"),
    }
    seccion = seccion_de_pagina(doc, pagina)
    if seccion is not None:
        meta["seccion"] = seccion.get("titulo")
        for campo in CAMPOS_OVERRIDE_SECCION:
            if seccion.get(campo) is not None:
                meta[campo] = seccion[campo]
    return meta


# ── validación ──────────────────────────────────────────────

CAMPOS_OBLIGATORIOS = ("doc_id", "distribucion", "titulo", "tipo_documento", "clase_equipo", "idioma",
                       "extraccion", "indexar")
IDIOMAS = ("es", "en")
METODOS_EXTRACCION = ("texto", "ocr", "docx", "xlsx", "jsonl")
PRIORIDADES = ("alta", "media", "baja")


def _valores(taxonomia: dict[str, Any], campo: str) -> set[str]:
    v = taxonomia.get(campo) or []
    return set(v) if not isinstance(v, dict) or campo != "componente" else set()


def _sha256(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def validar_catalogo(catalog: dict[str, Any], raw_dir: Path | None = None, catalog_dir: Path | None = None,
                     verificar_hash: bool = False) -> tuple[list[str], list[str]]:
    """Devuelve (errores, avisos).

    Errores: el catálogo es inconsistente (valores fuera de la taxonomía, doc_id repetido,
    rangos de páginas imposibles, referencias rotas, falta un archivo `publico` indexable).
    Avisos: cosas a revisar que no impiden indexar (archivos no públicos ausentes, secciones
    sin rango o solapadas, sha256 distinto al catalogado).
    """
    errores: list[str] = []
    avisos: list[str] = []
    tax = catalog.get("taxonomia") or {}
    controlados = {c: _valores(tax, c) for c in ("clase_equipo", "tipo_documento", "tipo_contenido",
                                                  "contexto_operativo", "conjunto", "distribucion")}
    clases = controlados["clase_equipo"]

    def fuera(doc_id: str, donde: str, campo: str, valor: Any) -> None:
        if valor is not None and controlados[campo] and valor not in controlados[campo]:
            errores.append(f"{doc_id}{donde}: {campo}={valor!r} no está en la taxonomía")

    for nombre, conj in (tax.get("conjunto") or {}).items():
        for c in conj.get("clases", []) if isinstance(conj, dict) else []:
            if c not in clases:
                errores.append(f"taxonomia.conjunto.{nombre}: clase {c!r} no está en clase_equipo")

    docs = catalog.get("documentos") or []
    ids = [d.get("doc_id") for d in docs]
    for doc_id in sorted({i for i in ids if ids.count(i) > 1}):
        errores.append(f"doc_id repetido: {doc_id}")
    conocidos = set(ids)

    for doc in docs:
        doc_id = doc.get("doc_id", "?")
        for campo in CAMPOS_OBLIGATORIOS:
            if doc.get(campo) in (None, ""):
                errores.append(f"{doc_id}: falta el campo obligatorio {campo!r}")
        for campo in ("clase_equipo", "tipo_documento", "conjunto", "distribucion"):
            fuera(doc_id, "", campo, doc.get(campo))
        for c in doc.get("clases_relacionadas") or []:
            fuera(doc_id, "", "clase_equipo", c)
        for c in doc.get("contexto_operativo") or []:
            fuera(doc_id, "", "contexto_operativo", c)
        if doc.get("idioma") not in (None, *IDIOMAS):
            errores.append(f"{doc_id}: idioma={doc['idioma']!r} (esperado es | en)")
        if doc.get("prioridad") not in (None, *PRIORIDADES):
            errores.append(f"{doc_id}: prioridad={doc['prioridad']!r} (esperado alta | media | baja)")
        metodo = (doc.get("extraccion") or {}).get("metodo")
        if metodo not in METODOS_EXTRACCION:
            errores.append(f"{doc_id}: extraccion.metodo={metodo!r} desconocido")
        if not isinstance(doc.get("indexar"), bool):
            errores.append(f"{doc_id}: indexar tiene que ser true / false")
        if doc.get("indexar") is False and not doc.get("motivo_exclusion"):
            avisos.append(f"{doc_id}: indexar=false sin motivo_exclusion")
        if doc.get("distribucion") == "publico" and doc.get("indexar") and metodo in ("texto", "ocr") and \
                not (doc.get("fuente_publica") or {}).get("url"):
            errores.append(f"{doc_id}: documento publico sin fuente_publica.url")
        for rel in doc.get("relacionados") or []:
            if rel not in conocidos:
                errores.append(f"{doc_id}: relacionado {rel!r} no existe en el catálogo")

        # secciones
        total = doc.get("paginas") or sum(int(p.get("paginas") or 0) for p in doc.get("partes") or []) or None
        rangos: list[tuple[int, int, str]] = []
        for s in doc.get("secciones") or []:
            titulo = s.get("titulo", "?")
            donde = f" · sección {titulo!r}"
            fuera(doc_id, donde, "tipo_contenido", s.get("tipo_contenido"))
            fuera(doc_id, donde, "clase_equipo", s.get("clase_equipo"))
            pags = s.get("paginas")
            if pags is None:
                avisos.append(f"{doc_id}{donde}: sin rango de páginas (no se aplica a ningún chunk)")
                continue
            if not (isinstance(pags, list) and len(pags) == 2 and all(isinstance(p, int) for p in pags)
                    and 1 <= pags[0] <= pags[1]):
                errores.append(f"{doc_id}{donde}: paginas={pags!r} inválido (esperado [ini, fin], base 1)")
                continue
            if total and pags[1] > total:
                errores.append(f"{doc_id}{donde}: termina en p. {pags[1]} pero el documento tiene {total}")
            rangos.append((pags[0], pags[1], titulo))
        rangos.sort()
        for (a0, a1, ta), (b0, b1, tb) in zip(rangos, rangos[1:]):
            if b0 <= a1:
                avisos.append(f"{doc_id}: secciones solapadas {ta!r} [{a0}, {a1}] y {tb!r} [{b0}, {b1}] "
                              f"(en las páginas comunes gana la primera del catálogo)")

        # archivos
        if not doc.get("indexar"):
            continue
        if metodo == "jsonl":
            registros = (doc.get("extraccion") or {}).get("registros")
            if catalog_dir is not None and (not registros or not (Path(catalog_dir) / registros).is_file()):
                errores.append(f"{doc_id}: no está el archivo de registros {registros!r} en {catalog_dir}")
            continue
        if raw_dir is None:
            continue
        archivos = resolver_archivos(doc, Path(raw_dir))
        if not archivos:
            msj = f"{doc_id}: falta el archivo en data/raw ({doc.get('archivo') or 'multiparte'})"
            if doc.get("distribucion") == "publico":
                errores.append(msj + " → correr scripts/descargar_manuales_publicos.py")
            else:
                avisos.append(msj + " (solo hace falta con CORPUS=completo)")
            continue
        esperado = (doc.get("fuente_publica") or {}).get("sha256")
        if verificar_hash and esperado and len(archivos) == 1 and _sha256(archivos[0][0]) != esperado:
            avisos.append(f"{doc_id}: sha256 distinto al del catálogo (¿nueva revisión? revisar rangos de secciones)")
    return errores, avisos


def validar_registros(registros: list[dict[str, Any]], taxonomia: dict[str, Any], origen: str) -> list[str]:
    """Clases de equipo de un historial (jsonl) dentro de la taxonomía."""
    clases = set(taxonomia.get("clase_equipo") or {})
    errores = []
    for i, r in enumerate(registros, 1):
        for c in [r.get("clase_equipo"), *(r.get("clases_relacionadas") or [])]:
            if c is not None and c not in clases:
                errores.append(f"{origen}:{i}: clase_equipo={c!r} no está en la taxonomía")
    return errores


def _cmd_validate(sin_hash: bool) -> int:
    settings = load_settings()
    catalog = load_catalog(settings.catalog_path)
    catalog_dir = Path(settings.catalog_path).parent
    errores, avisos = validar_catalogo(catalog, settings.raw_dir, catalog_dir, verificar_hash=not sin_hash)
    for doc in catalog.get("documentos") or []:
        registros = (doc.get("extraccion") or {}).get("registros")
        path = catalog_dir / registros if registros else None
        if path and path.is_file():
            filas = [json.loads(linea) for linea in path.read_text(encoding="utf-8").splitlines() if linea.strip()]
            errores += validar_registros(filas, catalog.get("taxonomia") or {}, registros)
    for a in avisos:
        print(f"  aviso  {a}")
    for e in errores:
        print(f"  ERROR  {e}")
    n = len(catalog.get("documentos") or [])
    print(f"{settings.catalog_path.name}: {n} documentos · {len(errores)} error(es) · {len(avisos)} aviso(s)")
    return 1 if errores else 0


def _cmd_list(corpus: str | None) -> int:
    settings = load_settings()
    corpus = corpus or settings.corpus
    catalog = load_catalog(settings.catalog_path)
    docs = documentos_a_indexar(catalog, corpus)
    faltantes = 0
    print(f"CORPUS={corpus}: {len(docs)} documentos a indexar")
    for doc in docs:
        registros = (doc.get("extraccion") or {}).get("registros")
        if registros:  # historial en JSONL junto al catálogo, no en data/raw
            hay = (Path(settings.catalog_path).parent / registros).is_file()
        else:
            hay = bool(resolver_archivos(doc, settings.raw_dir))
        estado = "ok" if hay else "FALTA ARCHIVO"
        faltantes += not hay
        metodo = (doc.get("extraccion") or {}).get("metodo", "?")
        print(f"  [{estado:13}] {doc['doc_id']:28} metodo={metodo:6} {doc.get('titulo', '')}")
    if faltantes:
        print(f"AVISO: {faltantes} documento(s) sin archivo en {settings.raw_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m troubleshooting_agent.catalog")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="documentos que entran al índice según CORPUS")
    p_list.add_argument("--corpus", choices=["demo", "completo"])
    p_val = sub.add_parser("validate", help="catálogo vs. taxonomía, rangos de páginas y archivos en data/raw")
    p_val.add_argument("--sin-hash", action="store_true", help="no calcular sha256 de los PDFs públicos")
    args = ap.parse_args(argv)
    if args.cmd == "list":
        return _cmd_list(args.corpus)
    if args.cmd == "validate":
        return _cmd_validate(args.sin_hash)
    return 1


if __name__ == "__main__":
    sys.exit(main())
