"""Descarga a data/raw/ los manuales del catálogo marcados como distribucion = "publico".

Solo usa la biblioteca estándar. Uso:

    uv run python scripts/descargar_manuales_publicos.py            # descarga lo que falte
    uv run python scripts/descargar_manuales_publicos.py --dry-run  # muestra qué haría
    uv run python scripts/descargar_manuales_publicos.py --force    # vuelve a descargar todo

Cada archivo se guarda con el nombre del campo `archivo` del catálogo, así la ingesta
lo encuentra igual que en el corpus completo. Si el sha256 no coincide con el del
catálogo, avisa (el fabricante puede haber publicado otra revisión) pero no falla.

Algunos sitios (Rockwell) rechazan las descargas automatizadas (HTTP 403). En ese caso
el script imprime el link: bajá el PDF con el navegador y dejalo en data/raw/ con el
nombre que se baja o con el del catálogo; al volver a correr el script lo reconoce, lo
renombra si hace falta y verifica el sha256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATALOGO = ROOT / "data" / "catalog" / "catalogo_documentos.json"
DESTINO = ROOT / "data" / "raw"
USER_AGENT = "troubleshooting-agent-itba/0.1 (descarga de manuales publicos)"
TIMEOUT_S = 60


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for bloque in iter(lambda: f.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def descargar(url: str, destino: Path) -> None:
    tmp = destino.with_suffix(destino.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp, tmp.open("wb") as f:
        while bloque := resp.read(1 << 20):
            f.write(bloque)
    with tmp.open("rb") as f:
        if f.read(5) != b"%PDF-":
            tmp.unlink()
            raise ValueError("la respuesta no es un PDF (¿página de login o redirección?)")
    tmp.replace(destino)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--catalogo", type=Path, default=CATALOGO)
    ap.add_argument("--destino", type=Path, default=DESTINO)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    catalogo = json.loads(args.catalogo.read_text(encoding="utf-8"))
    # solo documentos con archivo propio (el historial sintético vive en data/catalog/)
    publicos = [d for d in catalogo["documentos"] if d.get("distribucion") == "publico" and d.get("archivo")]
    args.destino.mkdir(parents=True, exist_ok=True)

    errores = 0
    manuales: list[str] = []
    for doc in publicos:
        fuente = doc.get("fuente_publica") or {}
        url, hash_esperado = fuente.get("url"), fuente.get("sha256")
        destino = args.destino / doc["archivo"]
        etiqueta = f"[{doc['doc_id']}]"

        if not url:
            print(f"{etiqueta} ERROR: marcado como público pero sin fuente_publica.url")
            errores += 1
            continue
        bajado = args.destino / url.rsplit("/", 1)[-1]  # nombre con el que lo guarda el navegador
        if not destino.exists() and bajado != destino and bajado.is_file():
            bajado.rename(destino)
            print(f"{etiqueta} {bajado.name} → {destino.name} (nombre del catálogo)")
        if destino.exists() and not args.force:
            obtenido = sha256(destino)
            estado = "OK" if not hash_esperado or obtenido == hash_esperado else \
                "AVISO: sha256 distinto al del catálogo (posible nueva revisión)"
            print(f"{etiqueta} ya existe: {destino.name} · {estado}")
            continue
        if args.dry_run:
            print(f"{etiqueta} descargaría {url} -> {destino.name}")
            continue

        try:
            print(f"{etiqueta} descargando {url}")
            descargar(url, destino)
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            print(f"{etiqueta} ERROR: {e}")
            manuales.append(f"  {url}\n    → guardar en {args.destino}/ como {destino.name} (o con el nombre original)")
            errores += 1
            continue

        obtenido = sha256(destino)
        if hash_esperado and obtenido != hash_esperado:
            print(f"{etiqueta} AVISO: sha256 distinto al del catálogo (posible nueva revisión). "
                  f"Revisar rangos de 'secciones'. sha256={obtenido}")
        else:
            print(f"{etiqueta} OK ({destino.stat().st_size / 1e6:.1f} MB)")

    print(f"\n{len(publicos)} documentos públicos con archivo en el catálogo, {errores} con error.")
    if manuales:
        print("\nNo se pudieron descargar automáticamente (el sitio rechaza clientes que no son un navegador\n"
              "o el link cambió). Bajalos con el navegador y volvé a correr este script para verificarlos:")
        print("\n".join(manuales))
    return 1 if errores else 0


if __name__ == "__main__":
    sys.exit(main())
