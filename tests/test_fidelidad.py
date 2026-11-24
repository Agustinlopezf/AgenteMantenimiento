"""Fidelidad por afirmación: chequeo léxico de términos clave y juez LLM (fake)."""

from troubleshooting_agent.agent.fidelidad import (
    SCHEMA_JUEZ,
    corregir_citas,
    evaluar_fidelidad,
    resumen_fidelidad,
    separar_afirmaciones,
    terminos_clave,
)
from troubleshooting_agent.agent.propuesta import validar_propuesta
from troubleshooting_agent.retrieval.store import Hit

P87 = Hit(1.0, {"chunk_id": "m::p0087::c00", "doc_id": "m", "pagina_inicio": 87, "modelos": ["PowerFlex 700"],
                "texto": "OverVoltage 5 DC bus voltage exceeded maximum value. Extend the decel time or install "
                         "dynamic brake option. See parameter 161 [Bus Reg Mode A]."})
P188 = Hit(1.0, {"chunk_id": "m::p0188::c00", "doc_id": "m", "pagina_inicio": 188, "modelos": ["PowerFlex 700"],
                 "texto": "Control vectorial sin sensor: ajuste de flujo del motor."})
CASO = Hit(1.0, {"chunk_id": "h::caso::S-002", "doc_id": "h", "caso_id": "S-002", "sintoma": "F5 al bajar",
                 "causa": "Decel corto", "solucion": "Se llevó el parámetro 142 a 12 s", "texto": "..."})

RESPUESTA = """\
# Qué indica
El código F5 OverVoltage indica tensión del bus DC excesiva [m, p. 87].
# Acciones
- Ajustar el parámetro 161 [Bus Reg Mode A] [m, p. 87].
- Ajustar el parámetro 146 a 30 s [m, p. 87].
- Extender el tiempo de desaceleración [m, p. 188].
- En un caso similar se llevó el parámetro 142 a 12 s [historial, caso S-002].
- Cambiar la placa [m, p. 999].
"""


def test_terminos_clave():
    assert terminos_clave("El F-12 HW OverCurrent en el PowerFlex 700 [m, p. 3]", {"PowerFlex 700"}) == ["F12", "OverCurrent"]
    assert terminos_clave("Parámetro 140 [Accel Time 1] a 10 s [m, p. 3]") == ["140", "10", "Accel Time 1"]
    assert terminos_clave("Revisar el caso S-014 del pozo SIM-101 (2025-03-04) [historial, caso S-014]") == []
    assert terminos_clave("Verificar el cableado [m, p. 3]") == []


def test_separar_afirmaciones_ignora_titulos_y_lineas_sin_cita():
    afirmaciones = separar_afirmaciones(RESPUESTA + "\nTexto sin cita.\n")
    assert len(afirmaciones) == 6
    assert afirmaciones[0][0].startswith("El código F5")


def test_evaluar_fidelidad_lexico():
    f = evaluar_fidelidad(RESPUESTA, [P87, P188, CASO])
    v = [a["veredicto"] for a in f["afirmaciones"]]
    assert v == ["respaldada", "respaldada", "no_respaldada", "no_verificable", "respaldada", "cita_invalida"]
    assert f["afirmaciones"][2]["faltantes"] == ["146", "30"]
    assert f["conteo"]["respaldada"] == 3
    assert f["tasa_respaldada"] == round(3 / 5, 3)
    assert resumen_fidelidad(f).startswith("3/6 respaldadas")


class Juez:
    nombre, simulado = "juez", False

    def __init__(self, veredicto):
        self.veredicto, self.llamadas = veredicto, []

    def generar_json(self, system, user, schema):
        assert schema is SCHEMA_JUEZ
        self.llamadas.append(user)
        return {"veredicto": self.veredicto, "motivo": "x"}


def test_juez_llm_decide_lo_no_verificable_sin_pisar_al_lexico():
    juez = Juez("respaldada")
    f = evaluar_fidelidad(RESPUESTA, [P87, P188, CASO], llm=juez)
    v = [a["veredicto"] for a in f["afirmaciones"]]
    # la inventada léxicamente no pasa a "respaldada"; la de cita inválida no se juzga
    assert v == ["respaldada", "respaldada", "parcial", "respaldada", "respaldada", "cita_invalida"]
    assert len(juez.llamadas) == 5 and "Control vectorial" in juez.llamadas[3]

    f = evaluar_fidelidad(RESPUESTA, [P87, P188, CASO], llm=Juez("no_respaldada"))
    assert f["afirmaciones"][3]["veredicto"] == "no_respaldada" and f["afirmaciones"][3]["metodo"] == "llm"


def test_juez_que_falla_deja_el_veredicto_lexico():
    class Roto(Juez):
        def generar_json(self, system, user, schema):
            raise TimeoutError("lento")

    f = evaluar_fidelidad(RESPUESTA, [P87], llm=Roto(None))
    assert f["afirmaciones"][0]["veredicto"] == "respaldada"
    assert f["afirmaciones"][2]["veredicto"] == "no_respaldada"
    assert "juez LLM falló" in f["afirmaciones"][2]["motivo"]


def test_propuesta_descarta_verificaciones_con_datos_inventados():
    p = validar_propuesta({"verificaciones": [
        {"accion": "Revisar parámetro 161 [Bus Reg Mode A]", "cita": "[m, p. 87]"},
        {"accion": "Poner el parámetro 146 en 30 s", "cita": "[m, p. 87]"},
        {"accion": "Verificar el cableado", "cita": "[m, p. 188]"},
    ]}, [P87, P188], [])
    assert [v["accion"] for v in p["verificaciones"]] == ["Revisar parámetro 161 [Bus Reg Mode A]", "Verificar el cableado"]
    assert "146" in p["descartadas"][0]["motivo"]


def test_corrige_cita_corrida_a_la_pagina_que_tiene_los_datos():
    respuesta = ("- Revisar el parámetro 161 [Bus Reg Mode A] [m, p. 188].\n"
                 "- OverVoltage: extender decel [m, p. 326].\n"          # p. 326 no se recuperó
                 "- El F5 es grave [m, p. 188].\n"                       # un solo término: no se corrige
                 "- Se llevó el parámetro 161 a 12 s [historial, caso S-002].\n")  # caso ↔ página: no se cruza
    f = evaluar_fidelidad(respuesta, [P87, P188, CASO])
    v = [(a["veredicto"], a["citas"]) for a in f["afirmaciones"]]
    assert v[0] == ("cita_corregida", ["[m, p. 87]"]) and f["afirmaciones"][0]["citas_originales"] == ["[m, p. 188]"]
    assert v[1][0] == "cita_invalida"  # "OverVoltage" solo: 1 término
    assert v[2][0] == "no_respaldada"
    assert v[3][0] == "parcial"  # 12 s está en el caso; 161 no
    assert f["conteo"]["cita_corregida"] == 1
    assert f["tasa_tras_correccion"] > f["tasa_respaldada"]

    nueva, cambios = corregir_citas(respuesta, f)
    assert "Revisar el parámetro 161 [Bus Reg Mode A] [m, p. 87]." in nueva
    assert "[Bus Reg Mode A]" in nueva  # no toca corchetes que no son citas
    assert "El F5 es grave [m, p. 188]" in nueva
    assert cambios == ["[m, p. 188] → [m, p. 87]"]


def test_corrige_cita_invalida_con_varios_terminos():
    f = evaluar_fidelidad("OverVoltage 5: ver parámetro 161 [m, p. 326].", [P87, P188])
    a = f["afirmaciones"][0]
    assert a["veredicto"] == "cita_corregida" and a["citas"] == ["[m, p. 87]"]
    assert corregir_citas("OverVoltage 5: ver parámetro 161 [m, p. 326].", f)[0].endswith("[m, p. 87].")


def test_no_corrige_si_mezcla_cita_de_manual_y_de_caso():
    f = evaluar_fidelidad("OverVoltage 5: ver parámetro 161 [m, p. 188; historial, caso S-002].", [P87, P188, CASO])
    assert f["afirmaciones"][0]["veredicto"] != "cita_corregida"
