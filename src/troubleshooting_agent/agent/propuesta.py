"""Propuesta de intervención (lo que el técnico responsable aprueba) y orden de trabajo simulada.

La propuesta se arma DESPUÉS de la respuesta, a partir de la misma evidencia:
- con LLM: salida JSON (`SCHEMA_PROPUESTA`), cada verificación con su cita;
- sin LLM (simulado o si el JSON falla): reglas sobre los fragmentos recuperados.

Toda verificación cuya cita no esté entre los fragmentos recuperados, o cuyos términos
clave (códigos, parámetros, valores) no aparezcan en la fuente citada, se descarta
(`validar_propuesta`, ver fidelidad.py). Si no queda ninguna, no hay nada que aprobar.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from troubleshooting_agent.agent.citas import extraer_citas
from troubleshooting_agent.agent.fidelidad import chequear_lexico, textos_por_cita
from troubleshooting_agent.agent.llm import LLM
from troubleshooting_agent.agent.prompts import es_caso, formatear_cita, formatear_cita_caso, formatear_fragmento
from troubleshooting_agent.agent.skills import seccion
from troubleshooting_agent.retrieval.store import Hit

PRIORIDADES = ("baja", "media", "alta")
DECISIONES = ("aprobar", "modificar", "rechazar")
MAX_MODIFICACIONES = 2

SCHEMA_PROPUESTA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "resumen": {"type": "string"},
        "verificaciones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"accion": {"type": "string"}, "cita": {"type": "string"}},
                "required": ["accion", "cita"],
            },
        },
        "intervencion": {"type": "string"},
        "seguridad": {"type": "array", "items": {"type": "string"}},
        "escalar": {"type": "boolean"},
        "motivo_escalamiento": {"type": "string"},
        "prioridad": {"type": "string", "enum": list(PRIORIDADES)},
    },
    "required": ["resumen", "verificaciones", "intervencion", "seguridad", "escalar", "prioridad"],
}

SYSTEM_PROPUESTA = """\
Armás la PROPUESTA DE INTERVENCIÓN que un técnico responsable va a aprobar antes de ejecutar. \
Devolvés solo JSON, en español.

- "verificaciones": pasos concretos, ordenados de la menos a la más invasiva. Cada uno con \
"cita" copiada EXACTA del encabezado del fragmento que lo respalda ([doc_id, p. N] o \
[historial, caso ID]). Solo pasos que estén en los fragmentos. Máximo 6.
- "intervencion": la acción correctiva propuesta si las verificaciones confirman la causa (una o dos oraciones).
- "seguridad": medidas de seguridad previas (LOTO, descarga del bus DC, despresurizar…).
- "escalar": true si aplica algún criterio de escalamiento; explicalo en "motivo_escalamiento".
- "prioridad": alta si hay equipo parado o riesgo; media si opera degradado; baja si no.

Criterios de escalamiento:
{escalamiento}
"""


def _fragmentos(hits: list[Hit], casos: list[Hit]) -> str:
    return "\n-----\n".join(formatear_fragmento(h) for h in [*hits, *casos])


def mensaje_propuesta(texto_tecnico: str, equipo: str, respuesta: str, hits: list[Hit], casos: list[Hit],
                      previa: dict[str, Any] | None = None, indicaciones: list[str] | None = None) -> str:
    partes = [
        f"FRAGMENTOS:\n{_fragmentos(hits, casos)}",
        f"CONSULTA DEL TÉCNICO:\n{texto_tecnico}",
        f"EQUIPO: {equipo}",
        f"DIAGNÓSTICO YA ENTREGADO AL TÉCNICO:\n{respuesta}",
    ]
    if previa is not None and indicaciones:
        partes.append("PROPUESTA ANTERIOR:\n" + json.dumps(_sin_meta(previa), ensure_ascii=False, indent=1))
        partes.append("EL RESPONSABLE PIDIÓ ESTOS CAMBIOS (aplicalos):\n" + "\n".join(f"- {i}" for i in indicaciones))
    return "\n\n".join(partes)


def _sin_meta(p: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in p.items() if k not in ("origen", "descartadas", "indicaciones_responsable", "version")}


def _cita_de(hit: Hit) -> str:
    p = hit.payload
    return formatear_cita_caso(p["caso_id"]) if es_caso(hit) else formatear_cita(p["doc_id"], p["pagina_inicio"])


def propuesta_reglas(hits: list[Hit], casos: list[Hit], indicaciones: list[str] | None = None) -> dict[str, Any]:
    """Propuesta determinística (modo simulado): revisar las fuentes recuperadas en orden."""
    verificaciones = [
        {"accion": f"Aplicar la solución del caso similar: {c.payload.get('solucion')}", "cita": _cita_de(c)}
        for c in casos[:2] if c.payload.get("solucion")
    ]
    verificaciones += [
        {"accion": f"Revisar en el manual: {h.payload.get('seccion') or h.payload.get('titulo')}", "cita": _cita_de(h)}
        for h in hits[:3]
    ]
    verificaciones += [{"accion": f"Indicación del responsable: {i}", "cita": "(responsable)"} for i in indicaciones or []]
    return {
        "resumen": "Propuesta armada sin LLM (modo simulado): verificar las fuentes recuperadas.",
        "verificaciones": verificaciones,
        "intervencion": "Definir la intervención según lo que indiquen las fuentes revisadas.",
        "seguridad": _vinetas(seccion("troubleshooting", "seguridad"))[:2],
        "escalar": False,
        "motivo_escalamiento": "",
        "prioridad": "media",
    }


def _vinetas(texto: str) -> list[str]:
    """Viñetas "- ..." de una sección markdown, uniendo las líneas de continuación."""
    vinetas: list[str] = []
    for linea in texto.splitlines():
        if linea.strip().startswith("- "):
            vinetas.append(linea.strip()[2:])
        elif vinetas and linea.strip():
            vinetas[-1] += " " + linea.strip()
    return vinetas


def validar_propuesta(p: dict[str, Any], hits: list[Hit], casos: list[Hit]) -> dict[str, Any]:
    """Normaliza campos y descarta verificaciones sin cita válida (las indicaciones del responsable se conservan)."""
    validas, descartadas = [], []
    fuentes = textos_por_cita([*hits, *casos])
    modelos = {m for h in [*hits, *casos] for m in (h.payload.get("modelos") or [])}
    for v in p.get("verificaciones") or []:
        accion, cita = str(v.get("accion", "")).strip(), str(v.get("cita", "")).strip()
        if not accion:
            continue
        if cita == "(responsable)":
            validas.append({"accion": accion, "cita": cita})
            continue
        a = chequear_lexico(f"{accion} {cita}", extraer_citas(cita), fuentes, modelos)
        if a.veredicto in ("cita_invalida", "no_respaldada"):
            motivo = "cita no recuperada" if a.veredicto == "cita_invalida" else f"no está en la fuente: {', '.join(a.faltantes)}"
            descartadas.append({"accion": accion, "cita": cita, "motivo": motivo})
        else:
            validas.append({"accion": accion, "cita": cita})
    prioridad = str(p.get("prioridad", "media")).lower()
    return {
        "resumen": str(p.get("resumen", "")).strip(),
        "verificaciones": validas,
        "intervencion": str(p.get("intervencion", "")).strip(),
        "seguridad": [str(s).strip() for s in p.get("seguridad") or [] if str(s).strip()],
        "escalar": bool(p.get("escalar")),
        "motivo_escalamiento": str(p.get("motivo_escalamiento") or "").strip(),
        "prioridad": prioridad if prioridad in PRIORIDADES else "media",
        "descartadas": descartadas,
    }


def generar_propuesta(llm: LLM, texto_tecnico: str, equipo: str, respuesta: str, hits: list[Hit],
                      casos: list[Hit], previa: dict[str, Any] | None = None,
                      indicaciones: list[str] | None = None) -> dict[str, Any]:
    origen, nota = "reglas", None
    if llm.simulado:
        bruta = propuesta_reglas(hits, casos, indicaciones)
    else:
        try:
            system = SYSTEM_PROPUESTA.format(escalamiento=seccion("troubleshooting", "escalamiento"))
            bruta = llm.generar_json(system, mensaje_propuesta(texto_tecnico, equipo, respuesta, hits, casos,
                                                               previa, indicaciones), SCHEMA_PROPUESTA)
            origen = "llm"
        except Exception as e:  # JSON inválido, Ollama caído…
            bruta, nota = propuesta_reglas(hits, casos, indicaciones), f"{type(e).__name__}: {e}"
    p = validar_propuesta(bruta, hits, casos)
    p["origen"] = origen
    p["indicaciones_responsable"] = list(indicaciones or [])
    if nota:
        p["nota"] = f"La propuesta del LLM falló ({nota}); se armó con reglas."
    return p


def normalizar_aprobacion(valor: Any) -> dict[str, str]:
    """Acepta {"decision", "comentario", "responsable"} o un texto ("aprobar", "r: motivo"…)."""
    if isinstance(valor, dict):
        decision = str(valor.get("decision", "")).strip().lower()
        comentario = str(valor.get("comentario", "") or "").strip()
        responsable = str(valor.get("responsable", "") or "").strip()
    else:
        texto = str(valor or "").strip()
        decision, _, comentario = texto.partition(":")
        decision, comentario, responsable = decision.strip().lower(), comentario.strip(), ""
    alias = {"a": "aprobar", "aprobado": "aprobar", "m": "modificar", "r": "rechazar", "rechazado": "rechazar"}
    decision = alias.get(decision, decision)
    if decision not in DECISIONES:
        decision = "invalida"
    return {"decision": decision, "comentario": comentario, "responsable": responsable or "(sin nombre)"}


# ── formato y orden de trabajo ──────────────────────────────


def formatear_propuesta(p: dict[str, Any]) -> str:
    lineas = [f"Resumen: {p.get('resumen') or '-'}", f"Prioridad: {p.get('prioridad')}", "Seguridad previa:"]
    lineas += [f"  - {s}" for s in p.get("seguridad") or ["(sin medidas específicas)"]]
    lineas.append("Verificaciones:")
    lineas += [f"  {i}. {v['accion']} {v['cita']}" for i, v in enumerate(p.get("verificaciones") or [], 1)]
    lineas.append(f"Intervención: {p.get('intervencion') or '-'}")
    if p.get("escalar"):
        lineas.append(f"ESCALAR: {p.get('motivo_escalamiento') or 'sí'}")
    if p.get("descartadas"):
        lineas.append(f"Descartadas por falta de respaldo ({len(p['descartadas'])}):")
        lineas += [f"  ✗ {d['accion']} {d['cita']} — {d.get('motivo', '')}" for d in p["descartadas"]]
    return "\n".join(lineas)


_NO_ARCHIVO = re.compile(r"[^A-Za-z0-9_-]")


def emitir_orden(directorio: Path, thread_id: str, equipo: dict[str, Any], texto_tecnico: str,
                 propuesta: dict[str, Any], aprobacion: dict[str, str], traza: list[dict[str, Any]],
                 ahora: datetime | None = None) -> dict[str, Any]:
    """Escribe la OT simulada (.json + .md). Devuelve el registro con las rutas."""
    ahora = ahora or datetime.now()
    ot_id = f"OT-{ahora:%Y%m%d-%H%M%S}-{_NO_ARCHIVO.sub('', thread_id)[:8]}"
    orden = {
        "ot_id": ot_id,
        "simulada": True,
        "emitida": ahora.isoformat(timespec="seconds"),
        "thread_id": thread_id,
        "equipo": {k: equipo.get(k) for k in ("clase_equipo", "fabricante", "modelo", "codigo_falla")},
        "sintoma_reportado": texto_tecnico,
        "prioridad": propuesta.get("prioridad"),
        "seguridad": propuesta.get("seguridad"),
        "verificaciones": propuesta.get("verificaciones"),
        "intervencion": propuesta.get("intervencion"),
        "escalar": propuesta.get("escalar"),
        "motivo_escalamiento": propuesta.get("motivo_escalamiento"),
        "aprobada_por": aprobacion.get("responsable"),
        "comentario_aprobacion": aprobacion.get("comentario"),
        "indicaciones_responsable": propuesta.get("indicaciones_responsable"),
        "decisiones_agente": [
            {k: t.get(k) for k in ("paso", "accion", "origen", "motivo")} for t in traza if t.get("tipo") == "decision"
        ],
    }
    directorio.mkdir(parents=True, exist_ok=True)
    ruta_json, ruta_md = directorio / f"{ot_id}.json", directorio / f"{ot_id}.md"
    ruta_json.write_text(json.dumps(orden, ensure_ascii=False, indent=2), encoding="utf-8")
    ruta_md.write_text(_orden_md(orden), encoding="utf-8")
    return {"ot_id": ot_id, "json": str(ruta_json), "md": str(ruta_md)}


def _orden_md(o: dict[str, Any]) -> str:
    eq = o["equipo"]
    equipo = " · ".join(str(x) for x in (eq.get("fabricante"), eq.get("modelo") or eq.get("clase_equipo"),
                                          eq.get("codigo_falla")) if x)
    md = [
        f"# Orden de trabajo {o['ot_id']} (SIMULADA)",
        "",
        f"- **Emitida:** {o['emitida']}",
        f"- **Equipo:** {equipo or '-'}",
        f"- **Prioridad:** {o['prioridad']}",
        f"- **Aprobada por:** {o['aprobada_por']}" + (f" — {o['comentario_aprobacion']}" if o["comentario_aprobacion"] else ""),
        f"- **Diagnóstico:** `{o['thread_id']}`",
        "",
        "## Síntoma reportado",
        o["sintoma_reportado"],
        "",
        "## Seguridad previa",
        *[f"- {s}" for s in o["seguridad"] or ["-"]],
        "",
        "## Verificaciones",
        *[f"{i}. {v['accion']} {v['cita']}" for i, v in enumerate(o["verificaciones"] or [], 1)],
        "",
        "## Intervención",
        o["intervencion"] or "-",
    ]
    if o["escalar"]:
        md += ["", "## Escalar", o["motivo_escalamiento"] or "Sí"]
    return "\n".join(md) + "\n"
