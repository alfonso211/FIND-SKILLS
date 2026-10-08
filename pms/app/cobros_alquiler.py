"""Cobros de alquiler residencial hechos fuera del PMS (facturas simplificadas de otro programa, una por inquilino).

Se lee cada factura en PDF (o un ZIP con varias): número, fecha, inquilino, importe y mes del concepto. La renta se
repite en los meses indicados (p. ej. de enero a octubre) y cada mes se guarda como un ingreso cobrado
(ExternalInvoice tipo «renta») que cuenta en la producción del activo. Al importar se abre la ficha del inquilino
si no existe; el piso y el contrato se completan después en el PMS."""
import io
import re
import unicodedata
import zipfile
from datetime import date

MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
         "NOVIEMBRE", "DICIEMBRE"]
_MES = re.compile(r"\b(" + "|".join(MESES) + r")\s+(\d{4})\b", re.I)
_NIF = re.compile(r"^(?:[0-9XYZ]\d{7}[A-Z]|[A-HJ-NP-SUVW]\d{7}[0-9A-J])$")
MAX_FICHEROS, MAX_TAM = 300, 10 * 1024 * 1024


def _importe(s: str) -> float:
    return float(s.replace(".", "").replace(",", "."))


def _texto_pdf(datos: bytes) -> str:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(datos)
    try:
        return "\n".join(p.get_textpage().get_text_range() for p in pdf).replace("\r", "")
    finally:
        pdf.close()


def leer_factura(datos: bytes) -> dict:
    """Datos de una factura simplificada de alquiler. ValueError si no se reconoce."""
    if not datos.startswith(b"%PDF"):
        raise ValueError("no es un PDF")
    t = _texto_pdf(datos)
    lineas = [x.strip() for x in t.split("\n") if x.strip()]
    num = re.search(r"N[úu]mero\s*#?\s*([A-Z0-9][\w\-/]*)", t)
    fecha = re.search(r"Fecha\s+(\d{2})/(\d{2})/(\d{4})", t)
    total = re.search(r"\bTOTAL\s+([\d.]+,\d{2})\s*€", t)
    if not (num and fecha and total):
        raise ValueError("no parece una factura de alquiler (falta número, fecha o total)")
    try:  # el inquilino va entre los datos del emisor (termina en su correo) y la tabla de conceptos
        i = next(k for k, x in enumerate(lineas) if "@" in x)
        j = next(k for k, x in enumerate(lineas) if x.upper().startswith("CONCEPTO"))
    except StopIteration:
        raise ValueError("no se encuentra el bloque del cliente") from None
    bloque = lineas[i + 1:j]
    nif = next((x.replace(" ", "").replace("-", "").upper() for x in bloque
                if _NIF.match(x.replace(" ", "").replace("-", "").upper())), None)
    nombre = []
    for x in bloque:  # el nombre: las líneas antes de la dirección (la primera con cifras)
        if re.search(r"\d", x) or (nif and x.replace(" ", "").upper() == nif):
            break
        nombre.append(x)
    direccion = next((x for x in bloque if re.search(r"\d", x) and not _NIF.match(x.replace(" ", "").upper())), None)
    conceptos = t[t.upper().find("CONCEPTO"):] if "CONCEPTO" in t.upper() else ""
    f = date(int(fecha.group(3)), int(fecha.group(2)), int(fecha.group(1)))
    m = _MES.search(conceptos)
    if m:
        mes = f"{m.group(2)}-{MESES.index(m.group(1).upper()) + 1:02d}"
    else:  # «ALQUILER SEPTIEMBRE» sin año: el de la factura (o el siguiente si es de diciembre para enero)
        m = re.search(r"\b(" + "|".join(MESES) + r")\b", conceptos, re.I)
        n = MESES.index(m.group(1).upper()) + 1 if m else None
        mes = f"{f.year + (1 if n and n < f.month - 6 else 0)}-{n:02d}" if n else None
    return {"numero": num.group(1), "fecha": f.isoformat(), "cliente": " ".join(" ".join(nombre).split()) or None,
            "nif": nif, "direccion": direccion, "total": _importe(total.group(1)), "mes": mes}


def leer_subida(ficheros: list[tuple[str, bytes]]) -> tuple[list[dict], list[str]]:
    """Facturas de una o varias subidas (PDF sueltos o ZIP con PDF). Devuelve (facturas, avisos)."""
    pdfs: list[tuple[str, bytes]] = []
    avisos: list[str] = []
    for nombre, datos in ficheros:
        if datos.startswith(b"PK"):
            try:
                z = zipfile.ZipFile(io.BytesIO(datos))
            except zipfile.BadZipFile:
                avisos.append(f"{nombre}: ZIP dañado")
                continue
            for info in z.infolist():
                if info.is_dir() or not info.filename.lower().endswith(".pdf"):
                    continue
                if info.file_size > MAX_TAM:
                    avisos.append(f"{info.filename}: supera 10 MB")
                    continue
                pdfs.append((info.filename.rsplit("/", 1)[-1], z.read(info)))
        else:
            pdfs.append((nombre, datos))
        if len(pdfs) > MAX_FICHEROS:
            raise ValueError(f"Demasiados ficheros (máximo {MAX_FICHEROS})")
    out = []
    for nombre, datos in pdfs:
        try:
            out.append({**leer_factura(datos), "fichero": nombre})
        except Exception as e:  # noqa: BLE001 — un PDF raro no impide leer el resto
            avisos.append(f"{nombre}: {e}")
    return out, avisos


def meses(desde: str, hasta: str) -> list[str]:
    """«2026-01», «2026-10» -> ['2026-01', …, '2026-10']."""
    y, m = map(int, desde.split("-"))
    y2, m2 = map(int, hasta.split("-"))
    out = []
    while (y, m) <= (y2, m2) and len(out) < 120:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def clave_inquilino(nif: str | None, cliente: str | None) -> str:
    """Identificador corto y estable del inquilino para numerar sus cobros (sin datos personales en claro)."""
    import hashlib
    base = (nif or "").upper() or unicodedata.normalize("NFKD", cliente or "").encode("ascii", "ignore").decode().upper()
    base = " ".join(sorted(re.sub(r"[^A-Z0-9 ]", " ", base).split()))
    return hashlib.sha1(base.encode()).hexdigest()[:10].upper()
