"""Lectura de la zona MRZ (ICAO 9303) de DNI, NIE/TIE, documentos de identidad y pasaportes.

Formatos: TD1 (tarjetas: 3 líneas de 30), TD2 (2 de 36) y TD3 (pasaportes: 2 de 44).
Todos los campos se validan con sus dígitos de control. Se corrigen las confusiones típicas del OCR
(O/0, I/1, B/8...) probando alternativas hasta que el dígito de control cuadra.
"""
import gettext
import itertools
from datetime import date

import pycountry

PESOS = (7, 3, 1)
A_NUM = str.maketrans({"O": "0", "Q": "0", "D": "0", "U": "0", "I": "1", "L": "1", "Z": "2", "S": "5",
                       "G": "6", "B": "8", "T": "7"})
A_ALFA = str.maketrans({"0": "O", "1": "I", "2": "Z", "5": "S", "6": "G", "8": "B"})
AMBIGUOS = {"0": "O", "O": "0", "1": "I", "I": "1", "8": "B", "B": "8", "5": "S", "S": "5", "2": "Z", "Z": "2"}

try:
    _es = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["es"]).gettext
except OSError:  # sin traducciones: nombres en inglés
    def _es(s):
        return s


def digito(campo: str) -> str:
    total = 0
    for i, c in enumerate(campo):
        v = int(c) if c.isdigit() else (ord(c) - 55 if c.isalpha() else 0)
        total += v * PESOS[i % 3]
    return str(total % 10)


def _ok(campo: str, control: str) -> bool:
    return control.translate(A_NUM) == digito(campo)


def _num(s: str) -> str:
    return s.translate(A_NUM)


def _alfa(s: str) -> str:
    return s.translate(A_ALFA)


def _corrige(campo: str, control: str, max_cambios: int = 2) -> str | None:
    """Devuelve el campo (alfanumérico) que cuadra con el dígito de control, probando confusiones del OCR."""
    if _ok(campo, control):
        return campo
    pos = [i for i, c in enumerate(campo) if c in AMBIGUOS]
    for n in range(1, max_cambios + 1):
        for combo in itertools.combinations(pos, n):
            cand = list(campo)
            for i in combo:
                cand[i] = AMBIGUOS[cand[i]]
            cand = "".join(cand)
            if _ok(cand, control):
                return cand
    return None


def _fecha(yymmdd: str, nacimiento: bool) -> date | None:
    try:
        yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
        hoy = date.today()
        siglo = 1900 if nacimiento and yy > hoy.year % 100 else 2000
        return date(siglo + yy, mm, dd)
    except ValueError:
        return None


def pais(iso3: str) -> str | None:
    if iso3 in ("D<<", "D"):  # Alemania usa "D" en la MRZ
        iso3 = "DEU"
    c = pycountry.countries.get(alpha_3=iso3)
    return _es(c.name) if c else None


def _nombres(campo: str) -> tuple[str, str]:
    campo = _alfa(campo).rstrip("<")
    apellidos, _, nombre = campo.partition("<<")
    limpio = lambda s: " ".join(p for p in s.replace("<", " ").split() if p).title()  # noqa: E731
    return limpio(nombre), limpio(apellidos)


def _limpia(linea: str) -> str:
    return "".join(c for c in linea.upper().replace(" ", "") if c.isalnum() or c == "<")


def _ajusta(linea: str, largo: int) -> str:
    return (linea + "<" * largo)[:largo]


def interpretar(lineas: list[str]) -> dict | None:
    """Interpreta las líneas MRZ leídas. Devuelve None si no forman una MRZ reconocible."""
    ls = [x for x in (_limpia(y) for y in lineas) if len(x) >= 25 or (len(x) >= 5 and "<" in x)]
    # El OCR suele perder los «<» finales de la línea del nombre: esa línea puede llegar más corta
    linea_nombre = {"TD1": 2, "TD3": 0, "TD2": 0}
    for i in range(len(ls)):
        for fmt, n, largo in (("TD1", 3, 30), ("TD3", 2, 44), ("TD2", 2, 36)):
            bloque = ls[i:i + n]
            if len(bloque) == n and all(
                    (len(x) <= largo + 3 and len(x) >= 5) if j == linea_nombre[fmt] else abs(len(x) - largo) <= 3
                    for j, x in enumerate(bloque)):
                r = (_td1 if fmt == "TD1" else _td23)([_ajusta(x, largo) for x in bloque], fmt)
                if r and r["checks_ok"] >= r["checks_total"] - 1:
                    return r
    return None


def _resultado(fmt, codigo, emisor, numero, nac, nacim, sexo, cad, nombre, apellidos, opcional, checks):
    tipo = codigo[0]
    emisor, nac = _alfa(emisor), _alfa(nac)
    r = {"formato": fmt, "codigo": codigo, "emisor": emisor, "nacionalidad_iso": nac,
         "nacionalidad": pais(nac), "pais_emisor": pais(emisor),
         "nombre": nombre, "apellidos": apellidos, "sexo": {"M": "M", "F": "F"}.get(sexo),
         "fecha_nacimiento": nacim, "fecha_caducidad": cad,
         "checks_ok": sum(checks), "checks_total": len(checks)}
    if emisor == "ESP" and tipo == "I" and codigo in ("ID", "I<"):
        r.update(documento_tipo="DNI", documento_num=opcional[:9].rstrip("<"), num_soporte=numero)
    elif emisor == "ESP" and tipo in ("I", "A", "C") and codigo != "ID":
        r.update(documento_tipo="NIE", documento_num=opcional[:9].rstrip("<"), num_soporte=numero)
    elif tipo == "P":
        r.update(documento_tipo="PAS", documento_num=numero, num_soporte=None)
    else:
        r.update(documento_tipo="OTRO", documento_num=numero, num_soporte=None)
    r["mrz_valido"] = r["checks_ok"] == r["checks_total"]
    return r


def _td1(l, fmt):
    l1, l2, l3 = l
    numero = _corrige(l1[5:14], l1[14]) or l1[5:14]
    nacim_txt, cad_txt = _num(l2[0:6]), _num(l2[8:14])
    checks = [_ok(numero, l1[14]), _ok(nacim_txt, l2[6]), _ok(cad_txt, l2[14])]
    comp = numero + l1[14] + l1[15:30] + nacim_txt + l2[6] + cad_txt + l2[14] + l2[18:29]
    checks.append(_ok(comp, l2[29]))
    nombre, apellidos = _nombres(l3)
    opcional = l1[15:30]
    return _resultado(fmt, l1[0:2], l1[2:5], numero.rstrip("<"), l2[15:18], _fecha(nacim_txt, True), l2[7],
                      _fecha(cad_txt, False), nombre, apellidos, opcional, checks)


def _td23(l, fmt):
    l1, l2 = l
    numero = _corrige(l2[0:9], l2[9]) or l2[0:9]
    nacim_txt, cad_txt = _num(l2[13:19]), _num(l2[21:27])
    checks = [_ok(numero, l2[9]), _ok(nacim_txt, l2[19]), _ok(cad_txt, l2[27])]
    if fmt == "TD3":
        personal = l2[28:42]
        if l2[42] != "<" or personal.strip("<"):
            checks.append(_ok(personal, l2[42]))
        comp = numero + l2[9] + nacim_txt + l2[19] + cad_txt + l2[27] + l2[28:43]
        checks.append(_ok(comp, l2[43]))
    else:
        personal = l2[28:35]
        comp = numero + l2[9] + nacim_txt + l2[19] + cad_txt + l2[27] + l2[28:35]
        checks.append(_ok(comp, l2[35]))
    nombre, apellidos = _nombres(l1[5:])
    return _resultado(fmt, l1[0:2], l1[2:5], numero.rstrip("<"), l2[10:13], _fecha(nacim_txt, True), l2[20],
                      _fecha(cad_txt, False), nombre, apellidos, personal, checks)
