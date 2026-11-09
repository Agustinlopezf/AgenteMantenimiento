"""Fixtures sintéticas: ningún texto de documentos propietarios / internos."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

PAGINAS_SINTETICAS = [
    "Manual sintético de prueba. Capítulo de instalación del variador de ejemplo.",
    "Troubleshooting. Falla F-99 sobretensión en bus DC. " + "Verificar tensión de línea. " * 80,
    "Apéndice. Repuestos del equipo de ejemplo.",
]


def _crear_pdf(path: Path, paginas: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = pymupdf.open()
    for texto in paginas:
        pagina = pdf.new_page()
        pagina.insert_textbox(pymupdf.Rect(40, 40, 560, 800), texto, fontsize=8)
    pdf.save(path)
    pdf.close()
    return path


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    _crear_pdf(raw / "sintetico.pdf", PAGINAS_SINTETICAS)
    _crear_pdf(raw / "subcarpeta" / "anidado.pdf", ["Documento en subcarpeta."])
    return raw


@pytest.fixture
def mini_catalogo() -> dict:
    base = {
        "tipo_documento": "manual_usuario",
        "clase_equipo": "variador_frecuencia",
        "fabricante": "Fabricante Demo",
        "modelos": ["Modelo X"],
        "idioma": "es",
        "contexto_operativo": ["general"],
        "conjunto": None,
    }
    return {
        "documentos": [
            {
                **base,
                "doc_id": "demo-publico",
                "archivo": "sintetico.pdf",
                "ruta_origen": "sintetico.pdf",
                "distribucion": "publico",
                "titulo": "Manual sintético",
                "extraccion": {"metodo": "texto", "requiere_ocr": False},
                "indexar": True,
                "secciones": [
                    {"titulo": "Cap. 1 Instalación", "paginas": [1, 1], "tipo_contenido": "instalacion"},
                    {
                        "titulo": "Cap. 2 Troubleshooting",
                        "paginas": [2, 2],
                        "tipo_contenido": "troubleshooting",
                        "clase_equipo": "motor_electrico",
                        "fabricante": "Otro Fabricante",
                        "modelos": ["Motor Y"],
                    },
                ],
            },
            {
                **base,
                "doc_id": "demo-propietario",
                "archivo": "anidado.pdf",
                "ruta_origen": "otra/ruta/anidado.pdf",
                "distribucion": "propietario",
                "titulo": "Doc propietario",
                "extraccion": {"metodo": "texto", "requiere_ocr": False},
                "indexar": True,
            },
            {
                **base,
                "doc_id": "demo-no-indexar",
                "archivo": "sintetico.pdf",
                "distribucion": "publico",
                "titulo": "Duplicado",
                "extraccion": {"metodo": "texto"},
                "indexar": False,
            },
            {
                **base,
                "doc_id": "demo-ocr",
                "archivo": "escaneado.pdf",
                "distribucion": "propietario",
                "titulo": "Escaneado",
                "extraccion": {"metodo": "ocr", "requiere_ocr": True},
                "indexar": True,
            },
            {
                **base,
                "doc_id": "demo-faltante",
                "archivo": "no_existe.pdf",
                "distribucion": "publico",
                "titulo": "Faltante",
                "extraccion": {"metodo": "texto", "requiere_ocr": False},
                "indexar": True,
            },
        ]
    }
