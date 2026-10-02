"""Lectura automática de documentos de identidad escaneados (imagen o PDF), en el propio servidor.

1. Se busca la zona MRZ (validada con dígitos de control) probando las cuatro orientaciones.
2. En el DNI español se intenta además leer el domicilio del reverso (texto libre: es una propuesta
   que recepción debe revisar).
Nada se envía a servicios externos.
"""
import io
import re
import shutil
from datetime import date

from PIL import Image, ImageOps

from . import mrz

FORMATOS = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp", "application/pdf"}
TAM_MAX = 15 * 1024 * 1024
WHITELIST_MRZ = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
FIN_DOMICILIO = ("LUGAR DE NAC", "HIJO", "EQUIPO", "NACIMIENTO", "IDESP", "IRESP")


def disponible() -> bool:
    return shutil.which("tesseract") is not None


def a_imagenes(datos: bytes) -> tuple[str, list[Image.Image]]:
    """Comprueba el fichero por su contenido (no por la extensión) y lo convierte en imágenes."""
    if datos[:5] == b"%PDF-":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(datos)
        paginas = [pdf[i].render(scale=300 / 72).to_pil() for i in range(min(len(pdf), 2))]
        return "application/pdf", paginas
    try:
        img = Image.open(io.BytesIO(datos))
        img.load()
    except Exception as exc:  # noqa: BLE001
        raise ValueError("El fichero no es una imagen ni un PDF válido") from exc
    mime = Image.MIME.get(img.format, "")
    if mime not in FORMATOS:
        raise ValueError(f"Formato no admitido ({img.format}). Use JPG, PNG o PDF")
    return mime, [ImageOps.exif_transpose(img)]


def _prepara(img: Image.Image) -> Image.Image:
    g = ImageOps.grayscale(img)
    if g.width < 1800:  # los escaneos pequeños se leen mucho mejor ampliados
        f = 1800 / g.width
        g = g.resize((int(g.width * f), int(g.height * f)), Image.LANCZOS)
    return ImageOps.autocontrast(g)


def _ocr(img: Image.Image, **kw) -> str:
    import pytesseract
    return pytesseract.image_to_string(img, **kw)


def _buscar_mrz(img: Image.Image) -> tuple[dict | None, Image.Image]:
    base = _prepara(img)
    cfg = f"--psm 6 -c tessedit_char_whitelist={WHITELIST_MRZ}"
    for giro in (0, 90, 270, 180):
        im = base.rotate(giro, expand=True) if giro else base
        # la MRZ está en la parte inferior; se prueba primero ahí (más rápido y fiable) y luego entera
        for recorte in (im.crop((0, int(im.height * 0.55), im.width, im.height)), im):
            texto = _ocr(recorte, lang="eng", config=cfg)
            r = mrz.interpretar([ln for ln in texto.splitlines() if ln.strip()])
            if r:
                return r, im
    return None, base


def _domicilio(img: Image.Image) -> dict:
    """Reverso del DNI: «DOMICILIO» seguido de dirección, municipio y provincia."""
    lineas = [ln.strip() for ln in _ocr(img, lang="spa", config="--psm 4").splitlines() if ln.strip()]
    for i, ln in enumerate(lineas):
        if "DOMICILIO" in ln.upper():
            siguientes = []
            for x in lineas[i + 1:i + 5]:
                if any(k in x.upper() for k in FIN_DOMICILIO):
                    break
                x = re.sub(r"[^\wÁÉÍÓÚÜÑáéíóúüñºª/.,\- ]", "", x).strip()
                if len(x) >= 3:
                    siguientes.append(x)
            if siguientes:
                # «P03» (planta 03) se lee a veces como «Po3»/«PO3»
                siguientes[0] = re.sub(r"\bP[oO]0?(\d)", r"P0\1", siguientes[0])
                return {"direccion": siguientes[0].title(),
                        "municipio": siguientes[1].title() if len(siguientes) > 1 else None,
                        "provincia": siguientes[2].title() if len(siguientes) > 2 else None}
    return {}


def leer(caras: list[bytes]) -> dict:
    """Lee una o varias caras del documento y devuelve los datos encontrados y los avisos."""
    if not disponible():
        return {"leido": False, "avisos": ["El servidor no tiene instalado el lector de documentos (OCR)"]}
    datos_mrz, avisos, domicilio = None, [], {}
    imagenes = []
    for contenido in caras:
        imagenes += a_imagenes(contenido)[1]
    for img in imagenes:
        r, orientada = _buscar_mrz(img)
        if r and (not datos_mrz or r["checks_ok"] > datos_mrz["checks_ok"]):
            datos_mrz = r
        if not domicilio:
            domicilio = _domicilio(orientada)
    if not datos_mrz:
        return {"leido": False, "domicilio": domicilio,
                "avisos": ["No se ha encontrado la zona de lectura mecánica (líneas con <<<). Escanee la cara "
                           "que la contiene (reverso del DNI/NIE, página de la foto del pasaporte), recta y nítida."]}
    if not datos_mrz["mrz_valido"]:
        avisos.append("Algún dígito de control no cuadra: revise número de documento y fechas.")
    if datos_mrz["fecha_caducidad"] and datos_mrz["fecha_caducidad"] < date.today():
        avisos.append(f"DOCUMENTO CADUCADO el {datos_mrz['fecha_caducidad']:%d/%m/%Y}.")
    if datos_mrz["documento_tipo"] != "DNI":
        domicilio = {}  # solo el DNI español lleva el domicilio impreso
    elif domicilio:
        domicilio["pais"] = "España"
        avisos.append("Domicilio leído del DNI: revíselo y complete el código postal (el DNI no lo incluye).")
    avisos.append("Los nombres de la zona de lectura mecánica no llevan tildes: añádalas si procede.")
    out = {k: v for k, v in datos_mrz.items() if k not in ("checks_ok", "checks_total")}
    for k in ("fecha_nacimiento", "fecha_caducidad"):
        out[k] = out[k].isoformat() if out[k] else None
    return {"leido": True, **out, "domicilio": domicilio, "avisos": avisos}
