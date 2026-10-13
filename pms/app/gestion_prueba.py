"""Prueba de la pasarela con INVERGESTION en el servidor (fase 4). Se usa junto con `python -m app.fase4_prueba` de
gestión, que lo coordina. Trabaja SOLO con un apartamento de prueba (ZZ-PRUEBA-F4, en Suite Aeropuerto) y fechas de
2031; no toca reservas reales.

    python -m app.gestion_prueba preparar   → crea el apartamento de prueba (muestra su número)
    python -m app.gestion_prueba actividad  → reservas, check-out, incidencias y liquidaciones de prueba; entrega los avisos
    python -m app.gestion_prueba pases      → pases del botón «Gestión» para comprobarlos desde gestión
    python -m app.gestion_prueba estado     → estado del apartamento de prueba
    python -m app.gestion_prueba limpiar    → borra todo lo de prueba
"""
import base64
import hashlib
import hmac
import json
import secrets
import sys
from datetime import date, datetime, timezone

from sqlalchemy import or_, select

from . import gestion
from .database import SessionLocal
from .models import (Asset, AuditLog, CleaningTask, Contact, GestionEvento, Reservation, Unit, UnitBlock, User, WorkOrder)

CODIGO = "ZZ-PRUEBA-F4"


def _unidad(db):
    a = db.scalar(select(Asset).where(Asset.codigo == "SAE"))
    return a, db.scalar(select(Unit).where(Unit.asset_id == a.id, Unit.codigo == CODIGO))


def preparar():
    with SessionLocal() as db:
        a, u = _unidad(db)
        if u is None:
            u = Unit(asset_id=a.id, codigo=CODIGO, bloque="PRUEBA", uso="apartamento", tipologia="Apartamento de prueba", planta="0",
                     capacidad=2, estado="disponible", notas="Apartamento de prueba de la fase 4: se borra al terminar")
            db.add(u)
            db.commit()
        print(json.dumps({"unidad_pms_id": u.id, "codigo": u.codigo}))


def _cliente(db):
    c = db.scalar(select(Contact).where(Contact.nombre == "Cliente prueba fase 4"))
    if c is None:
        a = db.scalar(select(Asset).where(Asset.codigo == "SAE"))
        c = Contact(nombre="Cliente prueba fase 4", tipo="huesped", company_id=a.company_id, asset_id=a.id)
        db.add(c)
        db.flush()
    return c


def actividad():
    with SessionLocal() as db:
        a, u = _unidad(db)
        g = _cliente(db)
        r1 = Reservation(unit_id=u.id, guest_id=g.id, localizador="PRUEBA-F4-1", canal="booking", fecha_entrada=date(2031, 1, 10),
                         fecha_salida=date(2031, 1, 14), importe_total=440, estado="confirmada")
        r2 = Reservation(unit_id=u.id, guest_id=g.id, localizador="PRUEBA-F4-2", canal="directo", fecha_entrada=date(2031, 1, 20),
                         fecha_salida=date(2031, 1, 22), importe_total=220, estado="confirmada")
        r3 = Reservation(unit_id=u.id, guest_id=g.id, localizador="PRUEBA-F4-3", canal="airbnb", fecha_entrada=date(2031, 2, 3),
                         fecha_salida=date(2031, 2, 5), importe_total=200, estado="confirmada")
        db.add_all([r1, r2, r3])
        db.commit()  # 3 × reserva.creada
        r1.estado = "checkin"
        db.commit()  # reserva.modificada
        r1.estado = "checkout"
        db.commit()  # checkout
        r2.estado = "checkin"
        db.commit()
        r2.estado = "checkout"
        db.commit()  # checkout sin incidencia: solo limpieza (en el PMS), nada en gestión
        # limpieza de salida de r1 con incidencia → orden del PMS + aviso (origen PMS_CHECKOUT)
        t = CleaningTask(asset_id=a.id, unit_id=u.id, fecha=date(2031, 1, 14), tipo="salida", reservation_id=r1.id,
                         clave=f"prueba-f4:{r1.id}", estado="hecha", nota="Prueba fase 4")
        w = WorkOrder(asset_id=a.id, unit_id=u.id, tipo="correctivo", categoria="general", prioridad="alta",
                      titulo=f"Incidencia tras la limpieza · Apartamento {CODIGO}", descripcion="Prueba fase 4: grifo que gotea",
                      bloquea_unidad=False)
        w._origen_gestion = "PMS_CHECKOUT"
        db.add_all([t, w])
        db.commit()
        # incidencia de recepción
        w2 = WorkOrder(asset_id=a.id, unit_id=u.id, tipo="correctivo", categoria="general", prioridad="media",
                       titulo="Prueba fase 4: persiana rota", descripcion="Incidencia de recepción de prueba")
        db.add(w2)
        db.commit()
        r3.estado = "cancelada"
        db.commit()  # reserva.cancelada
        u.notas = json.dumps({"comisiones_previas": a.comisiones_canal})  # se restauran al limpiar
        a.comisiones_canal = dict(a.comisiones_canal or {}, booking=15, airbnb=3)
        db.commit()
        gestion.enviar_liquidacion(db, a, "2031-01")
        gestion.enviar_liquidacion(db, a, "2031-02")
        db.commit()
        ids = {"reservas": [r1.id, r2.id, r3.id], "ots": [w.id, w2.id]}
        res = gestion.procesar_cola(db)
        pend = db.scalars(select(GestionEvento).where(GestionEvento.estado != "enviado")).all()
        mios = [e for e in db.scalars(select(GestionEvento).order_by(GestionEvento.id))
                if (e.datos or {}).get("unidad_codigo") == CODIGO or (e.tipo == "liquidacion.periodo" and str((e.datos or {}).get("periodo", "")).startswith("2031"))]
        print(json.dumps({"ids": ids, "envio": res, "pendientes": len(pend),
                          "eventos": [{"id_evento": e.id_evento, "tipo": e.tipo, "estado": e.estado, "error": e.ultimo_error} for e in mios]},
                         ensure_ascii=False, default=str))


def pases():
    """Pases firmados como los del botón: uno válido (Alfonso), uno sin usuario en gestión y uno de técnico."""
    def pase(email, activo="SAEROPUERTO", destino="unidad", unidad=CODIGO, uid=None):
        d = {"usuario_pms": 0, "email": email, "destino": destino, "activo": activo, "unidad": unidad, "unidad_pms_id": uid,
             "emitido": datetime.now(timezone.utc).isoformat(timespec="seconds"), "nonce": secrets.token_hex(16)}
        p = base64.urlsafe_b64encode(json.dumps(d, separators=(",", ":")).encode()).decode().rstrip("=")
        return f"/sso/pms?pase={p}&firma={hmac.new(gestion.SSO_SECRET.encode(), p.encode(), hashlib.sha256).hexdigest()}"
    with SessionLocal() as db:
        _, u = _unidad(db)
        print(json.dumps({"alfonso": pase("alfonso@inversiete.es", uid=u.id), "sin_usuario": pase("nadie.prueba@inversiete.es"),
                          "tecnico": pase("p.tecnico.f4@prueba.invalid")}))


def estado():
    with SessionLocal() as db:
        _, u = _unidad(db)
        bs = db.scalars(select(UnitBlock).where(UnitBlock.unit_id == u.id)).all() if u else []
        print(json.dumps({"estado": u.estado if u else None, "bloqueos": [{"origen": b.origen, "levantado": bool(b.levantado)} for b in bs]}))


def limpiar():
    with SessionLocal() as db:
        a, u = _unidad(db)
        n = 0
        if u is not None:
            try:
                previas = json.loads(u.notas or "{}").get("comisiones_previas", "nada")
            except ValueError:
                previas = "nada"
            if previas != "nada":
                a.comisiones_canal = previas
            rids = [r.id for r in db.scalars(select(Reservation).where(Reservation.unit_id == u.id))]
            for m in (CleaningTask, WorkOrder, UnitBlock):
                for x in db.scalars(select(m).where(m.unit_id == u.id)):
                    db.delete(x)
                    n += 1
            db.flush()
            for r in db.scalars(select(Reservation).where(Reservation.unit_id == u.id)):
                r._desde_gestion = True
                db.delete(r)
                n += 1
            db.flush()
            db.delete(u)
            n += 1
        for c in db.scalars(select(Contact).where(Contact.nombre == "Cliente prueba fase 4")):
            db.delete(c)
        for e in db.scalars(select(GestionEvento)):
            d = e.datos or {}
            if d.get("unidad_codigo") == CODIGO or (e.tipo == "liquidacion.periodo" and str(d.get("periodo", "")).startswith("2031")):
                db.delete(e)
                n += 1
        db.commit()
        quedan = db.scalar(select(Unit.id).where(Unit.codigo == CODIGO))
        print(json.dumps({"borrados": n, "queda_unidad": bool(quedan)}))


if __name__ == "__main__":
    {"preparar": preparar, "actividad": actividad, "pases": pases, "estado": estado, "limpiar": limpiar}[sys.argv[1]]()
