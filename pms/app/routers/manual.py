"""Manual de uso por puesto (dirección, recepción, mantenimiento, limpieza) y novedades de cada actualización.
El texto está en app/manual/*.md: se actualiza con cada versión del programa y se descarga en PDF para enviarlo."""
import io
import re
from datetime import date
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response

from .. import marca
from ..security import Scope, get_scope

router = APIRouter(prefix="/api/manual", tags=["manual de uso"])
MANUAL_DIR = Path(__file__).resolve().parent.parent / "manual"

SECCIONES = {  # id: título (orden del menú)
    "comun": "Primeros pasos",
    "recepcion": "Recepción",
    "direccion": "Dirección y administración",
    "mantenimiento": "Mantenimiento",
    "limpieza": "Limpieza",
    "novedades": "Novedades",
}
POR_ROL = {
    "Recepción": "recepcion",
    "Técnico Mantenimiento": "mantenimiento",
    "Gobernanta / Limpieza": "limpieza",
}  # el resto de roles (dirección, administración, gestor, consulta): manual de dirección


def texto(seccion: str) -> str:
    if seccion not in SECCIONES:
        raise HTTPException(404, "Sección del manual no encontrada")
    return (MANUAL_DIR / f"{seccion}.md").read_text(encoding="utf-8")


def version() -> str:
    """Última versión publicada: el primer apartado «## …» de las novedades."""
    m = re.search(r"^## (.+)$", texto("novedades"), re.M)
    return m.group(1).strip() if m else ""


def recomendada(scope: Scope) -> str:
    roles = [a.role.nombre for a in scope.user.assignments]
    return next((POR_ROL[r] for r in roles if r in POR_ROL), "direccion")


@router.get("")
def index(scope: Scope = Depends(get_scope)):
    return {"secciones": [{"id": k, "titulo": v} for k, v in SECCIONES.items()],
            "recomendada": recomendada(scope), "version": version()}


@router.get("/{seccion}")
def section(seccion: str, _: Scope = Depends(get_scope)):
    return {"id": seccion, "titulo": SECCIONES.get(seccion), "texto": texto(seccion)}


def _en_linea(s: str) -> str:
    """Markdown en línea (negrita, cursiva, código) a las etiquetas de los párrafos de reportlab."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", s)
    return re.sub(r"`(.+?)`", r"<font face='Courier'>\1</font>", s)


def pdf(secciones: list[str], titulo: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

    base = getSampleStyleSheet()
    oro = colors.HexColor(marca.ORO)
    st = {
        "t": ParagraphStyle("t", parent=base["Title"], fontSize=20, textColor=colors.HexColor(marca.NEGRO)),
        "h1": ParagraphStyle("h1", parent=base["Heading1"], fontSize=16, textColor=oro, spaceBefore=4),
        "h2": ParagraphStyle("h2", parent=base["Heading2"], fontSize=12.5, spaceBefore=8),
        "h3": ParagraphStyle("h3", parent=base["Heading3"], fontSize=11, spaceBefore=6),
        "p": ParagraphStyle("p", parent=base["BodyText"], fontSize=10, leading=13.5),
    }
    st["li"] = ParagraphStyle("li", parent=st["p"], leftIndent=14, bulletIndent=4)
    st["li2"] = ParagraphStyle("li2", parent=st["p"], leftIndent=28, bulletIndent=18)

    cuerpo = []
    logo = marca.imagen_pdf("inversiete", 60 * mm, 18 * mm)
    if logo:
        cuerpo += [logo, Spacer(1, 6 * mm)]
    cuerpo += [Paragraph(f"{marca.NOMBRE} · {_en_linea(titulo)}", st["t"]),
               Paragraph(f"Versión: {_en_linea(version())} · Edición del {date.today():%d/%m/%Y}", st["p"]),
               Spacer(1, 6 * mm)]
    for i, sec in enumerate(secciones):
        if i:
            cuerpo.append(PageBreak())
        for linea in texto(sec).splitlines():
            ln = linea.rstrip()
            if not ln.strip():
                continue
            if m := re.match(r"^(#{1,3}) (.+)", ln):
                cuerpo.append(Paragraph(_en_linea(m.group(2)), st["h" + str(len(m.group(1)))]))
            elif m := re.match(r"^(\s*)[-*] (.+)", ln):
                cuerpo.append(Paragraph(_en_linea(m.group(2)), st["li2" if m.group(1) else "li"], bulletText="•"))
            elif m := re.match(r"^(\s*)(\d+)\. (.+)", ln):
                cuerpo.append(Paragraph(_en_linea(m.group(3)), st["li2" if m.group(1) else "li"],
                                        bulletText=m.group(2) + "."))
            elif ln.startswith("> "):
                cuerpo.append(Paragraph("<i>" + _en_linea(ln[2:]) + "</i>", st["li"]))
            else:
                cuerpo.append(Paragraph(_en_linea(ln), st["p"]))

    def pie(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(18 * mm, 10 * mm, f"{marca.NOMBRE} · Manual de uso · {titulo}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Página {doc.page}")
        canvas.restoreState()

    out = io.BytesIO()
    SimpleDocTemplate(out, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                      bottomMargin=18 * mm, title=f"Manual de uso · {titulo}", author=marca.NOMBRE
                      ).build(cuerpo, onFirstPage=pie, onLaterPages=pie)
    return out.getvalue()


@router.get("/{seccion}/pdf")
def section_pdf(seccion: str, _: Scope = Depends(get_scope)):
    """PDF para enviar: el manual de un puesto (con los primeros pasos y las novedades) o solo las novedades."""
    texto(seccion)
    if seccion == "novedades":
        partes, nombre = ["novedades"], "Novedades"
    elif seccion == "comun":
        partes, nombre = ["comun", "novedades"], "Primeros pasos"
    else:
        partes, nombre = ["comun", seccion, "novedades"], SECCIONES[seccion]
    datos = pdf(partes, nombre)
    fichero = f"Manual_{re.sub(r'[^A-Za-z0-9]+', '_', seccion.capitalize())}_{date.today():%Y%m%d}.pdf"
    return Response(datos, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{fichero}"', "Cache-Control": "no-store"})
