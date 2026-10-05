"""Comprobación de NIF españoles (DNI, NIE y CIF de sociedades) y normalización de nombres para detectar
fichas repetidas."""
import re
import unicodedata

LETRAS_DNI = "TRWAGMYFPDXBNJZSQVHLCKE"
CIF_LETRA_CONTROL = "PQRSNW"  # control siempre letra (entidades, organismos, no residentes)
CIF_NUMERO_CONTROL = "ABEH"  # control siempre número (sociedades anónimas y limitadas, comunidades de bienes)


def normalizar(nif: str | None) -> str | None:
    n = re.sub(r"[\s.\-/]", "", nif or "").upper()
    return n or None


def tipo(nif: str) -> str | None:
    """«DNI», «NIE» o «CIF» si el número es válido (letra o dígito de control correcto); None si no lo es."""
    n = normalizar(nif) or ""
    if re.fullmatch(r"\d{8}[A-Z]", n):
        return "DNI" if LETRAS_DNI[int(n[:8]) % 23] == n[8] else None
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", n):
        return "NIE" if LETRAS_DNI[int(str("XYZ".index(n[0])) + n[1:8]) % 23] == n[8] else None
    if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", n):
        digitos = n[1:8]
        pares = sum(int(d) for d in digitos[1::2])
        impares = sum(sum(divmod(int(d) * 2, 10)) for d in digitos[::2])
        control = (10 - (pares + impares) % 10) % 10
        letra = "JABCDEFGHI"[control]
        if n[0] in CIF_LETRA_CONTROL:
            ok = n[8] == letra
        elif n[0] in CIF_NUMERO_CONTROL:
            ok = n[8] == str(control)
        else:
            ok = n[8] in (str(control), letra)
        return "CIF" if ok else None
    return None


def nombre_clave(*partes: str | None) -> str:
    """«María  López» y «MARIA LOPEZ» dan la misma clave (sin tildes, mayúsculas y espacios simples)."""
    t = " ".join(p for p in partes if p)
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return " ".join(re.sub(r"[^\w ]", " ", t.upper()).split())


def telefono_clave(t: str | None) -> str | None:
    d = re.sub(r"\D", "", t or "")
    if d.startswith("0034"):
        d = d[4:]
    elif d.startswith("34") and len(d) == 11:
        d = d[2:]
    return d or None
