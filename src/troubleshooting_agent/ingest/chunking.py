"""Chunking ingenuo de tamaño fijo (caracteres) dentro de una página."""

from __future__ import annotations


def chunk_id(doc_id: str, pagina: int, n: int) -> str:
    return f"{doc_id}::p{pagina:04d}::c{n:02d}"


def chunk_texto(texto: str, size: int, overlap: int) -> list[str]:
    """Parte `texto` en trozos de hasta `size` caracteres con `overlap` de solapamiento.

    Corta en el último salto de línea o espacio antes del límite para no partir
    palabras (si no hay ninguno en la segunda mitad del trozo, corta en seco).
    """
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Se requiere size > 0 y 0 <= overlap < size")
    texto = texto.strip()
    if not texto:
        return []

    chunks: list[str] = []
    inicio = 0
    while inicio < len(texto):
        fin = min(inicio + size, len(texto))
        if fin < len(texto):
            corte = max(texto.rfind("\n", inicio, fin), texto.rfind(" ", inicio, fin))
            if corte > inicio + size // 2:
                fin = corte
        trozo = texto[inicio:fin].strip()
        if trozo:
            chunks.append(trozo)
        if fin >= len(texto):
            break
        siguiente = fin - overlap
        if siguiente <= inicio:
            # Overlap mayor que lo avanzado: seguir sin solapamiento para no estancarse.
            siguiente = fin
        else:
            # Arrancar el solapamiento en un límite de palabra.
            espacio = texto.find(" ", siguiente, fin)
            if espacio != -1:
                siguiente = espacio + 1
        inicio = siguiente
    return chunks
