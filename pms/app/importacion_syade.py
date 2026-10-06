"""Listados de facturación del programa anterior (SYADE) exportados a Excel desde PDF.

Se reconocen cuatro listados por su cabecera:
- Facturas de alojamiento (N.Factura … Fianza): serie AE.
- Facturas de servicios (N.Factura … Total, sin fianza): serie SE. Sus fechas llegan sin el último dígito del año.
- Abonos (N.Abono … Rectif. Fra. Núm): serie AB_AE, en negativo.
- Fianzas devueltas (Fecha Rec. … Fianza Dev.).

La conversión desde PDF desplaza las columnas de una página a otra y repite la cabecera en cada página: cada
fila se lee por su forma (número, fecha, localizador, NIF, cliente y los importes al final), no por la posición.
La fila «Totales» del propio listado sirve para comprobar que se ha leído todo, al céntimo.
"""
import io
import re
from datetime import date, datetime
from decimal import Decimal

import openpyxl

TIPOS = {"alojamiento": "Facturas de alojamiento", "servicio": "Facturas de servicios", "abono": "Abonos",
         "fianza_devuelta": "Fianzas devueltas"}
_FECHA = re.compile(r"(\d{2})/(\d{2})/(\d{2,4})")
_IMPORTE = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+\.\d+|-?\d+,\d{2}")


def _num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _d(v) -> Decimal:
    return Decimal(str(v)).quantize(Decimal("0.01"))


def _importe(s: str) -> Decimal:
    s = s.strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    return _d(s)


def _texto(v) -> str | None:
    s = str(v).strip() if v is not None else ""
    return s or None


def _nif(v) -> str | None:
    if v is None:
        return None
    return (str(int(v)) if _num(v) else str(v)).strip().upper() or None


def _filas(datos: bytes):
    wb = openpyxl.load_workbook(io.BytesIO(datos), read_only=True, data_only=True)
    for ws in wb.worksheets:
        for r in ws.iter_rows(values_only=True):
            yield tuple(r)


def tipo_de(datos: bytes) -> str | None:
    try:
        primera = next(_filas(datos))
    except Exception:  # noqa: BLE001 — no es un Excel legible
        return None
    cab = " ".join(str(v) for v in primera if v is not None)
    if "N.Abono" in cab:
        return "abono"
    if "Fecha Rec" in cab and "Fianza" in cab:
        return "fianza_devuelta"
    if "N.Factura" in cab:
        return "alojamiento" if "Fianza" in cab else "servicio"
    return None


def _totales(fila) -> tuple[list[Decimal], int | None]:
    """Importes de la fila de totales (los que van detrás de «Totales») y nº de registros («Reg.»)."""
    texto = " | ".join(str(v) for v in fila if v is not None)
    reg = re.search(r"Reg\.[\s|]*(\d+)", texto)
    importes, tras = [], False
    for v in fila:
        if isinstance(v, str) and "Totales" in v:
            tras = True
            v = v.split("Totales")[-1]
        if not tras:
            continue
        if _num(v):
            importes.append(_d(v))
        elif isinstance(v, str):
            importes += [_importe(x) for x in _IMPORTE.findall(v)]
    return importes, int(reg.group(1)) if reg else None


def leer(datos: bytes, anio_por_defecto: int | None = None) -> dict:
    """{"tipo", "filas": [registro…], "esperado": {...} | None, "leido": {...}, "avisos": [...]}"""
    tipo = tipo_de(datos)
    if tipo is None:
        raise ValueError("No es un listado de SYADE reconocido (facturas, servicios, abonos o fianzas)")
    anio = anio_por_defecto or date.today().year
    filas, avisos, totales, n_reg = [], [], None, None
    sin_anio = sin_numero = 0
    for r in _filas(datos):
        if not r or all(v is None for v in r):
            continue
        texto = " ".join(str(v) for v in r if v is not None)
        if "Totales" in texto:
            importes, n = _totales(r)
            totales, n_reg = importes, n if n is not None else n_reg
            continue
        if "Reg." in texto and not totales:
            n_reg = _totales(r)[1]
            continue
        x = None
        if tipo == "alojamiento" and isinstance(r[2], datetime):
            t = [v for v in r[6:] if _num(v)]
            if len(t) == 5:
                x = {"serie": _texto(r[0]).rstrip("/ ").strip(), "numero": str(int(r[1])) if _num(r[1]) else None,
                     "fecha": r[2].date(), "localizador": _texto(int(r[3]) if _num(r[3]) else r[3]),
                     "nif": _nif(r[4]), "cliente": _texto(r[5]), "base": _d(t[0]), "tipo_iva": _d(t[1]),
                     "cuota": _d(t[2]), "total": _d(t[3]), "fianza": _d(t[4])}
        elif tipo == "servicio" and isinstance(r[2], str) and _FECHA.match(r[2].strip()):
            dd, mm, aa = _FECHA.match(r[2].strip()).groups()
            if len(aa) != 4:
                sin_anio += 1
                aa = str(anio)
            t = [v for v in r[6:] if _num(v)]
            if len(t) >= 4:
                x = {"serie": _texto(r[0]).rstrip("/ ").strip(), "numero": str(int(r[1])) if _num(r[1]) else None,
                     "fecha": date(int(aa), int(mm), int(dd)), "localizador": _texto(int(r[3]) if _num(r[3]) else r[3]),
                     "nif": _nif(r[4]), "cliente": _texto(r[5]), "base": _d(t[0]), "tipo_iva": _d(t[1]),
                     "cuota": _d(t[2]), "total": _d(t[3]), "fianza": Decimal(0)}
        elif tipo == "abono":
            if len(r) > 2 and isinstance(r[2], datetime):
                t = [v for v in r[6:] if _num(v)]
                cab = (_texto(r[0]), r[1], r[2].date(), r[3], r[4], r[5])
            elif isinstance(r[1], str) and re.match(r"\s*\d+\s+\d{2}/\d{2}/\d{4}\s+\d+", r[1]):
                # fila con número, fecha y localizador fundidos en una celda
                num, fch, loc = r[1].split()[:3]
                t = [v for v in r[4:] if _num(v)]
                cab = (_texto(r[0]), num, datetime.strptime(fch, "%d/%m/%Y").date(), loc, r[2], r[3])
            else:
                t, cab = [], None
            if cab and len(t) >= 4:
                x = {"serie": cab[0].rstrip("/ ").strip(), "numero": str(int(cab[1])) if _num(cab[1]) else str(cab[1]),
                     "fecha": cab[2], "localizador": _texto(int(cab[3]) if _num(cab[3]) else cab[3]),
                     "nif": _nif(cab[4]), "cliente": _texto(cab[5]), "base": _d(t[0]), "tipo_iva": _d(t[1]),
                     "cuota": _d(t[2]), "total": _d(t[3]), "fianza": Decimal(0),
                     "detalle": {"rectifica": str(int(t[4]))} if len(t) > 4 else None}
        elif tipo == "fianza_devuelta" and isinstance(r[0], datetime) and len(r) > 6 and isinstance(r[6], datetime):
            loc = _texto(int(r[1]) if _num(r[1]) else r[1])
            x = {"serie": "FZ", "numero": f"{loc}-{r[6]:%Y%m%d}", "fecha": r[6].date(), "localizador": loc,
                 "nif": None, "cliente": _texto(r[2]), "base": Decimal(0), "tipo_iva": None, "cuota": Decimal(0),
                 "total": Decimal(0), "fianza": _d(r[4] or 0),
                 "detalle": {"recibida_el": r[0].date().isoformat(), "recibida": float(_d(r[3] or 0)),
                             "retenida": float(_d(r[5] or 0)), "observaciones": _texto(r[7]) if len(r) > 7 else None}}
        if x:
            if not x["numero"]:  # el número se perdió al pasar el PDF a Excel: referencia por localizador y fecha
                x["numero"] = f"s/n {x['localizador'] or '-'} {x['fecha']:%d/%m/%Y}"
                x["detalle"] = {**(x.get("detalle") or {}), "sin_numero": True}
                sin_numero += 1
            filas.append(x)

    suma = lambda k: sum((f[k] for f in filas), Decimal(0))  # noqa: E731
    if tipo == "fianza_devuelta":
        leido = {"registros": len(filas), "devuelto": suma("fianza"),
                 "retenido": sum((_d(f["detalle"]["retenida"]) for f in filas), Decimal(0))}
        esperado = {"registros": None, "devuelto": totales[0], "retenido": totales[1]} if totales and len(totales) >= 2 else None
    else:
        leido = {"registros": len(filas), "base": suma("base"), "cuota": suma("cuota"), "total": suma("total")}
        if tipo == "alojamiento":
            leido["fianza"] = suma("fianza")
        esperado = None
        if totales and len(totales) >= 3:
            esperado = {"registros": n_reg, "base": totales[0], "cuota": totales[1], "total": totales[2]}
            if tipo == "alojamiento" and len(totales) >= 4:
                esperado["fianza"] = totales[3]
    if sin_numero:
        avisos.append(f"{sin_numero} factura(s) vienen sin número en el listado: se importan con la referencia "
                      "«s/n localizador fecha» para que la producción cuadre.")
    if sin_anio:
        avisos.append(f"{sin_anio} fecha(s) del listado vienen sin el último dígito del año: se ha tomado {anio}.")
    cuadra = esperado is not None and all(v is None or leido.get(k) == v for k, v in esperado.items())
    if esperado is None:
        avisos.append("El listado no trae la fila de totales: no se ha podido comprobar que esté completo.")
    elif not cuadra:
        avisos.append("Los importes leídos no cuadran con los totales del listado: revise el fichero.")
    return {"tipo": tipo, "filas": filas, "esperado": esperado, "leido": leido, "cuadra": cuadra, "avisos": avisos}
