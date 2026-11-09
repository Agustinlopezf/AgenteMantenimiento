"""Proveedores de LLM: Ollama (real) y simulado (sin GPU / sin Ollama)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Protocol

from troubleshooting_agent.agent.prompts import SEPARADOR_FRAGMENTO

if TYPE_CHECKING:
    from troubleshooting_agent.config import Settings


class LLM(Protocol):
    nombre: str
    simulado: bool

    def generar(self, system: str, user: str) -> str: ...


class OllamaLLM:
    simulado = False

    def __init__(self, settings: Settings, timeout_s: float = 600):
        import ollama

        self.nombre = settings.llm_model
        self._cliente = ollama.Client(host=settings.ollama_base_url, timeout=timeout_s)
        self._options = {"num_ctx": settings.llm_num_ctx, "temperature": settings.llm_temperature}
        self._think = settings.llm_think

    def generar(self, system: str, user: str) -> str:
        respuesta = self._cliente.chat(
            model=self.nombre,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            options=self._options,
            think=self._think,
        )
        return (respuesta.message.content or "").strip()


_ENCABEZADO = re.compile(r"^(\[[^\]]+\])\s*(.*)$")


class LLMSimulado:
    """No genera texto: lista los fragmentos recuperados con su cita (determinístico)."""

    nombre = "simulado"
    simulado = True

    def generar(self, system: str, user: str) -> str:
        cuerpo = user.split("FRAGMENTOS:\n", 1)[-1].split("\n\nPREGUNTA DEL TÉCNICO:", 1)[0]
        lineas = ["[MODO SIMULADO] No hay LLM activo; estos son los fragmentos más relevantes del corpus:"]
        for fragmento in cuerpo.split(SEPARADOR_FRAGMENTO):
            primera, _, texto = fragmento.partition("\n")
            m = _ENCABEZADO.match(primera.strip())
            if not m:
                continue
            extracto = " ".join(texto.split())[:240]
            lineas.append(f"- {m[1]} {m[2]}: {extracto}…")
        return "\n".join(lineas)


def _modelo_disponible(nombre: str, disponibles: list[str]) -> bool:
    if nombre in disponibles:
        return True
    return ":" not in nombre and f"{nombre}:latest" in disponibles


def crear_llm(settings: Settings) -> tuple[LLM, list[str]]:
    """Devuelve (llm, avisos). Nunca falla: si Ollama no está, cae a simulado con aviso."""
    if not settings.use_real_llm:
        return LLMSimulado(), ["USE_REAL_LLM=false: respuestas en modo simulado (sin LLM)."]
    try:
        import ollama

        cliente = ollama.Client(host=settings.ollama_base_url, timeout=5)
        disponibles = [m.model for m in cliente.list().models]
    except Exception as e:  # conexión rechazada, timeout, etc.
        return LLMSimulado(), [
            f"No se pudo conectar a Ollama en {settings.ollama_base_url} ({type(e).__name__}). "
            "Modo simulado. ¿Está corriendo `ollama serve`?"
        ]
    if not _modelo_disponible(settings.llm_model, disponibles):
        return LLMSimulado(), [
            f"El modelo {settings.llm_model!r} no está en Ollama. Modo simulado. "
            f"Bajarlo con: ollama pull {settings.llm_model}"
        ]
    return OllamaLLM(settings), []
