import json

import pytest

from troubleshooting_agent.ingest import ingerir
from troubleshooting_agent.ingest.chunking import chunk_id, chunk_texto
from troubleshooting_agent.ingest.extract import extraer_paginas_pdf

CAMPOS_PAYLOAD = {
    "chunk_id", "doc_id", "archivo", "pagina_inicio", "pagina_fin", "seccion",
    "clase_equipo", "clases_relacionadas", "componente", "conjunto", "fabricante",
    "modelos", "tipo_documento", "tipo_contenido", "contexto_operativo", "idioma",
    "prioridad", "fuente_texto", "texto",
}


def _leer(path):
    return [json.loads(linea) for linea in path.read_text(encoding="utf-8").splitlines()]


# ── chunking ────────────────────────────────────────────────

def test_chunk_id_formato():
    assert chunk_id("nov-3om00200-r01", 180, 2) == "nov-3om00200-r01::p0180::c02"


def test_chunk_texto_respeta_tamano_y_solapa():
    texto = " ".join(f"palabra{i}" for i in range(300))
    chunks = chunk_texto(texto, size=200, overlap=50)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)
    for a, b in zip(chunks, chunks[1:]):
        assert b.split()[0] in a  # el siguiente arranca dentro del anterior
    # no se pierden palabras
    assert set(texto.split()) == {p for c in chunks for p in c.split()}


def test_chunk_texto_corto_y_vacio():
    assert chunk_texto("hola", 100, 10) == ["hola"]
    assert chunk_texto("   ", 100, 10) == []


def test_chunk_texto_sin_espacios_avanza():
    chunks = chunk_texto("x" * 1000, size=100, overlap=90)
    assert "".join(chunks).count("x") >= 1000
    assert len(chunks) < 200


def test_chunk_texto_parametros_invalidos():
    with pytest.raises(ValueError):
        chunk_texto("abc", 10, 10)


# ── extracción ──────────────────────────────────────────────

def test_extraer_paginas_base_1(raw_dir):
    paginas = list(extraer_paginas_pdf(raw_dir / "sintetico.pdf"))
    assert [p for p, _ in paginas] == [1, 2, 3]
    assert "F-99" in paginas[1][1]


# ── pipeline ────────────────────────────────────────────────

def test_ingerir_demo(mini_catalogo, raw_dir, tmp_path):
    salida = tmp_path / "chunks" / "chunks.jsonl"
    r = ingerir(mini_catalogo, "demo", raw_dir, salida, size=300, overlap=50)

    assert r.procesados == ["demo-publico"]
    assert "no encontrado" in r.saltados["demo-faltante"]
    assert r.paginas == 3

    chunks = _leer(salida)
    assert len(chunks) == r.chunks
    assert all(CAMPOS_PAYLOAD <= c.keys() for c in chunks)
    assert all(c["pagina_inicio"] == c["pagina_fin"] for c in chunks)  # no cruzan páginas
    assert len({c["chunk_id"] for c in chunks}) == len(chunks)

    pag2 = [c for c in chunks if c["pagina_inicio"] == 2]
    assert len(pag2) > 1
    assert all(c["tipo_contenido"] == "troubleshooting" for c in pag2)
    assert all(c["clase_equipo"] == "motor_electrico" for c in pag2)
    assert pag2[0]["chunk_id"] == "demo-publico::p0002::c00"


def test_ingerir_completo_saltea_ocr(mini_catalogo, raw_dir, tmp_path):
    r = ingerir(mini_catalogo, "completo", raw_dir, tmp_path / "c.jsonl", size=300, overlap=50)
    assert "OCR" in r.saltados["demo-ocr"]
    assert set(r.procesados) == {"demo-publico", "demo-propietario"}


def test_ingerir_idempotente(mini_catalogo, raw_dir, tmp_path):
    salida = tmp_path / "chunks.jsonl"
    ingerir(mini_catalogo, "demo", raw_dir, salida, size=300, overlap=50)
    primera = _leer(salida)
    ingerir(mini_catalogo, "demo", raw_dir, salida, size=300, overlap=50)
    assert _leer(salida) == primera
