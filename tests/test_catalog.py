import copy
import json

from troubleshooting_agent.catalog import (
    documentos_a_indexar,
    load_catalog,
    main,
    metadata_para_pagina,
    resolver_archivos,
    validar_catalogo,
    validar_registros,
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
        "hist-sintetico-demo",
    }


TAXONOMIA = {
    "clase_equipo": {"variador_frecuencia": {}, "motor_electrico": {}},
    "tipo_documento": ["manual_usuario"],
    "tipo_contenido": ["instalacion", "troubleshooting", "general"],
    "contexto_operativo": ["general"],
    "conjunto": {"pozo": {"clases": ["variador_frecuencia"]}},
    "distribucion": ["publico", "propietario", "interno_pae"],
}


def _valido(mini_catalogo):
    cat = copy.deepcopy(mini_catalogo)
    cat["taxonomia"] = TAXONOMIA
    cat["documentos"][0]["fuente_publica"] = {"url": "https://ejemplo/manual.pdf"}
    cat["documentos"][2]["motivo_exclusion"] = "duplicado"
    cat["documentos"].pop()  # demo-faltante: público sin archivo
    return cat


def test_validar_catalogo_ok_y_avisos(mini_catalogo, raw_dir):
    errores, avisos = validar_catalogo(_valido(mini_catalogo), raw_dir)
    assert errores == []
    assert avisos == ["demo-ocr: falta el archivo en data/raw (escaneado.pdf) (solo hace falta con CORPUS=completo)"]


def test_validar_catalogo_detecta_errores(mini_catalogo, raw_dir):
    cat = copy.deepcopy(mini_catalogo)
    cat["taxonomia"] = TAXONOMIA
    pub = cat["documentos"][0]
    pub["clase_equipo"] = "licuadora"
    pub["paginas"] = 2
    pub["secciones"][0]["tipo_contenido"] = "receta"
    pub["secciones"][1]["paginas"] = [2, 5]
    pub["secciones"].append({"titulo": "Anidada", "paginas": [1, 1], "tipo_contenido": "general"})
    pub["secciones"].append({"titulo": "Al revés", "paginas": [3, 1], "tipo_contenido": "general"})
    pub["relacionados"] = ["no-existe"]
    cat["documentos"][1]["doc_id"] = "demo-publico"
    errores, avisos = validar_catalogo(cat, raw_dir)
    texto = "\n".join(errores)
    for esperado in ["doc_id repetido: demo-publico", "clase_equipo='licuadora'", "tipo_contenido='receta'",
                     "termina en p. 5 pero el documento tiene 2", "paginas=[3, 1] inválido",
                     "relacionado 'no-existe'", "documento publico sin fuente_publica.url",
                     "demo-faltante: falta el archivo"]:
        assert esperado in texto, esperado
    assert any("secciones solapadas" in a for a in avisos)
    assert any("indexar=false sin motivo_exclusion" in a for a in avisos)


def test_validar_registros_historial():
    filas = [{"clase_equipo": "variador_frecuencia"}, {"clase_equipo": "x", "clases_relacionadas": ["y"]}]
    assert validar_registros(filas, TAXONOMIA, "h.jsonl") == [
        "h.jsonl:2: clase_equipo='x' no está en la taxonomía", "h.jsonl:2: clase_equipo='y' no está en la taxonomía"]


def test_catalogo_real_sin_errores():
    catalog = load_catalog(REPO_ROOT / "data" / "catalog" / "catalogo_documentos.json")
    errores, _ = validar_catalogo(catalog, catalog_dir=REPO_ROOT / "data" / "catalog")
    assert errores == []
    filas = [json.loads(linea) for linea in
             (REPO_ROOT / "data" / "catalog" / "fallas_sinteticas.jsonl").read_text(encoding="utf-8").splitlines()
             if linea.strip()]
    assert validar_registros(filas, catalog["taxonomia"], "fallas_sinteticas.jsonl") == []


def test_cli_validate_exit_code(tmp_path, monkeypatch, mini_catalogo, raw_dir):
    cat = _valido(mini_catalogo)
    path = tmp_path / "catalog" / "catalogo_documentos.json"  # DATA_DIR=tmp_path → raw_dir = tmp_path/raw
    path.parent.mkdir()
    path.write_text(json.dumps(cat), encoding="utf-8")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert main(["validate", "--sin-hash"]) == 0
    cat["documentos"][0]["clase_equipo"] = "licuadora"
    path.write_text(json.dumps(cat), encoding="utf-8")
    assert main(["validate", "--sin-hash"]) == 1
