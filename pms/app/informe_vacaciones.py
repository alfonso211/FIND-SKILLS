"""Calendario de vacaciones del personal propio (formato de la Dirección Técnica): dos hojas con los doce meses (un
color por persona; bloque sólido = disfrutadas, claro = solicitadas, rayado = pendiente de aprobar; festivos de
Madrid, el día de hoy y el tramo modificado en esta revisión) y una hoja de resumen de saldos con los cambios, el
criterio de cómputo, los días pendientes de solicitar y los solapes.

Cada cambio en una solicitud de vacaciones genera una revisión y se envía por correo a todos los usuarios del PMS
(colaboradores incluidos). Cada lunes se recuerda a quien tiene días sin solicitar que lo haga antes de fin de año."""
import io
import logging
import threading
from datetime import date, datetime, timedelta
from html import escape

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import avisos, empleados
from .calendario import festivos
from .config import settings
from .models import Absence, EmailLog, StaffMember, User, VacationRevision

log = logging.getLogger("pms.vacaciones")
MESES = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
         "NOVIEMBRE", "DICIEMBRE"]
MES_CORTO = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
COLORES = ["#2f80c1", "#f39a3d", "#3f9b4f", "#7d4fb0", "#1f9e98", "#b8913a", "#d1495b", "#5c6bc0", "#8d6e63",
           "#00897b", "#c2185b", "#689f38", "#ef6c00", "#455a64", "#9e9d24", "#6d4c41"]
VIGENTES = ("pendiente", "visto_bueno", "aprobada")


def festivos_madrid(anio: int) -> set[date]:
    """Nacionales y de la Comunidad de Madrid, más los locales de Madrid capital (San Isidro y la Almudena)."""
    return festivos(anio) | {date(anio, 5, 15), date(anio, 11, 9)}


def fecha_corta(a: date, b: date) -> str:
    if a == b:
        return f"{a.day} {MES_CORTO[a.month - 1]}"
    if a.month == b.month:
        return f"{a.day}–{b.day} {MES_CORTO[a.month - 1]}"
    return f"{a.day} {MES_CORTO[a.month - 1]}–{b.day} {MES_CORTO[b.month - 1]}"


# --------------------------------------------------------------------------- datos
def _personas(db: Session, anio: int, hoy: date) -> list[dict]:
    ini, fin = date(anio, 1, 1), date(anio, 12, 31)
    fichas = [p for p in db.scalars(select(StaffMember).order_by(StaffMember.nombre))
              if empleados.es_propio(p) and (p.activo or p.user_id)]
    out = []
    for p in fichas:
        cond = [Absence.staff_id == p.id] + ([Absence.user_id == p.user_id] if p.user_id else [])
        ausencias = list(db.scalars(select(Absence).where(or_(*cond), Absence.tipo == "vacaciones",
                                                          Absence.estado.in_(VIGENTES), Absence.desde <= fin,
                                                          Absence.hasta >= ini).order_by(Absence.desde)))
        if not p.activo and not ausencias:
            continue
        tramos = []  # (desde, hasta, estado, ausencia)
        for x in ausencias:
            a, b = max(x.desde, ini), min(x.hasta, fin)
            if x.estado != "aprobada":
                tramos.append((a, b, "por_aprobar", x.id))
                continue
            if a <= hoy:
                tramos.append((a, min(b, hoy), "disfrutada", x.id))
            if b > hoy:
                tramos.append((max(a, hoy + timedelta(days=1)), b, "solicitada", x.id))
        out.append({"id": p.id, "nombre": p.nombre, "saldo": empleados.saldo(db, p, anio, hoy=hoy), "tramos": tramos,
                    "email": (db.get(User, p.user_id).email if p.user_id and db.get(User, p.user_id) else p.email)})
    for i, x in enumerate(out):
        x["n"], x["color"] = i + 1, COLORES[i % len(COLORES)]
    return out


def _solapes(personas: list[dict], hoy: date, anio: int) -> list[str]:
    """Coincidencias de dos o más personas a partir de hoy, agrupadas en tramos."""
    por_dia: dict[date, set[str]] = {}
    for p in personas:
        for a, b, _, _ in p["tramos"]:
            d = max(a, hoy)
            while d <= b:
                por_dia.setdefault(d, set()).add(p["nombre"])
                d += timedelta(days=1)
    out, dias = [], sorted(d for d, q in por_dia.items() if len(q) > 1)
    i = 0
    while i < len(dias):
        j, quienes = i, por_dia[dias[i]]
        while j + 1 < len(dias) and dias[j + 1] == dias[j] + timedelta(days=1) and por_dia[dias[j + 1]] == quienes:
            j += 1
        out.append(f"{fecha_corta(dias[i], dias[j])}: {' + '.join(sorted(quienes))} ({j - i + 1} día(s) de coincidencia)")
        i = j + 1
    return out


# --------------------------------------------------------------------------- PDF
def pdf(db: Session, anio: int, cambios: list[str] | None = None, modificados: list[tuple] | None = None,
        hoy: date | None = None, anterior: datetime | None = None) -> bytes:
    hoy = hoy or date.today()
    personas = _personas(db, anio, hoy)
    total = None
    for _ in range(2):  # la primera pasada cuenta las páginas («Página x/N»)
        datos, n = _dibuja(personas, anio, cambios or [], modificados or [], hoy, anterior, total)
        total = n
    return datos


def _dibuja(personas, anio, cambios, modificados, hoy, anterior, total):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
    from reportlab.platypus import Frame, KeepInFrame, Paragraph, Spacer, Table, TableStyle
    W, H = landscape(A4)
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=(W, H))
    c.setTitle(f"Calendario de vacaciones {anio}")
    azul, gris = colors.HexColor("#2a5c8a"), colors.HexColor("#6f6a61")
    fest = festivos_madrid(anio)
    tipo = personas[0]["saldo"]["tipo"] if personas else "naturales"
    asignados = sorted({p["saldo"]["corresponden"] for p in personas})
    cupo = f"{asignados[0]:g} días {tipo}" if len(asignados) == 1 else f"días {tipo} según ficha"
    dia_marcas: dict[date, list[tuple]] = {}
    for p in personas:
        for a, b, est, aid in p["tramos"]:
            d = a
            while d <= b:
                dia_marcas.setdefault(d, []).append((p, est))
                d += timedelta(days=1)
    mod_dias = {}
    for pid, a, b in modificados:
        d = max(a, date(anio, 1, 1))
        while d <= min(b, date(anio, 12, 31)):
            mod_dias.setdefault(d, set()).add(pid)
            d += timedelta(days=1)
    pagina = [0]

    def pie():
        pagina[0] += 1
        c.setFont("Helvetica", 8)
        c.setFillColor(gris)
        c.drawRightString(W - 12 * mm, H - 10 * mm, f"Página {pagina[0]}" + (f"/{total}" if total else ""))

    def cabecera():
        c.setFillColor(azul)
        c.setFont("Helvetica-Bold", 15)
        c.drawString(12 * mm, H - 15 * mm, f"CALENDARIO DE VACACIONES {anio} · INVERSIETE S.A. — Dirección Técnica")
        c.setFont("Helvetica-Oblique", 8.5)
        c.setFillColor(gris)
        c.drawString(12 * mm, H - 20 * mm, f"Revisión con situación a {hoy:%d/%m/%Y} · {cupo} por persona · "
                     + ("fines de semana y festivos incluidos en el periodo" if tipo == "naturales"
                        else "no computan fines de semana ni festivos"))
        y = H - 26 * mm
        c.setFont("Helvetica-Bold", 7.5)
        c.setFillColor(colors.black)
        c.drawString(12 * mm, y, "PERSONAL:")
        x = 12 * mm + 52
        for p in personas:
            etiqueta = f"{p['n']} {p['nombre'].upper()}"
            ancho = c.stringWidth(etiqueta, "Helvetica", 7.5) + 18
            if x + ancho > W - 12 * mm:
                x, y = 12 * mm + 52, y - 9
            c.setFillColor(colors.HexColor(p["color"]))
            c.rect(x, y - 1, 7, 7, stroke=0, fill=1)
            c.setFillColor(colors.black)
            c.setFont("Helvetica", 7.5)
            c.drawString(x + 10, y, etiqueta)
            x += ancho
        y -= 10
        c.setFont("Helvetica-Bold", 7.5)
        c.drawString(12 * mm, y, "CLAVE:")
        x = 12 * mm + 52
        for txt, dib in (("Disfrutadas (bloque sólido)", "solido"), ("Solicitadas (bloque claro)", "claro"),
                         ("Pendientes de aprobar (rayado)", "rayado"),
                         (f"Festivo Madrid{' (computa)' if tipo == 'naturales' else ''}", "festivo"),
                         (f"Hoy ({hoy:%d/%m/%Y})", "hoy"), ("Tramo modificado en esta revisión", "mod")):
            if dib == "solido":
                c.setFillColor(colors.HexColor("#555555"))
                c.rect(x, y - 1, 7, 7, stroke=0, fill=1)
            elif dib == "claro":
                c.setFillColor(colors.HexColor("#555555"), alpha=0.3)
                c.rect(x, y - 1, 7, 7, stroke=0, fill=1)
                c.setFillAlpha(1)
            elif dib == "rayado":
                c.setStrokeColor(colors.HexColor("#555555"))
                c.rect(x, y - 1, 7, 7, stroke=1, fill=0)
                c.line(x, y - 1, x + 7, y + 6)
            elif dib == "festivo":
                c.setFillColor(colors.HexColor("#fff59d"))
                c.setStrokeColor(colors.HexColor("#c8b400"))
                c.rect(x, y - 1, 7, 7, stroke=1, fill=1)
            else:
                c.setStrokeColor(colors.HexColor("#d32f2f" if dib == "hoy" else "#2e7d32"))
                c.setLineWidth(1.3)
                c.rect(x, y - 1, 7, 7, stroke=1, fill=0)
                c.setLineWidth(1)
            c.setFillColor(colors.black)
            c.setFont("Helvetica", 7.5)
            c.drawString(x + 10, y, txt)
            x += c.stringWidth(txt, "Helvetica", 7.5) + 24
        return y - 6

    def mes(x0, y0, w, h, m):
        c.setFillColor(azul)
        c.setFont("Helvetica-Bold", 9)
        c.drawCentredString(x0 + w / 2, y0 - 9, MESES[m - 1])
        cw, top = w / 7, y0 - 22
        c.setFont("Helvetica", 6.5)
        c.setFillColor(gris)
        for i, letra in enumerate("LMXJVSD"):
            c.drawString(x0 + i * cw + 2, top + 3, letra)
        primero = date(anio, m, 1)
        filas = 6
        ch = (h - 24) / filas
        d = primero
        while d.month == m:
            semana = (d.day - 1 + primero.weekday()) // 7
            col = d.weekday()
            cx, cy = x0 + col * cw, top - (semana + 1) * ch
            if d in fest:
                c.setFillColor(colors.HexColor("#fff59d"))
                c.rect(cx + 0.5, cy + 0.5, cw - 1, ch - 1, stroke=0, fill=1)
            c.setStrokeColor(colors.HexColor("#e2ddd2"))
            c.setLineWidth(0.4)
            c.line(cx, cy, cx + cw, cy)
            c.setFillColor(colors.black if col < 5 else gris)
            c.setFont("Helvetica-Bold" if d in fest else "Helvetica", 6.5)
            c.drawString(cx + 2, cy + ch - 7, str(d.day))
            marcas = dia_marcas.get(d, [])
            bw = min(6, (cw - 4) / max(1, min(len(marcas), 6)))
            for k, (p, est) in enumerate(marcas[:12]):
                fila, pos = divmod(k, 6)
                bx, by = cx + 2 + pos * bw, cy + 2 + fila * 7
                col_p = colors.HexColor(p["color"])
                if est == "disfrutada":
                    c.setFillColor(col_p)
                    c.rect(bx, by, bw - 1, 6, stroke=0, fill=1)
                else:
                    c.setFillColor(col_p, alpha=0.35)
                    c.rect(bx, by, bw - 1, 6, stroke=0, fill=1)
                    c.setFillAlpha(1)
                    if est == "por_aprobar":
                        c.setStrokeColor(col_p)
                        c.setLineWidth(0.6)
                        c.line(bx, by, bx + bw - 1, by + 6)
                if p["id"] in mod_dias.get(d, ()):
                    c.setStrokeColor(colors.HexColor("#2e7d32"))
                    c.setLineWidth(1.2)
                    c.rect(cx + 0.8, cy + 0.8, cw - 1.6, ch - 1.6, stroke=1, fill=0)
            if d == hoy:
                c.setStrokeColor(colors.HexColor("#d32f2f"))
                c.setLineWidth(1.4)
                c.rect(cx + 0.5, cy + 0.5, cw - 1, ch - 1, stroke=1, fill=0)
            c.setLineWidth(1)
            d += timedelta(days=1)

    for semestre in (0, 1):
        pie()
        y_top = cabecera()
        mw, gap = (W - 24 * mm - 2 * 10) / 3, 10
        mh = (y_top - 8 * mm - gap) / 2
        for i in range(6):
            fila, col = divmod(i, 3)
            mes(12 * mm + col * (mw + gap), y_top - fila * (mh + gap), mw, mh, semestre * 6 + i + 1)
        c.showPage()

    # hoja de resumen
    ss = getSampleStyleSheet()
    peq = ss["BodyText"].clone("peq", fontSize=8, leading=10)
    blanca = peq.clone("blanca", fontName="Helvetica-Bold", textColor=colors.white)
    tit = ss["Title"].clone("tit", alignment=0, textColor=azul, fontSize=16)
    sub = ss["Heading3"].clone("sub", textColor=azul, spaceBefore=6, spaceAfter=3)
    historia = [Paragraph("RESUMEN DE SALDOS POR PERSONA — REVISIÓN", tit),
                Paragraph(f"<i>INVERSIETE S.A. · Dirección Técnica · Situación actualizada a {hoy:%d/%m/%Y}"
                          + (f" (sustituye a la situación de {anterior:%d/%m/%Y %H:%M})" if anterior else "") + "</i>", peq)]
    if cambios:
        historia += [Paragraph("Cambios aplicados en esta revisión", sub)] + \
                    [Paragraph(f"• {escape(t)}", peq) for t in cambios]
    filas = [[Paragraph(t, blanca) for t in ("PERSONA", "DISFRUTADAS", "SOLICITADAS (pdte. disfrutar)",
                                           "TOTAL ASIGNADO", "PDTE. DE SOLICITAR", "REPARTO — PERIODOS")]]
    tot = {"d": 0, "s": 0, "c": 0.0, "p": 0.0}
    mod_ids = {pid for pid, _, _ in modificados}
    for p in personas:
        s = p["saldo"]
        disf = " · ".join(f"{fecha_corta(a, b)} ({empleados._computa(a, b, s['tipo'])})"
                          for a, b, e, _ in p["tramos"] if e == "disfrutada") or "—"
        soli = " · ".join(f"{fecha_corta(a, b)} ({empleados._computa(a, b, s['tipo'])})"
                          + (" *" if e == "por_aprobar" else "") for a, b, e, _ in p["tramos"] if e != "disfrutada") or "—"
        filas.append([Paragraph(f"<b>{escape(p['nombre'].upper())}</b>" if p["id"] in mod_ids else escape(p["nombre"].upper()), peq),
                      f"{s['disfrutadas']:g}", f"{s['solicitadas']:g}", f"{s['corresponden']:g}",
                      f"{s['pendientes_solicitar']:g}",
                      Paragraph(f"Disfrutadas: {disf}<br/>Solicitadas: {soli}", peq)])
        tot["d"] += s["disfrutadas"]
        tot["s"] += s["solicitadas"]
        tot["c"] += s["corresponden"]
        tot["p"] += s["pendientes_solicitar"]
    consumido = round(tot["d"] / tot["c"] * 100) if tot["c"] else 0
    sin_plan = round(tot["p"] / tot["c"] * 100) if tot["c"] else 0
    filas.append([Paragraph(f"<b>TOTAL ({len(personas)} personas · {tot['c']:g} días)</b>", peq), f"{tot['d']:g}",
                  f"{tot['s']:g}", f"{tot['c']:g}", f"{tot['p']:g}",
                  Paragraph(f"Consumido el {consumido} % de la bolsa anual; queda un {sin_plan} % sin planificar.", peq)])
    t = Table(filas, colWidths=[38 * mm, 25 * mm, 26 * mm, 22 * mm, 22 * mm, 132 * mm], repeatRows=1)
    est = [("BACKGROUND", (0, 0), (-1, 0), azul), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
           ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d6cfc0")),
           ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (1, 1), (4, -1), "CENTER"),
           ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#dceaf7"))]
    for i, p in enumerate(personas, 1):
        if p["id"] in mod_ids:
            est.append(("BOX", (0, i), (-1, i), 1.4, colors.HexColor("#2e7d32")))
    t.setStyle(TableStyle(est))
    historia += [Spacer(1, 4), t, Paragraph("Criterio de cómputo", sub)]
    if tipo == "naturales":
        historia.append(Paragraph("Vacaciones en días naturales: se imputan todos los días comprendidos entre la fecha "
                                  "de inicio y la de fin del periodo, incluidos sábados, domingos y festivos. Los festivos de "
                                  "Madrid se señalan en el calendario a título informativo, pero consumen día de vacaciones "
                                  "cuando caen dentro de un periodo solicitado. * = pendiente de aprobar.", peq))
    else:
        historia.append(Paragraph("Vacaciones en días laborables: no computan sábados, domingos ni festivos de Madrid. "
                                  "* = pendiente de aprobar.", peq))
    historia += [Paragraph("Días pendientes de solicitar", sub),
                 Paragraph(" · ".join(f"{escape(p['nombre'])} {p['saldo']['pendientes_solicitar']:g}" for p in personas)
                           + (f". Quedan {tot['p']:g} días sin planificar, a consumir antes del 31 de diciembre." if tot["p"] > 0 else "."), peq),
                 Paragraph(f"Solapes pendientes (a partir de hoy, {hoy.day} de {MESES[hoy.month - 1].lower()})", sub)]
    sol = _solapes(personas, hoy, anio)
    historia += [Paragraph(" · ".join(escape(x) for x in sol) + ". Revisar en esas fechas la cobertura de mantenimiento "
                           "correctivo y las guardias." if sol else "Sin coincidencias.", peq),
                 Spacer(1, 6), Paragraph("<i>Nota: recuadro verde = tramo modificado en esta revisión.</i>", peq)]
    while historia:
        pie()
        f = Frame(12 * mm, 10 * mm, W - 24 * mm, H - 24 * mm, showBoundary=0)
        antes = len(historia), historia[0]
        f.addFromList(historia, c)
        if historia and (len(historia), historia[0]) == antes:  # no cabe en una página: se reduce para que quepa
            historia[0] = KeepInFrame(f._aW, f._aH, [historia[0]], mode="shrink")
            f = Frame(12 * mm, 10 * mm, W - 24 * mm, H - 24 * mm, showBoundary=0)
            f.addFromList(historia, c)
        c.showPage()
    c.save()
    return out.getvalue(), pagina[0]


# --------------------------------------------------------------------------- envío
def destinatarios(db: Session) -> list[User]:
    """Todos los usuarios activos con correo, colaboradores (subcontratas) incluidos."""
    return [u for u in db.scalars(select(User).where(User.activo).order_by(User.nombre)) if u.email
            and not u.email.endswith(".invalid")]


def enviar(db: Session, anio: int, cambios: list[str], modificados: list[tuple], autor_id: int | None = None) -> int:
    anterior = db.scalar(select(VacationRevision.creado).where(VacationRevision.anio == anio)
                         .order_by(VacationRevision.id.desc()).limit(1))
    datos = pdf(db, anio, cambios, modificados, anterior=anterior)
    rev = VacationRevision(anio=anio, cambios=cambios, user_id=autor_id)
    db.add(rev)
    db.flush()
    asunto = f"Calendario de vacaciones {anio} — revisión {datetime.now():%d/%m/%Y %H:%M}"
    texto = ("Se ha actualizado el calendario de vacaciones del personal.\n\nCambios:\n"
             + "\n".join(f"- {x}" for x in cambios)
             + "\n\nSe adjunta el calendario con los saldos de cada persona. Para solicitar vacaciones: "
               "INVERPMS → Personal → Vacaciones y ausencias.")
    html = avisos._html(asunto, "<p>Se ha actualizado el calendario de vacaciones del personal.</p><ul>"
                        + "".join(f"<li>{escape(x)}</li>" for x in cambios)
                        + "</ul><p>Se adjunta el calendario con los saldos de cada persona.</p>")
    nombre = f"Calendario_vacaciones_{anio}_{datetime.now():%Y%m%d_%H%M}.pdf"
    n = 0
    if avisos.configurado():
        for u in destinatarios(db):
            try:
                avisos.enviar(u.email, asunto, texto, html, [(nombre, datos, "application/pdf")])
                ok, err = True, None
                n += 1
            except Exception as e:  # noqa: BLE001
                ok, err = False, str(e)[:300]
            db.add(EmailLog(clave=f"vacaciones_informe:{rev.id}", tipo="vacaciones", user_id=u.id,
                            destinatario=u.email, asunto=asunto[:200], ok=ok, error=err))
    rev.enviados = n
    db.commit()
    return n


def notificar(anio: int, cambios: list[str], modificados: list[tuple], autor_id: int | None = None) -> None:
    """Genera y envía la revisión. En segundo plano (son muchos correos), salvo en pruebas."""
    from .database import SessionLocal

    def tarea():
        try:
            with SessionLocal() as db:
                enviar(db, anio, cambios, modificados, autor_id)
        except Exception:  # noqa: BLE001
            log.exception("No se ha podido enviar el calendario de vacaciones")

    if settings.smtp_host == "memoria" or not avisos.configurado():
        tarea()
    else:
        threading.Thread(target=tarea, name="vacaciones", daemon=True).start()


def cambio_de(db: Session, x: Absence, que: str) -> tuple[str, tuple | None]:
    """Texto del cambio y tramo modificado (ficha, desde, hasta) de una solicitud de vacaciones."""
    ficha = empleados.ficha_de_ausencia(db, x)
    rango = f"del {x.desde:%d/%m/%Y}" + (f" al {x.hasta:%d/%m/%Y}" if x.hasta != x.desde else "")
    return f"{x.persona}: {que} {rango}.", (ficha.id, x.desde, x.hasta) if ficha else None


def tras_cambio(db: Session, x: Absence, que: str, autor_id: int | None) -> None:
    if x.tipo != "vacaciones":
        return
    texto, tramo = cambio_de(db, x, que)
    notificar(x.desde.year, [texto], [tramo] if tramo else [], autor_id)


# --------------------------------------------------------------------------- recordatorio semanal
def recordatorio_semanal(db: Session, dia: date) -> int:
    """Cada lunes: a quien le quedan días por solicitar, que los pida antes del 31 de diciembre."""
    if dia.weekday() != 0 or not avisos.configurado():
        return 0
    anio, semana = dia.year, dia.isocalendar()[1]
    n = 0
    for p in db.scalars(select(StaffMember).where(StaffMember.activo)):
        if not empleados.es_propio(p):
            continue
        u = db.get(User, p.user_id) if p.user_id else None
        email = (u.email if u and u.activo else None) or p.email
        if not email:
            continue
        s = empleados.saldo(db, p, anio, hoy=dia)
        if s["pendientes_solicitar"] <= 0:
            continue
        clave = f"vacaciones_recordatorio:{anio}-{semana:02d}:{p.id}"
        if db.scalar(select(EmailLog.id).where(EmailLog.clave == clave)):
            continue
        asunto = f"Vacaciones {anio}: le quedan {s['pendientes_solicitar']:g} días por solicitar"
        texto = (f"Hola {p.nombre.split()[0]}, según tu ficha te quedan {s['pendientes_solicitar']:g} días {s['tipo']} de "
                 f"vacaciones de {anio} sin solicitar (disfrutadas {s['disfrutadas']:g}, solicitadas {s['solicitadas']:g} "
                 f"de {s['corresponden']:g}). Recuerda solicitarlas antes del 31 de diciembre en INVERPMS → Personal → "
                 "Vacaciones y ausencias.")
        try:
            avisos.enviar(email, asunto, texto, avisos._html(asunto, f"<p>{escape(texto)}</p>"))
            ok, err = True, None
            n += 1
        except Exception as e:  # noqa: BLE001
            ok, err = False, str(e)[:300]
        db.add(EmailLog(clave=clave, tipo="vacaciones", user_id=u.id if u else None, destinatario=email,
                        asunto=asunto[:200], ok=ok, error=err))
    db.commit()
    return n
