"""Pasarela con INVERGESTION (gestion.inversiete.es) · fase 4 del plan ERP (13/10/2026).

PMS → gestión: cada cambio que interesa a gestión (reserva creada / modificada / cancelada, check-out, incidencia
y liquidación mensual) se guarda como un evento en la cola `gestion_cola` EN LA MISMA TRANSACCIÓN que el cambio.
Un hilo los envía firmados (HMAC-SHA256 con PMS_EVENTOS_SECRET) a POST /api/pms/eventos de gestión. Si gestión no
responde se reintenta a los 1 min, 5 min, 30 min y 2 h; después se avisa por correo y se sigue reintentando cada 2 h,
así que un corte no pierde nada. Gestión descarta los repetidos por `id_evento`.

Gestión → PMS (firmado con la misma clave): cierre y apertura de disponibilidad de un apartamento por una orden de
trabajo de gestión con «inhabilita la unidad» (POST /api/gestion/bloqueo) y lista de unidades para emparejarlas
(GET /api/gestion/unidades). Las reservas confirmadas en esas fechas NO se cancelan: se avisa a recepción.

Botón «Gestión»: GET /api/gestion/pase devuelve la dirección de entrada a gestión. Con PMS_GESTION_SSO_SECRET es un
pase firmado de un solo uso (60 s) que gestión comprueba; sin la clave, la dirección normal (gestión pide contraseña).
Las claves solo están en el .env del servidor; nunca en el código ni en el navegador.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from . import avisos
from .config import settings
from .database import SessionLocal, get_db
from .models import (Asset, AuditLog, EmailLog, GestionEvento, Reservation, Unit, UnitBlock, User, WorkOrder)
from .security import Scope, get_scope
from .utils import bad_request, get_or_404

log = logging.getLogger("pms.gestion")

EVENTOS_SECRET = os.environ.get("PMS_EVENTOS_SECRET") or ""
SSO_SECRET = os.environ.get("PMS_GESTION_SSO_SECRET") or ""
GESTION_URL = (os.environ.get("PMS_GESTION_URL") or "http://invergestion:8000").rstrip("/")
GESTION_PUBLICA = (os.environ.get("PMS_GESTION_PUBLICA") or "https://gestion.inversiete.es").rstrip("/")
AUTO = (os.environ.get("PMS_GESTION_AUTO") or "1") != "0"
VENTANA = 300  # segundos de margen para la firma (los dos programas están en el mismo servidor)
REINTENTOS = [60, 300, 1800, 7200]  # 1 min, 5 min, 30 min, 2 h; después cada 2 h con aviso
ACTIVOS = {"SFL": "SFLORIDA", "SAE": "SAEROPUERTO", "BAB35": "BABILONIA35"}
CANALES = ["directo", "booking", "airbnb", "expedia", "web", "agencia", "otros"]
IVA_ALOJAMIENTO = 10.0
ORIGEN = "gestion:"  # UnitBlock.origen de los bloqueos que pone gestión
# Avisos nuevos (contrato v2, ver docs/pasarela_v2.md): se guardan siempre en la cola, pero solo se mandan cuando
# gestión ya los sabe recibir (PMS_GESTION_EVENTOS_V2=1). Al activarlo salen todos los guardados, no se pierde nada.
EVENTOS_V2 = ("reserva.ampliada", "fianza.cobrada", "fianza.devolucion", "fianza.transferida", "caja.cierre",
              "incidencia.cerrada", "kpi.diario")
V2 = (os.environ.get("PMS_GESTION_EVENTOS_V2") or "0") == "1"
avisos.TIPOS.setdefault("bloqueo_gestion", ("Apartamento cerrado desde gestión por una avería con reservas que hay "
                                            "que reubicar (al momento)", "reservas.ver"))

router = APIRouter(prefix="/api/gestion", tags=["gestion"])


# --------------------------------------------------------------------------- firma
def firmar(secreto: str, ts: str, cuerpo: bytes) -> str:
    return hmac.new(secreto.encode(), ts.encode() + b"." + cuerpo, hashlib.sha256).hexdigest()


def comprobar(secreto: str, ts: str | None, firma: str | None, cuerpo: bytes) -> None:
    if not secreto:
        raise HTTPException(503, "Pasarela con gestión sin configurar (PMS_EVENTOS_SECRET)")
    try:
        edad = abs(time.time() - int(ts or ""))
    except ValueError:
        raise HTTPException(401, "Petición sin fecha")
    if edad > VENTANA:
        raise HTTPException(401, "Petición caducada")
    if not firma or not hmac.compare_digest(firmar(secreto, ts or "", cuerpo), firma):
        raise HTTPException(401, "Firma no válida")


def _codigo_gestion(asset: Asset | None) -> str | None:
    return ACTIVOS.get(asset.codigo, asset.codigo) if asset else None


def _nombre(c) -> str:
    return " ".join(x for x in (getattr(c, "nombre", None), getattr(c, "apellidos", None)) if x) if c else ""


def _num(x) -> float:
    return float(x) if isinstance(x, (Decimal, int, float)) else float(x or 0)


# --------------------------------------------------------------------------- cola de eventos
def encolar(db: Session, tipo: str, datos: dict, clave: str | None = None) -> GestionEvento | None:
    """Añade un evento a la cola (se guarda con la transacción en curso). `clave`: id fijo para no repetirlo."""
    ide = clave or f"pms-{tipo}-{uuid.uuid4().hex}"
    if clave and db.scalar(select(GestionEvento.id).where(GestionEvento.id_evento == clave)):
        return None
    ev = GestionEvento(id_evento=ide, tipo=tipo, datos=datos, estado="pendiente", intentos=0, proximo=datetime.now())
    db.add(ev)
    return ev


def _datos_reserva(r: Reservation) -> dict:
    u = r.unit
    a = u.asset if u else None
    return {"reserva_id": r.id, "localizador": r.localizador, "activo": _codigo_gestion(a), "activo_pms": a.codigo if a else None,
            "unidad_pms_id": r.unit_id, "unidad_codigo": u.codigo if u else None, "uso": u.uso if u else None,
            "canal": (r.canal or "directo").lower(), "entrada": r.fecha_entrada.isoformat() if r.fecha_entrada else None,
            "salida": r.fecha_salida.isoformat() if r.fecha_salida else None, "adultos": r.adultos, "ninos": r.ninos,
            "importe_total": _num(r.importe_total), "importe_pagado": _num(r.importe_pagado), "estado": r.estado}


def _datos_ot(w: WorkOrder, origen: str) -> dict:
    u = w.unit_id and getattr(w, "_unidad", None)
    return {"ot_pms_id": w.id, "activo": _codigo_gestion(w._activo) if getattr(w, "_activo", None) else None,
            "unidad_pms_id": w.unit_id, "unidad_codigo": u.codigo if u else None, "zona": w.zona, "titulo": w.titulo,
            "descripcion": w.descripcion, "prioridad": w.prioridad, "categoria": w.categoria, "tipo": w.tipo,
            "bloquea_unidad": bool(w.bloquea_unidad), "origen": origen,
            "fecha": (w.fecha_apertura or date.today()).isoformat()}


RES_CAMPOS = ("estado", "fecha_entrada", "fecha_salida", "unit_id", "importe_total", "canal", "adultos", "ninos")


@event.listens_for(SessionLocal, "after_flush")
def _detectar(session: Session, _ctx) -> None:
    """Tras cada escritura: reservas y órdenes nuevas o cambiadas → eventos (se añaden al final del flush)."""
    from sqlalchemy import inspect as sa_inspect
    pend = session.info.setdefault("gestion_pend", [])
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Reservation):
            st = sa_inspect(obj)
            if obj in session.new:
                pend.append(("reserva.creada", obj))
                continue
            cambios = {k for k in RES_CAMPOS if st.attrs[k].history.has_changes()}
            if not cambios:
                continue
            if "estado" in cambios and obj.estado == "checkout":
                # la estancia sigue en una ampliación: no es una salida (el cliente no se va)
                pend.append(("reserva.ampliada" if getattr(obj, "_ampliada_en", None) else "checkout", obj))
            elif "estado" in cambios and obj.estado in ("cancelada", "no_show", "anulada"):
                pend.append(("reserva.cancelada", obj))
            else:
                pend.append(("reserva.modificada", obj))
        elif isinstance(obj, WorkOrder) and obj in session.new:
            if obj.tipo in ("correctivo", "mejora") or getattr(obj, "_origen_gestion", None):
                pend.append(("incidencia.reportada", obj))
        elif isinstance(obj, WorkOrder) and obj.estado in ("cerrada", "cancelada") and obj.tipo in ("correctivo", "mejora"):
            if sa_inspect(obj).attrs["estado"].history.has_changes():
                pend.append(("incidencia.cerrada", obj))


@event.listens_for(SessionLocal, "after_flush_postexec")
def _encolar_detectados(session: Session, _ctx) -> None:
    pend = session.info.pop("gestion_pend", [])
    vistos = set()
    for tipo, obj in pend:
        k = (tipo, type(obj).__name__, obj.id)
        if k in vistos or getattr(obj, "_desde_gestion", False):
            continue
        vistos.add(k)
        try:
            if isinstance(obj, Reservation):
                datos = _datos_reserva(obj)
                if tipo == "checkout":
                    datos["fecha_checkout"] = date.today().isoformat()
                elif tipo == "reserva.ampliada":
                    datos["fecha_fin_tramo"] = date.today().isoformat()
                    datos["continua_en"] = _datos_reserva(obj._ampliada_en)
            elif tipo == "incidencia.cerrada":
                datos = {"ot_pms_id": obj.id, "estado": obj.estado, "fecha_cierre": (obj.fecha_cierre or date.today())
                         .isoformat(), "solucion": obj.solucion, "coste_real": _num(obj.coste_real) if obj.coste_real
                         is not None else None, "asignado_a": obj.asignado_a}
            else:
                obj._activo = session.get(Asset, obj.asset_id)
                obj._unidad = session.get(Unit, obj.unit_id) if obj.unit_id else None
                datos = _datos_ot(obj, getattr(obj, "_origen_gestion", None) or "PMS_INCIDENCIA")
            encolar(session, tipo, datos)
        except Exception:  # noqa: BLE001 — un fallo al preparar el aviso a gestión no debe impedir la operación
            log.exception("No se pudo preparar el evento %s para gestión", tipo)


def _enviar(ev: GestionEvento) -> tuple[bool, str]:
    from . import fusion
    if (ev.datos or {}).get("version") == fusion.VERSION:  # avisos de la fusión: cabecera completa «fusion1»
        cuerpo = fusion.cuerpo(ev)
    else:
        cuerpo = json.dumps({"id_evento": ev.id_evento, "tipo": ev.tipo, "emitido": ev.creado.isoformat(timespec="seconds"),
                             "datos": ev.datos}, ensure_ascii=False, default=str).encode()
    ts = str(int(time.time()))
    req = urllib.request.Request(GESTION_URL + "/api/pms/eventos", data=cuerpo, method="POST",
                                 headers={"Content-Type": "application/json", "X-INVG": "1", "X-PMS-Fecha": ts,
                                          "X-PMS-Firma": firmar(EVENTOS_SECRET, ts, cuerpo)})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return True, r.read(4000).decode(errors="replace")
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read(300).decode(errors='replace')}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:300]


def procesar_cola(db: Session, ahora: datetime | None = None, limite: int = 50) -> dict:
    """Envía los eventos pendientes cuyo turno ha llegado. Devuelve cuántos se enviaron y cuántos fallaron."""
    if not EVENTOS_SECRET:
        return {"enviados": 0, "fallidos": 0, "sin_configurar": True}
    ahora = ahora or datetime.now()
    env = fal = 0
    q = select(GestionEvento).where(GestionEvento.estado.in_(("pendiente", "aviso")), GestionEvento.proximo <= ahora)
    if not V2:  # los avisos nuevos esperan en la cola hasta que gestión los sepa recibir
        q = q.where(GestionEvento.tipo.not_in(EVENTOS_V2))
    from . import fusion
    if not fusion.SYNC:  # fusión apagada (PMS_GESTION_SYNC_FACTURAS=0): sus avisos esperan
        q = q.where(GestionEvento.tipo.not_in(fusion.TIPOS))
    from . import calendario_comun as calendario
    if not calendario.activo(db):  # calendario común apagado: sus avisos esperan
        q = q.where(GestionEvento.tipo.not_in(calendario.TIPOS_EVENTO))
    for ev in db.scalars(q.order_by(GestionEvento.id).limit(limite)):
        if calendario.es_aviso(ev) and calendario.bloqueado(db, ev):
            continue  # en orden por uid: espera a que salga el anterior de la misma entrada
        if ev.tipo in fusion.TIPOS and not fusion.materializar(db, ev):
            ev.estado, ev.ultimo_error = "descartado", "El registro ya no existe en el PMS"
            db.commit()
            continue
        ok, resp = _enviar(ev)
        ev.intentos += 1
        if ok:
            ev.estado, ev.enviado, ev.ultimo_error = "enviado", datetime.now(), None
            if ev.tipo in fusion.TIPOS:
                fusion.entregado(db, ev, resp)
            elif calendario.es_aviso(ev):
                calendario.entregado(db, ev)
            env += 1
        else:
            fal += 1
            ev.ultimo_error = resp
            ev.proximo = ahora + timedelta(seconds=REINTENTOS[min(ev.intentos - 1, len(REINTENTOS) - 1)])
            if ev.intentos >= len(REINTENTOS) and ev.estado != "aviso":
                ev.estado = "aviso"
                _avisar_fallo(db, ev)
        db.commit()
        if not ok and ("refused" in resp or "timed out" in resp or "Name or service" in resp):
            break  # gestión no responde: no tiene sentido seguir probando los demás ahora
    return {"enviados": env, "fallidos": fal}


def _avisar_fallo(db: Session, ev: GestionEvento) -> None:
    clave = f"gestion_cola_aviso:{date.today().isoformat()}"
    if db.scalar(select(EmailLog.id).where(EmailLog.clave == clave)) or not avisos.configurado():
        return
    n = db.scalar(select(func.count()).select_from(GestionEvento).where(GestionEvento.estado == "aviso")) or 1
    texto = (f"Hay {n} aviso(s) del PMS que gestión (INVERGESTION) no ha recibido tras varios intentos. "
             f"Último error: {ev.ultimo_error}. El PMS sigue reintentando cada 2 horas; no se pierde nada.")
    avisos._enviar_registrado(db, None, settings.mantenimiento_email, clave, "sistema",
                              "PMS → gestión: avisos sin entregar", texto, avisos._html("Avisos a gestión sin entregar", f"<p>{texto}</p>"))


# --------------------------------------------------------------------------- liquidación mensual
def _mes(periodo: str) -> tuple[date, date]:
    y, m = (int(x) for x in periodo.split("-"))
    ini = date(y, m, 1)
    fin = date(y + (m == 12), m % 12 + 1, 1)
    return ini, fin


def liquidacion(db: Session, asset: Asset, periodo: str) -> dict:
    """Producción del mes por canal: bruto (IVA incluido) prorrateado por noches del mes, IVA, comisión y neto.
    Solo apartamentos (los garajes van aparte en sus recibos). Comisión: % fijo por canal del activo."""
    ini, fin = _mes(periodo)
    pct = {k.lower(): _num(v) for k, v in (asset.comisiones_canal or {}).items() if not k.startswith("_")}
    unidades = list(db.scalars(select(Unit).where(Unit.asset_id == asset.id, Unit.uso != "garaje")))
    ids = [u.id for u in unidades]
    canales: dict[str, dict] = {}
    noches_total = 0
    for r in db.scalars(select(Reservation).where(Reservation.unit_id.in_(ids) if ids else False,
                                                 Reservation.estado.in_(("confirmada", "checkin", "checkout")),
                                                 Reservation.fecha_entrada < fin, Reservation.fecha_salida > ini)):
        noches = (r.fecha_salida - r.fecha_entrada).days or 1
        en_mes = (min(r.fecha_salida, fin) - max(r.fecha_entrada, ini)).days
        if en_mes <= 0:
            continue
        c = (r.canal or "directo").lower()
        x = canales.setdefault(c, {"canal": c, "reservas": 0, "noches": 0, "bruto": 0.0})
        x["reservas"] += 1
        x["noches"] += en_mes
        x["bruto"] += _num(r.importe_total) * en_mes / noches
        noches_total += en_mes
    filas = []
    for c, x in sorted(canales.items()):
        bruto = round(x["bruto"], 2)
        base = round(bruto / (1 + IVA_ALOJAMIENTO / 100), 2)
        p = pct.get(c, 0.0)
        com = round(bruto * p / 100, 2)
        filas.append({"canal": c, "reservas": x["reservas"], "noches": x["noches"], "bruto": bruto, "base": base,
                      "iva": round(bruto - base, 2), "tipo_iva": IVA_ALOJAMIENTO, "comision_pct": p, "comision": com,
                      "neto": round(bruto - com, 2)})
    dias = (fin - ini).days
    disp = len(unidades) * dias
    tot = {k: round(sum(f[k] for f in filas), 2) for k in ("bruto", "base", "iva", "comision", "neto")}
    return {"activo": _codigo_gestion(asset), "activo_pms": asset.codigo, "periodo": periodo, "canales": filas,
            "totales": tot, "reservas": sum(f["reservas"] for f in filas), "noches_ocupadas": noches_total,
            "unidades": len(unidades), "noches_disponibles": disp,
            "ocupacion": round(noches_total / disp * 100, 2) if disp else None,
            "calculada": datetime.now().isoformat(timespec="seconds")}


def enviar_liquidacion(db: Session, asset: Asset, periodo: str, clave: str | None = None) -> GestionEvento | None:
    return encolar(db, "liquidacion.periodo", liquidacion(db, asset, periodo), clave)


def liquidaciones_automaticas(db: Session, hoy: date | None = None) -> int:
    """El día 2 de cada mes (o después, si no se hizo) manda la liquidación del mes anterior de cada activo turístico que
    lo tenga activado («Mandar sola cada mes» en Pasarela con gestión). Por defecto no: hasta que las reservas del PMS
    reflejen toda la producción, una liquidación automática daría cifras incompletas."""
    hoy = hoy or date.today()
    if hoy.day < 2:
        return 0
    prev = (hoy.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    n = 0
    for a in db.scalars(select(Asset).where(Asset.modalidad == "apartamentos_turisticos", Asset.activo.is_(True))):
        if not (a.comisiones_canal or {}).get("_auto"):  # solo si dirección lo ha activado (con sus comisiones puestas)
            continue
        if enviar_liquidacion(db, a, prev, clave=f"liq-auto-{a.codigo}-{prev}"):
            n += 1
    db.commit()
    return n


# --------------------------------------------------------------------------- hilo de envío
def _bucle() -> None:
    time.sleep(20)
    while True:
        try:
            with SessionLocal() as db:
                procesar_cola(db)
            if datetime.now().hour >= 6:
                with SessionLocal() as db:
                    liquidaciones_automaticas(db)
        except Exception:  # noqa: BLE001
            log.exception("Error en la cola de avisos a gestión")
        time.sleep(30)


def arrancar() -> None:
    if AUTO:
        threading.Thread(target=_bucle, name="gestion", daemon=True).start()


# --------------------------------------------------------------------------- entradas firmadas desde gestión
async def _firmado(request: Request) -> dict:
    cuerpo = await request.body()
    comprobar(EVENTOS_SECRET, request.headers.get("x-pms-fecha"), request.headers.get("x-pms-firma"), cuerpo)
    try:
        return json.loads(cuerpo or b"{}")
    except ValueError:
        bad_request("Formato no válido")


@router.get("/unidades")
async def unidades_para_emparejar(request: Request, db: Session = Depends(get_db)):
    await _firmado(request)
    return [{"id": u.id, "activo": _codigo_gestion(a), "activo_pms": a.codigo, "codigo": u.codigo, "uso": u.uso,
             "bloque": u.bloque, "planta": u.planta, "estado": u.estado}
            for u, a in db.execute(select(Unit, Asset).join(Asset, Asset.id == Unit.asset_id).order_by(Asset.codigo, Unit.codigo))]


def _bloqueo_abierto(db: Session, uid: int, ot: str | None = None) -> list[UnitBlock]:
    q = select(UnitBlock).where(UnitBlock.unit_id == uid, UnitBlock.levantado.is_(None), UnitBlock.origen.like(ORIGEN + "%"))
    if ot:
        q = q.where(UnitBlock.origen == ORIGEN + ot)
    return list(db.scalars(q))


def _avisar_recepcion(db: Session, u: Unit, ot: str, motivo: str, afectadas: list[dict], huesped: str | None) -> int:
    filas = [[x["localizador"] or f"R-{x['id']}", x["huesped"], x["entrada"], x["salida"]] for x in afectadas]
    txt = (f"Gestión ha cerrado la disponibilidad del apartamento {u.codigo} por una avería ({ot}: {motivo}). "
           + (f"Hay un huésped alojado ({huesped}): el apartamento quedará bloqueado al hacer su check-out. " if huesped else "")
           + (f"Hay {len(afectadas)} reserva(s) confirmada(s) que NO se han cancelado: cámbielas de apartamento o avise al cliente."
              if afectadas else ""))
    html = avisos._html(f"Apartamento {u.codigo} cerrado por avería", f"<p>{txt}</p>" + (
        avisos._tabla(["Reserva", "Huésped", "Entrada", "Salida"], filas) if filas else ""))
    n = 0
    for usr, ids in avisos.suscritos(db, "bloqueo_gestion"):
        if ids is None or u.asset_id in ids:
            if avisos.configurado():
                avisos._enviar_registrado(db, usr, usr.email, f"bloqueo_gestion:{ot}:{usr.id}", "bloqueo_gestion",
                                          f"Reubicar huéspedes: apartamento {u.codigo} cerrado por avería", txt, html)
            n += 1
    return n


class BloqueoIn(BaseModel):
    accion: str = Field(pattern="^(cerrar|abrir)$")
    ot: str = Field(min_length=1, max_length=60)
    unidad_pms_id: int | None = None
    activo: str | None = None
    unidad_codigo: str | None = None
    motivo: str | None = Field(default=None, max_length=300)
    hasta: date | None = None


@router.post("/bloqueo")
async def bloqueo_desde_gestion(request: Request, db: Session = Depends(get_db)):
    """Cierra o abre la disponibilidad de un apartamento por una orden de trabajo de gestión. Idempotente por OT."""
    d = BloqueoIn(**await _firmado(request))
    u = db.get(Unit, d.unidad_pms_id) if d.unidad_pms_id else None
    if u is None and d.activo and d.unidad_codigo:
        inv = {v: k for k, v in ACTIVOS.items()}
        u = db.scalar(select(Unit).join(Asset).where(Asset.codigo == inv.get(d.activo, d.activo), Unit.codigo == d.unidad_codigo))
    if u is None:
        raise HTTPException(404, "Unidad no encontrada en el PMS")
    hoy = date.today()
    if d.accion == "cerrar":
        previo = _bloqueo_abierto(db, u.id, d.ot)
        alojado = db.scalar(select(Reservation).where(Reservation.unit_id == u.id, Reservation.estado == "checkin"))
        q = select(Reservation).where(Reservation.unit_id == u.id, Reservation.estado == "confirmada", Reservation.fecha_salida > hoy)
        if d.hasta:
            q = q.where(Reservation.fecha_entrada <= d.hasta)
        afectadas = [{"id": r.id, "localizador": r.localizador, "huesped": _nombre(r.guest),
                      "entrada": r.fecha_entrada.isoformat(), "salida": r.fecha_salida.isoformat()}
                     for r in db.scalars(q.order_by(Reservation.fecha_entrada))]
        if previo:
            return {"estado": "pendiente_huesped" if alojado else "cerrada", "unidad_estado": u.estado, "ya_estaba": True,
                    "reservas_afectadas": afectadas}
        b = UnitBlock(unit_id=u.id, motivo=f"Avería · orden de gestión {d.ot}: {d.motivo or ''}".strip(), hasta=d.hasta,
                      origen=ORIGEN + d.ot)
        db.add(b)
        anterior = u.estado
        if not alojado and u.estado not in ("bloqueada", "fuera_servicio", "mantenimiento"):
            u.estado = "bloqueada"
        huesped = (_nombre(alojado.guest) or "huésped") if alojado else None
        avisados = _avisar_recepcion(db, u, d.ot, d.motivo or "", afectadas, huesped) if (afectadas or alojado) else 0
        db.add(AuditLog(user_id=None, accion="bloquear_gestion", entidad="unidad", entidad_id=u.id,
                        detalle={"ot": d.ot, "estado_anterior": anterior, "reservas_afectadas": len(afectadas),
                                 "huesped_alojado": bool(alojado), "avisados": avisados}))
        db.commit()
        return {"estado": "pendiente_huesped" if alojado else "cerrada", "unidad_estado": u.estado,
                "reservas_afectadas": afectadas, "avisados": avisados}
    abiertos = _bloqueo_abierto(db, u.id, d.ot)
    for b in abiertos:
        b.levantado, b.nota_levantado = datetime.now(), f"Orden {d.ot} cerrada en gestión"
    otros = db.scalar(select(UnitBlock.id).where(UnitBlock.unit_id == u.id, UnitBlock.levantado.is_(None),
                                                 UnitBlock.id.notin_([b.id for b in abiertos] or [0])))
    if not otros and u.estado == "bloqueada":
        u.estado = "disponible"
    db.add(AuditLog(user_id=None, accion="desbloquear_gestion", entidad="unidad", entidad_id=u.id,
                    detalle={"ot": d.ot, "bloqueos": [b.id for b in abiertos]}))
    db.commit()
    return {"estado": "abierta", "unidad_estado": u.estado, "ya_estaba": not abiertos}


def bloqueado_por_gestion(db: Session, uid: int) -> UnitBlock | None:
    bs = _bloqueo_abierto(db, uid)
    return bs[0] if bs else None


# --------------------------------------------------------------------------- botón «Gestión» (pase firmado)
DESTINOS = {"inicio", "unidad", "incidencias", "produccion"}


def puede_ir(u: User) -> bool:
    """El botón «Gestión» solo es para el superadministrador y las cuentas de PMS_GESTION_USUARIOS."""
    return bool(u.is_superadmin or (u.email or "").lower() in settings.gestion_usuarios)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


@router.get("/pase")
def pase(destino: str = "inicio", asset_id: int | None = None, unit_id: int | None = None,
         scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Dirección para abrir gestión desde el PMS. La firma se calcula aquí, en el servidor."""
    if not puede_ir(scope.user):
        raise HTTPException(403, "El acceso a gestión solo está habilitado para la Dirección")
    if destino not in DESTINOS:
        bad_request("Destino no válido")
    a = db.get(Asset, asset_id) if asset_id else None
    u = db.get(Unit, unit_id) if unit_id else None
    if u is not None:
        a = a or db.get(Asset, u.asset_id)
    if a is not None and scope.asset_ids("activos.ver") is not None and a.id not in scope.asset_ids("activos.ver"):
        raise HTTPException(403, "Sin acceso a ese activo")
    activo, unidad = _codigo_gestion(a), (u.codigo if u else None)
    if not SSO_SECRET:
        qs = "&".join(f"{k}={v}" for k, v in (("destino", destino), ("activo", activo), ("unidad", unidad)) if v)
        return {"url": f"{GESTION_PUBLICA}/{'?' + qs if qs else ''}", "nivel": 1}
    datos = {"usuario_pms": scope.user.id, "email": scope.user.email, "destino": destino, "activo": activo,
             "unidad": unidad, "unidad_pms_id": u.id if u else None,
             "emitido": datetime.now(timezone.utc).isoformat(timespec="seconds"), "nonce": secrets.token_hex(16)}
    p = _b64(json.dumps(datos, ensure_ascii=False, separators=(",", ":")).encode())
    f = hmac.new(SSO_SECRET.encode(), p.encode(), hashlib.sha256).hexdigest()
    db.add(AuditLog(user_id=scope.user.id, accion="pase_gestion", entidad="activo", entidad_id=a.id if a else None,
                    detalle={"destino": destino, "unidad": unidad}))
    db.commit()
    return {"url": f"{GESTION_PUBLICA}/sso/pms?pase={p}&firma={f}", "nivel": 2}


# --------------------------------------------------------------------------- pantalla «Pasarela con gestión»
def _solo_admin(scope: Scope) -> None:
    if not (scope.user.is_superadmin or scope.is_group_level("usuarios.gestionar")):
        raise HTTPException(403, "Solo dirección")


@router.get("/estado")
def estado(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _solo_admin(scope)
    cuenta = dict(db.execute(select(GestionEvento.estado, func.count()).group_by(GestionEvento.estado)).all())
    ult = [{"id": e.id, "id_evento": e.id_evento, "tipo": e.tipo, "estado": e.estado, "intentos": e.intentos,
            "creado": e.creado.isoformat(timespec="seconds"), "enviado": e.enviado.isoformat(timespec="seconds") if e.enviado else None,
            "error": e.ultimo_error, "resumen": _resumen(e)}
           for e in db.scalars(select(GestionEvento).order_by(GestionEvento.id.desc()).limit(200))]
    activos = [{"id": a.id, "codigo": a.codigo, "nombre": a.nombre, "comisiones": a.comisiones_canal or {}}
               for a in db.scalars(select(Asset).where(Asset.modalidad == "apartamentos_turisticos").order_by(Asset.codigo))]
    en_espera = 0 if V2 else db.scalar(select(func.count()).select_from(GestionEvento).where(
        GestionEvento.estado.in_(("pendiente", "aviso")), GestionEvento.tipo.in_(EVENTOS_V2)))
    return {"configurado": bool(EVENTOS_SECRET), "sso": bool(SSO_SECRET), "url": GESTION_URL, "cuenta": cuenta,
            "eventos": ult, "activos": activos, "canales": CANALES, "v2": V2, "v2_en_espera": en_espera}


def _resumen(e: GestionEvento) -> str:
    d = e.datos or {}
    from . import fusion
    if e.tipo in fusion.TIPOS:
        return fusion.resumen(e)
    if e.tipo.startswith("calendario."):
        x = d.get("datos") or {}
        return f"{x.get('uid')} v{x.get('version')} · {x.get('tipo')} · {x.get('inicio')} · {x.get('titulo')}"
    if e.tipo.startswith("reserva") or e.tipo == "checkout":
        return f"{d.get('activo_pms')} {d.get('unidad_codigo')} · {d.get('localizador') or 'R-' + str(d.get('reserva_id'))} · {d.get('entrada')} → {d.get('salida')}"
    if e.tipo == "incidencia.reportada":
        return f"{d.get('activo')} {d.get('unidad_codigo') or d.get('zona') or ''} · OT-{d.get('ot_pms_id')} · {d.get('titulo')}"
    if e.tipo == "liquidacion.periodo":
        return f"{d.get('activo')} {d.get('periodo')} · bruto {d.get('totales', {}).get('bruto')} €"
    if e.tipo.startswith("fianza."):
        return (f"{d.get('activo_pms')} {d.get('unidad_codigo')} · {d.get('localizador') or 'R-' + str(d.get('reserva_id'))}"
                f" · fianza {d.get('fianza')} €" + (f" · devuelto {d.get('devuelto')} €" if "devuelto" in d else ""))
    if e.tipo == "caja.cierre":
        return f"{d.get('activo_pms')} · {d.get('recepcionista')} · {d.get('hasta')} · diferencia {d.get('diferencia')} €"
    if e.tipo == "incidencia.cerrada":
        return f"OT-{d.get('ot_pms_id')} · {d.get('estado')} {d.get('fecha_cierre')}"
    if e.tipo == "kpi.diario":
        return f"{d.get('activo_pms')} {d.get('fecha')} · ocupación {d.get('ocupacion')} %"
    return ""


class ComisionesIn(BaseModel):
    comisiones: dict[str, float]
    auto: bool = False


@router.put("/activos/{aid}/comisiones")
def guardar_comisiones(aid: int, data: ComisionesIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _solo_admin(scope)
    a = get_or_404(db, Asset, aid)
    limpio = {}
    for k, v in data.comisiones.items():
        if k.lower() not in CANALES or not 0 <= float(v) <= 50:
            bad_request(f"Comisión no válida para {k}")
        limpio[k.lower()] = round(float(v), 2)
    if data.auto:
        limpio["_auto"] = True
    a.comisiones_canal = limpio
    db.add(AuditLog(user_id=scope.user.id, accion="comisiones_canal", entidad="activo", entidad_id=aid, detalle=limpio))
    db.commit()
    return {"comisiones": limpio}


class LiquidacionIn(BaseModel):
    asset_id: int
    periodo: str = Field(pattern=r"^\d{4}-\d{2}$")


@router.post("/liquidacion/previa")
def previa(data: LiquidacionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _solo_admin(scope)
    return liquidacion(db, get_or_404(db, Asset, data.asset_id), data.periodo)


@router.post("/liquidacion/enviar")
def enviar_liq(data: LiquidacionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _solo_admin(scope)
    ev = enviar_liquidacion(db, get_or_404(db, Asset, data.asset_id), data.periodo)
    db.add(AuditLog(user_id=scope.user.id, accion="liquidacion_gestion", entidad="activo", entidad_id=data.asset_id,
                    detalle={"periodo": data.periodo}))
    db.commit()
    return {"id_evento": ev.id_evento if ev else None}


@router.post("/cola/reintentar")
def reintentar(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Adelanta el reintento de los avisos pendientes (no reenvía los ya entregados)."""
    _solo_admin(scope)
    n = 0
    for e in db.scalars(select(GestionEvento).where(GestionEvento.estado.in_(("pendiente", "aviso")))):
        e.proximo = datetime.now()
        n += 1
    db.commit()
    return {"reprogramados": n, **procesar_cola(db)}
