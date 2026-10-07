"""Lector de facturas recibidas (PDF o foto): saca el texto y propone los datos para el formulario.

PDF con texto: se lee tal cual (rápido y exacto). PDF escaneado o foto: OCR en español con Tesseract.
Cada dato propuesto lleva su grado de confianza; lo que no se encuentra o no cuadra se marca «a revisar»
(en amarillo en la pantalla). Nunca se registra nada solo: quien sube la factura revisa y guarda."""
import io
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

from PIL import Image, ImageOps

from . import nif
from .vigilante import trabajo_pesado

PAGINAS = 3  # las facturas traen los datos en la primera; el total a veces en la última
OCR_TIEMPO = 25  # s por página
LADO_MAX = 2600
MESES = {m: i for i, m in enumerate(("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                                     "septiembre", "octubre", "noviembre", "diciembre"), 1)}
IVAS = (21, 10, 5, 4, 0)
RETENCIONES = {15: "irpf_profesional", 7: "irpf_inicio", 19: "irpf_arrendamiento", 1: "irpf_modulos"}


# --------------------------------------------------------------------------- texto
def _ocr(img: Image.Image) -> str:
    import pytesseract
    img = ImageOps.exif_transpose(img).convert("L")
    if max(img.size) > LADO_MAX:
        img.thumbnail((LADO_MAX, LADO_MAX))
    try:
        return pytesseract.image_to_string(img, lang="spa", config="--psm 6", timeout=OCR_TIEMPO)
    except RuntimeError:  # tiempo agotado
        return ""


def texto(datos: bytes) -> tuple[str, str]:
    """(texto, método). Método: «pdf» (texto del propio PDF) u «ocr» (escaneado o foto)."""
    with trabajo_pesado("lectura de facturas"):
        if datos[:5] == b"%PDF-":
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(datos)
            n = min(len(pdf), PAGINAS)
            t = "\n".join(pdf[i].get_textpage().get_text_range() for i in range(n))
            if len(re.sub(r"\s", "", t)) >= 40:
                return t, "pdf"
            return "\n".join(_ocr(pdf[i].render(scale=min(250 / 72, 3500 / max(*pdf[i].get_size(), 1))).to_pil())
                             for i in range(n)), "ocr"
        try:
            img = Image.open(io.BytesIO(datos))
            img.load()
        except Exception as exc:  # noqa: BLE001
            raise ValueError("El fichero no es una imagen ni un PDF válido") from exc
        return _ocr(img), "ocr"


# --------------------------------------------------------------------------- utilidades
def _plano(s: str) -> str:
    """Minúsculas sin tildes, para buscar palabras clave."""
    return unicodedata.normalize("NFKD", s.lower()).encode("ascii", "ignore").decode()


IMPORTE = r"(-?\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})|-?\d+(?:[.,]\d{1,2})?)"


def importe(s: str) -> Decimal | None:
    s = s.replace(" ", "").replace("€", "")
    if "," in s:  # formato español: 1.234,56
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or re.search(r"\.\d{3}$", s):  # 1.234 (miles)
        s = s.replace(".", "")
    try:
        return Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def _fecha(s: str) -> date | None:
    s = _plano(s)
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b", s)
    if m:
        d, mes, a = (int(x) for x in m.groups())
        a += 2000 if a < 100 else 0
    else:
        m = re.search(r"\b(\d{1,2})\s+de\s+([a-z]+)\s+(?:de\s+|del\s+)?(\d{4})\b", s)
        if not m or m.group(2) not in MESES:
            return None
        d, mes, a = int(m.group(1)), MESES[m.group(2)], int(m.group(3))
    try:
        return date(a, mes, d)
    except ValueError:
        return None


def _lineas(t: str) -> list[str]:
    return [" ".join(x.split()) for x in t.splitlines() if x.strip()]


def _tras(lineas: list[str], claves: tuple[str, ...], patron: str, mirar_siguiente: bool = True,
          excluir: tuple[str, ...] = ()) -> str | None:
    """Primer valor que cumple el patrón detrás de una de las palabras clave (en la línea o en la siguiente)."""
    for i, ln in enumerate(lineas):
        p = _plano(ln)
        if any(e in p for e in excluir):
            continue
        for c in claves:
            k = p.find(c)
            if k < 0:
                continue
            m = re.search(patron, ln[k + len(c):], re.I)
            if m:
                return m.group(1)
            if mirar_siguiente and i + 1 < len(lineas):
                m = re.search(patron, lineas[i + 1], re.I)
                if m:
                    return m.group(1)
    return None


def _importes_tras(lineas: list[str], claves: tuple[str, ...], excluir: tuple[str, ...] = ()) -> list[Decimal]:
    out = []
    for i, ln in enumerate(lineas):
        p = _plano(ln)
        if any(c in p for c in claves) and not any(e in p for e in excluir):
            for cand in (ln, lineas[i + 1] if i + 1 < len(lineas) else ""):
                vals = [importe(x) for x in re.findall(IMPORTE + r"\s*(?:€|eur)?", cand)]
                vals = [v for v in vals if v is not None and v != 0]
                if vals:
                    out.append(vals[-1])
                    break
    return out


def _tabla_totales(lineas: list[str]) -> dict | None:
    for i, ln in enumerate(lineas[:-1]):
        p = _plano(ln)
        if "base" not in p or "total" not in p:
            continue
        vals = [v for v in (importe(x) for x in re.findall(IMPORTE, lineas[i + 1])) if v is not None]
        if len(vals) < 2 or re.findall(IMPORTE, ln):
            continue
        base, out = vals[0], {"base": vals[0], "total": vals[-1]}
        for v in vals[1:-1]:
            iva = next((x for x in IVAS if x and abs(base * x / 100 - v) <= Decimal("0.05")), None)
            if iva:
                out.update(cuota=v, tipo_iva=iva)
            elif v in IVAS:
                out.setdefault("tipo_iva", int(v))
        return out
    return None


# --------------------------------------------------------------------------- extracción
def extraer(t: str, nifs_propios: set[str] = frozenset(), proveedores: dict[str, str] | None = None) -> dict:
    """{"campos": {...}, "dudosos": [...], "leidos": [...]}. `proveedores`: NIF -> nombre de los ya conocidos."""
    lineas = _lineas(t)
    plano = _plano(t)
    campos, dudosos = {}, set()

    # NIF del emisor: el primero válido que no sea de una sociedad del grupo (esas son el receptor)
    candidatos = re.findall(r"\b(?:ES)?([A-HJ-NP-SUVW]\d{7}[0-9A-J]|\d{8}[A-Z]|[XYZ]\d{7}[A-Z])\b",
                            t.upper().replace("-", ""))
    validos = [c for c in dict.fromkeys(candidatos) if nif.tipo(c) and c not in nifs_propios]
    if validos:
        campos["nif"] = validos[0]
    elif [c for c in candidatos if c not in nifs_propios]:
        campos["nif"] = next(c for c in candidatos if c not in nifs_propios)
        dudosos.add("nif")  # la letra de control no cuadra: mal leído

    # emisor: el proveedor ya conocido por su NIF; si no, la primera línea con forma jurídica
    nombre = (proveedores or {}).get(campos.get("nif", ""))
    if nombre:
        campos["emisor"] = nombre
    else:
        for ln in lineas[:25]:
            if re.search(r"\b(s\.?\s?l\.?u?|s\.?\s?a\.?u?|s\.?\s?coop\.?|c\.?\s?b\.?)\s*$", _plano(ln)) and \
                    not any(n in ln.upper() for n in ("INVERSIETE", "COMERCIAL DEL CAMPO", "EDIFICIOS CAMERANOS",
                                                      "ETHOSA", "EMPRESA TURISTICA")):
                campos["emisor"] = ln.strip(" .,:;")[:200]
                break
        dudosos.add("emisor")  # nombre sacado del texto: comprobarlo siempre

    # nº de factura
    num = _tras(lineas, ("n factura", "no factura", "nº factura", "n. factura", "num. factura", "numero factura",
                         "numero de factura", "factura n", "factura num", "factura no", "invoice no", "invoice number",
                         "factura:", "factura"),
                r"[:#ºo°.\s]*([A-Z0-9][A-Z0-9/\-.]{0,28}[0-9])", excluir=("fecha", "total", "importe"))
    if num and _fecha(num):  # era una fecha, no un número de factura
        num = None
    if num:
        campos["referencia"] = num.strip(".")
        if not re.search(r"\d", num):
            dudosos.add("referencia")

    # fechas
    patron_fecha = r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}\s+de\s+[a-zA-Záéíóú]+\s+(?:de\s+)?\d{4})"
    f = _tras(lineas, ("fecha factura", "fecha de factura", "fecha emision", "fecha de emision", "fecha expedicion",
                       "fecha:", "fecha"), patron_fecha)
    fecha = _fecha(f) if f else None
    if not fecha:  # la primera fecha del documento
        m = re.search(patron_fecha, t)
        fecha = _fecha(m.group(1)) if m else None
        dudosos.add("fecha")
    if fecha:
        campos["fecha"] = fecha.isoformat()
        if fecha > date.today() or fecha.year < date.today().year - 2:
            dudosos.add("fecha")
    v = _tras(lineas, ("vencimiento", "fecha vto", "vto.", "vence"), patron_fecha)
    venc = _fecha(v) if v else None
    if venc and (not fecha or venc >= fecha):
        campos["vencimiento"] = venc.isoformat()

    # importes
    totales = _importes_tras(lineas, ("total factura", "total a pagar", "importe total", "total eur", "total €",
                                      "total"), excluir=("subtotal", "total base", "total iva", "total bruto"))
    total = max(totales, key=abs) if totales else None
    bases = _importes_tras(lineas, ("base imponible", "base imp", "base"))
    base = bases[0] if bases else None
    tipo_iva = None
    m = re.search(r"i\.?v\.?a\.?[^0-9\n]{0,15}(21|10|5|4)\s*(?:[.,]0+)?\s*%", plano) or \
        re.search(r"(21|10|5|4)\s*(?:[.,]0+)?\s*%\s*i\.?v\.?a", plano)
    if m:
        tipo_iva = int(m.group(1))
    cuotas = _importes_tras(lineas, ("cuota iva", "iva"), excluir=("base", "total", "exento"))
    cuota = cuotas[0] if cuotas else None
    ret_pct = ret = None
    m = re.search(r"(?:i\.?r\.?p\.?f\.?|retencion)[^0-9\n]{0,15}(\d{1,2})\s*(?:[.,]0+)?\s*%", plano)
    if m:
        ret_pct = int(m.group(1))
    rets = _importes_tras(lineas, ("irpf", "retencion"))
    ret = abs(rets[0]) if rets else None
    tabla = _tabla_totales(lineas)
    if tabla:  # cuadro «Base imponible · % IVA · Cuota · Total» con los importes en la línea de debajo
        base, cuota, tipo_iva, total = tabla["base"], tabla.get("cuota", cuota), tabla.get("tipo_iva", tipo_iva), \
            tabla.get("total", total)
    if base and not tipo_iva and cuota:  # IVA % a partir de la cuota
        tipo_iva = next((i for i in IVAS if abs(base * i / 100 - cuota) <= Decimal("0.05")), None)
    if base and tipo_iva is not None and ret_pct and ret is None:
        ret = (base * ret_pct / 100).quantize(Decimal("0.01"))
    if total is not None:
        campos["total"] = float(total)
    else:
        dudosos.add("total")
    if tipo_iva is not None:
        campos["tipo_iva"] = tipo_iva
    else:
        dudosos.add("tipo_iva")
    if ret_pct:
        campos["retencion_tipo"] = RETENCIONES.get(ret_pct, "otra")
        campos["retencion_pct"] = ret_pct
    # cuadre: base + IVA − retención = total. Si no cuadra con un solo tipo de IVA, se propone la base
    if total is not None and base is not None and tipo_iva is not None:
        esperado = base + (cuota if cuota is not None else base * tipo_iva / 100) - (ret or 0)
        if abs(esperado - total) > Decimal("0.05"):
            campos["base"] = float(base)
            dudosos.update({"total", "base", "tipo_iva"})
    elif total is not None:
        dudosos.add("tipo_iva" if tipo_iva is None else "total")

    # forma de pago
    if re.search(r"domiciliad|domiciliacion|adeudo|cargo en (su )?cuenta|recibo bancario|sepa", plano):
        campos["forma_pago"] = "domiciliacion"
    elif "transferencia" in plano:
        campos["forma_pago"] = "transferencia"
    elif re.search(r"\btarjeta\b", plano):
        campos["forma_pago"] = "tarjeta"
    elif re.search(r"\bcontado\b|\befectivo\b", plano):
        campos["forma_pago"] = "efectivo"
    else:
        dudosos.add("forma_pago")

    obligatorios = ("emisor", "referencia", "fecha", "total", "tipo_iva", "forma_pago")
    dudosos.update(k for k in obligatorios if k not in campos)
    return {"campos": campos, "dudosos": sorted(dudosos), "leidos": sorted(campos)}


def leer(datos: bytes, nifs_propios: set[str] = frozenset(), proveedores: dict[str, str] | None = None) -> dict:
    t, metodo = texto(datos)
    if len(re.sub(r"\s", "", t)) < 20:
        return {"campos": {}, "dudosos": ["emisor", "referencia", "fecha", "total", "tipo_iva", "forma_pago"],
                "leidos": [], "metodo": metodo,
                "aviso": "No se ha podido leer el texto: compruebe que la foto está nítida y derecha"}
    return {**extraer(t, nifs_propios, proveedores), "metodo": metodo}
