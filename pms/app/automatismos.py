"""Tareas automáticas del programador de avisos (app/avisos.py · _bucle):

- Mensaje al cliente la víspera de su llegada: documentos de todos los huéspedes para el registro de viajeros (SES),
  hora de entrada, fianza y lo pendiente de pago.
- Plazo de respuesta de las órdenes de trabajo según la prioridad (urgente 4 h, alta 24 h): si nadie ha actuado,
  aviso al director técnico (una vez por orden).
- Preventivo: se generan solas las órdenes de los planes que vencen en los próximos 7 días.
- Informe diario de dirección a primera hora: ocupación, ADR, RevPAR, llegadas y salidas, cobros pendientes,
  fianzas por transferir, órdenes urgentes y fuera de plazo y descuadres de caja. Cada activo va también a gestión
  (kpi.diario).
"""
import logging
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from html import escape

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import avisos
from .config import settings
from .facturacion import dinero
from .models import (MODALIDADES_RESERVA, Asset, AuditLog, CashClose, DepositRefund, EmailLog, PreventivePlan,
                     Reservation, Unit, User, WorkOrder, WorkOrderVisit)

log = logging.getLogger("pms.automatismos")
IVA_ALOJAMIENTO = Decimal("10")


def _euros(x) -> str:
    return f"{float(x):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------- víspera de la llegada
def _texto_llegada(db: Session, r: Reservation) -> str:
    from . import fianzas
    from .routers.turistico import saldo
    a, u = r.unit.asset, r.unit
    huespedes = r.adultos + r.ninos
    lineas = [f"Le esperamos mañana, {r.fecha_entrada:%d/%m/%Y}, en {a.nombre}"
              + (f" ({a.direccion}{', ' + a.municipio if a.municipio else ''})" if a.direccion else "")
              + f". La entrada es a partir de las 15:00 y la salida, el {r.fecha_salida:%d/%m/%Y}, antes de las 12:00.",
              f"Por normativa (Real Decreto 933/2021) tenemos que registrar a todos los huéspedes. Al llegar, tenga a mano "
              f"el DNI, NIE o pasaporte de cada uno de los {huespedes} huésped{'es' if huespedes != 1 else ''} (los "
              "menores sin documento, con el de su padre, madre o tutor). Así la entrada será más rápida."]
    f = fianzas.importe(r)
    if f > 0 and not r.fianza_cobro:
        lineas.append(f"A la llegada se solicita una fianza de {_euros(f)}, que se devuelve al finalizar la estancia.")
    pend = saldo(db, r)["total"]
    if pend > 0.004:
        lineas.append(f"Importe pendiente de su reserva: {_euros(pend)}.")
    return "\n\n".join(lineas)


def avisos_llegada(db: Session, hoy: date) -> int:
    """Correo a los clientes que llegan mañana (una vez por reserva)."""
    if not settings.aviso_llegada or not avisos.configurado():
        return 0
    manana = hoy + timedelta(days=1)
    n = 0
    for r in db.scalars(select(Reservation).join(Unit, Unit.id == Reservation.unit_id).join(Asset, Asset.id == Unit.asset_id)
                        .where(Reservation.fecha_entrada == manana, Reservation.estado == "confirmada",
                               Reservation.aviso_llegada.is_(None), Reservation.renueva_id.is_(None),
                               Unit.uso != "garaje", Asset.modalidad.in_(MODALIDADES_RESERVA))):
        g = r.guest
        if not g.email:
            continue
        a = r.unit.asset
        asunto = f"Su llegada mañana a {a.nombre} · reserva {r.localizador or r.id}"
        texto = _texto_llegada(db, r)
        cuerpo = "".join(f"<p>{escape(p)}</p>" for p in texto.split("\n\n"))
        ok = avisos._enviar_registrado(db, None, g.email, f"aviso_llegada:{r.id}", "aviso_llegada", asunto,
                                       f"Estimado/a cliente:\n\n{texto}\n\nAtentamente,\n{a.nombre}",
                                       avisos._html(f"Su llegada a {a.nombre}", f"<p>Estimado/a cliente:</p>{cuerpo}"
                                                    f"<p>Atentamente,<br>{escape(a.nombre)}</p>"))
        if ok:
            r.aviso_llegada = datetime.now()
            n += 1
    db.commit()
    return n


# --------------------------------------------------------------------------- plazo de respuesta de las OT
PLAZOS_HORAS = {"urgente": 4, "alta": 24}
SIN_RESPUESTA = ("abierta", "asignada", "escalada", "revisar")


def limite(w: WorkOrder) -> datetime | None:
    h = PLAZOS_HORAS.get(w.prioridad)
    if not h:
        return None
    inicio = w.creada or datetime.combine(w.fecha_apertura or date.today(), time(8, 0))
    return inicio + timedelta(hours=h)


def fuera_de_plazo(db: Session, ahora: datetime) -> list[WorkOrder]:
    """OT urgentes o de prioridad alta sin respuesta (nadie ha ido ni ha empezado el trabajo) pasado su plazo."""
    out = []
    for w in db.scalars(select(WorkOrder).where(WorkOrder.prioridad.in_(tuple(PLAZOS_HORAS)),
                                                WorkOrder.estado.in_(SIN_RESPUESTA),
                                                WorkOrder.fecha_apertura >= ahora.date() - timedelta(days=30))):
        lim = limite(w)
        if lim and lim < ahora and not db.scalar(select(WorkOrderVisit.id).where(WorkOrderVisit.work_order_id == w.id)):
            out.append(w)
    return out


def avisar_plazos(db: Session, ahora: datetime | None = None) -> int:
    """Aviso al director técnico de cada OT que supera su plazo de respuesta (una vez por orden)."""
    ahora = ahora or datetime.now()
    nuevas = [w for w in fuera_de_plazo(db, ahora) if w.plazo_avisado is None]
    if not nuevas:
        return 0
    nombres = dict(db.execute(select(Asset.id, Asset.nombre)).all())
    filas = [[f"OT-{w.id:05d}", nombres.get(w.asset_id, ""), w.titulo, w.prioridad.upper(), w.asignado_a or "sin asignar",
              f"{limite(w):%d/%m %H:%M}", f"{(ahora - limite(w)).total_seconds() / 3600:.0f} h"] for w in nuevas]
    asunto = f"Órdenes de trabajo fuera de plazo: {len(nuevas)}"
    texto = asunto + "\n" + "\n".join(" · ".join(map(str, f)) for f in filas)
    html = avisos._html("Órdenes de trabajo sin respuesta en plazo",
                        "<p>Plazo de respuesta: urgente 4 horas, alta 24 horas. Nadie ha empezado todavía estas "
                        "órdenes:</p>" + avisos._tabla(["OT", "Activo", "Trabajo", "Prioridad", "Asignada a", "Límite",
                                                       "Retraso"], filas))
    if avisos.configurado():
        dt = db.scalar(select(User).where(User.email == settings.mantenimiento_email))
        avisos._enviar_registrado(db, dt, settings.mantenimiento_email,
                                  f"ot_plazo:{ahora:%Y%m%d%H%M}", "ot_plazo", asunto, texto, html)
    for w in nuevas:
        w.plazo_avisado = ahora
    db.commit()
    return len(nuevas)


# --------------------------------------------------------------------------- preventivo automático
def generar_preventivo(db: Session, asset_ids: set[int] | None, dias_antelacion: int, user: User | None) -> int:
    """Crea las OT preventivas que vencen dentro de la antelación (si el plan no tiene ya una abierta) y avanza la
    próxima fecha del plan."""
    from .routers.mantenimiento import ABIERTAS
    from .utils import scoped
    tope = date.today() + timedelta(days=dias_antelacion)
    creadas = 0
    for p in db.scalars(scoped(select(PreventivePlan), PreventivePlan.asset_id, asset_ids).where(
            PreventivePlan.activo, PreventivePlan.proxima_fecha <= tope)):
        if db.scalar(select(WorkOrder.id).where(WorkOrder.plan_id == p.id, WorkOrder.estado.in_(ABIERTAS))):
            continue
        db.add(WorkOrder(asset_id=p.asset_id, plan_id=p.id, tipo="preventivo", categoria=p.categoria,
                         prioridad="media", titulo=p.titulo, descripcion=p.normativa, proveedor=p.proveedor,
                         fecha_prevista=p.proxima_fecha))
        p.proxima_fecha = p.proxima_fecha + timedelta(days=p.periodicidad_dias)
        creadas += 1
    return creadas


def preventivo_automatico(db: Session, hoy: date) -> int:
    if not settings.preventivo_auto:
        return 0
    n = generar_preventivo(db, None, 7, None)
    if n:
        db.add(AuditLog(user_id=None, accion="generar_preventivo", entidad="orden_trabajo", entidad_id=None,
                        detalle={"creadas": n, "automatico": True}))
    db.commit()
    return n


# --------------------------------------------------------------------------- informe diario de dirección
def _noche(db: Session, asset_id: int, dia: date) -> tuple[int, Decimal]:
    """Noches vendidas la noche de `dia` y su ingreso sin IVA (importe de la reserva repartido por noches)."""
    n, ingreso = 0, Decimal(0)
    for r in db.scalars(select(Reservation).join(Unit, Unit.id == Reservation.unit_id).where(
            Unit.asset_id == asset_id, Unit.uso != "garaje", Reservation.estado.in_(("confirmada", "checkin", "checkout")),
            Reservation.fecha_entrada <= dia, Reservation.fecha_salida > dia)):
        noches = (r.fecha_salida - r.fecha_entrada).days or 1
        n += 1
        ingreso += dinero(r.importe_total) / noches / (1 + IVA_ALOJAMIENTO / 100)
    return n, dinero(ingreso)


def kpis(db: Session, a: Asset, hoy: date) -> dict:
    from .facturacion import pendientes_cobro
    from .routers.turistico import saldo
    ayer = hoy - timedelta(days=1)
    unidades = db.scalar(select(func.count()).select_from(Unit).where(
        Unit.asset_id == a.id, Unit.uso != "garaje", Unit.estado != "fuera_servicio")) or 0
    vend_ayer, ingreso = _noche(db, a.id, ayer)
    vend_hoy, _ = _noche(db, a.id, hoy)
    base = select(func.count()).select_from(Reservation).join(Unit, Unit.id == Reservation.unit_id).where(
        Unit.asset_id == a.id, Unit.uso != "garaje", Reservation.renueva_id.is_(None))
    llegadas = db.scalar(base.where(Reservation.fecha_entrada == hoy, Reservation.estado.in_(("confirmada", "checkin")))) or 0
    salidas = db.scalar(base.where(Reservation.fecha_salida == hoy, Reservation.estado.in_(("checkin", "checkout")))) or 0
    facturas = [f for f in pendientes_cobro(db, {a.id}, hoy)]
    alojados = list(db.scalars(select(Reservation).join(Unit, Unit.id == Reservation.unit_id).where(
        Unit.asset_id == a.id, Reservation.estado == "checkin")))
    deuda_alojados = sum(x["estancia"] + x["extras"] for x in (saldo(db, r) for r in alojados))
    fianzas = db.execute(select(func.count(), func.coalesce(func.sum(DepositRefund.importe), 0)).where(
        DepositRefund.asset_id == a.id, DepositRefund.estado == "pendiente")).one()
    urgentes = db.scalar(select(func.count()).select_from(WorkOrder).where(
        WorkOrder.asset_id == a.id, WorkOrder.prioridad == "urgente",
        WorkOrder.estado.not_in(("cerrada", "cancelada")))) or 0
    fuera = len([w for w in fuera_de_plazo(db, datetime.now()) if w.asset_id == a.id])
    descuadres = list(db.scalars(select(CashClose).where(
        CashClose.asset_id == a.id, CashClose.diferencia != 0,
        CashClose.hasta >= datetime.combine(ayer, time.min), CashClose.hasta < datetime.combine(hoy, time.min))))
    return {"activo": a.codigo, "activo_pms": a.codigo, "nombre": a.nombre, "fecha": hoy.isoformat(),
            "unidades": unidades, "ocupadas_hoy": vend_hoy,
            "ocupacion": round(vend_hoy / unidades * 100, 1) if unidades else None,
            "ocupacion_ayer": round(vend_ayer / unidades * 100, 1) if unidades else None,
            "adr_ayer": float(dinero(ingreso / vend_ayer)) if vend_ayer else None,
            "revpar_ayer": float(dinero(ingreso / unidades)) if unidades else None,
            "ingreso_ayer": float(ingreso), "llegadas_hoy": llegadas, "salidas_hoy": salidas,
            "facturas_pendientes": len(facturas), "facturas_pendientes_importe": round(sum(f["total"] for f in facturas), 2),
            "deuda_alojados": round(deuda_alojados, 2),
            "fianzas_por_transferir": fianzas[0], "fianzas_por_transferir_importe": float(fianzas[1]),
            "ot_urgentes_abiertas": urgentes, "ot_fuera_de_plazo": fuera,
            "descuadres_caja_ayer": [{"diferencia": float(c.diferencia), "nota": c.nota} for c in descuadres]}


def informe_direccion(db: Session, hoy: date, forzar: bool = False) -> int:
    """Correo a la Dirección con los indicadores del día de cada activo turístico (una vez al día) y aviso a gestión."""
    clave, marca = f"informe_direccion:{hoy.isoformat()}", f"informe_direccion_hecho:{hoy.isoformat()}"
    if not forzar and db.scalar(select(EmailLog.id).where(EmailLog.clave == marca)):
        return 0
    db.add(EmailLog(clave=marca, tipo="sistema", asunto="Informe de dirección lanzado"))
    activos = list(db.scalars(select(Asset).where(Asset.modalidad.in_(MODALIDADES_RESERVA), Asset.activo.is_(True))
                              .order_by(Asset.codigo)))
    if not activos:
        return 0
    from . import gestion
    datos = []
    for a in activos:
        k = kpis(db, a, hoy)
        datos.append(k)
        gestion.encolar(db, "kpi.diario", {**k, "activo": gestion._codigo_gestion(a)}, clave=f"pms-kpi-{a.codigo}-{hoy}")
    pct = lambda x: "—" if x is None else f"{x:.1f} %".replace(".", ",")  # noqa: E731
    eur = lambda x: "—" if x is None else _euros(x)  # noqa: E731
    filas = [["Ocupación hoy", *[f"{pct(k['ocupacion'])} ({k['ocupadas_hoy']}/{k['unidades']})" for k in datos]],
             ["Ocupación ayer", *[pct(k["ocupacion_ayer"]) for k in datos]],
             ["ADR ayer (sin IVA)", *[eur(k["adr_ayer"]) for k in datos]],
             ["RevPAR ayer (sin IVA)", *[eur(k["revpar_ayer"]) for k in datos]],
             ["Llegadas / salidas hoy", *[f"{k['llegadas_hoy']} / {k['salidas_hoy']}" for k in datos]],
             ["Facturas pendientes de cobro", *[f"{k['facturas_pendientes']} · {eur(k['facturas_pendientes_importe'])}" for k in datos]],
             ["Pendiente de alojados", *[eur(k["deuda_alojados"]) for k in datos]],
             ["Fianzas por transferir", *[f"{k['fianzas_por_transferir']} · {eur(k['fianzas_por_transferir_importe'])}" for k in datos]],
             ["OT urgentes abiertas", *[str(k["ot_urgentes_abiertas"]) for k in datos]],
             ["OT fuera de plazo", *[str(k["ot_fuera_de_plazo"]) for k in datos]],
             ["Descuadres de caja ayer", *[", ".join(f"{d['diferencia']:+.2f} €" for d in k["descuadres_caja_ayer"]) or "—"
                                           for k in datos]]]
    cab = ["Indicador", *[k["nombre"] for k in datos]]
    asunto = f"PMS · Informe diario de dirección {hoy:%d/%m/%Y}"
    texto = asunto + "\n\n" + "\n".join(f"{f[0]}: " + " | ".join(f"{c}: {v}" for c, v in zip(cab[1:], f[1:]))
                                        for f in filas) + (f"\n\n{settings.url}" if settings.url else "")
    html = avisos._html(f"Informe diario de dirección · {hoy:%d/%m/%Y}", avisos._tabla(cab, filas))
    n = 0
    if avisos.configurado():
        for e in settings.informe_direccion:
            u = db.scalar(select(User).where(User.email == e))
            n += avisos._enviar_registrado(db, u, e, clave, "informe_direccion", asunto, texto, html)
    db.commit()
    return n
