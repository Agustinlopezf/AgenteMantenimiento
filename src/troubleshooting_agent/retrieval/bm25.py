"""BM25 (Okapi) en memoria sobre los payloads indexados.

Complementa al retriever denso en lo que los embeddings hacen mal: códigos de falla,
números de parámetro y nombres exactos ("F5", "OverVoltage", "P461"). No cruza
idiomas: por eso el router incluye en la consulta el nombre de la falla tal como
aparece en el manual.

Tokenizador: minúsculas, sin tildes, alfanumérico. Normaliza códigos de falla
("F-12", "F 12" → "f12") y emite además el número solo ("12"), porque las tablas de
fallas de los manuales listan "OverVoltage 5", no "F5".
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from typing import Any

from troubleshooting_agent.retrieval.store import Filtros, Hit, cumple_filtros

_TOKEN = re.compile(r"[a-z0-9]+")
_CODIGO = re.compile(r"\bf\s*-?\s*(\d{1,4})\b")

STOPWORDS = frozenset(
    """
    a al ante con de del desde el en entre es esta este hay la las lo los para por que se sin
    su sus un una uno y o u me mi muestra tira da cuando como cual qué que no si ya
    the of and or to in on at for is are be by with from as an it this that not when
    """.split()
)


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))


def tokenizar(texto: str) -> list[str]:
    texto = _sin_tildes(texto.lower())
    tokens: list[str] = []
    for m in _CODIGO.finditer(texto):
        tokens += [f"f{m[1]}", m[1]]
    texto = _CODIGO.sub(" ", texto)
    tokens += [t for t in _TOKEN.findall(texto) if t not in STOPWORDS and (len(t) > 1 or t.isdigit())]
    return tokens


class BM25:
    def __init__(self, payloads: list[dict[str, Any]], k1: float = 1.5, b: float = 0.75):
        self.payloads = payloads
        self.k1, self.b = k1, b
        self._tf: list[Counter[str]] = [Counter(tokenizar(self._texto(p))) for p in payloads]
        self._largo = [sum(tf.values()) for tf in self._tf]
        self._promedio = (sum(self._largo) / len(self._largo)) if self._largo else 0.0
        df: Counter[str] = Counter()
        self._postings: dict[str, list[int]] = {}
        for i, tf in enumerate(self._tf):
            for termino in tf:
                df[termino] += 1
                self._postings.setdefault(termino, []).append(i)
        n = len(payloads)
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @staticmethod
    def _texto(p: dict[str, Any]) -> str:
        # el título de sección ayuda (ej. "Troubleshooting", "Localización de problemas")
        return " ".join(str(x) for x in (p.get("seccion"), p.get("texto")) if x)

    def __len__(self) -> int:
        return len(self.payloads)

    def buscar(self, consulta: str, k: int, filtros: Filtros | None = None) -> list[Hit]:
        terminos = set(tokenizar(consulta))
        scores: dict[int, float] = {}
        for t in terminos:
            idf = self._idf.get(t)
            if idf is None:
                continue
            for i in self._postings[t]:
                f = self._tf[i][t]
                norma = f + self.k1 * (1 - self.b + self.b * self._largo[i] / (self._promedio or 1))
                scores[i] = scores.get(i, 0.0) + idf * f * (self.k1 + 1) / norma
        candidatos = sorted(scores.items(), key=lambda kv: -kv[1])
        hits: list[Hit] = []
        for i, s in candidatos:
            if cumple_filtros(self.payloads[i], filtros):
                hits.append(Hit(score=s, payload=self.payloads[i]))
                if len(hits) == k:
                    break
        return hits
