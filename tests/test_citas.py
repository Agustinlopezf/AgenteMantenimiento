from troubleshooting_agent.agent.citas import Cita, armar_fuentes, clasificar_citas, extraer_citas
from troubleshooting_agent.retrieval.store import Hit


def _hit(doc_id, pagina, seccion="Sec"):
    return Hit(0.9, {"doc_id": doc_id, "pagina_inicio": pagina, "titulo": f"Título {doc_id}", "seccion": seccion, "texto": "x"})


def test_extraer_variantes():
    texto = (
        "Verificar la tensión [rok-20b-um001-en, p. 85]. También [rok-20b-um001-en, pág. 86] "
        "y [rok-750-rm002-en, page 160; flexim-fluxus-f532wd-es, p.12]. "
        "Rango [rok-pflex-um-es, p. 40-41]. Repetida [rok-20b-um001-en, p. 85]. "
        "No es cita: [nota al pie] [1]."
    )
    assert extraer_citas(texto) == [
        Cita("rok-20b-um001-en", 85),
        Cita("rok-20b-um001-en", 86),
        Cita("rok-750-rm002-en", 160),
        Cita("flexim-fluxus-f532wd-es", 12),
        Cita("rok-pflex-um-es", 40),
    ]


def test_clasificar_y_fuentes():
    hits = [_hit("a", 1), _hit("b", 5)]
    citas = [Cita("a", 1), Cita("a", 2), Cita("c", 1)]
    validas, invalidas = clasificar_citas(citas, hits)
    assert validas == [Cita("a", 1)]
    assert invalidas == [Cita("a", 2), Cita("c", 1)]
    assert armar_fuentes(validas, hits) == ["[a, p. 1] Título a · Sec"]
