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

from sqlalchemy import select

from .config import settings
from .database import SessionLocal
from .models import Asset, Charge, Contact, EmailLog, Lease, PreventivePlan, Unit, User, WorkOrder
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
}
RESUMEN = ("recibos_impagados", "contratos_vencen", "revisiones_normativas")
DIAS_CONTRATOS, DIAS_REVISIONES = 90, 30

BANDEJA: list[dict] = []  # correos «enviados» con PMS_SMTP_HOST=memoria (pruebas automáticas)


def hoy() -> date:
    return datetime.now(ZONA).date()


def configurado() -> bool:
    return bool(settings.smtp_host)


def remitente() -> str | None:
    return settings.smtp_from or settings.smtp_user


def enviar(destino: str, asunto: str, texto: str, html: str) -> None:
    """Envía un correo. Lanza excepción si falla."""
    if not configurado():
        raise RuntimeError("Correo no configurado (falta PMS_SMTP_HOST en el servidor)")
    if settings.smtp_host == "memoria":
        BANDEJA.append({"para": destino, "asunto": asunto, "texto": texto, "html": html})
        return
    msg = EmailMessage()
    msg["From"] = formataddr(("INVERPMS · Grupo INVERSIETE", remitente()))
    msg["To"] = destino
    msg["Subject"] = asunto
    msg["Message-ID"] = make_msgid(domain=(remitente() or "pms").split("@")[-1])
    msg.set_content(texto)
    msg.add_alternative(html, subtype="html")
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
    return [t for t, (_, perm) in TIPOS.items() if scope.has_any(perm)]


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
        db.commit()
        return enviados


# --------------------------------------------------------------------------- resumen diario
def _datos_resumen(db, dia: date) -> dict[str, list[tuple[int, list]]]:
    """Todas las incidencias del día, cada una con su activo (luego se filtran por usuario)."""
    nombres = dict(db.execute(select(Asset.id, Asset.nombre)).all())
    recibos = []
    for c, l, u, t in db.execute(
            select(Charge, Lease, Unit, Contact).join(Lease, Lease.id == Charge.lease_id)
            .join(Unit, Unit.id == Lease.unit_id).join(Contact, Contact.id == Lease.tenant_id)
            .where(Charge.estado.in_(("pendiente", "parcial")), Charge.fecha_vencimiento < dia)
            .order_by(Charge.fecha_vencimiento)):
        pendiente = float(c.importe) - float(c.importe_pagado)
        recibos.append((u.asset_id, [nombres[u.asset_id], u.codigo, f"{t.nombre} {t.apellidos or ''}".strip(),
                                     c.periodo, c.fecha_vencimiento.strftime("%d/%m/%Y"),
                                     f"{(dia - c.fecha_vencimiento).days} días", f"{pendiente:,.2f} €"
                                     .replace(",", "X").replace(".", ",").replace("X", ".")]))
    contratos = []
    for l, u, t in db.execute(
            select(Lease, Unit, Contact).join(Unit, Unit.id == Lease.unit_id).join(Contact, Contact.id == Lease.tenant_id)
            .where(Lease.estado == "vigente", Lease.fecha_fin.is_not(None), Lease.fecha_fin >= dia,
                   Lease.fecha_fin <= dia + timedelta(days=DIAS_CONTRATOS)).order_by(Lease.fecha_fin)):
        contratos.append((u.asset_id, [nombres[u.asset_id], u.codigo, f"{t.nombre} {t.apellidos or ''}".strip(),
                                       l.fecha_fin.strftime("%d/%m/%Y"), f"{(l.fecha_fin - dia).days} días"]))
    revisiones = []
    for p in db.scalars(select(PreventivePlan).where(PreventivePlan.activo, PreventivePlan.proxima_fecha <= dia + timedelta(
            days=DIAS_REVISIONES)).order_by(PreventivePlan.proxima_fecha)):
        dias = (p.proxima_fecha - dia).days
        revisiones.append((p.asset_id, [nombres[p.asset_id], p.titulo, p.normativa or "", p.proveedor or "",
                                        p.proxima_fecha.strftime("%d/%m/%Y"),
                                        f"VENCIDA hace {-dias} días" if dias < 0 else f"en {dias} días"]))
    return {"recibos_impagados": recibos, "contratos_vencen": contratos, "revisiones_normativas": revisiones}


SECCIONES = {
    "recibos_impagados": ("Recibos vencidos sin cobrar", ["Activo", "Unidad", "Inquilino", "Periodo", "Vencimiento",
                                                          "Retraso", "Pendiente"], "recibo(s) impagado(s)"),
    "contratos_vencen": ("Contratos que vencen", ["Activo", "Unidad", "Inquilino", "Fin de contrato", "Quedan"],
                         "contrato(s) por vencer"),
    "revisiones_normativas": ("Revisiones preventivas y normativas", ["Activo", "Revisión", "Normativa", "Mantenedor",
                                                                      "Fecha", "Plazo"], "revisión(es)"),
}


def resumen_diario(db, dia: date | None = None, forzar: bool = False) -> dict:
    """Envía a cada usuario su resumen. Sin `forzar`, no repite a quien ya lo recibió ese día."""
    dia = dia or hoy()
    datos = _datos_resumen(db, dia)
    destinatarios: dict[int, tuple[User, dict]] = {}
    for tipo in RESUMEN:
        for user, ids in suscritos(db, tipo):
            filas = [f for aid, f in datos[tipo] if ids is None or aid in ids]
            if filas:
                destinatarios.setdefault(user.id, (user, {}))[1][tipo] = filas
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
        except Exception:  # noqa: BLE001
            log.exception("Error en el programador de avisos")
        time.sleep(300)


def arrancar_programador() -> None:
    if settings.avisos_auto and configurado() and settings.smtp_host != "memoria":
        threading.Thread(target=_bucle, name="avisos", daemon=True).start()
