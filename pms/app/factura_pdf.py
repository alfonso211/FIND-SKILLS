"""Factura en PDF (A4) con los datos que exige el reglamento de facturación (RD 1619/2012, art. 6)."""
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .facturacion import FORMAS_PAGO
from .models import Invoice

AZUL = colors.HexColor("#13294b")
GRIS = colors.HexColor("#6b7785")
LINEA = colors.HexColor("#d5dbe3")


def _eur(x) -> str:
    s = f"{Decimal(str(x)):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{s} €"


def _fecha(d) -> str:
    return d.strftime("%d/%m/%Y")


def _esc(s) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def generar(f: Invoice, asset, original: Invoice | None = None) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Factura {f.codigo}", author=f.emisor["nombre"])
    ss = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=ss["Normal"], fontName="Helvetica", fontSize=9.5, leading=13)
    peq = ParagraphStyle("p", parent=normal, fontSize=8, leading=10.5, textColor=GRIS)
    titulo = ParagraphStyle("t", parent=normal, fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=AZUL,
                            alignment=TA_RIGHT)
    der = ParagraphStyle("d", parent=normal, alignment=TA_RIGHT)
    emp = ParagraphStyle("e", parent=normal, fontName="Helvetica-Bold", fontSize=12.5, leading=16, textColor=AZUL)
    rotulo = ParagraphStyle("r", parent=peq, fontName="Helvetica-Bold", textColor=AZUL)

    e, c = f.emisor, f.cliente
    rect = f.tipo == "rectificativa"
    cab = Table([[
        [Paragraph(_esc(e["nombre"]), emp), Paragraph(f"CIF {_esc(e['nif'])}<br/>{_esc(e['domicilio'])}", normal)],
        [Paragraph("FACTURA RECTIFICATIVA" if rect else "FACTURA", titulo),
         Paragraph(f"<b>Nº {_esc(f.codigo)}</b><br/>Fecha de expedición: {_fecha(f.fecha_expedicion)}"
                   + (f"<br/>Fecha de la operación: {_fecha(f.fecha_operacion)}"
                      if f.fecha_operacion != f.fecha_expedicion else ""), der)],
    ]], colWidths=[100 * mm, 74 * mm])
    cab.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    lineas_cli = [f"<b>{_esc(c['nombre'])}</b>"]
    if c.get("nif"):
        lineas_cli.append(f"NIF / Documento: {_esc(c['nif'])}")
    if c.get("domicilio"):
        lineas_cli.append(_esc(c["domicilio"]))
    cli = Table([[Paragraph("CLIENTE", rotulo)], [Paragraph("<br/>".join(lineas_cli), normal)]], colWidths=[174 * mm])
    cli.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.6, LINEA), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f4f6f9")),
                             ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4),
                             ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))

    iva_txt = "Exento" if Decimal(str(f.tipo_iva)) == 0 else f"{Decimal(str(f.tipo_iva)).normalize():f} %"
    det = Table([
        ["Concepto", "Base imponible", "IVA", "Cuota IVA", "Total"],
        [Paragraph(_esc(f.concepto), normal), _eur(f.base_imponible), iva_txt, _eur(f.cuota_iva), _eur(f.total)],
    ], colWidths=[82 * mm, 28 * mm, 16 * mm, 22 * mm, 26 * mm], repeatRows=1)
    det.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.6, LINEA), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))

    tot = Table([["Base imponible", _eur(f.base_imponible)], [f"IVA ({iva_txt})", _eur(f.cuota_iva)],
                 ["TOTAL FACTURA", _eur(f.total)]], colWidths=[40 * mm, 30 * mm], hAlign="RIGHT")
    tot.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT"), ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                             ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"), ("TEXTCOLOR", (0, 2), (-1, 2), AZUL),
                             ("LINEABOVE", (0, 2), (-1, 2), 1, AZUL), ("TOPPADDING", (0, 0), (-1, -1), 3)]))

    cuerpo = [cab, Spacer(1, 9 * mm), cli, Spacer(1, 7 * mm), det, Spacer(1, 4 * mm), tot, Spacer(1, 6 * mm)]
    if rect and original is not None:
        cuerpo.append(Paragraph(
            f"<b>Rectifica la factura {_esc(original.codigo)}</b> de fecha {_fecha(original.fecha_expedicion)} "
            f"(art. 15 RD 1619/2012). Motivo: {_esc(f.motivo)}", normal))
        cuerpo.append(Spacer(1, 3 * mm))
    if f.exencion:
        cuerpo.append(Paragraph(_esc(f.exencion), normal))
        cuerpo.append(Spacer(1, 3 * mm))
    if f.forma_pago:
        cuerpo.append(Paragraph(f"Forma de pago: {_esc(FORMAS_PAGO.get(f.forma_pago, f.forma_pago))}", normal))
    pie = [f"Inmueble: {_esc(asset.nombre)}" + (f", {_esc(asset.direccion)}" if asset.direccion else "")
           + (f", {_esc(asset.cp)}" if asset.cp else "") + (f" {_esc(asset.municipio)}" if asset.municipio else "")]
    if asset.num_registro_turistico:
        pie.append(f"Nº de registro de empresas turísticas de la Comunidad de Madrid: {_esc(asset.num_registro_turistico)}")
    cuerpo += [Spacer(1, 8 * mm), Paragraph("<br/>".join(pie), peq)]
    doc.build(cuerpo)
    return buf.getvalue()
