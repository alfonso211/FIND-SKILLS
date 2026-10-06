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
# cifras que el OCR confunde entre sí (fechas y dígitos de control)
CIFRAS_PARECIDAS = {"0": "68", "6": "058", "8": "0369", "5": "6", "1": "7", "7": "1", "3": "8", "9": "8"}

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


def _candidatos(campo: str, control: str, fecha: bool = False) -> list[tuple[str, str]]:
    """Lecturas posibles de un campo numérico y su dígito de control: la leída si cuadra; si no, primero con una
    cifra parecida cambiada que cuadre con su propio dígito (doble comprobación) y, por último, con el dígito de
    control recalculado (por si lo mal leído es el propio dígito). El dígito de control global decide."""
    if _ok(campo, control):
        return [(campo, control)]
    valida = (lambda x: _fecha(x, False) is not None) if fecha else (lambda x: True)  # noqa: E731
    out = []
    for i, c in enumerate(campo):
        for alt in CIFRAS_PARECIDAS.get(c, ""):
            cand = campo[:i] + alt + campo[i + 1:]
            if _ok(cand, control) and valida(cand):
                out.append((cand, control))
    if valida(campo):
        out.append((campo, digito(campo)))
    return out


def _con_global(campos: list[tuple[str, str]], compuesto, control_global: str):
    """Elige, entre las lecturas posibles de cada campo, la combinación que cuadra con el dígito global.
    Devuelve (campos, corregido) o None si ninguna cuadra."""
    opciones = [_candidatos(c, d, fecha=n > 0) for n, (c, d) in enumerate(campos)]  # campos: número y dos fechas
    for combo in itertools.product(*opciones):
        if _ok(compuesto(combo), control_global):
            return list(combo), any(c != o for c, o in zip(combo, campos))
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


def _rellena(linea: str, largo: int) -> str:
    """El OCR suele comerse algunos «<» seguidos: si la línea es corta y acaba en el dígito de control final,
    los «<» que faltan son los de relleno que van justo antes."""
    if len(linea) < largo and linea[-1:].isdigit() and "<<" in linea:
        return linea[:-1] + "<" * (largo - len(linea)) + linea[-1]
    return linea


def interpretar(lineas: list[str]) -> dict | None:
    """Interpreta las líneas MRZ leídas. Devuelve None si no forman una MRZ reconocible. Se prueban todos los
    formatos posibles y se elige el que mejor cuadra con los dígitos de control."""
    ls = [x for x in (_limpia(y) for y in lineas) if len(x) >= 25 or (len(x) >= 5 and "<" in x)]
    # El OCR suele perder los «<» finales de la línea del nombre: esa línea puede llegar más corta
    linea_nombre = {"TD1": 2, "TD3": 0, "TD2": 0}
    mejor = None
    for i in range(len(ls)):
        for fmt, n, largo in (("TD1", 3, 30), ("TD3", 2, 44), ("TD2", 2, 36)):
            bloque = ls[i:i + n]
            if len(bloque) != n:
                continue
            bloque = [x if j == linea_nombre[fmt] else _rellena(x, largo) for j, x in enumerate(bloque)]
            if all((len(x) <= largo + 3 and len(x) >= 5) if j == linea_nombre[fmt] else abs(len(x) - largo) <= 3
                   for j, x in enumerate(bloque)):
                r = (_td1 if fmt == "TD1" else _td23)([_ajusta(x, largo) for x in bloque], fmt)
                if r and r["checks_ok"] >= r["checks_total"] - 1:
                    # código del documento: «P» en pasaportes (TD3), «I/A/C» en tarjetas (TD1/TD2)
                    propio = (bloque[0][:1] == "P") == (fmt == "TD3")
                    clave = (r["mrz_valido"], r["checks_ok"] - r["checks_total"], propio,
                             -sum(abs(len(x) - largo) for x in bloque))
                    if mejor is None or clave > mejor[0]:
                        mejor = (clave, r)
    return mejor[1] if mejor else None


def _resultado(fmt, codigo, emisor, numero, nac, nacim, sexo, cad, nombre, apellidos, opcional, checks,
               corregido=False):
    # 1.ª letra del código: I, A o C en las tarjetas (TD1/TD2) y P en los pasaportes (el OCR lee «I» como «T» o «1»)
    codigo = _alfa(codigo)
    if fmt == "TD3" and codigo[0] not in "PV":
        codigo = "P" + codigo[1]
    elif fmt != "TD3" and codigo[0] not in "IAC":
        codigo = "I" + codigo[1]
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
    r["corregido"] = corregido  # alguna cifra dudosa se ha corregido con el dígito de control global
    return r


def _td1(l, fmt):
    l1, l2, l3 = l
    numero = _corrige(l1[5:14], l1[14]) or l1[5:14]
    nacim_txt, cad_txt = _num(l2[0:6]), _num(l2[8:14])
    campos = [(numero, l1[14]), (nacim_txt, _num(l2[6])), (cad_txt, _num(l2[14]))]
    checks = [_ok(c, d) for c, d in campos]
    comp = lambda f: f[0][0] + f[0][1] + l1[15:30] + f[1][0] + f[1][1] + f[2][0] + f[2][1] + l2[18:29]  # noqa: E731
    checks.append(_ok(comp(campos), l2[29]))
    corregido = False
    if not all(checks) and (arreglo := _con_global(campos, comp, l2[29])):
        campos, corregido = arreglo
        checks = [True] * 4
    (numero, _), (nacim_txt, _), (cad_txt, _) = campos
    nombre, apellidos = _nombres(l3)
    opcional = l1[15:30]
    return _resultado(fmt, l1[0:2], l1[2:5], numero.rstrip("<"), l2[15:18], _fecha(nacim_txt, True), l2[7],
                      _fecha(cad_txt, False), nombre, apellidos, opcional, checks, corregido)


def _td23(l, fmt):
    l1, l2 = l
    numero = _corrige(l2[0:9], l2[9]) or l2[0:9]
    nacim_txt, cad_txt = _num(l2[13:19]), _num(l2[21:27])
    campos = [(numero, l2[9]), (nacim_txt, _num(l2[19])), (cad_txt, _num(l2[27]))]
    checks = [_ok(c, d) for c, d in campos]
    if fmt == "TD3":
        personal = l2[28:42]
        if l2[42] != "<" or personal.strip("<"):
            checks.append(_ok(personal, l2[42]))
        resto, control_global = l2[28:43], l2[43]
    else:
        personal = l2[28:35]
        resto, control_global = l2[28:35], l2[35]
    comp = lambda f: f[0][0] + f[0][1] + f[1][0] + f[1][1] + f[2][0] + f[2][1] + resto  # noqa: E731
    checks.append(_ok(comp(campos), control_global))
    corregido = False
    if not all(checks[:3] + checks[-1:]) and (arreglo := _con_global(campos, comp, control_global)):
        campos, corregido = arreglo
        checks = [True] * 3 + checks[3:-1] + [True]
    (numero, _), (nacim_txt, _), (cad_txt, _) = campos
    nombre, apellidos = _nombres(l1[5:])
    return _resultado(fmt, l1[0:2], l1[2:5], numero.rstrip("<"), l2[10:13], _fecha(nacim_txt, True), l2[20],
                      _fecha(cad_txt, False), nombre, apellidos, personal, checks, corregido)
