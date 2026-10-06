"""Lectura automática de documentos de identidad escaneados (imagen o PDF), en el propio servidor.

1. Se endereza la imagen: giro de 90/180/270° e inclinación fina (fotos de cámara con el documento torcido).
2. Se localizan las líneas de la zona MRZ («<<<»), se recortan y se amplían; se leen con el modelo de Tesseract
   entrenado para la zona MRZ (fuente OCR-B, app/tessdata) con varias preparaciones de la imagen hasta que los
   dígitos de control cuadran y dos lecturas coinciden. El modelo general (eng) queda de reserva.
   Las fotos de móvil (12 MP) se reducen antes de leerlas y cada documento tiene un tiempo máximo: nunca se queda
   «pensando».
3. En el DNI español se intenta además leer el domicilio del reverso (texto libre: es una propuesta
   que recepción debe revisar).
El operario puede indicar el tipo de documento y la cara: el anverso de un DNI/NIE no lleva zona MRZ y solo se
guarda la copia. Nada se envía a servicios externos.
"""
import io
import os
import re
import shutil
import time
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from . import mrz
from .vigilante import trabajo_pesado

FORMATOS = {"image/jpeg", "image/png", "image/webp", "image/tiff", "image/bmp", "application/pdf"}
TAM_MAX = 15 * 1024 * 1024
WHITELIST_MRZ = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
FIN_DOMICILIO = ("LUGAR DE NAC", "HIJO", "EQUIPO", "NACIMIENTO", "IDESP", "IRESP")
TIPOS = {"DNI": "DNI", "NIE": "NIE / TIE", "PAS": "Pasaporte", "OTRO": "Otro documento"}
CON_DOS_CARAS = ("DNI", "NIE")  # tarjetas: la zona MRZ está en el reverso
TESSDATA = Path(__file__).parent / "tessdata"
LADO_MAX = 2600  # px: una foto de móvil de 12 MP se reduce (la zona MRZ sigue con letras de sobra)
TIEMPO_DOCUMENTO = 30  # s como máximo por documento; pasado ese tiempo se responde con lo que haya
# Tesseract usa por defecto todos los núcleos en cada lectura: con varias lecturas a la vez se estorban.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")


def modelos_mrz() -> list[str]:
    """Primero el modelo entrenado para la MRZ (OCR-B); el general de Tesseract, de reserva."""
    return (["mrz"] if (TESSDATA / "mrz.traineddata").exists() else []) + ["eng"]


def disponible() -> bool:
    return shutil.which("tesseract") is not None


def a_imagenes(datos: bytes) -> tuple[str, list[Image.Image]]:
    """Comprueba el fichero por su contenido (no por la extensión) y lo convierte en imágenes."""
    if datos[:5] == b"%PDF-":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(datos)
        paginas = []
        for i in range(min(len(pdf), 2)):  # 300 ppp, como mucho 4.000 px de lado (una página enorme no agota la memoria)
            ancho, alto = pdf[i].get_size()
            paginas.append(pdf[i].render(scale=min(300 / 72, 4000 / max(ancho, alto, 1))).to_pil())
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


OCR_TIEMPO = 20  # s por lectura: una imagen rara no puede dejar a Tesseract trabajando indefinidamente


def _ocr(img: Image.Image, **kw) -> str:
    import pytesseract
    try:
        return pytesseract.image_to_string(img, timeout=OCR_TIEMPO, **kw)
    except RuntimeError:  # tiempo agotado: se trata como lectura vacía
        return ""


def _a_ancho(img: Image.Image, ancho: int) -> Image.Image:
    f = ancho / img.width
    return img.resize((max(1, int(img.width * f)), max(1, int(img.height * f))), Image.LANCZOS)


def _tinta(g: Image.Image) -> Image.Image:
    """Trazos oscuros respecto a su entorno: no depende de la iluminación ni de los reflejos."""
    a = np.asarray(g, dtype=np.int16)
    m = np.asarray(g.filter(ImageFilter.BoxBlur(max(3, g.width // 60))), dtype=np.int16)
    return Image.fromarray(((m - a) > 18).astype(np.uint8) * 255)


def _horizontalidad(t: Image.Image, angulo: float) -> float:
    filas = np.asarray(t.rotate(angulo, expand=True), dtype=np.int64).sum(axis=1)
    return float(np.square(np.diff(filas)).sum())


def _angulo(g: Image.Image) -> float:
    """Giro que deja las líneas de texto horizontales (0/90° más una inclinación de hasta ±12°)."""
    peq = g.copy()
    peq.thumbnail((1000, 1000))
    t = _tinta(peq)
    mejor = max((_horizontalidad(t, base + a), base + a) for base in (0, 90) for a in range(-12, 13))
    fino = max((_horizontalidad(t, mejor[1] + d / 10), mejor[1] + d / 10) for d in range(-9, 10, 3))
    return fino[1]


def _cajas_mrz(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Zona de las líneas MRZ: palabras con «<<» o cadenas largas en mayúsculas y números."""
    import pytesseract
    try:
        d = pytesseract.image_to_data(img, lang="eng", config="--psm 11", output_type=pytesseract.Output.DICT,
                                      timeout=OCR_TIEMPO)
    except RuntimeError:
        return None
    cajas = []
    for i, t in enumerate(d["text"]):
        t = t.strip()
        if t.count("<") >= 2 or (len(t) >= 14 and t.upper() == t and sum(c.isalnum() or c == "<" for c in t) >= len(t) - 1):
            cajas.append((d["left"][i], d["top"][i], d["left"][i] + d["width"][i], d["top"][i] + d["height"][i]))
    if not cajas:
        return None
    x0, y0 = min(c[0] for c in cajas), min(c[1] for c in cajas)
    x1, y1 = max(c[2] for c in cajas), max(c[3] for c in cajas)
    h = y1 - y0
    y0, y1 = max(0, y0 - h), min(img.height, y1 + h)  # puede faltar una línea entera por detectar
    # a lo ancho: hasta donde siga habiendo texto (el principio de la línea no siempre se detecta como palabra)
    columnas = np.asarray(_tinta(img.crop((0, y0, img.width, y1))), dtype=bool).any(axis=0)
    hueco = max(25, (y1 - y0) // 6)
    while x0 > 0 and columnas[max(0, x0 - hueco):x0].any():
        x0 -= 1
    while x1 < img.width and columnas[x1:x1 + hueco].any():
        x1 += 1
    margen = hueco // 2
    return max(0, x0 - margen), y0, min(img.width, x1 + margen), y1


def _variantes(recorte: Image.Image):
    """Preparaciones de la zona MRZ, de la más rápida a la más costosa."""
    base = _a_ancho(recorte, 1600) if recorte.width < 1600 else recorte
    yield ImageOps.autocontrast(base)
    yield ImageOps.invert(_tinta(base))  # umbral local: resiste reflejos y sombras
    yield ImageOps.autocontrast(_a_ancho(recorte, 2400).filter(ImageFilter.UnsharpMask(2, 120, 3)))
    yield ImageOps.autocontrast(base).point(lambda v: 255 if v > 140 else 0)


def _lee_mrz(img: Image.Image, modelo: str = "eng") -> dict | None:
    datos = f"--tessdata-dir {TESSDATA} " if modelo == "mrz" else ""
    txt = _ocr(img, lang=modelo, config=f"{datos}--psm 6 -c tessedit_char_whitelist={WHITELIST_MRZ}")
    return mrz.interpretar([ln.replace(" ", "") for ln in txt.splitlines() if ln.strip()])


def _firma(r: dict) -> tuple:
    return r["documento_tipo"], r["documento_num"], r["fecha_nacimiento"], r["fecha_caducidad"]


def _buscar_mrz(img: Image.Image, limite: float | None = None) -> tuple[dict | None, Image.Image]:
    """Las letras confundibles con cifras (L/1, B/1, A/0…) pueden cuadrar igual con el dígito de control: se
    leen varias preparaciones de la imagen y se da por buena la lectura en la que coinciden al menos dos.
    `limite` (time.monotonic): pasado ese momento no se intentan más lecturas."""
    limite = limite or time.monotonic() + TIEMPO_DOCUMENTO
    g = ImageOps.grayscale(img)
    if max(g.size) > LADO_MAX:
        g.thumbnail((LADO_MAX, LADO_MAX), Image.LANCZOS)
    angulo = _angulo(g)
    mejor, orientada, validas = None, None, []
    for extra in (0, 180):  # al revés: la inclinación es la misma
        if time.monotonic() > limite:
            break
        im = g.rotate(angulo + extra, expand=True, fillcolor=255, resample=Image.BICUBIC)
        if im.width < 2000:
            im = _a_ancho(im, 2000)
        im = ImageOps.autocontrast(im)
        if orientada is None:
            orientada = im
        zona = _cajas_mrz(im)
        recortes = ([im.crop(zona)] if zona else []) + [im.crop((0, int(im.height * 0.5), im.width, im.height))]
        preparadas = [list(_variantes(recorte)) if n == 0 and zona else [ImageOps.autocontrast(recorte)]
                      for n, recorte in enumerate(recortes)]
        intentos = [(modelo, v) for vs in preparadas for modelo in modelos_mrz() for v in vs]
        for modelo, variante in intentos:
            if time.monotonic() > limite:
                break
            r = _lee_mrz(variante, modelo)
            if not r:
                continue
            if r["mrz_valido"]:
                orientada = im
                if any(_firma(v) == _firma(r) for v in validas):
                    return r, im
                validas.append(r)
            elif not mejor or r["checks_ok"] > mejor["checks_ok"]:
                mejor = r
        if validas:
            break
    if validas:  # sin coincidencia: la más repetida; a igualdad, la primera
        return max(validas, key=lambda v: sum(_firma(x) == _firma(v) for x in validas)), orientada
    return mejor, orientada


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


def _como_caras(caras) -> list[tuple[str, bytes]]:
    return [c if isinstance(c, tuple) else ("anverso" if n == 0 else "reverso", c) for n, c in enumerate(caras)]


def leer(caras, tipo: str | None = None) -> dict:
    with trabajo_pesado("lectura de documentos"):
        return _leer(caras, tipo)


def _leer(caras, tipo: str | None = None) -> dict:
    """Lee las caras del documento ([bytes] o [(cara, bytes)]) y devuelve los datos encontrados y los avisos.
    `tipo` (DNI, NIE, PAS, OTRO) es lo que indica el operario: con DNI/NIE el anverso no se lee (no lleva MRZ)."""
    if not disponible():
        return {"leido": False, "avisos": ["El servidor no tiene instalado el lector de documentos (OCR)"]}
    tipo = tipo if tipo in TIPOS else None
    caras = _como_caras(caras)
    if tipo in CON_DOS_CARAS:
        a_leer = [c for c in caras if c[0] == "reverso"]
        if not a_leer:
            return {"leido": False, "solo_copia": True,
                    "avisos": [f"Anverso del {TIPOS[tipo]} guardado. Para leer los datos, escanee ahora el "
                               "reverso (la cara con las líneas «<<<»)."]}
    else:
        a_leer = caras
    datos_mrz, avisos, domicilio = None, [], {}
    imagenes = []
    for _, contenido in a_leer:
        imagenes += a_imagenes(contenido)[1]
    limite = time.monotonic() + TIEMPO_DOCUMENTO  # para todas las caras juntas
    for img in imagenes:
        if datos_mrz and datos_mrz["mrz_valido"] or time.monotonic() > limite:
            break
        r, orientada = _buscar_mrz(img, limite)
        if r and (not datos_mrz or r["checks_ok"] > datos_mrz["checks_ok"]):
            datos_mrz = r
        # el domicilio solo lo lleva el DNI español, en la mitad superior del reverso
        es_dni = (r or {}).get("documento_tipo") == "DNI" if r else tipo == "DNI"
        if not domicilio and es_dni and tipo in (None, "DNI") and time.monotonic() < limite:
            domicilio = _domicilio(orientada.crop((0, 0, orientada.width, int(orientada.height * 0.6))))
    if not datos_mrz:
        donde = {"DNI": "el reverso del DNI", "NIE": "el reverso de la tarjeta NIE/TIE",
                 "PAS": "la página de la foto del pasaporte"}.get(tipo, "la cara que las contiene")
        return {"leido": False, "domicilio": domicilio,
                "avisos": [f"No se han podido leer las líneas «<<<». Escanee {donde} recto, nítido, sin reflejos "
                           "y ocupando todo el marco. Si no se lee, complete los datos a mano."]}
    if tipo and datos_mrz["documento_tipo"] != tipo and not (tipo == "OTRO" and datos_mrz["documento_tipo"] == "OTRO"):
        avisos.append(f"Ha indicado «{TIPOS[tipo]}», pero el documento leído es "
                      f"«{TIPOS.get(datos_mrz['documento_tipo'], datos_mrz['documento_tipo'])}»: se usa lo leído.")
    if not datos_mrz["mrz_valido"]:
        avisos.append("Algún dígito de control no cuadra: revise número de documento y fechas.")
    elif datos_mrz.get("corregido"):
        avisos.append("Se ha corregido alguna cifra poco nítida con los dígitos de control: compruebe las fechas.")
    if datos_mrz["fecha_caducidad"] and datos_mrz["fecha_caducidad"] < date.today():
        avisos.append(f"DOCUMENTO CADUCADO el {datos_mrz['fecha_caducidad']:%d/%m/%Y}.")
    if datos_mrz["documento_tipo"] != "DNI":
        domicilio = {}  # solo el DNI español lleva el domicilio impreso
    elif domicilio:
        domicilio["pais"] = "España"
        avisos.append("Domicilio leído del DNI: revíselo y complete el código postal (el DNI no lo incluye).")
    avisos.append("Los nombres de la zona de lectura mecánica no llevan tildes: añádalas si procede.")
    out = {k: v for k, v in datos_mrz.items() if k not in ("checks_ok", "checks_total", "corregido")}
    for k in ("fecha_nacimiento", "fecha_caducidad"):
        out[k] = out[k].isoformat() if out[k] else None
    return {"leido": True, **out, "domicilio": domicilio, "avisos": avisos}
