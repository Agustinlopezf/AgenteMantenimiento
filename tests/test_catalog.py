from troubleshooting_agent.catalog import (
    documentos_a_indexar,
    load_catalog,
    metadata_para_pagina,
    resolver_archivos,
)
from troubleshooting_agent.config import REPO_ROOT


def _ids(docs):
    return {d["doc_id"] for d in docs}


def test_demo_solo_publicos_indexables(mini_catalogo):
    assert _ids(documentos_a_indexar(mini_catalogo, "demo")) == {"demo-publico", "demo-faltante"}


def test_completo_excluye_indexar_false(mini_catalogo):
    ids = _ids(documentos_a_indexar(mini_catalogo, "completo"))
    assert "demo-no-indexar" not in ids
    assert ids == {"demo-publico", "demo-propietario", "demo-ocr", "demo-faltante"}


def test_herencia_y_override_por_seccion(mini_catalogo):
    doc = mini_catalogo["documentos"][0]

    p1 = metadata_para_pagina(doc, 1)
    assert p1["seccion"] == "Cap. 1 Instalación"
    assert p1["tipo_contenido"] == "instalacion"
    assert p1["clase_equipo"] == "variador_frecuencia"

    p2 = metadata_para_pagina(doc, 2)
    assert p2["tipo_contenido"] == "troubleshooting"
    assert p2["clase_equipo"] == "motor_electrico"
    assert p2["fabricante"] == "Otro Fabricante"
    assert p2["modelos"] == ["Motor Y"]

    p3 = metadata_para_pagina(doc, 3)  # fuera de toda sección
    assert p3["seccion"] is None
    assert p3["tipo_contenido"] == "general"
    assert p3["fabricante"] == "Fabricante Demo"


def test_override_no_muta_documento(mini_catalogo):
    doc = mini_catalogo["documentos"][0]
    metadata_para_pagina(doc, 2)["modelos"].append("x")
    assert doc["modelos"] == ["Modelo X"]


def test_resolver_archivos(mini_catalogo, raw_dir):
    publico, propietario, *_ , faltante = mini_catalogo["documentos"]
    assert resolver_archivos(publico, raw_dir) == [(raw_dir / "sintetico.pdf", 0)]
    # ruta_origen no existe → busca `archivo` en subcarpetas
    assert resolver_archivos(propietario, raw_dir) == [(raw_dir / "subcarpeta" / "anidado.pdf", 0)]
    assert resolver_archivos(faltante, raw_dir) == []


def test_resolver_multiparte_offsets(raw_dir):
    doc = {
        "doc_id": "multi",
        "archivo": None,
        "partes": [
            {"archivo": "sintetico.pdf", "paginas": 3},
            {"archivo": "anidado.pdf", "paginas": 1},
        ],
    }
    assert resolver_archivos(doc, raw_dir) == [
        (raw_dir / "sintetico.pdf", 0),
        (raw_dir / "subcarpeta" / "anidado.pdf", 3),
    ]
    doc["partes"].append({"archivo": "falta.pdf", "paginas": 5})
    assert resolver_archivos(doc, raw_dir) == []


def test_catalogo_real_demo():
    catalog = load_catalog(REPO_ROOT / "data" / "catalog" / "catalogo_documentos.json")
    assert _ids(documentos_a_indexar(catalog, "demo")) == {
        "rok-20b-um001-en",
        "rok-pflex-um-es",
        "rok-pflex-rm001-en",
        "rok-750-rm002-en",
        "rok-750-pm001-en",
        "flexim-fluxus-f532wd-es",
    }
