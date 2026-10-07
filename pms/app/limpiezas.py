"""Parte diario de limpieza.

Cada día salen en el parte, ordenadas por prioridad:
1. Limpiezas por salida de un cliente: SOLO cuando recepción ha hecho el check-out (no se prevén por la fecha de
   salida: el cliente puede renovar). Si el apartamento tiene otra llegada, se indica «antes de la llegada del día…»
   (y van primero las que tienen llegada ese mismo día).
2. Limpiezas contratadas por el cliente en su reserva, según el día de inicio y la periodicidad elegidos.
3. Limpiezas extra que añade recepción (no programadas).
Lo que no valida recepción sigue pendiente y pasa al día siguiente («pendiente desde…»).

La limpieza de salida se crea al hacer el check-out; las contratadas se generan solas al consultar el parte (sin duplicarse: «clave» única);
si la reserva se cancela o cambia de fechas, las pendientes que ya no corresponden se anulan.
"""
from datetime import date, datetime, timedelta
from io import BytesIO

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import marca
from .models import CleaningTask, Reservation, Unit, User
from .utils import bad_request

PERIODICIDADES = {
    "unica": "Un día concreto",
    "diaria": "Diaria",
    "cada_2": "Cada 2 días",
    "cada_3": "Cada 3 días",
    "semanal": "Semanal",
    "quincenal": "Quincenal",
    "otra": "Otra (indicar)",
}
PASO = {"diaria": 1, "cada_2": 2, "cada_3": 3, "semanal": 7, "quincenal": 15}
TIPOS = {"salida": "Salida", "contratada": "Contratada", "extra": "Extra"}
VIVAS = ("confirmada", "checkin", "checkout")


def _d(x) -> date | None:
    if x is None or isinstance(x, date):
        return x
    return date.fromisoformat(str(x)[:10])


def fechas_plan(plan: dict | None, entrada: date, salida: date) -> list[date]:
    """Días de limpieza contratada dentro de la estancia (sin el día de entrada ni el de salida: ese día ya se
    limpia por la salida)."""
    if not plan:
        return []
    dentro = lambda d: entrada < d < salida  # noqa: E731
    if plan.get("periodicidad") == "otra":
        return sorted({d for d in (_d(x) for x in plan.get("fechas") or []) if d and dentro(d)})
    inicio = _d(plan.get("inicio"))
    if not inicio:
        return []
    if plan.get("periodicidad") == "unica":
        return [inicio] if dentro(inicio) else []
    paso = PASO.get(plan.get("periodicidad"), 0)
    out, d = [], inicio
    while paso and d < salida:
        if dentro(d):
            out.append(d)
        d += timedelta(days=paso)
    return out


def validar_plan(plan: dict, entrada: date, salida: date) -> dict:
    """Normaliza y comprueba el plan de limpieza de una reserva. Devuelve el plan guardable."""
    per = plan.get("periodicidad")
    if per not in PERIODICIDADES:
        bad_request("Periodicidad de limpieza no válida")
    texto = (plan.get("texto") or "").strip() or None
    out = {"periodicidad": per, "texto": texto}
    if per == "otra":
        if not texto:
            bad_request("Indique la periodicidad de la limpieza")
        fechas = sorted({_d(x) for x in plan.get("fechas") or [] if x})
        if not fechas:
            bad_request("Indique los días de limpieza")
        if any(not (entrada < f < salida) for f in fechas):
            bad_request("Los días de limpieza deben estar dentro de la estancia (sin el día de entrada ni el de salida)")
        out["fechas"] = [f.isoformat() for f in fechas]
    else:
        inicio = _d(plan.get("inicio"))
        if not inicio:
            bad_request("Indique el día de la limpieza")
        if not (entrada < inicio < salida):
            bad_request("El día de la limpieza debe estar dentro de la estancia (sin el día de entrada ni el de salida)")
        out["inicio"] = inicio.isoformat()
    return out


def describir(plan: dict | None) -> str:
    if not plan:
        return ""
    per = plan.get("periodicidad")
    if per == "otra":
        return f"{plan.get('texto')}: " + ", ".join(f"{_d(x):%d/%m}" for x in plan.get("fechas") or [])
    inicio = _d(plan.get("inicio"))
    return (f"{PERIODICIDADES.get(per, per)} desde el {inicio:%d/%m/%Y}" if per != "unica"
            else f"El {inicio:%d/%m/%Y}") if inicio else ""


# --------------------------------------------------------------------------- generación del parte
def _asegura(db: Session, clave: str, **campos) -> CleaningTask:
    t = db.scalar(select(CleaningTask).where(CleaningTask.clave == clave))
    if t is None:
        t = CleaningTask(clave=clave, **campos)
        db.add(t)
    elif t.estado == "anulada":  # vuelve a corresponder (p.ej. se reactivó la reserva)
        t.estado, t.fecha = "pendiente", campos["fecha"]
    elif t.estado == "pendiente" and t.fecha != campos["fecha"]:
        t.fecha = campos["fecha"]
    return t


def sincronizar(db: Session, asset_id: int, dia: date) -> None:
    """Crea las limpiezas contratadas del día y anula las pendientes que ya no corresponden. Las de salida no se
    prevén: las crea el check-out (salida_realizada)."""
    uids = list(db.scalars(select(Unit.id).where(Unit.asset_id == asset_id, Unit.uso != "garaje")))
    if not uids:
        return
    for r in db.scalars(select(Reservation).where(
            Reservation.unit_id.in_(uids), Reservation.limpieza.is_not(None), Reservation.fecha_entrada < dia,
            Reservation.fecha_salida > dia, Reservation.estado.in_(("confirmada", "checkin")))):
        if dia in fechas_plan(r.limpieza, r.fecha_entrada, r.fecha_salida):
            _asegura(db, f"contratada:{r.id}:{dia.isoformat()}", asset_id=asset_id, unit_id=r.unit_id, fecha=dia,
                     tipo="contratada", reservation_id=r.id)
    db.flush()
    # apartamentos pendientes de limpieza sin ninguna limpieza pendiente (p.ej. de antes de existir el parte)
    con_tarea = set(db.scalars(select(CleaningTask.unit_id).where(CleaningTask.unit_id.in_(uids),
                                                                  CleaningTask.estado == "pendiente")))
    for u in db.scalars(select(Unit).where(Unit.id.in_(uids), Unit.estado == "pendiente_limpieza")):
        if u.id not in con_tarea:
            _asegura(db, f"pendiente:{u.id}:{dia.isoformat()}", asset_id=asset_id, unit_id=u.id, fecha=dia,
                     tipo="salida", nota="Pendiente de limpieza")
    # las que ya no corresponden: reserva cancelada, fechas cambiadas o limpieza contratada modificada
    for t in db.scalars(select(CleaningTask).where(CleaningTask.asset_id == asset_id,
                                                   CleaningTask.estado == "pendiente",
                                                   CleaningTask.reservation_id.is_not(None),
                                                   CleaningTask.tipo.in_(("salida", "contratada")))):
        r = db.get(Reservation, t.reservation_id)
        if r is None or r.estado not in VIVAS or r.unit_id != t.unit_id:
            t.estado = "anulada"
        elif t.tipo == "salida" and r.estado != "checkout":
            t.estado = "anulada"  # sin check-out no hay limpieza de salida
        elif t.tipo == "contratada" and (r.estado == "checkout"
                                         or t.fecha not in fechas_plan(r.limpieza, r.fecha_entrada, r.fecha_salida)):
            t.estado = "anulada"
    db.flush()


def salida_realizada(db: Session, r: Reservation) -> CleaningTask | None:
    """Check-out hecho por recepción: la limpieza de salida entra en el parte de ese día."""
    if r.unit.uso == "garaje":
        return None
    return _asegura(db, f"salida:{r.id}", asset_id=r.unit.asset_id, unit_id=r.unit_id, fecha=date.today(),
                    tipo="salida", reservation_id=r.id)


def _proxima_llegada(db: Session, unit_id: int, desde: date) -> Reservation | None:
    return db.scalars(select(Reservation).where(Reservation.unit_id == unit_id, Reservation.estado == "confirmada",
                                                Reservation.fecha_entrada >= desde)
                      .order_by(Reservation.fecha_entrada)).first()


def parte(db: Session, asset_id: int, dia: date) -> list[dict]:
    """Limpiezas del parte del día: las del día y las pendientes de días anteriores (más las ya validadas hoy)."""
    sincronizar(db, asset_id, dia)
    tareas = list(db.scalars(select(CleaningTask).where(
        CleaningTask.asset_id == asset_id,
        ((CleaningTask.estado == "pendiente") & (CleaningTask.fecha <= dia))
        | ((CleaningTask.estado == "hecha") & (CleaningTask.fecha == dia)))))
    nombres = {u.id: u.nombre for u in db.scalars(select(User).where(User.id.in_(
        {t.validada_por for t in tareas if t.validada_por} | {t.creada_por for t in tareas if t.creada_por}
        or {-1})))}
    out = []
    for t in tareas:
        u = t.unit
        llegada = _proxima_llegada(db, u.id, t.fecha if t.tipo == "salida" else dia) if t.tipo == "salida" else None
        if llegada and t.tipo == "salida" and llegada.id == t.reservation_id:
            llegada = None
        antes = llegada.fecha_entrada if llegada else None
        r = db.get(Reservation, t.reservation_id) if t.reservation_id else None
        if t.tipo == "salida":
            motivo = t.nota or "Salida realizada"
        elif t.tipo == "contratada":
            motivo = "Limpieza contratada" + (f" ({describir(r.limpieza)})" if r and r.limpieza else "")
        else:
            motivo = "Limpieza extra" + (f": {t.nota}" if t.nota else "")
        urgente = antes is not None and antes <= dia
        out.append({"id": t.id, "unit_id": u.id, "codigo": u.codigo, "bloque": u.bloque, "planta": u.planta,
                    "tipologia": u.tipologia, "tipo": t.tipo, "tipo_nombre": TIPOS[t.tipo], "motivo": motivo,
                    "nota": t.nota, "fecha": t.fecha.isoformat(), "arrastrada": t.fecha < dia,
                    "antes_de": antes.isoformat() if antes else None, "urgente": urgente,
                    "pax_llegada": (llegada.adultos + llegada.ninos) if llegada else None,
                    "estado": t.estado, "hecha": t.hecha.isoformat() if t.hecha else None,
                    "validada_por": nombres.get(t.validada_por), "creada_por": nombres.get(t.creada_por)})
    orden_tipo = {"salida": 0, "contratada": 1, "extra": 2}
    out.sort(key=lambda x: (x["estado"] != "pendiente", not x["urgente"], x["antes_de"] or "9999",
                            orden_tipo[x["tipo"]], x["bloque"] or "", x["codigo"]))
    return out


def validar(db: Session, t: CleaningTask, user: User) -> None:
    """Recepción da la limpieza por hecha: sale del parte. La de salida deja el apartamento disponible."""
    t.estado, t.hecha, t.validada_por = "hecha", datetime.now(), user.id
    u = t.unit
    otras = db.scalar(select(CleaningTask.id).where(CleaningTask.unit_id == u.id, CleaningTask.id != t.id,
                                                    CleaningTask.estado == "pendiente", CleaningTask.tipo == "salida"))
    if t.tipo == "salida" and u.estado == "pendiente_limpieza" and not otras:
        u.estado = "disponible"


def limpieza_unidad_hecha(db: Session, u: Unit, user: User) -> None:
    """La gobernanta marca el apartamento como limpio: se validan sus limpiezas de salida pendientes."""
    for t in db.scalars(select(CleaningTask).where(CleaningTask.unit_id == u.id, CleaningTask.estado == "pendiente",
                                                   CleaningTask.tipo == "salida", CleaningTask.fecha <= date.today())):
        t.estado, t.hecha, t.validada_por = "hecha", datetime.now(), user.id


# --------------------------------------------------------------------------- documentos
def _lugar(x: dict) -> str:
    return " · ".join(p for p in (x["bloque"], f"planta {x['planta']}" if x["planta"] else None) if p)


def _prioridad(x: dict, dia: date) -> str:
    if x["antes_de"]:
        antes = date.fromisoformat(x["antes_de"])
        pax = f" ({x['pax_llegada']} pax)" if x["pax_llegada"] else ""
        return f"LLEGADA HOY{pax}" if antes <= dia else f"Antes del {antes:%d/%m}{pax}"
    return ""


def texto(asset, dia: date, filas: list[dict], nota: str | None = None) -> str:
    pend = [x for x in filas if x["estado"] == "pendiente"]
    lineas = [f"- {x['codigo']}{' (' + _lugar(x) + ')' if _lugar(x) else ''}: {x['motivo']}"
              + (f" · {_prioridad(x, dia)}" if _prioridad(x, dia) else "")
              + (f" · pendiente desde {date.fromisoformat(x['fecha']):%d/%m}" if x["arrastrada"] else "")
              for x in pend]
    return (f"Parte de limpieza {asset.nombre} · {dia:%d/%m/%Y} · {len(pend)} limpieza(s)\n" + "\n".join(lineas)
            + (f"\n\nNota: {nota}" if nota else "")
            + "\n\nPrimero las de LLEGADA HOY. Avise a recepción al terminar cada una.")


def pdf(asset, company, dia: date, filas: list[dict], nota: str | None = None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title=f"Parte de limpieza {asset.nombre} {dia:%d-%m-%Y}")
    st = getSampleStyleSheet()
    p = ParagraphStyle("p", parent=st["BodyText"], fontSize=9, leading=11)
    h = ParagraphStyle("h", parent=st["Title"], fontSize=15, alignment=0, spaceAfter=2)
    ancho = A4[0] - 28 * mm
    el = []
    cab = marca.cabecera_pdf(marca.clave_sociedad(company.cif if company else None), marca.clave_activo(asset.codigo),
                             ancho, 16 * mm)
    if cab is not None:
        el += [cab, Spacer(1, 4 * mm)]
    pend = [x for x in filas if x["estado"] == "pendiente"]
    el += [Paragraph(f"Parte de limpieza · {asset.nombre}", h),
           Paragraph(f"{dia:%d/%m/%Y} · {len(pend)} limpieza(s) pendiente(s). Primero las de <b>LLEGADA HOY</b>. "
                     "Marque cada una al terminar y avise a recepción.", p), Spacer(1, 4 * mm)]
    esc = lambda s: str(s or "").replace("&", "&amp;").replace("<", "&lt;")  # noqa: E731
    datos = [["Hecha", "Apartamento", "Ubicación", "Limpieza", "Prioridad", "Observaciones"]]
    estilo = [("FONTSIZE", (0, 0), (-1, -1), 8.5), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(marca.NEGRO)),
              ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), .4, colors.HexColor("#cfc6b4")),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 1), (0, -1), "CENTER"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f3ea")])]
    def casilla():  # recuadro vacío para marcar a mano
        c = Table([[""]], colWidths=[4.2 * mm], rowHeights=[4.2 * mm])
        c.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), .9, colors.HexColor(marca.NEGRO))]))
        return c

    for i, x in enumerate(pend, start=1):
        pri = _prioridad(x, dia)
        motivo = esc(x["motivo"]) + (f"<br/><font color='#a15c00'>pendiente desde {date.fromisoformat(x['fecha']):%d/%m}</font>"
                                     if x["arrastrada"] else "")
        datos.append([casilla(), Paragraph(f"<b>{esc(x['codigo'])}</b>", p), Paragraph(esc(_lugar(x)), p),
                      Paragraph(motivo, p), Paragraph(f"<b>{esc(pri)}</b>" if pri else "", p), ""])
        if x["urgente"]:
            estilo.append(("BACKGROUND", (4, i), (4, i), colors.HexColor("#f8d7d3")))
    if len(datos) == 1:
        datos.append(["", "", "", Paragraph("Sin limpiezas pendientes para este día.", p), "", ""])
    t = Table(datos, colWidths=[12 * mm, 24 * mm, 30 * mm, 58 * mm, 30 * mm, ancho - 154 * mm], repeatRows=1)
    t.setStyle(TableStyle(estilo))
    el.append(t)
    if nota:
        el += [Spacer(1, 4 * mm), Paragraph(f"<b>Nota de recepción:</b> {esc(nota)}", p)]
    el += [Spacer(1, 10 * mm), Paragraph("Firma limpieza: ______________________________ &nbsp;&nbsp;&nbsp; "
                                         "Validado recepción: ______________________________", p)]
    doc.build(el)
    return out.getvalue()


def excel(asset, dia: date, filas: list[dict]) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Parte de limpieza"
    ws.append([f"Parte de limpieza · {asset.nombre} · {dia:%d/%m/%Y}"])
    ws["A1"].font = Font(bold=True, size=13)
    cab = ["Apartamento", "Bloque", "Planta", "Tipo", "Limpieza", "Día previsto", "Antes de la llegada",
           "Pax llegada", "Estado", "Validada", "Validada por", "Añadida por"]
    ws.append(cab)
    for c in ws[2]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1A1A1C")
    for x in filas:
        ws.append([x["codigo"], x["bloque"], x["planta"], x["tipo_nombre"], x["motivo"],
                   date.fromisoformat(x["fecha"]), date.fromisoformat(x["antes_de"]) if x["antes_de"] else None,
                   x["pax_llegada"], "Hecha" if x["estado"] == "hecha" else "Pendiente",
                   datetime.fromisoformat(x["hecha"]) if x["hecha"] else None, x["validada_por"], x["creada_por"]])
    for col, w in zip("ABCDEFGHIJKL", (12, 14, 8, 11, 48, 12, 16, 10, 10, 17, 18, 18), strict=True):
        ws.column_dimensions[col].width = w
    for fila in ws.iter_rows(min_row=3):
        fila[5].number_format = fila[6].number_format = "DD/MM/YYYY"
        fila[9].number_format = "DD/MM/YYYY HH:MM"
    out = BytesIO()
    wb.save(out)
    return out.getvalue()
