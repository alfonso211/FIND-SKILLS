"""Parte de incidencia (orden de trabajo) en PDF para entregar a la subcontrata.

Primera parte: datos de la incidencia y fotos de la avería. Segunda parte: en blanco, para que la subcontrata
anote horas, trabajos y materiales, y firmen las dos partes la conformidad.
"""
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

AZUL = colors.HexColor("#13294b")
GRIS = colors.HexColor("#6b7785")
LINEA = colors.HexColor("#c9d1db")
FONDO = colors.HexColor("#f4f6f9")

PRIORIDADES = {"baja": "Baja", "media": "Media", "alta": "Alta", "urgente": "URGENTE"}


def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")


def generar(w, asset, company, unidad, abierta_por: str | None, fotos: list[bytes], categoria: str,
            zona: str | None = None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=f"Parte de incidencia OT-{w.id:05d}", author=company.nombre)
    ss = getSampleStyleSheet()
    n = ParagraphStyle("n", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, leading=12.5)
    peq = ParagraphStyle("p", parent=n, fontSize=8, leading=10, textColor=GRIS)
    rot = ParagraphStyle("r", parent=n, fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=AZUL)
    tit = ParagraphStyle("t", parent=n, fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=AZUL,
                         alignment=TA_RIGHT)
    der = ParagraphStyle("d", parent=n, alignment=TA_RIGHT)
    emp = ParagraphStyle("e", parent=n, fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=AZUL)
    sec = ParagraphStyle("s", parent=n, fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.white)
    ancho = 178 * mm

    def seccion(texto):
        t = Table([[Paragraph(texto, sec)]], colWidths=[ancho])
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), AZUL), ("TOPPADDING", (0, 0), (-1, -1), 3),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return t

    def rejilla(filas, anchos, alto=None):
        t = Table(filas, colWidths=anchos, rowHeights=alto)
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, LINEA), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return t

    def celda(rotulo, valor):
        return [Paragraph(rotulo, rot), Paragraph(_esc(valor) or "&nbsp;", n)]

    direccion = ", ".join(x for x in (asset.direccion, asset.cp, asset.municipio) if x)
    cab = Table([[
        [Paragraph(_esc(company.nombre), emp), Paragraph(f"CIF {_esc(company.cif)}" if company.cif else "", n),
         Paragraph(f"{_esc(asset.nombre)}<br/>{_esc(direccion)}", n)],
        [Paragraph("PARTE DE INCIDENCIA", tit),
         Paragraph(f"<b>Orden de trabajo OT-{w.id:05d}</b><br/>Fecha de apertura: {w.fecha_apertura:%d/%m/%Y}", der)],
    ]], colWidths=[100 * mm, 78 * mm])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    if unidad:
        lugar = " · ".join(x for x in (unidad.bloque, f"planta {unidad.planta}" if unidad.planta else None,
                                        f"{unidad.uso} {unidad.codigo}") if x)
    else:
        lugar = f"Zonas comunes · {zona}" if zona else "Zonas comunes"
    c4 = 178 * mm / 4
    datos = rejilla([
        [celda("UBICACIÓN", lugar), celda("INSTALACIÓN / GREMIO", categoria), celda("TIPO", w.tipo.capitalize()),
         celda("PRIORIDAD", PRIORIDADES.get(w.prioridad, w.prioridad))],
        [celda("SUBCONTRATA / PROVEEDOR", w.proveedor), celda("ASIGNADO A", w.asignado_a),
         celda("FECHA PREVISTA", w.fecha_prevista.strftime("%d/%m/%Y") if w.fecha_prevista else ""),
         celda("AVISO DE", abierta_por)],
    ], [c4] * 4)
    desc = rejilla([[[Paragraph("TÍTULO", rot), Paragraph(f"<b>{_esc(w.titulo)}</b>", n), Spacer(1, 2 * mm),
                      Paragraph("DESCRIPCIÓN DE LA AVERÍA", rot),
                      Paragraph(_esc(w.descripcion) or "&nbsp;", n)]]], [ancho])

    cuerpo = [cab, Spacer(1, 6 * mm), seccion("1. Incidencia"), datos, desc]
    if fotos:
        cuerpo += [Spacer(1, 3 * mm), Paragraph("FOTOS DE LA AVERÍA", rot), Spacer(1, 1.5 * mm)]
        celdas = []
        for f in fotos[:4]:
            img = Image(BytesIO(f))
            esc = min(86 * mm / img.imageWidth, 62 * mm / img.imageHeight)
            img.drawWidth, img.drawHeight = img.imageWidth * esc, img.imageHeight * esc
            celdas.append(img)
        filas = [celdas[i:i + 2] + [""] * (2 - len(celdas[i:i + 2])) for i in range(0, len(celdas), 2)]
        t = Table(filas, colWidths=[89 * mm, 89 * mm])
        t.setStyle(TableStyle([("ALIGN", (0, 0), (-1, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        cuerpo.append(t)

    lineas = lambda k: [[""] for _ in range(k)]  # noqa: E731
    trabajos = Table([[Paragraph("TRABAJOS REALIZADOS / DIAGNÓSTICO", rot)]] + lineas(6), colWidths=[ancho],
                     rowHeights=[6 * mm] + [7.5 * mm] * 6)
    trabajos.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, LINEA),
                                  ("LINEBELOW", (0, 1), (-1, -2), 0.3, LINEA)]))
    materiales = Table([[Paragraph(x, rot) for x in ("MATERIAL EMPLEADO", "CANTIDAD", "OBSERVACIONES")]]
                       + [["", "", ""] for _ in range(5)],
                       colWidths=[90 * mm, 25 * mm, 63 * mm], rowHeights=[6 * mm] + [7 * mm] * 5)
    materiales.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, LINEA), ("BACKGROUND", (0, 0), (-1, 0), FONDO)]))
    horas = rejilla([[celda("EMPRESA", ""), celda("TÉCNICO", ""), celda("FECHA", ""),
                      celda("HORA LLEGADA / SALIDA", "")]], [c4] * 4, alto=[13 * mm])
    estado = Paragraph("Estado al finalizar:&nbsp;&nbsp; [   ] Resuelta &nbsp;&nbsp; [   ] Pendiente de material "
                       "&nbsp;&nbsp; [   ] Requiere otra visita &nbsp;&nbsp; [   ] Presupuesto aparte", n)
    firmas = Table([[Paragraph("Firma técnico de la subcontrata", rot), Paragraph("Conformidad de la propiedad "
                                                                                 "(nombre y firma)", rot)],
                    ["", ""]], colWidths=[89 * mm, 89 * mm], rowHeights=[6 * mm, 24 * mm])
    firmas.setStyle(TableStyle([("BOX", (0, 0), (0, -1), 0.5, LINEA), ("BOX", (1, 0), (1, -1), 0.5, LINEA)]))
    cuerpo += [Spacer(1, 5 * mm), KeepTogether([
        seccion("2. A rellenar por la subcontrata"), horas, Spacer(1, 2 * mm), trabajos, Spacer(1, 2 * mm),
        materiales, Spacer(1, 3 * mm), estado, Spacer(1, 4 * mm), firmas, Spacer(1, 3 * mm),
        Paragraph(f"Devuelva este parte firmado junto con la factura, indicando la referencia OT-{w.id:05d}. "
                  "La orden no se da por cerrada hasta que la propiedad confirma el trabajo.", peq)])]
    doc.build(cuerpo)
    return buf.getvalue()
