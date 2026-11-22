"""Router del agente: decide la próxima acción.

El LLM elige entre `buscar_manual`, `buscar_historial`, `pedir_datos` y `responder`
con salida JSON validada. Unas guardas acotan el loop. Si el LLM es simulado o
devuelve algo inválido, decide un router de reglas determinístico.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from troubleshooting_agent.agent.equipo import Equipo
from troubleshooting_agent.agent.llm import LLM
from troubleshooting_agent.agent.skills import seccion

ACCIONES = ("buscar_manual", "buscar_historial", "pedir_datos", "responder")
TOOLS = ("buscar_manual", "buscar_historial")
MAX_PASOS = 4  # búsquedas + pedidos de datos antes de forzar la respuesta
MAX_PEDIDOS = 2

SCHEMA_DECISION: dict[str, Any] = {
    "type": "object",
    "properties": {
        "accion": {"type": "string", "enum": list(ACCIONES)},
        "motivo": {"type": "string"},
        "consulta": {"type": "string"},
        "pregunta": {"type": "string"},
    },
    "required": ["accion", "motivo"],
}

_DESCRIPCION_FALTANTES = {
    "equipo": "qué equipo es (tipo, marca y modelo)",
    "equipo_ambiguo": "qué equipo es exactamente (la descripción admite más de un tipo)",
    "modelo": "el modelo exacto del equipo",
}


@dataclass
class Decision:
    accion: str
    motivo: str
    consulta: str = ""
    pregunta: str = ""
    origen: str = "reglas"  # llm | reglas | guarda
    notas: list[str] = field(default_factory=list)

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Contexto:
    """Lo que el router necesita saber del estado (sin depender del TypedDict del grafo)."""

    texto: str
    equipo: Equipo
    consultas: list[dict[str, Any]]  # [{accion, consulta, resumen, n}]
    pedidos: int
    clases_en_corpus: list[str]

    @property
    def pasos(self) -> int:
        return len(self.consultas) + self.pedidos

    def ya_hecho(self, accion: str, consulta: str | None = None) -> bool:
        return any(
            c["accion"] == accion and (consulta is None or c["consulta"].strip().lower() == consulta.strip().lower())
            for c in self.consultas
        )


def consulta_por_defecto(ctx: Contexto) -> str:
    extra = [x for x in (ctx.equipo.modelo, ctx.equipo.codigo_falla) if x and x.lower() not in ctx.texto.lower()]
    return " ".join([ctx.texto, *extra]).strip()


def pregunta_por_defecto(ctx: Contexto) -> str:
    faltan = [_DESCRIPCION_FALTANTES[f] for f in ctx.equipo.faltantes if f in _DESCRIPCION_FALTANTES]
    if not faltan:
        return "¿Podés dar más detalles del síntoma (código o mensaje que muestra el equipo, cuándo ocurre)?"
    return "Para seguir necesito: " + "; ".join(faltan) + "."


# ── reglas ──────────────────────────────────────────────────


def decidir_reglas(ctx: Contexto) -> Decision:
    eq = ctx.equipo
    if ctx.pasos >= MAX_PASOS:
        return Decision("responder", f"Se alcanzó el máximo de {MAX_PASOS} pasos.")
    sin_equipo = eq.clase_equipo is None
    falta_modelo = "modelo" in eq.faltantes and not ctx.consultas
    if (sin_equipo or falta_modelo) and ctx.pedidos < MAX_PEDIDOS:
        return Decision("pedir_datos", "Falta identificar el equipo antes de buscar.", pregunta=pregunta_por_defecto(ctx))
    if eq.clase_equipo and not eq.en_corpus:
        return Decision("responder", f"No hay documentación indexada para la clase {eq.clase_equipo}.")
    consulta = consulta_por_defecto(ctx)
    if not ctx.ya_hecho("buscar_historial"):
        return Decision("buscar_historial", "Buscar casos similares ya resueltos.", consulta=consulta)
    if not ctx.ya_hecho("buscar_manual"):
        return Decision("buscar_manual", "Buscar la falla en el manual del fabricante.", consulta=consulta)
    return Decision("responder", "Ya se consultaron historial y manual.")


# ── LLM ─────────────────────────────────────────────────────

SYSTEM_ROUTER = """\
Sos el coordinador de un agente de troubleshooting de equipos industriales. No respondés \
al técnico: decidís la PRÓXIMA ACCIÓN y devolvés solo JSON.

Acciones posibles:
- buscar_manual: buscar en los manuales del fabricante (descripción de fallas, causas, acciones). \
"consulta" = texto a buscar; incluí modelo, código de falla y el nombre de ESA falla como \
figura en el manual (los manuales Rockwell están en inglés), además de los términos en español.
- buscar_historial: buscar casos de fallas ya resueltas en campo. "consulta" = síntoma + equipo.
- pedir_datos: preguntarle al técnico un dato que falta. "pregunta" = pregunta corta en español.
- responder: ya hay evidencia suficiente, o no hay más fuentes útiles.

Procedimiento a seguir:
{procedimiento}

Reglas: no repitas una búsqueda ya hecha con la misma consulta; no pidas datos que el técnico \
ya dio; "motivo" en una oración en español.
"""


def _mensaje_router(ctx: Contexto) -> str:
    eq = ctx.equipo
    hechas = "\n".join(f"- {c['accion']}({c['consulta']!r}) → {c['resumen']}" for c in ctx.consultas) or "- (ninguna)"
    faltantes = ", ".join(_DESCRIPCION_FALTANTES.get(f, f) for f in eq.faltantes) or "ninguno"
    return (
        f"LO QUE DIJO EL TÉCNICO:\n{ctx.texto}\n\n"
        f"EQUIPO IDENTIFICADO: {eq.resumen()} (el código de falla es opcional: no todos los equipos tienen)\n"
        f"DATOS QUE FALTAN: {faltantes}\n"
        f"CLASES CON MANUALES INDEXADOS: {', '.join(ctx.clases_en_corpus) or 'ninguna'}\n"
        f"ACCIONES YA HECHAS:\n{hechas}\n"
        f"FUENTES SIN CONSULTAR: {', '.join(t for t in TOOLS if not ctx.ya_hecho(t)) or 'ninguna'}\n"
        f"PEDIDOS DE DATOS: {ctx.pedidos}/{MAX_PEDIDOS} · PASO {ctx.pasos + 1}/{MAX_PASOS}\n\n"
        "¿Próxima acción?"
    )


def decidir_llm(llm: LLM, ctx: Contexto) -> Decision:
    """Lanza ValueError si la salida no es una decisión válida."""
    system = SYSTEM_ROUTER.format(procedimiento=seccion("troubleshooting", "procedimiento"))
    datos = llm.generar_json(system, _mensaje_router(ctx), SCHEMA_DECISION)
    accion = str(datos.get("accion", "")).strip()
    if accion not in ACCIONES:
        raise ValueError(f"acción inválida: {accion!r}")
    return Decision(
        accion=accion,
        motivo=str(datos.get("motivo") or "").strip() or "(sin motivo)",
        consulta=str(datos.get("consulta") or "").strip(),
        pregunta=str(datos.get("pregunta") or "").strip(),
        origen="llm",
    )


# ── guardas ─────────────────────────────────────────────────


def aplicar_guardas(d: Decision, ctx: Contexto) -> Decision:
    """Corrige decisiones que romperían el loop o el procedimiento; deja nota del cambio."""

    def reemplazar(motivo_guarda: str) -> Decision:
        nueva = decidir_reglas(ctx)
        nueva.origen = "guarda"
        nueva.notas = [f"{d.accion} descartada: {motivo_guarda}"]
        return nueva

    if ctx.pasos >= MAX_PASOS and d.accion != "responder":
        return Decision("responder", f"Se alcanzó el máximo de {MAX_PASOS} pasos.", origen="guarda",
                        notas=[f"{d.accion} descartada: límite de pasos"])
    if d.accion in TOOLS:
        if not d.consulta:
            d.consulta = consulta_por_defecto(ctx)
        if ctx.ya_hecho(d.accion, d.consulta):
            return reemplazar("búsqueda repetida")
    if d.accion == "pedir_datos":
        if ctx.pedidos >= MAX_PEDIDOS:
            return reemplazar(f"ya se pidieron datos {MAX_PEDIDOS} veces")
        if not d.pregunta:
            d.pregunta = pregunta_por_defecto(ctx)
    if d.accion != "responder" and ctx.equipo.clase_equipo and not ctx.equipo.en_corpus:
        return Decision("responder", f"No hay documentación indexada para la clase {ctx.equipo.clase_equipo}.",
                        origen="guarda", notas=[f"{d.accion} descartada: clase sin documentación"])
    if d.accion == "responder" and not ctx.consultas and ctx.equipo.en_corpus:
        return reemplazar("responder sin haber consultado ninguna fuente")
    return d


def decidir(llm: LLM, ctx: Contexto) -> Decision:
    if llm.simulado:
        return aplicar_guardas(decidir_reglas(ctx), ctx)
    try:
        d = decidir_llm(llm, ctx)
    except Exception as e:  # JSON inválido, Ollama caído, timeout…
        d = decidir_reglas(ctx)
        d.notas.append(f"router LLM falló ({type(e).__name__}: {e}); se usaron reglas")
    return aplicar_guardas(d, ctx)
