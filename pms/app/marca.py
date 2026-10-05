"""Identidad corporativa INVERPMS: logotipos de las sociedades del grupo y de los activos.

Los ficheros están en static/marca/<clave>-claro.png (para fondo blanco: facturas, partes) y
<clave>-oscuro.png (para fondo negro: menú lateral, acceso)."""
from pathlib import Path

NOMBRE = "INVERPMS"
MARCA_DIR = Path(__file__).resolve().parent.parent / "static" / "marca"

LOGO_SOCIEDAD = {  # por CIF
    "A78072915": "inversiete",
    "A28362309": "comercial_del_campo",
    "A28309433": "edificios_cameranos",
}
LOGO_ACTIVO = {  # por código de activo
    "SFL": "suite_florida",
    "SAE": "suite_aeropuerto",
}


def _norm(cif: str | None) -> str:
    return (cif or "").replace("-", "").replace(" ", "").upper()


def clave_sociedad(cif: str | None) -> str | None:
    return LOGO_SOCIEDAD.get(_norm(cif))


def clave_activo(codigo: str | None) -> str | None:
    return LOGO_ACTIVO.get((codigo or "").upper())


def url(clave: str | None, variante: str = "oscuro") -> str | None:
    return f"/static/marca/{clave}-{variante}.png" if clave else None


def fichero(clave: str | None, variante: str = "claro") -> Path | None:
    if not clave:
        return None
    p = MARCA_DIR / f"{clave}-{variante}.png"
    return p if p.exists() else None


def imagen_pdf(clave: str | None, ancho_max: float, alto_max: float, variante: str = "claro"):
    """Logotipo como imagen de reportlab, escalado para caber en ancho_max × alto_max (puntos). None si no hay."""
    p = fichero(clave, variante)
    if p is None:
        return None
    from reportlab.platypus import Image
    img = Image(str(p))
    esc = min(ancho_max / img.imageWidth, alto_max / img.imageHeight)
    img.drawWidth, img.drawHeight = img.imageWidth * esc, img.imageHeight * esc
    return img


def cabecera_pdf(clave_izq: str | None, clave_der: str | None, ancho: float, alto: float):
    """Banda de logotipos (sociedad a la izquierda, activo a la derecha) con filete dorado. None si no hay logos."""
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle
    izq = imagen_pdf(clave_izq, ancho * 0.4, alto)
    der = imagen_pdf(clave_der, ancho * 0.45, alto * 0.62)
    if izq is None and der is None:
        return None
    t = Table([[izq or "", der or ""]], colWidths=[ancho / 2, ancho / 2])
    t.setStyle(TableStyle([("ALIGN", (0, 0), (0, 0), "LEFT"), ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                           ("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.HexColor(ORO))]))
    return t


NEGRO = "#1a1a1c"
ORO = "#b08d45"
