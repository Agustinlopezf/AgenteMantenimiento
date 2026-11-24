"""Fidelidad por afirmación: ¿la fuente citada respalda lo que dice la frase?

`citas.py` solo verifica que la página citada esté entre los fragmentos recuperados.
Acá se baja a cada afirmación (línea o viñeta con cita):

1. Chequeo léxico (siempre, determinístico): los TÉRMINOS CLAVE de la frase
   —códigos de falla, números de parámetro, valores con unidad, nombres de
   falla/parámetro en CamelCase o entre corchetes— tienen que aparecer en el texto
   de alguna de las fuentes que cita. Es justo lo que un LLM chico inventa o mezcla
   entre páginas. Si la frase no tiene términos clave, el chequeo léxico no decide
   (`no_verificable`): el manual suele estar en inglés y la respuesta en español.
2. Juez LLM (opcional, FIDELIDAD_LLM=true): decide respaldada / parcial /
   no_respaldada leyendo la frase y el texto citado. Más lento; se usa en evaluación.

3. Reparación de citas corridas (siempre): el modelo chico a veces cita la página
   equivocada (p. 326 en vez de p. 316) aunque el fragmento correcto esté recuperado.
   Si una afirmación no está respaldada (o cita una página no recuperada) pero TODOS
   sus términos clave (≥ 2) aparecen en otra fuente recuperada del mismo tipo, se
   marca `cita_corregida` con la cita nueva y `corregir_citas` reescribe la respuesta.
   La corrección se le muestra al técnico; no se oculta.

Veredictos: respaldada · cita_corregida · parcial · no_respaldada · no_verificable · cita_invalida.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from troubleshooting_agent.agent.citas import Cita, CitaAny, CitaCaso, extraer_citas
from troubleshooting_agent.retrieval.store import Hit

_CORCHETES = re.compile(r"\[[^\[\]]*\]")
_CODIGO = re.compile(r"\bF\s?-?\s?(\d{1,4})\b")
_NUMERO = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)\s?(%|v|vdc|vac|a|hz|khz|s|seg|ms|min|°c|c|kw|hp|rpm|mm|bar|psi)?\b", re.I)
_CAMEL = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-z0-9]+)+\b")  # OverVoltage, UnderVoltage, PowerFlex
_ENTRE_COMILLAS = re.compile(r"[\"“«]([^\"”»]{3,40})[\"”»]")
_IDENTIFICADOR = re.compile(r"\b[A-Z]{1,4}-\d+\b|\b\d{4}-\d{2}-\d{2}\b")  # S-014, SIM-101, fechas
_TITULO = re.compile(r"^\s*(#+\s*)?\**\s*[\wÁÉÍÓÚáéíóúñ ]{2,40}\s*:?\**\s*:?\s*$")

VEREDICTOS = ("respaldada", "cita_corregida", "parcial", "no_respaldada", "no_verificable", "cita_invalida")
MIN_TERMINOS_CORRECCION = 2  # con un solo término (p. ej. "F5") cualquier página con un "5" serviría


def _norm(texto: str) -> str:
    texto = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(texto.lower().split())


@dataclass
class Afirmacion:
    texto: str
    citas: list[str]
    terminos: list[str] = field(default_factory=list)
    faltantes: list[str] = field(default_factory=list)
    veredicto: str = "no_verificable"
    metodo: str = "lexico"
    motivo: str = ""
    citas_originales: list[str] = field(default_factory=list)  # solo si se corrigió la cita

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)


def separar_afirmaciones(respuesta: str) -> list[tuple[str, list[CitaAny]]]:
    """Líneas / viñetas con al menos una cita. Un párrafo largo se parte por oraciones."""
    salida: list[tuple[str, list[CitaAny]]] = []
    for linea in respuesta.splitlines():
        linea = linea.strip()
        if not linea or _TITULO.match(linea):
            continue
        partes = re.split(r"(?<=[.!?\]])\s+(?=[A-ZÁÉÍÓÚ¿¡])", linea) if len(linea) > 220 else [linea]
        for parte in partes:
            citas = extraer_citas(parte)
            if citas:
                salida.append((parte.strip(" -*•"), citas))
    return salida


def terminos_clave(frase: str, modelos_conocidos: set[str] | None = None) -> list[str]:
    """Términos que tienen que aparecer textuales en la fuente (se ignoran las citas)."""
    sin_citas = _CORCHETES.sub(lambda m: " " if extraer_citas(m.group(0)) else m.group(0), frase)
    sin_citas = _IDENTIFICADOR.sub(lambda m: m.group(0) if _CODIGO.fullmatch(m.group(0)) else " ", sin_citas)
    terminos: list[str] = []
    for m in _CODIGO.finditer(sin_citas):
        terminos.append(f"F{m[1]}")
    sin_codigos = _CODIGO.sub(" ", sin_citas)
    # números del nombre del modelo ("PowerFlex 700") no son afirmaciones técnicas
    for modelo in modelos_conocidos or ():
        sin_codigos = re.sub(re.escape(modelo), " ", sin_codigos, flags=re.I)
    for m in _NUMERO.finditer(sin_codigos):
        numero = m[1]
        if len(numero.replace(",", "").replace(".", "")) >= 2 or m[2]:
            terminos.append(numero)
    terminos += [m for m in _CAMEL.findall(sin_codigos) if m.lower() != "powerflex"]
    for m in re.finditer(r"\[([^\[\]]{3,40})\]", sin_citas):  # [Accel Time 1]
        if not extraer_citas(m.group(0)):
            terminos.append(m[1].strip())
    terminos += [m.strip() for m in _ENTRE_COMILLAS.findall(sin_codigos)]
    vistos: dict[str, None] = {}
    for t in terminos:
        vistos.setdefault(t, None)
    return list(vistos)


def _aparece(termino: str, texto_norm: str) -> bool:
    if re.fullmatch(r"F\d+", termino):  # "F5" aparece como "F5", "F 5" o la fila "OverVoltage 5"
        n = termino[1:]
        return bool(re.search(rf"(\bf\s?-?\s?{n}\b)|(\b{n}\b)", texto_norm))
    t = _norm(termino)
    if re.fullmatch(r"\d+(?:[.,]\d+)?", t):
        return bool(re.search(rf"(?<![\d.,]){re.escape(t)}(?![\d])", texto_norm)) or \
            bool(re.search(rf"(?<![\d.,]){re.escape(t.replace(',', '.'))}(?![\d])", texto_norm))
    return t in texto_norm


def _clave(hit: Hit) -> CitaAny:
    p = hit.payload
    return CitaCaso(str(p["caso_id"])) if "caso_id" in p else Cita(p["doc_id"], p["pagina_inicio"])


def _texto_fuente(hit: Hit) -> str:
    p = hit.payload
    partes = [p.get("texto"), p.get("sintoma"), p.get("causa"), p.get("solucion"), p.get("codigo_falla"),
              p.get("seccion"), p.get("titulo"), p.get("pozo"), p.get("fecha"), " ".join(p.get("modelos") or [])]
    return " ".join(str(x) for x in partes if x)


def textos_por_cita(hits: list[Hit]) -> dict[CitaAny, str]:
    """Una página puede tener varios chunks: se concatenan."""
    salida: dict[CitaAny, str] = {}
    for h in hits:
        k = _clave(h)
        salida[k] = (salida.get(k, "") + " " + _texto_fuente(h)).strip()
    return salida


def chequear_lexico(frase: str, citas: list[CitaAny], fuentes: dict[CitaAny, str],
                    modelos_conocidos: set[str] | None = None) -> Afirmacion:
    a = Afirmacion(frase, [str(c) for c in citas])
    textos = [fuentes[c] for c in citas if c in fuentes]
    if not textos:
        a.veredicto, a.motivo = "cita_invalida", "ninguna de las fuentes citadas fue recuperada"
        return a
    a.terminos = terminos_clave(frase, modelos_conocidos)
    if not a.terminos:
        a.motivo = "sin términos clave verificables léxicamente"
        return a
    texto = _norm(" ".join(textos))
    a.faltantes = [t for t in a.terminos if not _aparece(t, texto)]
    if not a.faltantes:
        a.veredicto = "respaldada"
    elif len(a.faltantes) < len(a.terminos):
        a.veredicto, a.motivo = "parcial", "algunos términos no están en la fuente citada"
    else:
        a.veredicto, a.motivo = "no_respaldada", "los términos clave no están en la fuente citada"
    return a


def buscar_cita_alternativa(frase: str, citas: list[CitaAny], fuentes: dict[CitaAny, str],
                            modelos_conocidos: set[str] | None = None) -> CitaAny | None:
    """Otra fuente recuperada donde están todos los términos clave de la frase.

    Solo del mismo tipo que la cita original (página de manual ↔ página, caso ↔ caso);
    prefiere el mismo documento y la página más cercana.
    """
    terminos = terminos_clave(frase, modelos_conocidos)
    if len(terminos) < MIN_TERMINOS_CORRECCION or not citas:
        return None
    original = citas[0]
    if any(type(c) is not type(original) for c in citas):
        return None  # cita manual + caso a la vez: no se reemplazan las dos por una sola fuente
    candidatas = []
    for c, texto in fuentes.items():
        if c in citas or type(c) is not type(original):
            continue
        texto_norm = _norm(texto)
        if all(_aparece(t, texto_norm) for t in terminos):
            if isinstance(c, Cita) and isinstance(original, Cita):
                orden = (c.doc_id != original.doc_id, abs(c.pagina - original.pagina))
            else:
                orden = (0, 0)
            candidatas.append((orden, str(c), c))
    return min(candidatas)[2] if candidatas else None


def corregir_citas(respuesta: str, fidelidad: dict[str, Any]) -> tuple[str, list[str]]:
    """Reescribe en la respuesta las citas de las afirmaciones `cita_corregida`.

    Devuelve (respuesta, ["[doc, p. 326] → [doc, p. 316]", ...]).
    """
    cambios: list[str] = []
    for a in fidelidad.get("afirmaciones") or []:
        if a["veredicto"] != "cita_corregida" or a["texto"] not in respuesta:
            continue
        malas = set(extraer_citas(" ".join(a["citas_originales"])))
        nueva = a["citas"][0]

        def reemplazar(m: re.Match) -> str:
            encontradas = extraer_citas(m.group(0))
            return nueva if encontradas and set(encontradas) <= malas else m.group(0)

        texto = _CORCHETES.sub(reemplazar, a["texto"])
        if texto != a["texto"]:
            respuesta = respuesta.replace(a["texto"], texto, 1)
            cambios.append(f"{', '.join(a['citas_originales'])} → {nueva}")
    return respuesta, cambios


# ── juez LLM (opcional) ─────────────────────────────────────

SCHEMA_JUEZ: dict[str, Any] = {
    "type": "object",
    "properties": {
        "veredicto": {"type": "string", "enum": ["respaldada", "parcial", "no_respaldada"]},
        "motivo": {"type": "string"},
    },
    "required": ["veredicto", "motivo"],
}

SYSTEM_JUEZ = """\
Sos un verificador estricto. Recibís una AFIRMACIÓN (en español) y el TEXTO de la fuente que cita \
(puede estar en inglés). Decidí si el texto respalda la afirmación:
- respaldada: el texto dice lo mismo (aunque esté en otro idioma o con otras palabras);
- parcial: respalda una parte, pero agrega datos que el texto no dice;
- no_respaldada: el texto no dice eso, o dice otra cosa.
No uses conocimiento propio. Devolvé solo JSON con "veredicto" y "motivo" (una oración)."""


def juzgar_llm(llm, a: Afirmacion, fuentes: dict[CitaAny, str], max_chars: int = 3000) -> Afirmacion:
    citas = [c for c in extraer_citas(" ".join(a.citas)) if c in fuentes]
    if not citas:
        return a
    texto = "\n\n".join(f"{c}\n{fuentes[c][:max_chars]}" for c in citas)
    try:
        r = llm.generar_json(SYSTEM_JUEZ, f"AFIRMACIÓN:\n{a.texto}\n\nTEXTO DE LA FUENTE:\n{texto}", SCHEMA_JUEZ)
        veredicto = str(r.get("veredicto", "")).strip()
        if veredicto in ("respaldada", "parcial", "no_respaldada"):
            # el chequeo léxico manda si detectó un término inventado
            if a.veredicto == "no_respaldada" and veredicto == "respaldada":
                veredicto = "parcial"
            a.veredicto, a.metodo, a.motivo = veredicto, "llm", str(r.get("motivo", "")).strip()
    except Exception as e:  # el juez es opcional: si falla queda el veredicto léxico
        a.motivo = (a.motivo + f" (juez LLM falló: {type(e).__name__})").strip()
    return a


# ── API ─────────────────────────────────────────────────────


def evaluar_fidelidad(respuesta: str, hits: list[Hit], llm=None, modelos_conocidos: set[str] | None = None) -> dict[str, Any]:
    """Devuelve {"afirmaciones": [...], "conteo": {veredicto: n}, "tasa_respaldada": float | None}."""
    fuentes = textos_por_cita(hits)
    modelos = modelos_conocidos if modelos_conocidos is not None else {
        m for h in hits for m in (h.payload.get("modelos") or [])}
    afirmaciones = []
    for frase, citas in separar_afirmaciones(respuesta):
        a = chequear_lexico(frase, citas, fuentes, modelos)
        if a.veredicto in ("no_respaldada", "cita_invalida") and \
                (nueva := buscar_cita_alternativa(frase, citas, fuentes, modelos)) is not None:
            a.citas_originales, a.citas = a.citas, [str(nueva)]
            a.terminos, a.faltantes = terminos_clave(frase, modelos), []
            a.veredicto = "cita_corregida"
            a.motivo = f"la fuente citada no lo dice; los términos clave están en {nueva}"
        elif llm is not None and not llm.simulado and a.veredicto != "cita_invalida":
            a = juzgar_llm(llm, a, fuentes)
        afirmaciones.append(a)
    conteo = {v: sum(a.veredicto == v for a in afirmaciones) for v in VEREDICTOS}
    decididas = sum(conteo[v] for v in ("respaldada", "cita_corregida", "parcial", "no_respaldada", "cita_invalida"))
    return {
        "afirmaciones": [a.como_dict() for a in afirmaciones],
        "conteo": conteo,
        # tal como la escribió el modelo / después de corregir las citas corridas
        "tasa_respaldada": round(conteo["respaldada"] / decididas, 3) if decididas else None,
        "tasa_tras_correccion": round((conteo["respaldada"] + conteo["cita_corregida"]) / decididas, 3)
        if decididas else None,
    }


def resumen_fidelidad(f: dict[str, Any]) -> str:
    c = f["conteo"]
    total = sum(c.values())
    if not total:
        return "sin afirmaciones con cita"
    partes = [f"{c['respaldada']}/{total} respaldadas"]
    partes += [f"{c[v]} {v.replace('_', ' ')}" for v in VEREDICTOS[1:] if c[v]]
    return " · ".join(partes)
