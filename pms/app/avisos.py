"""Avisos por correo.

- OT urgente: al momento, a quien ve el mantenimiento de ese activo (salvo a quien la abrió).
- Resumen diario (a la hora PMS_AVISOS_HORA, hora de Madrid): recibos impagados, contratos que vencen y
  revisiones preventivas o normativas próximas. Cada usuario recibe solo lo de sus activos y solo si hay algo.

Cada usuario elige qué avisos recibe en «Mi perfil»; por defecto, todos los que le permiten sus permisos.
"""
import logging
import smtplib
import ssl
import threading
import time
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from . import hitos
from .config import settings
from .database import SessionLocal
from .models import (MODALIDADES_RESERVA, Asset, Charge, Contact, EmailLog, Expense, Lease, PreventivePlan,
                     Reservation, StaffMember, Unit, User, WorkOrder)
from .planos import zonas
from .security import Scope

log = logging.getLogger("pms.avisos")
ZONA = ZoneInfo("Europe/Madrid")

# tipo -> (descripción, permiso necesario)
TIPOS = {
    "ot_urgente": ("Órdenes de trabajo urgentes (al momento)", "mantenimiento.ver"),
    "recibos_impagados": ("Recibos de alquiler vencidos sin cobrar (resumen diario)", "alquiler.ver"),
    "contratos_vencen": ("Contratos de alquiler que vencen en los próximos 90 días (resumen diario)", "alquiler.ver"),
    "revisiones_normativas": ("Revisiones preventivas y normativas en los próximos 30 días o vencidas "
                              "(resumen diario)", "mantenimiento.editar"),
    "estancias_vencidas": ("Estancias vencidas (siguen alojados después de su fecha de salida) y las que terminan "
                           "en 3 días (resumen diario)", "reservas.ver"),
    "garajes_impagados": ("Plazas de garaje alquiladas a clientes externos: recibos vencidos sin cobrar "
                          "(resumen diario)", "reservas.ver"),
    "garajes_vencen": ("Plazas de garaje alquiladas a clientes externos: bajas en los próximos 30 días "
                       "(resumen diario)", "reservas.ver"),
    "facturas_pendientes": ("Facturas emitidas pendientes de cobro (renovaciones y reservas que pagan por "
                            "transferencia): revisar si ha llegado el pago (resumen diario)", "facturas.ver"),
    "pagos_retenidos": ("Facturas recibidas con el pago retenido: aviso al momento de retenerlas y, en el resumen "
                        "diario, las retenidas con su fecha de revisión", "finanzas.ver"),
    "informe_presidencia": ("Informe mensual a la presidencia: aviso el primer día laborable del mes para revisarlo "
                            "y enviarlo (a quien lo tiene asignado, por defecto «Recepción 1» de cada activo)",
                            "facturas.ver"),
    "hitos_normativos": ("Hitos normativos (Verifactu, factura electrónica…) con antelación para adaptar el PMS "
                         "(resumen diario)", "finanzas.ver"),
    "agenda": ("Agenda: tareas, reuniones y recordatorios que le envían, aviso antes de cada cita y su agenda del "
               "día en el resumen", None),
}
RESUMEN = ("hitos_normativos", "pagos_retenidos", "facturas_pendientes", "estancias_vencidas", "recibos_impagados", "contratos_vencen", "garajes_impagados",
           "garajes_vencen", "revisiones_normativas")
DIAS_ESTANCIAS = 3
DIAS_GARAJES = 30
DIAS_CONTRATOS, DIAS_REVISIONES = 90, 30

BANDEJA: list[dict] = []  # correos «enviados» con PMS_SMTP_HOST=memoria (pruebas automáticas)


def hoy() -> date:
    return datetime.now(ZONA).date()


def configurado() -> bool:
    return bool(settings.smtp_host)


def remitente() -> str | None:
    return settings.smtp_from or settings.smtp_user


def enviar(destino: str, asunto: str, texto: str, html: str,
           adjuntos: list[tuple[str, bytes, str]] | None = None) -> None:
    """Envía un correo. `adjuntos`: [(nombre, contenido, tipo MIME)]. Lanza excepción si falla."""
    if not configurado():
        raise RuntimeError("Correo no configurado (falta PMS_SMTP_HOST en el servidor)")
    if settings.smtp_host == "memoria":
        BANDEJA.append({"para": destino, "asunto": asunto, "texto": texto, "html": html,
                        "adjuntos": [(n, len(c), m) for n, c, m in adjuntos or []]})
        return
    msg = EmailMessage()
    msg["From"] = formataddr(("INVERPMS · Grupo INVERSIETE", remitente()))
    msg["To"] = destino
    msg["Subject"] = asunto
    msg["Message-ID"] = make_msgid(domain=(remitente() or "pms").split("@")[-1])
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
    for nombre, contenido, mime in adjuntos or []:
        tipo, _, sub = mime.partition("/")
        msg.add_attachment(contenido, maintype=tipo, subtype=sub, filename=nombre)
    ctx = ssl.create_default_context()
    if settings.smtp_seguridad == "ssl":
        smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30, context=ctx)
    else:
        smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
    with smtp:
        if settings.smtp_seguridad == "starttls":
            smtp.starttls(context=ctx)
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)


def _enviar_registrado(db, user: User | None, destino: str, clave: str, tipo: str, asunto: str, texto: str,
                       html: str) -> bool:
    try:
        enviar(destino, asunto, texto, html)
        ok, error = True, None
    except Exception as e:  # noqa: BLE001 — un fallo de correo no debe parar el PMS
        ok, error = False, str(e)[:300]
        log.warning("Aviso %s a %s no enviado: %s", clave, destino, error)
    db.add(EmailLog(clave=clave, tipo=tipo, user_id=user.id if user else None, destinatario=destino,
                    asunto=asunto[:200], ok=ok, error=error))
    return ok


def _html(titulo: str, cuerpo: str) -> str:
    enlace = (f'<p style="margin-top:20px"><a href="{escape(settings.url)}" style="background:#c9a45a;color:#0e0e10;'
              f'padding:9px 16px;border-radius:8px;text-decoration:none;font-weight:600">Abrir INVERPMS</a></p>'
              ) if settings.url else ""
    cabecera = ('<div style="background:#0e0e10;padding:16px 22px;border-bottom:3px solid #c9a45a">'
                '<span style="color:#fff;font-size:18px;letter-spacing:5px;font-weight:300">INVER'
                '<b style="color:#c9a45a;font-weight:700">PMS</b></span>'
                '<span style="color:#8d877b;font-size:11px;letter-spacing:2px;margin-left:12px">GRUPO INVERSIETE</span></div>')
    return (f'<div style="font-family:Segoe UI,Arial,sans-serif;font-size:14px;color:#1a1a1c;max-width:760px;'
            f'border:1px solid #e7e1d4;border-radius:10px;overflow:hidden">{cabecera}<div style="padding:20px 22px">'
            f'<h2 style="color:#0e0e10;margin:0 0 12px;font-weight:600">{escape(titulo)}</h2>{cuerpo}{enlace}'
            f'<p style="color:#8d877b;font-size:12px;margin-top:22px">Aviso automático de INVERPMS · Grupo INVERSIETE. '
            f'Puede elegir qué avisos recibe en «Mi perfil».</p></div></div>')


def _tabla(cabecera: list[str], filas: list[list]) -> str:
    th = "".join(f'<th style="text-align:left;padding:5px 8px;background:#f7f3ea;border-bottom:1px solid #e7e1d4">'
                 f'{escape(c)}</th>' for c in cabecera)
    tr = "".join("<tr>" + "".join(f'<td style="padding:5px 8px;border-bottom:1px solid #eee8dc">{escape(str(v))}</td>'
                                  for v in f) + "</tr>" for f in filas)
    return f'<table style="border-collapse:collapse;width:100%;font-size:13px">{th and "<tr>" + th + "</tr>"}{tr}</table>'


def suscritos(db, tipo: str) -> list[tuple[User, set[int] | None]]:
    """Usuarios activos que reciben ese aviso, con los activos en los que tienen el permiso (None = todos)."""
    perm = TIPOS[tipo][1]
    out = []
    for u in db.scalars(select(User).where(User.activo)):
        if u.avisos is not None and tipo not in u.avisos:
            continue
        ids = Scope(u, db).asset_ids(perm)
        if ids is None or ids:
            out.append((u, ids))
    return out


def tipos_permitidos(scope: Scope) -> list[str]:
    return [t for t, (_, perm) in TIPOS.items() if perm is None or scope.has_any(perm)]


def quiere(u: User, tipo: str) -> bool:
    return u.activo and (u.avisos is None or tipo in u.avisos)


# --------------------------------------------------------------------------- OT urgente (al momento)
def ot_urgente(wid: int, autor_id: int | None) -> int:
    if not configurado():
        return 0
    with SessionLocal() as db:
        w = db.get(WorkOrder, wid)
        a = db.get(Asset, w.asset_id)
        u = db.get(Unit, w.unit_id) if w.unit_id else None
        autor = db.get(User, autor_id) if autor_id else None
        zona = zonas(a.codigo).get(w.zona) if w.zona else None
        lugar = (f"{u.uso} {u.codigo}" + (f" ({u.bloque})" if u.bloque else "") if u
                 else f"Zonas comunes · {zona}" if zona else "Zonas comunes")
        asunto = f"OT URGENTE · {a.nombre} · {lugar}: {w.titulo}"[:200]
        filas = [("Orden", f"OT-{w.id:05d}"), ("Activo", a.nombre), ("Ubicación", lugar), ("Avería", w.titulo),
                 ("Instalación", w.categoria), ("Descripción", w.descripcion or "—"),
                 ("Abierta por", autor.nombre if autor else "—"), ("Bloquea la unidad", "Sí" if w.bloquea_unidad else "No")]
        texto = "\n".join(f"{k}: {v}" for k, v in filas) + (f"\n\n{settings.url}/#ordenes" if settings.url else "")
        html = _html("Orden de trabajo urgente", _tabla([], [[k, v] for k, v in filas]))
        enviados = 0
        for user, ids in suscritos(db, "ot_urgente"):
            if user.id == autor_id or (ids is not None and w.asset_id not in ids):
                continue
            clave = f"ot_urgente:{wid}"
            if db.scalar(select(EmailLog.id).where(EmailLog.clave == clave, EmailLog.user_id == user.id, EmailLog.ok)):
                continue  # ya avisado de esta OT
            enviados += _enviar_registrado(db, user, user.email, clave, "ot_urgente", asunto, texto, html)
        enviados += _ot_urgente_personal(db, w)
        db.commit()
        return enviados


def _ot_urgente_personal(db, w: WorkOrder) -> int:
    """Personal de mantenimiento con «avisar de las urgentes»: recibe la OT con el parte en PDF, sin esperar a que
    alguien se la envíe."""
    from .routers.mantenimiento import mensaje_ot, parte  # import local: el router importa este módulo
    from .routers.personal import registrar_envio_ot
    personas = [p for p in db.scalars(select(StaffMember).where(
        StaffMember.activo, StaffMember.avisar_urgentes, StaffMember.area == "mantenimiento",
        StaffMember.email.is_not(None), or_(StaffMember.asset_id.is_(None), StaffMember.asset_id == w.asset_id)))
        if not db.scalar(select(EmailLog.id).where(EmailLog.clave == f"ot_urgente:{w.id}:p{p.id}", EmailLog.ok))]
    if not personas:
        return 0
    asunto, texto, html = mensaje_ot(db, w)
    adj = [(f"Parte_OT-{w.id:05d}.pdf", parte(db, w), "application/pdf")]
    res = []
    for p in personas:
        try:
            enviar(p.email, asunto, texto, html, adj)
            ok, error = True, None
        except Exception as e:  # noqa: BLE001
            ok, error = False, str(e)[:300]
            log.warning("OT urgente %s a %s no enviada: %s", w.id, p.email, error)
        db.add(EmailLog(clave=f"ot_urgente:{w.id}:p{p.id}", tipo="ot_urgente", destinatario=p.email,
                        asunto=asunto[:200], ok=ok, error=error))
        res.append({"canal": "email", "destino": p.email, "nombre": p.nombre, "ok": ok})
    registrar_envio_ot(w, res, "Aviso automático (urgente)")
    if any(r["ok"] for r in res) and w.estado == "abierta":
        w.estado = "asignada"
    return sum(r["ok"] for r in res)


# --------------------------------------------------------------------------- pago retenido (al momento)
def _euros(x) -> str:
    return f"{float(x):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _fila_retenido(db, g: Expense, activo: str, dia: date) -> list:
    autor = db.get(User, g.pago_retenido_user_id) if g.pago_retenido_user_id else None
    dias = (g.pago_retenido_revision - dia).days if g.pago_retenido_revision else 0
    return [activo, g.proveedor or "", g.numero_factura or "", g.fecha.strftime("%d/%m/%Y"),
            _euros(float(g.total) - float(g.retencion or 0)), g.pago_retenido_motivo or "",
            autor.nombre if autor else "",
            g.pago_retenido_revision.strftime("%d/%m/%Y") if g.pago_retenido_revision else "",
            f"REVISAR: pasada hace {-dias} días" if dias < 0 else "REVISAR HOY" if dias == 0 else f"en {dias} días"]


def pago_retenido(gid: int, autor_id: int | None) -> int:
    """Aviso a quien paga (dirección, administración) de que una factura no debe pagarse de momento."""
    if not configurado():
        return 0
    with SessionLocal() as db:
        g = db.get(Expense, gid)
        if g is None or not g.pago_retenido:
            return 0
        a = db.get(Asset, g.asset_id)
        cab = ["Activo", "Proveedor", "Nº factura", "Fecha", "A pagar", "Motivo", "Retenida por", "Revisión",
               "Situación"]
        fila = _fila_retenido(db, g, a.nombre, hoy())
        asunto = f"PAGO RETENIDO · {a.nombre} · {g.proveedor or 'proveedor'} {g.numero_factura or ''}".strip()[:200]
        texto = ("No pagar esta factura hasta su revisión:\n\n" + "\n".join(f"{k}: {v}" for k, v in zip(cab, fila))
                 + (f"\n\n{settings.url}/#gastos" if settings.url else ""))
        html = _html("Factura con el pago retenido", "<p>No pagar esta factura hasta su revisión.</p>"
                     + _tabla([], [[k, v] for k, v in zip(cab, fila)]))
        clave = f"pago_retenido:{gid}:{g.pago_retenido_revision}"
        enviados = 0
        for user, ids in suscritos(db, "pagos_retenidos"):
            if user.id == autor_id or (ids is not None and g.asset_id not in ids):
                continue
            if db.scalar(select(EmailLog.id).where(EmailLog.clave == clave, EmailLog.user_id == user.id, EmailLog.ok)):
                continue
            enviados += _enviar_registrado(db, user, user.email, clave, "pagos_retenidos", asunto, texto, html)
        db.commit()
        return enviados


# --------------------------------------------------------------------------- informe a la presidencia
def informe_mensual(db, dia: date) -> int:
    """El primer día laborable del mes: aviso a quien revisa y envía el informe del mes anterior de cada activo."""
    from .calendario import primer_laborable
    from .informe_presidencia import MESES
    from .routers.presidencia import _registro, responsable
    if dia != primer_laborable(dia.year, dia.month):
        return 0
    anio, mes = (dia.year - 1, 12) if dia.month == 1 else (dia.year, dia.month - 1)
    periodo = f"{MESES[mes - 1]} {anio}"
    enviados = 0
    for a in db.scalars(select(Asset).where(Asset.activo).order_by(Asset.id)):
        u = responsable(db, a)
        r = _registro(db, a.id, anio, mes)
        if u is None or not quiere(u, "informe_presidencia") or (r is not None and r.enviado_en):
            continue
        clave = f"informe_presidencia:{a.id}:{anio}-{mes:02d}"
        if db.scalar(select(EmailLog.id).where(EmailLog.clave == clave, EmailLog.user_id == u.id, EmailLog.ok)):
            continue
        asunto = f"Informe mensual a la presidencia · {a.nombre} · {periodo}: pendiente de revisar y enviar"
        texto = (f"Hoy toca preparar el informe mensual a la presidencia de {a.nombre} ({periodo}).\n"
                 "Entre en INVERPMS → Facturación e informes → Informe a presidencia, revise que todos los datos son "
                 "correctos y envíelo por correo o por WhatsApp (siempre en PDF)."
                 + (f"\n\n{settings.url}/#presidencia" if settings.url else ""))
        html = _html("Informe mensual a la presidencia", f"<p>Hoy toca preparar el informe mensual a la presidencia "
                     f"de <b>{escape(a.nombre)}</b> ({escape(periodo)}).</p><p>Entre en <b>Facturación e informes → "
                     "Informe a presidencia</b>, revise que todos los datos son correctos y envíelo por correo o por "
                     "WhatsApp (siempre en PDF).</p>")
        enviados += _enviar_registrado(db, u, u.email, clave, "informe_presidencia", asunto, texto, html)
    db.commit()
    return enviados


# --------------------------------------------------------------------------- resumen diario
def _renovada():
    from .routers.turistico import _renovada as cond  # import local: el router importa este módulo
    return cond()


def _datos_resumen(db, dia: date) -> dict[str, list[tuple[int, list]]]:
    """Todas las incidencias del día, cada una con su activo (luego se filtran por usuario)."""
    nombres = dict(db.execute(select(Asset.id, Asset.nombre)).all())
    turisticos = set(db.scalars(select(Asset.id).where(Asset.modalidad.in_(MODALIDADES_RESERVA))))
    garaje_ext = lambda u: u.uso == "garaje" and u.asset_id in turisticos  # noqa: E731  cliente externo de garaje
    recibos, garajes, garajes_fin = [], [], []
    for c, l, u, t in db.execute(
            select(Charge, Lease, Unit, Contact).join(Lease, Lease.id == Charge.lease_id)
            .join(Unit, Unit.id == Lease.unit_id).join(Contact, Contact.id == Lease.tenant_id)
            .where(Charge.estado.in_(("pendiente", "parcial")), Charge.fecha_vencimiento < dia)
            .order_by(Charge.fecha_vencimiento)):
        pendiente = float(c.importe) - float(c.importe_pagado)
        (garajes if garaje_ext(u) else recibos).append((u.asset_id, [nombres[u.asset_id], u.codigo, f"{t.nombre} {t.apellidos or ''}".strip(),
                                     c.periodo, c.fecha_vencimiento.strftime("%d/%m/%Y"),
                                     f"{(dia - c.fecha_vencimiento).days} días", f"{pendiente:,.2f} €"
                                     .replace(",", "X").replace(".", ",").replace("X", ".")]))
    contratos = []
    for l, u, t in db.execute(
            select(Lease, Unit, Contact).join(Unit, Unit.id == Lease.unit_id).join(Contact, Contact.id == Lease.tenant_id)
            .where(Lease.estado == "vigente", Lease.fecha_fin.is_not(None), Lease.fecha_fin >= dia,
                   Lease.fecha_fin <= dia + timedelta(days=DIAS_CONTRATOS)).order_by(Lease.fecha_fin)):
        if garaje_ext(u):
            if l.fecha_fin <= dia + timedelta(days=DIAS_GARAJES):
                garajes_fin.append((u.asset_id, [nombres[u.asset_id], u.codigo, f"{t.nombre} {t.apellidos or ''}".strip(),
                                                 t.telefono or "", l.fecha_fin.strftime("%d/%m/%Y"),
                                                 f"{(l.fecha_fin - dia).days} días"]))
            continue
        contratos.append((u.asset_id, [nombres[u.asset_id], u.codigo, f"{t.nombre} {t.apellidos or ''}".strip(),
                                       l.fecha_fin.strftime("%d/%m/%Y"), f"{(l.fecha_fin - dia).days} días"]))
    revisiones = []
    for p in db.scalars(select(PreventivePlan).where(PreventivePlan.activo, PreventivePlan.proxima_fecha <= dia + timedelta(
            days=DIAS_REVISIONES)).order_by(PreventivePlan.proxima_fecha)):
        dias = (p.proxima_fecha - dia).days
        revisiones.append((p.asset_id, [nombres[p.asset_id], p.titulo, p.normativa or "", p.proveedor or "",
                                        p.proxima_fecha.strftime("%d/%m/%Y"),
                                        f"VENCIDA hace {-dias} días" if dias < 0 else f"en {dias} días"]))
    estancias = []
    for r, u, t in db.execute(
            select(Reservation, Unit, Contact).join(Unit, Unit.id == Reservation.unit_id)
            .join(Contact, Contact.id == Reservation.guest_id)
            .where(Reservation.estado == "checkin", Unit.uso != "garaje",
                   Reservation.fecha_salida <= dia + timedelta(days=DIAS_ESTANCIAS), ~_renovada())
            .order_by(Reservation.fecha_salida, Unit.codigo)):
        dias = (r.fecha_salida - dia).days
        estancias.append((u.asset_id, [nombres[u.asset_id], u.codigo, f"{t.nombre} {t.apellidos or ''}".strip(),
                                       t.telefono or "", r.fecha_salida.strftime("%d/%m/%Y"),
                                       f"VENCIDA hace {-dias} días" if dias < 0 else "sale hoy" if dias == 0
                                       else f"en {dias} días"]))
    normativos = [(None, [h.titulo, h.fecha.strftime("%d/%m/%Y"), h.detalle]) for h in hitos.para_correo(dia)]
    from .facturacion import pendientes_cobro
    facturas = [(f["asset_id"], [f["activo"], f["codigo"], f"{date.fromisoformat(f['fecha']):%d/%m/%Y}", f["cliente"],
                                 f["unidad"] or "", f"{f['total']:,.2f} €".replace(",", "X").replace(".", ",")
                                 .replace("X", "."), f"{f['dias']} días"]) for f in pendientes_cobro(db, None, dia)]
    retenidos = []
    for g in db.scalars(select(Expense).where(Expense.pago_retenido, ~Expense.pagado)
                        .order_by(Expense.pago_retenido_revision, Expense.id)):
        retenidos.append((g.asset_id, _fila_retenido(db, g, nombres[g.asset_id], dia)))
    return {"hitos_normativos": normativos, "pagos_retenidos": retenidos, "facturas_pendientes": facturas, "estancias_vencidas": estancias, "recibos_impagados": recibos, "contratos_vencen": contratos,
            "garajes_impagados": garajes,
            "garajes_vencen": garajes_fin, "revisiones_normativas": revisiones}


SECCIONES = {
    "agenda": ("Su agenda de hoy y tareas pendientes", ["Hora", "Tipo", "Asunto", "De", "Situación"], "cita(s) en agenda"),
    "hitos_normativos": ("Hitos normativos: preparar el PMS con tiempo", ["Hito", "Fecha límite", "Qué hacer"],
                         "hito(s) normativo(s)"),
    "pagos_retenidos": ("Facturas recibidas con el pago retenido: no pagar hasta revisarlas",
                        ["Activo", "Proveedor", "Nº factura", "Fecha", "A pagar", "Motivo", "Retenida por",
                         "Revisión", "Situación"], "pago(s) retenido(s)"),
    "facturas_pendientes": ("Facturas pendientes de cobro: compruebe si ha llegado la transferencia y márquela "
                            "cobrada", ["Activo", "Factura", "Fecha", "Cliente", "Apartamento", "Total", "Pendiente"],
                            "factura(s) pendiente(s) de cobro"),
    "recibos_impagados": ("Recibos vencidos sin cobrar", ["Activo", "Unidad", "Inquilino", "Periodo", "Vencimiento",
                                                          "Retraso", "Pendiente"], "recibo(s) impagado(s)"),
    "contratos_vencen": ("Contratos que vencen", ["Activo", "Unidad", "Inquilino", "Fin de contrato", "Quedan"],
                         "contrato(s) por vencer"),
    "estancias_vencidas": ("Estancias vencidas o que terminan en 3 días: renovar o dar la salida",
                           ["Activo", "Apartamento", "Cliente", "Teléfono", "Salida", "Situación"], "estancia(s)"),
    "garajes_impagados": ("Plazas de garaje: recibos vencidos sin cobrar", ["Activo", "Plaza", "Cliente", "Periodo",
                                                                            "Vencimiento", "Retraso", "Pendiente"],
                          "recibo(s) de garaje impagado(s)"),
    "garajes_vencen": ("Plazas de garaje: bajas próximas", ["Activo", "Plaza", "Cliente", "Teléfono", "Fecha de baja",
                                                           "Quedan"], "baja(s) de garaje"),
    "revisiones_normativas": ("Revisiones preventivas y normativas", ["Activo", "Revisión", "Normativa", "Mantenedor",
                                                                      "Fecha", "Plazo"], "revisión(es)"),
}


def resumen_diario(db, dia: date | None = None, forzar: bool = False) -> dict:
    """Envía a cada usuario su resumen. Sin `forzar`, no repite a quien ya lo recibió ese día."""
    dia = dia or hoy()
    informe_mensual(db, dia)
    from .recibos import garajes_al_dia
    garajes_al_dia(db, hoy=dia)  # emite los recibos de garaje del mes aunque nadie haya entrado en el PMS
    datos = _datos_resumen(db, dia)
    destinatarios: dict[int, tuple[User, dict]] = {}
    for tipo in RESUMEN:
        for user, ids in suscritos(db, tipo):
            if tipo == "hitos_normativos":  # del grupo: solo dirección y administración de sociedad o grupo
                filas = [f for _, f in datos[tipo]] if hitos.autorizado(Scope(user, db)) else []
            else:
                filas = [f for aid, f in datos[tipo] if ids is None or aid in ids]
            if filas:
                destinatarios.setdefault(user.id, (user, {}))[1][tipo] = filas
    for user in db.scalars(select(User).where(User.activo)):  # agenda del día de cada uno
        filas = _agenda_del_dia(db, user, dia) if quiere(user, "agenda") else []
        if filas:
            secciones = destinatarios.setdefault(user.id, (user, {}))[1]
            destinatarios[user.id] = (user, {"agenda": filas, **secciones})
    clave = f"resumen:{dia.isoformat()}"
    enviados = errores = 0
    for user, secciones in destinatarios.values():
        if not forzar and db.scalar(select(EmailLog.id).where(EmailLog.clave == clave, EmailLog.user_id == user.id,
                                                              EmailLog.ok)):
            continue
        partes = [f"{len(f)} {SECCIONES[t][2]}" for t, f in secciones.items()]
        asunto = f"PMS · Resumen del {dia:%d/%m/%Y}: " + ", ".join(partes)
        texto, cuerpo = [], ""
        for t, filas in secciones.items():
            titulo, cab, _ = SECCIONES[t]
            texto.append(f"{titulo.upper()} ({len(filas)})\n" + "\n".join(" · ".join(map(str, f)) for f in filas))
            cuerpo += f'<h3 style="color:#13294b;margin:18px 0 6px">{escape(titulo)} ({len(filas)})</h3>' + _tabla(cab, filas)
        ok = _enviar_registrado(db, user, user.email, clave, "resumen", asunto,
                                "\n\n".join(texto) + (f"\n\n{settings.url}" if settings.url else ""),
                                _html(f"Resumen diario · {dia:%d/%m/%Y}", cuerpo))
        enviados += ok
        errores += not ok
    db.commit()
    return {"enviados": enviados, "errores": errores, "fecha": dia.isoformat()}


# --------------------------------------------------------------------------- agenda
def _agenda_del_dia(db, user: User, dia: date) -> list[list]:
    """Citas del día en las que participa (suyas o enviadas a él) y tareas suyas vencidas sin terminar."""
    from . import agenda
    from .models import AgendaEvent, AgendaParticipant
    mias = select(AgendaParticipant.event_id).where(AgendaParticipant.user_id == user.id)
    nombres = dict(db.execute(select(User.id, User.nombre)).all())
    filas = []
    for e in db.scalars(select(AgendaEvent).where((AgendaEvent.creador_id == user.id) | AgendaEvent.id.in_(mias),
                                                  AgendaEvent.inicio < datetime.combine(dia + timedelta(days=1),
                                                                                        datetime.min.time()))):
        if any(p.user_id == user.id and p.respuesta == "rechaza" for p in e.participantes):
            continue
        tipo = {"reunion": "Reunión", "tarea": "Tarea", "recordatorio": "Recordatorio"}.get(e.tipo, "Evento")
        de = "" if e.creador_id == user.id else nombres.get(e.creador_id, "")
        for x in agenda.ocurrencias(e, dia, dia):
            filas.append((x, ["Todo el día" if e.todo_el_dia else f"{x:%H:%M}", tipo, e.titulo, de,
                              "hecha" if e.hecha else ("PRIORIDAD ALTA" if e.prioridad == "alta" else "")]))
        if e.tipo == "tarea" and not e.hecha and e.inicio.date() < dia:
            filas.append((e.inicio, [f"{e.inicio:%d/%m}", tipo, e.titulo, de,
                                     f"VENCIDA hace {(dia - e.inicio.date()).days} días"]))
    return [f for _, f in sorted(filas, key=lambda x: x[0])]


def agenda_enviada(eid: int, user_ids: list[int]) -> int:
    """Correo a quien recibe una tarea, recordatorio o convocatoria."""
    if not configurado():
        return 0
    from .models import AgendaEvent
    with SessionLocal() as db:
        e = db.get(AgendaEvent, eid)
        if not e:
            return 0
        autor = db.get(User, e.creador_id)
        tipo = {"reunion": "Convocatoria de reunión", "tarea": "Nueva tarea", "recordatorio": "Recordatorio"}.get(
            e.tipo, "Nueva cita")
        cuando = f"{e.inicio:%d/%m/%Y}" + ("" if e.todo_el_dia else f" a las {e.inicio:%H:%M}")
        asunto = f"PMS · {tipo} de {autor.nombre}: {e.titulo}"[:200]
        filas = [["Cuándo", cuando], ["De", autor.nombre]] + ([["Lugar", e.lugar]] if e.lugar else []) + \
            ([["Prioridad", "ALTA"]] if e.prioridad == "alta" else []) + ([["Detalle", e.descripcion]] if e.descripcion else [])
        texto = f"{tipo}: {e.titulo}\n" + "\n".join(f"{a}: {b}" for a, b in filas) + (f"\n\n{settings.url}" if settings.url else "")
        enviados = 0
        for u in db.scalars(select(User).where(User.id.in_(user_ids))):
            if quiere(u, "agenda"):
                enviados += _enviar_registrado(db, u, u.email, f"agenda:{e.id}:alta", "agenda", asunto, texto,
                                               _html(f"{tipo}: {e.titulo}", _tabla(["", ""], filas)))
        db.commit()
        return enviados


def recordatorios_agenda(db, ahora: datetime | None = None) -> int:
    """Aviso por correo antes de cada cita con «avisar antes» (una vez por cita, fecha y persona)."""
    from . import agenda
    ahora = ahora or datetime.now(ZONA).replace(tzinfo=None)
    enviados = 0
    for e, x in agenda.recordatorios_pendientes(db, ahora):
        for u in agenda.destinatarios(db, e):
            clave = f"agenda:{e.id}:{x:%Y%m%d%H%M}:{u.id}"
            if not quiere(u, "agenda") or db.scalar(select(EmailLog.id).where(EmailLog.clave == clave)):
                continue
            cuando = f"{x:%d/%m/%Y}" + ("" if e.todo_el_dia else f" a las {x:%H:%M}")
            asunto = f"PMS · Recordatorio: {e.titulo} ({cuando})"[:200]
            filas = [["Cuándo", cuando]] + ([["Lugar", e.lugar]] if e.lugar else []) + \
                ([["Detalle", e.descripcion]] if e.descripcion else [])
            enviados += _enviar_registrado(db, u, u.email, clave, "agenda", asunto,
                                           f"Recordatorio: {e.titulo}\nCuándo: {cuando}",
                                           _html(f"Recordatorio: {e.titulo}", _tabla(["", ""], filas)))
    db.commit()
    return enviados


# --------------------------------------------------------------------------- programador (un hilo, un worker)
def _bucle() -> None:
    hh, mm = (int(x) for x in settings.avisos_hora.split(":"))
    while True:
        try:
            ahora = datetime.now(ZONA)
            if (ahora.hour, ahora.minute) >= (hh, mm):
                marca = f"resumen_ejecutado:{ahora.date().isoformat()}"
                with SessionLocal() as db:
                    if not db.scalar(select(EmailLog.id).where(EmailLog.clave == marca)):
                        db.add(EmailLog(clave=marca, tipo="sistema", asunto="Resumen diario lanzado"))
                        db.commit()
                        log.info("Resumen diario: %s", resumen_diario(db, ahora.date()))
            with SessionLocal() as db:
                recordatorios_agenda(db, ahora.replace(tzinfo=None))
        except Exception:  # noqa: BLE001
            log.exception("Error en el programador de avisos")
        time.sleep(120)  # cada 2 minutos: los recordatorios de la agenda llegan a su hora


def arrancar_programador() -> None:
    if settings.avisos_auto and configurado() and settings.smtp_host != "memoria":
        threading.Thread(target=_bucle, name="avisos", daemon=True).start()
