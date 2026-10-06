"""Recibo de entrega de cantidades del contrato de vivienda (primer periodo, fianza, garantía): quién entrega,
cuánto (en cifra y en letra), por qué concepto y de qué forma."""
from datetime import date
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from . import marca
from .contrato_vivienda import CONCEPTOS, FORMAS_PAGO, _d, dinero, en_letra, euros

NEGRO = colors.HexColor(marca.NEGRO)
GRIS = colors.HexColor("#6b7785")
LINEA = colors.HexColor("#ddd6c8")


def _esc(s) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def forma_texto(e: dict) -> str:
    forma, ref, ent = e.get("forma"), e.get("referencia"), e.get("entidad")
    if forma == "transferencia":
        return "Transferencia bancaria" + (f" a la cuenta {e['cuenta']}" if e.get("cuenta") else "") + \
            (f", referencia {ref}" if ref else "") + (f", fecha valor {_d(e.get('fecha')).strftime('%d/%m/%Y')}"
                                                       if e.get("fecha") else "")
    if forma == "cheque":
        return "Cheque nominativo" + (f" nº {ref}" if ref else "") + (f" de {ent}" if ent else "") + \
            ", salvo buen fin"
    if forma == "aval":
        return "Aval bancario a primer requerimiento" + (f" nº {ref}" if ref else "") + \
            (f" emitido por {ent}" if ent else "") + \
            (f", con vencimiento {_d(e['vencimiento']).strftime('%d/%m/%Y')}" if e.get("vencimiento") else "") + \
            ". Se recibe el documento original, que queda en custodia de la ARRENDADORA"
    if forma == "efectivo":
        return "Efectivo"
    return FORMAS_PAGO.get(forma, forma or "")


def generar(lease, e: dict, numero: str, sociedad, contrato_ref: str, vivienda: str) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=16 * mm,
                            bottomMargin=16 * mm, title=f"Recibo {numero}", author=sociedad.nombre,
                            creator=marca.NOMBRE)
    ss = getSampleStyleSheet()
    normal = ParagraphStyle("n", parent=ss["Normal"], fontName="Helvetica", fontSize=10.5, leading=15)
    peq = ParagraphStyle("p", parent=normal, fontSize=8.5, leading=11, textColor=GRIS)
    titulo = ParagraphStyle("t", parent=normal, fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=NEGRO)
    der = ParagraphStyle("d", parent=normal, alignment=TA_RIGHT)
    ancho = A4[0] - 40 * mm

    t = lease.tenant
    pagador = e.get("pagador") or f"{t.nombre} {t.apellidos or ''}".strip()
    doc_pagador = e.get("pagador_doc") or f"{t.documento_tipo or 'DNI'} {t.documento_num or ''}".strip()
    concepto = e.get("concepto_texto") or CONCEPTOS.get(e["concepto"], e["concepto"])
    if e["concepto"] == "renta_inicial" and e.get("periodo"):
        concepto += f" ({e['periodo']})"
    es_aval = e.get("forma") == "aval"
    fecha = _d(e.get("fecha")) or date.today()

    hist = []
    cab = marca.cabecera_pdf(marca.clave_sociedad(sociedad.cif), marca.clave_activo(lease.unit.asset.codigo),
                             ancho, 18 * mm)
    if cab is not None:
        hist += [cab, Spacer(1, 6 * mm)]
    hist.append(Table([[Paragraph("RECIBO DE ENTREGA" if not es_aval else "RECIBÍ DE AVAL BANCARIO", titulo),
                        Paragraph(f"<b>Nº {_esc(numero)}</b><br/>Fecha: {fecha.strftime('%d/%m/%Y')}", der)]],
                      colWidths=[ancho * 0.6, ancho * 0.4],
                      style=[("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                             ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    hist.append(Spacer(1, 8 * mm))
    importe = f"<b>{euros(e['importe'])} €</b> ({_esc(en_letra(e['importe']))})"
    verbo = "ha recibido en garantía un aval bancario por importe de" if es_aval else "ha recibido la cantidad de"
    hist.append(Paragraph(
        f"<b>{_esc(sociedad.nombre)}</b>, con CIF {_esc(sociedad.cif)}, como ARRENDADORA, declara que {verbo} "
        f"{importe} de D./Dña. <b>{_esc(pagador)}</b>, con {_esc(doc_pagador)}, en relación con el contrato de "
        f"arrendamiento de vivienda ref. <b>{_esc(contrato_ref)}</b> de la vivienda sita en {_esc(vivienda)}.", normal))
    hist.append(Spacer(1, 6 * mm))

    filas = [["Concepto", Paragraph(_esc(concepto), normal)],
             ["Importe", Paragraph(importe, normal)],
             ["Forma de entrega", Paragraph(_esc(forma_texto(e)), normal)]]
    if e.get("observaciones"):
        filas.append(["Observaciones", Paragraph(_esc(e["observaciones"]), normal)])
    tabla = Table(filas, colWidths=[40 * mm, ancho - 40 * mm])
    tabla.setStyle(TableStyle([("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9.5), ("TEXTCOLOR", (0, 0), (0, -1), NEGRO),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINEA),
                               ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    hist += [tabla, Spacer(1, 6 * mm)]

    notas = []
    if e["concepto"] == "fianza":
        notas.append("La fianza legal se depositará en la Agencia de Vivienda Social de la Comunidad de Madrid "
                     "(cláusula 7.1 del contrato) y se devolverá a la finalización del contrato en los términos pactados.")
    if e["concepto"] == "garantia" and not es_aval:
        notas.append("Garantía adicional (art. 36.5 LAU, cláusula 7.2): no devenga intereses y se devolverá a la "
                     "finalización del contrato una vez comprobado el cumplimiento de las obligaciones del ARRENDATARIO.")
    if e.get("forma") == "cheque":
        notas.append("El presente recibo queda condicionado al buen fin del cheque.")
    if e["concepto"] == "renta_inicial":
        notas.append("Este recibo sirve como carta de pago del periodo indicado (cláusula 4.3 del contrato).")
    for n in notas:
        hist.append(Paragraph(_esc(n), peq))
        hist.append(Spacer(1, 2 * mm))
    hist.append(Spacer(1, 18 * mm))

    firmas = Table([[Paragraph("<b>RECIBÍ</b> — LA ARRENDADORA", normal),
                     Paragraph("<b>ENTREGUÉ</b> — EL ARRENDATARIO", normal)],
                    ["\n\n\n", "\n\n\n"],
                    [Paragraph(f"Fdo.: {_esc(e.get('firma_receptor') or '')}<br/>p.p. {_esc(sociedad.nombre)}", peq),
                     Paragraph(f"Fdo.: {_esc(pagador)}", peq)]],
                   colWidths=[ancho / 2, ancho / 2], rowHeights=[None, 22 * mm, None])
    firmas.setStyle(TableStyle([("LINEBELOW", (0, 1), (-1, 1), 0.6, GRIS), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 14)]))
    hist.append(firmas)
    hist.append(Spacer(1, 10 * mm))
    hist.append(Paragraph(f"Registrado en INVERPMS por {_esc(e.get('usuario') or '')}. Importe total: "
                          f"{euros(dinero(e['importe']))} €.", peq))
    doc.build(hist)
    return buf.getvalue()
