"""Registro de viajeros (RD 933/2021) y comunicación a SES.HOSPEDAJE (Ministerio del Interior).

- Todos los ocupantes de una reserva quedan registrados: los mayores de edad con su documento; los menores
  sin documento, con registro manual y su parentesco con un adulto de la reserva.
- Códigos que pide SES: país ISO 3166-1 alfa-3, municipio español con código INE de 5 cifras, tipo de documento
  (NIF, NIE, PAS, OTRO), sexo (H, M, O) y parentesco de los menores.
- El fichero XML sigue la estructura de la comunicación de partes de viajeros (alta, tipo «PV») de SES.HOSPEDAJE
  para la carga de ficheros en la sede: un <comunicacion> por reserva con su <contrato> y una <persona> por ocupante.
"""
import csv
import gettext
import unicodedata
from datetime import date, datetime, time
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

import pycountry

DATOS = Path(__file__).parent / "data"
NS_ALTA = "http://www.neg.hospedajes.mir.es/altaParteHospedaje"
HORA_ENTRADA, HORA_SALIDA = time(15, 0), time(12, 0)

PARENTESCOS = {  # códigos de SES.HOSPEDAJE (obligatorio en los menores de edad)
    "PM": "Padre o madre", "TU": "Tutor/a", "HR": "Hermano/a", "AB": "Abuelo/a", "TI": "Tío/a",
    "SB": "Sobrino/a", "BA": "Bisabuelo/a", "CY": "Cónyuge", "HJ": "Hijo/a", "NI": "Nieto/a", "BN": "Bisnieto/a",
    "CD": "Cuñado/a", "SG": "Suegro/a", "YN": "Yerno o nuera", "OT": "Otro",
}
TIPOS_DOCUMENTO = {"DNI": "NIF", "NIF": "NIF", "NIE": "NIE", "PAS": "PAS", "OTRO": "OTRO"}
TIPOS_PAGO = {"efectivo": "EFECT", "tarjeta": "TARJT", "transferencia": "TRANS", "domiciliacion": "TRANS",
              "bizum": "MOVIL", "plataforma": "PLATF"}
CANALES_INTERNET = {"booking", "airbnb", "expedia", "web"}
PARTICULAS = {"DE", "DEL", "LA", "LAS", "LOS", "Y", "SAN", "SANTA", "VAN", "VON", "DA", "DOS", "DI", "MC", "MAC"}

# Provincia (2 primeras cifras del código postal y del código INE) -> comunidad autónoma (para la encuesta del INE)
CCAA = {
    "Andalucía": "04 11 14 18 21 23 29 41", "Aragón": "22 44 50", "Asturias, Principado de": "33",
    "Balears, Illes": "07", "Canarias": "35 38", "Cantabria": "39", "Castilla y León": "05 09 24 34 37 40 42 47 49",
    "Castilla - La Mancha": "02 13 16 19 45", "Cataluña": "08 17 25 43", "Comunitat Valenciana": "03 12 46",
    "Extremadura": "06 10", "Galicia": "15 27 32 36", "Madrid, Comunidad de": "28", "Murcia, Región de": "30",
    "Navarra, Comunidad Foral de": "31", "País Vasco": "01 20 48", "Rioja, La": "26", "Ceuta": "51", "Melilla": "52",
}
CCAA_DE_PROVINCIA = {p: ca for ca, ps in CCAA.items() for p in ps.split()}


def _norm(s) -> str:
    s = unicodedata.normalize("NFD", str(s or "")).encode("ascii", "ignore").decode().upper()
    return " ".join("".join(c if c.isalnum() else " " for c in s).split())


# --------------------------------------------------------------------------- países
try:
    _es = gettext.translation("iso3166-1", pycountry.LOCALES_DIR, languages=["es"]).gettext
except OSError:  # pragma: no cover
    def _es(s):
        return s


@lru_cache
def _paises() -> dict[str, str]:
    """Nombre normalizado (español, inglés, alfa-2 y alfa-3) -> alfa-3."""
    m = {}
    for c in pycountry.countries:
        nombres = {c.name, _es(c.name), getattr(c, "common_name", ""), getattr(c, "official_name", "")}
        nombres |= {_es(c.name).split(",")[0]}  # «Corea, República de» -> «Corea»
        for n in nombres:
            if n:
                m.setdefault(_norm(n), c.alpha_3)
        m[c.alpha_3] = c.alpha_3
        m.setdefault(c.alpha_2, c.alpha_3)
    m.update({"ESPANA": "ESP", "ESPANOLA": "ESP", "ESPANOL": "ESP", "REINO UNIDO": "GBR", "INGLATERRA": "GBR",
              "EEUU": "USA", "EE UU": "USA", "ESTADOS UNIDOS": "USA", "RUSIA": "RUS", "COREA DEL SUR": "KOR",
              "HOLANDA": "NLD", "PAISES BAJOS": "NLD", "D": "DEU"})
    return m


def pais_iso3(nombre: str | None) -> str | None:
    if not nombre:
        return None
    return _paises().get(_norm(nombre))


def nombre_pais(iso3: str | None) -> str | None:
    c = pycountry.countries.get(alpha_3=iso3) if iso3 else None
    return _es(c.name).split(",")[0] if c else None


def lista_paises() -> list[str]:
    return sorted({_es(c.name).split(",")[0] for c in pycountry.countries}, key=_norm)


# --------------------------------------------------------------------------- municipios (nomenclátor INE)
@lru_cache
def _municipios() -> list[tuple[str, str, str]]:
    """(código INE de 5 cifras, nombre, nombre normalizado)."""
    with open(DATOS / "municipios_ine.csv", encoding="utf-8") as fh:
        return [(r["municipio_id"], r["nombre"], _norm(r["nombre"])) for r in csv.DictReader(fh)]


def _variantes(nombre: str) -> set[str]:
    """«Rozas de Madrid, Las» / «Las Rozas de Madrid» / «Alegría-Dulantzi» / «Agurain/Salvatierra»."""
    out = {_norm(nombre)}
    for parte in nombre.split("/"):
        p = parte.strip()
        out.add(_norm(p))
        if ", " in p:
            base, art = p.rsplit(", ", 1)
            out.add(_norm(f"{art} {base}"))
            out.add(_norm(base))
    return out


@lru_cache
def _indice_municipios() -> dict[str, list[tuple[str, str]]]:
    idx: dict[str, list[tuple[str, str]]] = {}
    for cod, nombre, _ in _municipios():
        for v in _variantes(nombre):
            idx.setdefault(v, []).append((cod, nombre))
    return idx


def municipio_ine(municipio: str | None, cp: str | None = None) -> str | None:
    """Código INE del municipio a partir de su nombre (y del código postal para deshacer homónimos)."""
    if not municipio:
        return None
    candidatos = _indice_municipios().get(_norm(municipio), [])
    prov = (cp or "").strip()[:2]
    if prov.isdigit() and len(prov) == 2:
        candidatos = [c for c in candidatos if c[0][:2] == prov]  # el C.P. fija la provincia
    return candidatos[0][0] if len(candidatos) == 1 else None


def nombre_municipio(cod: str | None) -> str | None:
    return next((n for c, n, _ in _municipios() if c == cod), None) if cod else None


def buscar_municipios(q: str, cp: str | None = None, limite: int = 20) -> list[dict]:
    nq = _norm(q)
    if len(nq) < 2:
        return []
    prov = (cp or "")[:2]
    out = [{"codigo": c, "nombre": n} for c, n, nn in _municipios()
           if (nq in nn) and (not prov.isdigit() or c[:2] == prov)]
    out.sort(key=lambda x: (not _norm(x["nombre"]).startswith(nq), x["nombre"]))
    return out[:limite]


def comunidad(cp: str | None = None, cod_municipio: str | None = None) -> str | None:
    prov = (cod_municipio or cp or "")[:2]
    return CCAA_DE_PROVINCIA.get(prov)


# --------------------------------------------------------------------------- personas
def apellidos_ses(apellidos: str | None) -> tuple[str, str]:
    """Separa primer y segundo apellido, uniendo partículas («de la Fuente García» -> «de la Fuente», «García»)."""
    pal = (apellidos or "").split()
    if not pal:
        return "", ""
    primero = []
    i = 0
    while i < len(pal):
        primero.append(pal[i])
        if pal[i].upper().strip(".") not in PARTICULAS:
            i += 1
            break
        i += 1
    return " ".join(primero), " ".join(pal[i:])


def edad(nacimiento: date | None, en: date) -> int | None:
    if not nacimiento:
        return None
    return en.year - nacimiento.year - ((en.month, en.day) < (nacimiento.month, nacimiento.day))


def es_menor(nacimiento: date | None, en: date) -> bool:
    e = edad(nacimiento, en)
    return e is not None and e < 18


EDAD_SIN_PLAZA = 16  # los menores de 16 años no ocupan plaza (cuentan como «niños» en la reserva)


def ocupa_plaza(nacimiento: date | None, en: date) -> bool:
    e = edad(nacimiento, en)
    return e is None or e >= EDAD_SIN_PLAZA


def faltan_persona(c, titular: bool, parentesco: str | None, en: date) -> list[str]:
    """Datos que faltan para el parte de viajeros. `c` es la ficha (Contact) del ocupante."""
    f = []
    menor = es_menor(c.fecha_nacimiento, en)
    if not c.nombre:
        f.append("nombre")
    if not c.apellidos:
        f.append("apellidos")
    if not c.fecha_nacimiento:
        f.append("fecha de nacimiento")
    if not c.sexo:
        f.append("sexo")
    if not pais_iso3(c.nacionalidad):
        f.append("nacionalidad")
    if not menor or c.documento_num:  # el documento es obligatorio para los mayores de edad
        if not (c.documento_tipo in TIPOS_DOCUMENTO and c.documento_num):
            f.append("documento (tipo y número)")
        elif c.documento_tipo in ("DNI", "NIF", "NIE") and not c.num_soporte:
            f.append("nº de soporte del documento")
        if c.documento_tipo in ("DNI", "NIF") and len(apellidos_ses(c.apellidos)[1]) == 0 and c.apellidos:
            f.append("segundo apellido (obligatorio con DNI)")
    if menor and not titular and parentesco not in PARENTESCOS:
        f.append("parentesco con un adulto (menor de edad)")
    if not c.direccion:
        f.append("dirección del domicilio")
    iso = pais_iso3(c.pais)
    if not iso:
        f.append("país de residencia")
    elif iso == "ESP":
        if not c.cp:
            f.append("código postal")
        if not (getattr(c, "municipio_ine", None) or municipio_ine(c.municipio, c.cp)):
            f.append("municipio (no reconocido en el nomenclátor del INE)")
    elif not c.municipio:
        f.append("localidad")
    if titular and not (c.telefono or c.email):
        f.append("teléfono o correo del titular")
    return f


# --------------------------------------------------------------------------- fichero XML para SES.HOSPEDAJE
def _sub(padre, etiqueta, valor):
    if valor not in (None, ""):
        ET.SubElement(padre, etiqueta).text = str(valor)


def _persona(padre, c, parentesco: str | None, titular_tel: str | None, titular_email: str | None, en: date):
    p = ET.SubElement(padre, "persona")
    _sub(p, "rol", "VI")
    _sub(p, "nombre", c.nombre.strip())
    a1, a2 = apellidos_ses(c.apellidos)
    _sub(p, "apellido1", a1)
    _sub(p, "apellido2", a2)
    if c.documento_num:
        _sub(p, "tipoDocumento", TIPOS_DOCUMENTO.get(c.documento_tipo or "", "OTRO"))
        _sub(p, "numeroDocumento", c.documento_num.upper().replace(" ", ""))
        if c.documento_tipo in ("DNI", "NIF", "NIE"):
            _sub(p, "soporteDocumento", (c.num_soporte or "").upper())
    _sub(p, "fechaNacimiento", c.fecha_nacimiento.isoformat() if c.fecha_nacimiento else None)
    _sub(p, "nacionalidad", pais_iso3(c.nacionalidad))
    _sub(p, "sexo", {"M": "H", "F": "M"}.get(c.sexo or "", "O"))
    d = ET.SubElement(p, "direccion")
    _sub(d, "direccion", c.direccion)
    iso = pais_iso3(c.pais)
    if iso == "ESP":
        _sub(d, "codigoMunicipio", getattr(c, "municipio_ine", None) or municipio_ine(c.municipio, c.cp))
    else:
        _sub(d, "nombreMunicipio", c.municipio)
    _sub(d, "codigoPostal", c.cp)
    _sub(d, "pais", iso)
    # los menores pueden ir con el contacto del titular
    _sub(p, "telefono", c.telefono or titular_tel)
    _sub(p, "correo", c.email or titular_email)
    if es_menor(c.fecha_nacimiento, en):
        _sub(p, "parentesco", parentesco)


def xml_partes(codigo_establecimiento: str, reservas: list[dict]) -> bytes:
    """`reservas`: [{reserva, ocupantes: [(Contact, parentesco)], forma_pago, fecha_pago}]. Devuelve el XML."""
    raiz = ET.Element("ns2:peticion", {"xmlns:ns2": NS_ALTA})
    sol = ET.SubElement(raiz, "solicitud")
    _sub(sol, "codigoEstablecimiento", codigo_establecimiento)
    for item in reservas:
        r, ocupantes = item["reserva"], item["ocupantes"]
        com = ET.SubElement(sol, "comunicacion")
        ct = ET.SubElement(com, "contrato")
        _sub(ct, "referencia", r.localizador or f"R-{r.id}")
        _sub(ct, "fechaContrato", (r.creada.date() if r.creada else r.fecha_entrada).isoformat())
        _sub(ct, "fechaEntrada", datetime.combine(r.fecha_entrada, HORA_ENTRADA).isoformat())
        _sub(ct, "fechaSalida", datetime.combine(r.fecha_salida, HORA_SALIDA).isoformat())
        _sub(ct, "numPersonas", len(ocupantes))
        _sub(ct, "numHabitaciones", r.unit.dormitorios or 1)
        _sub(ct, "internet", "true" if r.canal in CANALES_INTERNET else "false")
        pago = ET.SubElement(ct, "pago")
        _sub(pago, "tipoPago", TIPOS_PAGO.get(item.get("forma_pago") or "", "PLATF" if r.canal in CANALES_INTERNET
                                              else "DESTI"))
        _sub(pago, "fechaPago", item["fecha_pago"].isoformat() if item.get("fecha_pago") else None)
        tit = r.guest
        for c, parentesco in ocupantes:
            _persona(com, c, parentesco, tit.telefono, tit.email, r.fecha_entrada)
    ET.indent(raiz)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(raiz, encoding="utf-8")


def completar_municipio(c) -> None:
    """Fija el código INE del municipio de una ficha de residente en España (o lo borra si no procede).
    Manda el nombre del municipio (con el C.P.); si no se reconoce, se conserva el código elegido en la lista."""
    if pais_iso3(c.pais) != "ESP":
        c.municipio_ine = None
        return
    cod = municipio_ine(c.municipio, c.cp)
    actual = (c.municipio_ine or "").strip()
    if cod:
        c.municipio_ine = cod
    elif len(actual) == 5 and actual.isdigit() and nombre_municipio(actual):
        c.municipio_ine = actual
        c.municipio = c.municipio or nombre_municipio(actual)
    else:
        c.municipio_ine = None
