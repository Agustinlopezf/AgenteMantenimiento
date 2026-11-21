"""Identificación determinística del equipo a partir del texto del técnico.

Usa solo el catálogo (taxonomía + `modelos` / `fabricante` de los documentos), nunca
nombres de archivo. No llama al LLM: es barato, testeable y alimenta al router.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from troubleshooting_agent.catalog import Doc, documentos_a_indexar

_CODIGO_FALLA = re.compile(r"\b[Ff]\s?-?\s?(\d{1,3})\b|\b(?:falla|fallo|fault)\s*(?:n[°º.]?\s*)?(\d{1,3})\b", re.IGNORECASE)


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return sin_tildes.lower()


def _patron(frase: str) -> re.Pattern[str]:
    """Frase → regex con bordes de palabra; espacios/guiones internos opcionales."""
    partes = [re.escape(p) for p in re.split(r"[\s\-]+", _normalizar(frase)) if p]
    return re.compile(r"(?<![\w])" + r"[\s\-]*".join(partes) + r"(?![\w])")


def _alias_modelo(modelo: str) -> list[str]:
    alias = [modelo]
    m = re.match(r"(?i)powerflex\s*(\w+)$", modelo)
    if m:
        alias += [f"PF {m[1]}", f"PF{m[1]}"]
    ultimo = modelo.split()[-1]
    if ultimo != modelo and re.search(r"[A-Za-z]", ultimo) and re.search(r"\d", ultimo):
        alias.append(ultimo)  # "FLUXUS F532WD" → "F532WD"
    return alias


@dataclass
class Equipo:
    clase_equipo: str | None = None
    clases_candidatas: list[str] = field(default_factory=list)
    fabricante: str | None = None
    modelo: str | None = None
    codigo_falla: str | None = None
    faltantes: list[str] = field(default_factory=list)
    en_corpus: bool = False  # hay documentación indexada para la clase

    def como_dict(self) -> dict[str, Any]:
        return asdict(self)

    def resumen(self) -> str:
        partes = [
            f"clase={self.clase_equipo or '¿?'}",
            f"modelo={self.modelo or '¿?'}",
            f"fabricante={self.fabricante or '¿?'}",
            f"código={self.codigo_falla or '-'}",
        ]
        if len(self.clases_candidatas) > 1:
            partes.append("candidatas=" + "/".join(self.clases_candidatas))
        return ", ".join(partes)


class IdentificadorEquipo:
    def __init__(self, taxonomia: dict[str, Any], documentos: list[Doc]):
        self._sinonimos: list[tuple[re.Pattern[str], str]] = []
        for clase, info in (taxonomia.get("clase_equipo") or {}).items():
            for frase in [clase.replace("_", " "), *(info.get("sinonimos") or [])]:
                self._sinonimos.append((_patron(frase), clase))

        # modelo → (clase, fabricante); con docs del corpus actual
        self._modelos: list[tuple[re.Pattern[str], str, str, str]] = []
        vistos: set[str] = set()
        self.modelos_por_clase: dict[str, set[str]] = {}
        for doc in documentos:
            if doc.get("tipo_documento") == "historial_fallas":
                continue  # sus `modelos` mezclan clases; cada caso trae la suya
            for modelo in doc.get("modelos") or []:
                self.modelos_por_clase.setdefault(doc["clase_equipo"], set()).add(modelo)
                if modelo in vistos:
                    continue
                vistos.add(modelo)
                for alias in _alias_modelo(modelo):
                    self._modelos.append((_patron(alias), modelo, doc["clase_equipo"], doc.get("fabricante") or ""))
        # Familia como alias ("FLUXUS" → FLUXUS F532WD) solo si identifica un único modelo.
        familias: dict[str, list[tuple[str, str, str]]] = {}
        for _, modelo, clase, fabricante in self._modelos:
            if " " in modelo:
                familias.setdefault(modelo.split()[0], [])
                if (modelo, clase, fabricante) not in familias[modelo.split()[0]]:
                    familias[modelo.split()[0]].append((modelo, clase, fabricante))
        for familia, modelos in familias.items():
            if len(modelos) == 1:
                self._modelos.append((_patron(familia), *modelos[0]))
        # alias más largos primero: "PowerFlex 700" antes que "PowerFlex 70"
        self._modelos.sort(key=lambda t: -len(t[0].pattern))
        self.clases_en_corpus = sorted(self.modelos_por_clase)

    @classmethod
    def desde_catalogo(cls, catalog: dict[str, Any], corpus: str) -> IdentificadorEquipo:
        return cls(catalog.get("taxonomia") or {}, documentos_a_indexar(catalog, corpus))

    def identificar(self, texto: str) -> Equipo:
        norm = _normalizar(texto)
        eq = Equipo()

        for patron, modelo, clase, fabricante in self._modelos:
            if patron.search(norm):
                eq.modelo, eq.clase_equipo, eq.fabricante = modelo, clase, fabricante or None
                break

        candidatas = sorted({clase for patron, clase in self._sinonimos if patron.search(norm)})
        eq.clases_candidatas = candidatas
        if eq.clase_equipo is None and len(candidatas) == 1:
            eq.clase_equipo = candidatas[0]
        if eq.clase_equipo and eq.clase_equipo not in eq.clases_candidatas:
            eq.clases_candidatas = sorted({*candidatas, eq.clase_equipo})

        m = _CODIGO_FALLA.search(texto)
        if m:
            eq.codigo_falla = f"F{int(m[1] or m[2])}"

        if eq.clase_equipo is None:
            eq.faltantes.append("equipo" if not candidatas else "equipo_ambiguo")
        elif eq.modelo is None and len(self.modelos_por_clase.get(eq.clase_equipo, ())) > 1:
            eq.faltantes.append("modelo")
        eq.en_corpus = eq.clase_equipo in self.modelos_por_clase
        return eq
