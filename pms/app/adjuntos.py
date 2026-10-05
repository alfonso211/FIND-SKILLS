"""Fotos y documentos de las órdenes de trabajo.

Las fotos del móvil se giran según su orientación (EXIF), se reducen a 2000 px y se guardan en JPEG: ocupan
unos 300-500 KB en lugar de varios MB y se quitan los datos de ubicación del teléfono. Los PDF se guardan tal cual.
"""
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError

TAM_MAX = 20 * 1024 * 1024
LADO_MAX = 2000

TIPOS_ADJUNTO = {
    "averia": "Foto de la avería",
    "trabajo": "Foto del trabajo terminado",
    "oca": "Certificado OCA / inspección",
    "factura": "Factura de proveedor",
    "presupuesto": "Presupuesto",
    "otro": "Otro documento",
}
# Lo que puede subir quien solo abre avisos (recepción, limpieza); el resto es de mantenimiento
TIPOS_AVISO = {"averia", "otro"}

_FIRMAS_IMAGEN = (b"\xff\xd8\xff", b"\x89PNG", b"RIFF", b"GIF8")


def normalizar(datos: bytes, nombre: str) -> tuple[bytes, str, str]:
    """Valida el fichero por su contenido. Devuelve (bytes, mime, nombre)."""
    if len(datos) > TAM_MAX:
        raise ValueError("El fichero supera los 20 MB")
    if datos.startswith(b"%PDF"):
        return datos, "application/pdf", nombre if nombre.lower().endswith(".pdf") else f"{nombre}.pdf"
    if datos[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
        raise ValueError("Formato HEIC del iPhone no admitido: en Ajustes > Cámara > Formatos elija "
                         "«Más compatible», o envíe la foto como JPG")
    if not datos.startswith(_FIRMAS_IMAGEN):
        raise ValueError("Formato no admitido: adjunte fotos (JPG, PNG) o documentos PDF")
    try:
        img = Image.open(BytesIO(datos))
        img = ImageOps.exif_transpose(img)
    except (UnidentifiedImageError, OSError):
        raise ValueError("La imagen está dañada o no se puede leer")
    if img.mode not in ("RGB", "L"):
        fondo = Image.new("RGB", img.size, "white")
        fondo.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
        img = fondo
    img.thumbnail((LADO_MAX, LADO_MAX))
    out = BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=85, optimize=True)  # sin EXIF: fuera la ubicación GPS
    base = nombre.rsplit(".", 1)[0] if "." in nombre else nombre
    return out.getvalue(), "image/jpeg", f"{base or 'foto'}.jpg"
