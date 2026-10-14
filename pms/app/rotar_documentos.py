"""Cambio de la clave de las copias de documentos (PMS_DOCS_KEY) sin perder ninguno.

Con PMS_DOCS_KEY = clave nueva y PMS_DOCS_KEY_ANTERIOR = clave antigua, el PMS lee con las dos y guarda con la nueva.
Este programa vuelve a cifrar con la nueva cada documento que aún esté con la antigua:

    python -m app.rotar_documentos            # solo cuenta (no cambia nada)
    python -m app.rotar_documentos --aplicar  # vuelve a cifrar

Cada fichero se escribe aparte y se sustituye de golpe solo si se puede leer con la clave nueva: si se corta a
medias, se vuelve a lanzar y sigue donde iba. Cuando diga «pendientes: 0», se quita PMS_DOCS_KEY_ANTERIOR.
"""
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from .config import settings
from .documentos import clave_actual


def rotar(carpeta: Path, nueva, anterior, aplicar: bool = False) -> dict:
    fn, fa = Fernet(nueva), Fernet(anterior)
    mf = MultiFernet([fn, fa])
    out = {"total": 0, "ya_nuevos": 0, "pendientes": 0, "cifrados": 0, "ilegibles": 0}
    for f in sorted(carpeta.glob("*.bin")):
        out["total"] += 1
        token = f.read_bytes()
        try:
            fn.decrypt(token)
            out["ya_nuevos"] += 1
            continue
        except InvalidToken:
            pass
        try:
            original = fa.decrypt(token)
        except InvalidToken:
            out["ilegibles"] += 1  # ni con la nueva ni con la antigua: no se toca
            continue
        if not aplicar:
            out["pendientes"] += 1
            continue
        nuevo = mf.rotate(token)
        if fn.decrypt(nuevo) != original:
            raise RuntimeError(f"{f.name}: comprobación fallida, no se ha cambiado")
        tmp = f.with_suffix(".bin.tmp")
        tmp.write_bytes(nuevo)
        os.replace(tmp, f)
        out["cifrados"] += 1
    return out


def main(argv: list[str]) -> int:
    if not settings.docs_key or not settings.docs_key_anterior:
        print("Faltan PMS_DOCS_KEY (nueva) y PMS_DOCS_KEY_ANTERIOR (antigua) en el .env")
        return 2
    aplicar = "--aplicar" in argv
    r = rotar(settings.docs_dir, clave_actual(), settings.docs_key_anterior, aplicar)
    print(f"documentos: {r['total']} · ya con la clave nueva: {r['ya_nuevos']} · "
          f"{'vueltos a cifrar: ' + str(r['cifrados']) if aplicar else 'pendientes: ' + str(r['pendientes'])} · "
          f"ilegibles: {r['ilegibles']}")
    if r["ilegibles"]:
        print("AVISO: hay documentos que no se leen con ninguna de las dos claves (no se han tocado)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
