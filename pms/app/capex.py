"""CAPEX: cálculo del presupuesto (PEM, gastos generales, beneficio industrial, PBL e IVA), cuadro comparativo de
ofertas con su mapa de calor, Excel ciego para los contratistas (sin precios base) y su lectura, y PDF del comparativo.

Los precios unitarios (base y ofertas) son de ejecución material: el PMS suma a todos por igual los gastos generales
y el beneficio industrial del proyecto, así las ofertas se comparan en las mismas condiciones."""
import hashlib
import io
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import settings
from .models import (Asset, CapexItem, CapexProject, Supplier, SupplierBid, TenderInvite, TenderProcess)

# Desviación de la oferta frente al precio base (mapa de calor)
NIVELES = (  # (límite superior de la desviación, nivel)
    (-0.25, "anormal"),  # posible baja anormal: comprobar que la oferta está bien entendida
    (-0.10, "bajo"),
    (0.10, "ok"),
    (0.25, "alto"),
)
NIVEL_TXT = {"anormal": "Baja anormal (≤ −25 %)", "bajo": "Por debajo (−25 % a −10 %)", "ok": "En precio (±10 %)",
             "alto": "Por encima (+10 % a +25 %)", "exceso": "Exceso (> +25 %)", "sin_precio": "Sin precio",
             "sin_base": "Sin precio base"}
COLORES = {"anormal": "#cfe0f7", "bajo": "#dff1e4", "ok": "#ffffff", "alto": "#fdecc8", "exceso": "#f7cdc8",
           "sin_precio": "#eeeeee", "sin_base": "#ffffff"}


def r2(x) -> float:
    return round(float(x or 0) + 0.0, 2)


def partidas(db: Session, pid: int) -> list[CapexItem]:
    return list(db.scalars(select(CapexItem).where(CapexItem.project_id == pid)
                           .order_by(CapexItem.capitulo, CapexItem.orden, CapexItem.id)))


def capitulos(items: list[CapexItem]) -> list[tuple[str, str]]:
    vistos: dict[str, str] = {}
    for x in items:
        vistos.setdefault(x.capitulo, x.capitulo_nombre)
    return sorted(vistos.items())


def importes(p: CapexProject, pem: float) -> dict:
    gg, bi = r2(pem * float(p.gg_pct) / 100), r2(pem * float(p.bi_pct) / 100)
    pbl = r2(pem + gg + bi)
    iva = r2(pbl * float(p.iva_pct) / 100)
    return {"pem": r2(pem), "gg": gg, "bi": bi, "pbl": pbl, "iva": iva, "total": r2(pbl + iva)}


def totales(p: CapexProject, items: list[CapexItem]) -> dict:
    caps = []
    for cod, nombre in capitulos(items):
        caps.append({"capitulo": cod, "nombre": nombre, "partidas": sum(1 for x in items if x.capitulo == cod),
                     "importe": r2(sum(float(x.cantidad) * float(x.precio) for x in items if x.capitulo == cod))})
    t = importes(p, sum(c["importe"] for c in caps))
    t["capitulos"] = caps
    objetivo = float(p.presupuesto_objetivo) if p.presupuesto_objetivo else None
    t["desviacion_objetivo"] = round((t["pbl"] - objetivo) / objetivo * 100, 1) if objetivo else None
    return t


def codigo_nuevo(db: Session, anio: int | None = None) -> str:
    anio = anio or date.today().year
    n = db.scalar(select(func.count(CapexProject.id)).where(CapexProject.codigo.like(f"CPX-{anio}-%"))) or 0
    while True:
        n += 1
        cod = f"CPX-{anio}-{n:03d}"
        if not db.scalar(select(CapexProject.id).where(CapexProject.codigo == cod)):
            return cod


# --------------------------------------------------------------------------- comparativo
def nivel(base: float, oferta: float | None) -> tuple[str, float | None]:
    if oferta is None:
        return "sin_precio", None
    if not base:
        return "sin_base", None
    d = (oferta - base) / base
    for lim, n in NIVELES:
        if d <= lim:
            return n, round(d * 100, 1)
    return "exceso", round(d * 100, 1)


def ofertas(db: Session, pid: int, solo_enviadas: bool = True) -> list[SupplierBid]:
    stmt = (select(SupplierBid).join(TenderProcess, TenderProcess.id == SupplierBid.tender_id)
            .where(TenderProcess.project_id == pid))
    if solo_enviadas:
        stmt = stmt.where(SupplierBid.estado == "enviada")
    return list(db.scalars(stmt.order_by(SupplierBid.id)))


def precio_oferta(b: SupplierBid, item_id: int) -> float | None:
    v = (b.precios or {}).get(str(item_id))
    return float(v) if v is not None and v != "" else None


def comparativo(db: Session, p: CapexProject) -> dict:
    items = partidas(db, p.id)
    bids = ofertas(db, p.id)
    nombres = {s.id: s.nombre for s in db.scalars(select(Supplier).where(Supplier.id.in_([b.supplier_id for b in bids] or [-1])))}
    filas = []
    for x in items:
        base = float(x.precio)
        celdas = {}
        for b in bids:
            pr = precio_oferta(b, x.id)
            n, d = nivel(base, pr)
            celdas[b.id] = {"precio": pr, "importe": r2(pr * float(x.cantidad)) if pr is not None else None,
                            "desviacion": d, "nivel": n}
        validos = [c["precio"] for c in celdas.values() if c["precio"] is not None]
        filas.append({"id": x.id, "capitulo": x.capitulo, "codigo": x.codigo, "descripcion": x.descripcion,
                      "unidad": x.unidad, "cantidad": float(x.cantidad), "precio_base": base,
                      "importe_base": r2(base * float(x.cantidad)), "ofertas": celdas,
                      "mejor": min(validos) if validos else None})
    caps = []
    for cod, nombre in capitulos(items):
        de = [f for f in filas if f["capitulo"] == cod]
        base = r2(sum(f["importe_base"] for f in de))
        por = {}
        for b in bids:
            imp = [f["ofertas"][b.id]["importe"] for f in de]
            tot = r2(sum(i for i in imp if i is not None))
            n, d = nivel(base, tot if all(i is not None for i in imp) else None)
            por[b.id] = {"importe": tot, "completo": all(i is not None for i in imp), "desviacion": d, "nivel": n}
        validos = [(v["importe"], k) for k, v in por.items() if v["completo"]]
        caps.append({"capitulo": cod, "nombre": nombre, "importe_base": base, "ofertas": por,
                     "mejor": min(validos)[1] if validos else None})
    base_total = importes(p, sum(c["importe_base"] for c in caps))
    resumen = []
    for b in bids:
        pem = sum(c["ofertas"][b.id]["importe"] for c in caps)
        faltan = sum(1 for f in filas if f["ofertas"][b.id]["precio"] is None)
        t = importes(p, pem)
        n, d = nivel(base_total["pem"], pem if not faltan else None)
        resumen.append({"bid_id": b.id, "proveedor": nombres.get(b.supplier_id, "?"), "supplier_id": b.supplier_id,
                        **t, "faltan": faltan, "completa": not faltan, "desviacion": d, "nivel": n,
                        "plazo_dias": b.plazo_dias, "notas": b.notas, "origen": b.origen,
                        "enviada_en": b.enviada_en.isoformat() if b.enviada_en else None})
    return {"partidas": filas, "capitulos": caps, "base": base_total, "ofertas": resumen, "niveles": NIVEL_TXT,
            "colores": COLORES, "umbral": settings.capex_umbral}


def lote(p: CapexProject, cmp: dict, bid_id: int, caps: list[str]) -> dict:
    """PEM e importe (con GG y BI, sin IVA) de los capítulos adjudicados a una oferta."""
    sel = [c for c in cmp["capitulos"] if not caps or c["capitulo"] in caps]
    pem = sum(c["ofertas"][bid_id]["importe"] for c in sel)
    return importes(p, pem)


# --------------------------------------------------------------------------- Excel ciego
def _clave_excel(invite_id: int) -> str:
    return hashlib.sha256(f"capex-excel:{invite_id}:{settings.secret_key}".encode()).hexdigest()[:16]


def excel_ciego(db: Session, p: CapexProject, inv: TenderInvite) -> bytes:
    """Plantilla Excel protegida: solo se pueden escribir los precios unitarios (celdas amarillas)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill, Protection
    t = db.get(TenderProcess, inv.tender_id)
    s = db.get(Supplier, inv.supplier_id)
    a = db.get(Asset, p.asset_id)
    wb = Workbook()
    ws = wb.active
    ws.title = "Oferta"
    ws.append([f"PETICIÓN DE OFERTA {p.codigo} · {p.titulo}"])
    ws.append([f"Activo: {a.nombre}{f' · {p.ubicacion}' if p.ubicacion else ''}"])
    ws.append([f"Contratista: {s.nombre} · Plazo de presentación: {t.fecha_limite:%d/%m/%Y}"])
    ws.append(["Escriba el PRECIO UNITARIO de ejecución material (sin gastos generales, beneficio industrial ni IVA) "
               "en las celdas amarillas y devuelva este fichero sin cambiar nada más."])
    ws.append([])
    ws.append(["ID", "Capítulo", "Código", "Descripción", "Ud", "Cantidad", "Precio unitario €", "Importe €"])
    cab = 6
    amarillo = PatternFill("solid", fgColor="FFF4C2")
    for c in ws[cab]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1A1A1C")
    ws["A1"].font = Font(bold=True, size=13)
    oferta = db.scalar(select(SupplierBid).where(SupplierBid.invite_id == inv.id))
    fila = cab
    for x in partidas(db, p.id):
        fila += 1
        previo = precio_oferta(oferta, x.id) if oferta else None
        ws.append([x.id, f"{x.capitulo} {x.capitulo_nombre}", x.codigo or "", x.descripcion, x.unidad or "",
                   float(x.cantidad), previo, f"=IF(G{fila}=\"\",\"\",ROUND(F{fila}*G{fila},2))"])
        g = ws[f"G{fila}"]
        g.fill, g.protection, g.number_format = amarillo, Protection(locked=False), "#,##0.00"
        ws[f"H{fila}"].number_format = "#,##0.00"
        ws[f"D{fila}"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.append([])
    ws.append(["", "", "", "TOTAL EJECUCIÓN MATERIAL", "", "", "", f"=SUM(H{cab + 1}:H{fila})"])
    ws[f"H{fila + 2}"].font = Font(bold=True)
    ws[f"H{fila + 2}"].number_format = "#,##0.00"
    for col, ancho in zip("ABCDEFGH", (6, 26, 12, 70, 6, 10, 16, 14)):
        ws.column_dimensions[col].width = ancho
    ws.column_dimensions["A"].hidden = True
    ws.freeze_panes = f"A{cab + 1}"
    datos = wb.create_sheet("_pms")
    datos.append(["proyecto", p.id])
    datos.append(["invitacion", inv.id])
    datos.append(["clave", _clave_excel(inv.id)])
    datos.sheet_state = "veryHidden"
    ws.protection.sheet = True
    ws.protection.password = _clave_excel(inv.id)[:8]
    ws.protection.formatColumns = False  # se puede ensanchar columnas
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def leer_excel(db: Session, p: CapexProject, inv: TenderInvite, datos: bytes) -> dict[str, float]:
    """Precios de la plantilla devuelta. Comprueba que es la del proyecto y de este contratista."""
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(datos), data_only=True)
    except Exception:  # noqa: BLE001
        raise ValueError("No se puede leer el fichero: devuelva la plantilla Excel (.xlsx) descargada del PMS")
    if "_pms" not in wb.sheetnames or "Oferta" not in wb.sheetnames:
        raise ValueError("No es la plantilla de oferta del PMS: descárguela de nuevo y rellene los precios")
    meta = {str(r[0].value): r[1].value for r in wb["_pms"].iter_rows(min_row=1, max_row=5) if r[0].value}
    if meta.get("proyecto") != p.id or meta.get("invitacion") != inv.id or meta.get("clave") != _clave_excel(inv.id):
        raise ValueError("Esta plantilla es de otro proyecto o de otro contratista")
    validos = {x.id for x in partidas(db, p.id)}
    precios: dict[str, float] = {}
    for fila in wb["Oferta"].iter_rows(min_row=7):
        iid, pr = fila[0].value, fila[6].value
        if not isinstance(iid, int) or iid not in validos or pr in (None, ""):
            continue
        try:
            v = float(str(pr).replace(",", ".")) if isinstance(pr, str) else float(pr)
        except ValueError:
            raise ValueError(f"Precio no válido en la fila {fila[0].row}: «{pr}»")
        if v < 0:
            raise ValueError(f"Precio negativo en la fila {fila[0].row}")
        precios[str(iid)] = round(v, 2)
    if not precios:
        raise ValueError("La plantilla no tiene ningún precio: rellene las celdas amarillas")
    return precios


# --------------------------------------------------------------------------- PDF del comparativo
def comparativo_pdf(db: Session, p: CapexProject, cmp: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    ss = getSampleStyleSheet()
    peq = ss["BodyText"].clone("peq", fontSize=7, leading=8.5)
    a = db.get(Asset, p.asset_id)
    eur = lambda v: "—" if v is None else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")  # noqa: E731
    out = io.BytesIO()
    doc = SimpleDocTemplate(out, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=10 * mm,
                            bottomMargin=10 * mm, title=f"Comparativo {p.codigo}")
    ofs = cmp["ofertas"]
    h = [Paragraph(f"<b>CUADRO COMPARATIVO · {p.codigo} · {p.titulo}</b>", ss["Title"]),
         Paragraph(f"{a.nombre}{f' · {p.ubicacion}' if p.ubicacion else ''} · {datetime.now():%d/%m/%Y %H:%M} · "
                   f"Precios de ejecución material; importes con GG {float(p.gg_pct):g} % y BI {float(p.bi_pct):g} %, "
                   "sin IVA.", ss["Normal"]), Spacer(1, 3 * mm)]
    # resumen por oferta
    datos = [["", "PBL (base)", *[o["proveedor"][:28] for o in ofs]],
             ["Ejecución material", eur(cmp["base"]["pem"]), *[eur(o["pem"]) for o in ofs]],
             ["Importe (PEM + GG + BI)", eur(cmp["base"]["pbl"]), *[eur(o["pbl"]) for o in ofs]],
             ["Desviación", "", *[("—" if o["desviacion"] is None else f"{o['desviacion']:+.1f} %") for o in ofs]],
             ["Partidas sin precio", "", *[str(o["faltan"]) for o in ofs]],
             ["Plazo (días)", "", *[str(o["plazo_dias"] or "—") for o in ofs]]]
    ancho = (277 * mm - 50 * mm) / (len(ofs) + 1)
    t = Table(datos, colWidths=[50 * mm] + [ancho] * (len(ofs) + 1))
    est = [("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d6cfc0")), ("FONTSIZE", (0, 0), (-1, -1), 8),
           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1c")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
           ("ALIGN", (1, 1), (-1, -1), "RIGHT")]
    for j, o in enumerate(ofs):
        est.append(("BACKGROUND", (j + 2, 3), (j + 2, 3), colors.HexColor(COLORES[o["nivel"]])))
    t.setStyle(TableStyle(est))
    h += [t, Spacer(1, 4 * mm)]
    # por capítulos
    datos = [["Capítulo", "Base", *[o["proveedor"][:20] for o in ofs]]]
    est = [("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d6cfc0")), ("FONTSIZE", (0, 0), (-1, -1), 8),
           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1c")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
           ("ALIGN", (1, 1), (-1, -1), "RIGHT")]
    for i, c in enumerate(cmp["capitulos"], 1):
        datos.append([Paragraph(f"{c['capitulo']} {c['nombre']}", peq), eur(c["importe_base"]),
                      *[eur(c["ofertas"][o["bid_id"]]["importe"]) + ("" if c["ofertas"][o["bid_id"]]["completo"] else " *")
                        for o in ofs]])
        for j, o in enumerate(ofs):
            est.append(("BACKGROUND", (j + 2, i), (j + 2, i), colors.HexColor(COLORES[c["ofertas"][o["bid_id"]]["nivel"]])))
            if c["mejor"] == o["bid_id"]:
                est.append(("FONTNAME", (j + 2, i), (j + 2, i), "Helvetica-Bold"))
    t = Table(datos, colWidths=[70 * mm] + [(207 * mm) / (len(ofs) + 1)] * (len(ofs) + 1), repeatRows=1)
    t.setStyle(TableStyle(est))
    h += [Paragraph("<b>Por capítulos</b> (en negrita, la mejor oferta completa; * = faltan precios)", ss["Normal"]),
          t, PageBreak()]
    # por partidas (precio unitario)
    datos = [["Partida", "Ud", "Cant.", "Base", *[o["proveedor"][:16] for o in ofs]]]
    est = [("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d6cfc0")), ("FONTSIZE", (0, 0), (-1, -1), 7),
           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a1c")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
           ("ALIGN", (1, 1), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "TOP")]
    for i, f in enumerate(cmp["partidas"], 1):
        datos.append([Paragraph(f"{f['codigo'] or ''} {f['descripcion'].splitlines()[0][:110]}", peq), f["unidad"] or "",
                      f"{f['cantidad']:g}", eur(f["precio_base"]),
                      *[eur(f["ofertas"][o["bid_id"]]["precio"]) for o in ofs]])
        for j, o in enumerate(ofs):
            est.append(("BACKGROUND", (j + 4, i), (j + 4, i), colors.HexColor(COLORES[f["ofertas"][o["bid_id"]]["nivel"]])))
    resto = 277 * mm - 95 * mm - 12 * mm - 16 * mm
    t = Table(datos, colWidths=[95 * mm, 12 * mm, 16 * mm] + [resto / (len(ofs) + 1)] * (len(ofs) + 1), repeatRows=1)
    t.setStyle(TableStyle(est))
    ley = " · ".join(f'<font backColor="{COLORES[k]}">&nbsp;{v}&nbsp;</font>' for k, v in NIVEL_TXT.items()
                     if k not in ("sin_base",))
    h += [Paragraph("<b>Precios unitarios por partida</b>", ss["Normal"]), t, Spacer(1, 3 * mm), Paragraph(ley, peq)]
    doc.build(h)
    return out.getvalue()
