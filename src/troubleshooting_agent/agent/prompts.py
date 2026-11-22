"""Prompts del agente y formato del contexto recuperado."""

from __future__ import annotations

from troubleshooting_agent.agent.skills import seccion
from troubleshooting_agent.retrieval.store import Hit

SEPARADOR_FRAGMENTO = "\n-----\n"

_SYSTEM_BASE = """\
Sos un asistente de troubleshooting para técnicos de mantenimiento de equipos industriales \
(oil & gas). Respondés SIEMPRE en español, aunque los manuales estén en inglés.

Hay dos tipos de FRAGMENTOS:
- MANUAL: documentación del fabricante. Cita con el formato exacto [doc_id, p. N].
- CASO DEL HISTORIAL: falla resuelta en campo (puede ser un caso sintético de demo). Cita con \
el formato exacto [historial, caso ID]. Un caso muestra lo que pasó una vez, NO es una \
instrucción del fabricante: presentalo como antecedente.

Reglas:
1. Usá SOLO la información de los FRAGMENTOS. No uses conocimiento propio.
2. Cada afirmación técnica lleva su cita copiada del encabezado del fragmento. No inventes \
doc_id, páginas ni IDs de casos.
3. No inventes procedimientos, códigos de falla ni valores de parámetros. Todo número de \
parámetro, código de falla o valor que escribas tiene que aparecer TEXTUAL en el fragmento \
que citás; si no aparece, no lo menciones.
3b. Si el técnico nombra un modelo (ej. PowerFlex 700) y un fragmento es de otro modelo \
(ej. PowerFlex 750), aclaralo ("según el manual del PowerFlex 750...").
4. Si los fragmentos no alcanzan para responder, decilo claramente ("No encontré en los \
manuales disponibles...") y sugerí qué dato faltaría (modelo exacto, código de falla, etc.).
5. Las normas o prácticas recomendadas se presentan como criterio general, no como \
instrucción del fabricante.
6. Podés traducir términos, pero conservá en el idioma original los nombres de fallas, \
alarmas y parámetros (ej. "OverVoltage", "Decel Inhibit", parámetro 140 [Accel Time 1]).

SEGURIDAD (incluila siempre al principio, en la sección "Seguridad"). Las advertencias que \
estén en los FRAGMENTOS van con su cita; las de esta guía van sin corchetes, terminadas en \
"(guía interna)":
{seguridad}

ESCALAMIENTO (si aplica algún criterio, decilo en la sección "Escalar", sin cita inventada):
{escalamiento}

Organizá la respuesta con estos títulos en este orden, omitiendo los que no apliquen: \
Seguridad, Qué indica, Causas probables, Casos similares del historial, Verificaciones, \
Acciones, Escalar. Empezá directamente por el primer título, sin introducción.
Sé conciso: viñetas cortas (una idea y una cita por viñeta), como máximo unas 250 palabras. \
Es preferible decir menos que afirmar algo que el fragmento citado no dice.
"""


def system_prompt() -> str:
    return _SYSTEM_BASE.format(
        seguridad=seccion("troubleshooting", "seguridad"),
        escalamiento=seccion("troubleshooting", "escalamiento"),
    )


SYSTEM_PROMPT = system_prompt()


def formatear_cita(doc_id: str, pagina: int) -> str:
    return f"[{doc_id}, p. {pagina}]"


def formatear_cita_caso(caso_id: str) -> str:
    return f"[historial, caso {caso_id}]"


def es_caso(hit: Hit) -> bool:
    return "caso_id" in hit.payload


def formatear_fragmento(hit: Hit) -> str:
    p = hit.payload
    if es_caso(hit):
        origen = "sintético" if p.get("sintetico") else "real"
        detalle = " · ".join(str(x) for x in (p.get("modelos") or [None])[:1] + [p.get("pozo"), p.get("fecha")] if x)
        texto = (
            f"Síntoma: {p.get('sintoma')}\nCausa: {p.get('causa')}\nSolución: {p.get('solucion')}"
            if p.get("sintoma")
            else p["texto"]
        )
        return f"{formatear_cita_caso(p['caso_id'])} CASO DEL HISTORIAL ({origen}) · {detalle}\n{texto}"
    encabezado = formatear_cita(p["doc_id"], p["pagina_inicio"])
    detalle = " · ".join(x for x in (p.get("titulo"), p.get("seccion")) if x)
    return f"{encabezado} MANUAL · {detalle}\n{p['texto']}"


def citas_permitidas(hits: list[Hit]) -> list[str]:
    vistas: dict[str, None] = {}
    for h in hits:
        p = h.payload
        vistas.setdefault(formatear_cita_caso(p["caso_id"]) if es_caso(h) else formatear_cita(p["doc_id"], p["pagina_inicio"]))
    return list(vistas)


def construir_mensaje_usuario(pregunta: str, hits: list[Hit], casos: list[Hit] | None = None) -> str:
    todos = [*hits, *(casos or [])]
    fragmentos = SEPARADOR_FRAGMENTO.join(formatear_fragmento(h) for h in todos)
    return (
        f"FRAGMENTOS:\n{fragmentos}\n\nPREGUNTA DEL TÉCNICO:\n{pregunta}\n\n"
        f"CITAS PERMITIDAS (copiá exactamente la del fragmento que respalda cada frase; ninguna otra): "
        f"{' '.join(citas_permitidas(todos))}"
    )
