"""Calendario común PMS ↔ gestión (INVERGESTION) · contrato «fusion1», tipos calendario.creada / .actualizada /
.cancelada (instrucción del 15/10/2026). Ver docs/pasarela_v2.md, apartado «Calendario común».

Una sola agenda para los dos programas. Viajan citas y tareas, mantenimiento (OT programadas, preventivo, bloqueos y
limpiezas) y, solo para administración y dirección, vencimientos y fiscal. Las reservas NO entran.

- Gestión → PMS: llega por POST /api/gestion/eventos (la ruta de la fusión, misma firma). Se guarda por uid en
  `calendario_comun`; si ya está con versión ≥ la recibida se ignora. Gestión manda: su versión sustituye a la del
  PMS y el cambio local que hubiera queda en el historial de la entrada. «cancelada» no borra: marca CANCELADA.
- PMS → gestión: citas y tareas de la Agenda compartidas o públicas (las privadas no salen) y limpiezas programadas,
  por la cola de la fusión (mismos reintentos), en orden por uid. Nunca vencimientos ni fiscal ni nada de solo lectura.
  Lo que llega de gestión no se devuelve nunca (sin eco).
- Casilla «Sincronizar el calendario con gestión» (solo superadministración), apagada al desplegar: con ella apagada
  lo que llega se guarda «sin tratar» y no se manda nada.
- Visibilidad: vencimientos y fiscal (y todo lo que gestión marque solo para administración y dirección) solo los ve
  la superadministración y los roles de dirección y administración (ROLES_DIRECCION), cada uno solo los de sus
  sociedades (o, si la entrada no indica sociedad, de sus activos); recepción y técnicos nunca, ni en pantalla ni en
  Outlook.
- Outlook: cada usuario tiene su enlace privado /cal/<clave>.ics (solo lectura). En la base solo la sha256 de la clave.
"""
import hashlib
import logging
import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from . import agenda, avisos, gestion
from .config import settings
from .database import SessionLocal, get_db
from .models import (TIPOS_AGENDA, AgendaEvent, Ajuste, Asset, AuditLog, CalendarioEnlace, CalendarioEntrada,
                     CleaningTask, Company, GestionEvento, Unit, User)
from .security import Scope, audit, get_scope
from .utils import bad_request

log = logging.getLogger("pms.calendario_comun")
ZONA = ZoneInfo("Europe/Madrid")

TIPOS_EVENTO = ("calendario.creada", "calendario.actualizada", "calendario.cancelada")
TIPOS = ("CITA", "TAREA", "OT", "PREVENTIVO", "BLOQUEO", "LIMPIEZA", "VENCIMIENTO_PAGO", "VENCIMIENTO_COBRO", "FISCAL",
         "CONTRATO", "SEGURO", "AVAL")
FINANCIEROS = {"VENCIMIENTO_PAGO", "VENCIMIENTO_COBRO", "FISCAL", "CONTRATO", "SEGURO", "AVAL"}
MANTENIMIENTO = {"OT", "PREVENTIVO", "BLOQUEO", "LIMPIEZA"}
PERFILES_DIRECCION = {"superadmin", "administracion", "direccion"}
ESTADOS = ("PENDIENTE", "HECHA", "CANCELADA")
REPETICIONES = ("diaria", "laborables", "semanal", "mensual", "anual")
# Dirección y administración: superadministración y estos roles (no un permiso suelto: «finanzas.ver» lo tiene también
# el Gestor Alquiler Residencial). Cada uno ve solo lo de sus sociedades y activos, salvo la superadministración.
ROLES_DIRECCION = {"Dirección Grupo", "Dirección Sociedad", "Administración / Finanzas"}
AJUSTE = "calendario_sync"
UID = re.compile(r"^[A-Za-z0-9._:@-]{1,120}$")
DIAS_CANCELADAS = 60  # las canceladas se siguen sirviendo en Outlook 60 días (para que las quite)
DIAS_CARGA = 60  # al encender: lo de los últimos 60 días
MAX_PETICIONES_HORA = 60
ANTES_ICS = 120  # días hacia atrás que se sirven en Outlook

router = APIRouter(prefix="/api/calendario", tags=["calendario"])
publico = APIRouter(tags=["calendario"])


# --------------------------------------------------------------------------- casilla
def activo(db: Session) -> bool:
    a = db.get(Ajuste, AJUSTE)
    return bool(a and (a.valor or {}).get("activo"))


def poner(db: Session, valor: bool, user: User | None) -> None:
    a = db.get(Ajuste, AJUSTE)
    if a is None:
        a = Ajuste(clave=AJUSTE)
        db.add(a)
    a.valor, a.cambiado, a.user_id = {"activo": bool(valor)}, datetime.now(), user.id if user else None


# --------------------------------------------------------------------------- visibilidad
def correo(e: str | None) -> str:
    """inversiete.es e inversiete.com son el mismo buzón."""
    e = (e or "").strip().lower()
    return e[:-len("@inversiete.com")] + "@inversiete.es" if e.endswith("@inversiete.com") else e


def ambito(scope: Scope) -> SimpleNamespace | None:
    """Sociedades y activos en los que el usuario es dirección o administración (None: no lo es en ninguno).
    `grupo`: todo (superadministración o rol de dirección o administración para todo el grupo)."""
    if hasattr(scope, "_cal_ambito"):
        return scope._cal_ambito
    a = None
    if scope.user.is_superadmin:
        a = SimpleNamespace(grupo=True, sociedades=set(), activos=set())
    else:
        asig = [x for x in scope.user.assignments if x.role and x.role.nombre in ROLES_DIRECCION]
        if asig:
            a = SimpleNamespace(grupo=any(x.company_id is None and x.asset_id is None for x in asig),
                                sociedades=set(), activos=set())
            if not a.grupo:
                empresas = {x.company_id for x in asig if x.company_id and not x.asset_id}
                activos = {x.asset_id for x in asig if x.asset_id}
                filas = scope.db.execute(select(Asset.id, Asset.company_id)).all()
                a.activos = activos | {i for i, c in filas if c in empresas}
                a.sociedades = empresas | {c for i, c in filas if i in activos}
                codigos = _codigos_sociedad(scope.db)
                a.sociedades = {codigos[c] for c in a.sociedades if c in codigos}
    scope._cal_ambito = a
    return a


def _codigos_sociedad(db: Session) -> dict[int, str]:
    from . import fusion
    return {c.id: cod for c in db.scalars(select(Company)) if (cod := fusion.sociedad(c))}


def es_direccion(scope: Scope) -> bool:
    return ambito(scope) is not None


def en_ambito(c: CalendarioEntrada, scope: Scope) -> bool:
    """La entrada es de una sociedad (o, si no la indica, de un activo) del ámbito de dirección del usuario."""
    a = ambito(scope)
    if a is None:
        return False
    if a.grupo:
        return True
    if c.sociedad:
        return c.sociedad in a.sociedades
    return c.asset_id is not None and c.asset_id in a.activos


def restringida(c: CalendarioEntrada) -> bool:
    """Solo para administración y dirección: vencimientos y fiscal, y lo que gestión no abre a perfiles operativos."""
    roles = {str(r).lower() for r in (c.roles or [])}
    return c.tipo in FINANCIEROS or (bool(roles) and roles <= PERFILES_DIRECCION)


def puede_ver(c: CalendarioEntrada, scope: Scope) -> bool:
    if en_ambito(c, scope):
        return True
    if restringida(c):
        return False  # recepción y técnicos nunca ven vencimientos ni fiscal
    if c.tipo in MANTENIMIENTO:
        return c.asset_id is not None and scope.can_asset("activos.ver", c.asset_id)
    yo = correo(scope.user.email)
    return yo in {correo(x) for x in (c.responsables or []) + (c.invitados or [])}


def puede_editar(c: CalendarioEntrada, scope: Scope) -> bool:
    """Solo las de gestión que se editan en los dos programas, y solo sus responsables e invitados o la dirección."""
    if c.solo_lectura or c.editable_en != "AMBOS" or c.origen != "GESTION" or c.estado == "CANCELADA":
        return False
    if c.tipo in FINANCIEROS or not puede_ver(c, scope):
        return False
    yo = correo(scope.user.email)
    return en_ambito(c, scope) or yo in {correo(x) for x in (c.responsables or []) + (c.invitados or [])}


# --------------------------------------------------------------------------- fechas
def _fecha(txt, campo: str) -> tuple[datetime, bool]:
    """«AAAA-MM-DD» (día completo) o «AAAA-MM-DDTHH:MM» (hora de Madrid, sin zona)."""
    s = str(txt or "").strip()
    try:
        if len(s) == 10:
            return datetime.strptime(s, "%Y-%m-%d"), True
        return datetime.strptime(s[:16], "%Y-%m-%dT%H:%M"), False
    except ValueError:
        bad_request(f"Fecha no válida en «{campo}» (AAAA-MM-DD o AAAA-MM-DDTHH:MM)")


def _txt(d: datetime | None, todo_el_dia: bool) -> str | None:
    if d is None:
        return None
    return d.strftime("%Y-%m-%d") if todo_el_dia else d.strftime("%Y-%m-%dT%H:%M")


def _lista(x) -> list[str]:
    return [correo(e) for e in (x or []) if isinstance(e, str) and "@" in e][:100]


def _url(u) -> str | None:
    u = str(u or "").strip()
    return u[:500] if u.startswith(("https://", "http://")) else None  # nunca javascript: ni similares


# --------------------------------------------------------------------------- gestión → PMS
def _foto(c: CalendarioEntrada) -> dict:
    return {**datos_de(c), "ultimo_cambio": c.ultimo_cambio}


def recibir(db: Session, ev: dict) -> tuple[str, dict | None]:
    """Aplica un aviso calendario.* de gestión. Devuelve (estado de la entrada, resultado)."""
    d = ev.get("datos") or {}
    uid = str(d.get("uid") or "")
    if not UID.match(uid):
        bad_request("Entrada de calendario sin uid válido")
    try:
        version = int(d.get("version"))
    except (TypeError, ValueError):
        bad_request("Entrada de calendario sin versión")
    if version < 1:
        bad_request("La versión empieza en 1")
    tipo = str(d.get("tipo") or "").upper()
    if tipo not in TIPOS:
        bad_request(f"Tipo de calendario no válido: {tipo}")
    if not activo(db):
        return "sin_tratar", None
    c = db.scalar(select(CalendarioEntrada).where(CalendarioEntrada.uid == uid))
    if c is not None and c.version >= version:
        return "aplicado", {"uid": uid, "ignorado": "version", "version": c.version}
    if c is None:
        c = CalendarioEntrada(uid=uid, historial=[], origen="GESTION", version=version)
        db.add(c)
    elif c.cambio_local:
        # choque: el PMS tiene un cambio que gestión aún no ha recibido. Gestión manda: lo del PMS queda en el historial
        # y su aviso pendiente se descarta. (Si el cambio del PMS ya se entregó, no hay choque: es un cambio posterior.)
        c.historial = [*(c.historial or []), {"fecha": datetime.now().isoformat(timespec="seconds"),
                                              "motivo": "Sustituido por la versión de gestión",
                                              "version": c.version, "pendiente_de_enviar": c.cambio_local,
                                              "datos": _foto(c)}][-20:]
        for x in _pendientes(db, uid):
            x.estado, x.ultimo_error = "descartado", "Sustituido por la versión de gestión (manda gestión)"
    inicio, dia = _fecha(d.get("inicio"), "inicio")
    todo_el_dia = bool(d.get("todo_el_dia")) if "todo_el_dia" in d else dia
    if "fin" in d:
        fin = _fecha(d["fin"], "fin")[0] if d.get("fin") else None
    else:  # gestión no la manda: se conserva la que había (citas de varios días)
        fin = c.fin if c.id else None
    if fin and fin < inicio:
        bad_request("El final no puede ser anterior al inicio")
    asset = _activo_pms(db, d.get("activo") or ev.get("activo"))
    editable = str(d.get("editable_en") or "GESTION").upper()
    if editable not in ("GESTION", "PMS", "AMBOS"):
        editable = "GESTION"
    estado = str(d.get("estado") or "PENDIENTE").upper()
    if ev.get("tipo") == "calendario.cancelada":
        estado = "CANCELADA"
    rep = d.get("repeticion") if d.get("repeticion") in REPETICIONES else None
    c.version, c.version_remota = version, version
    c.tipo, c.subtipo = tipo, (str(d.get("subtipo"))[:40] if d.get("subtipo") else None)
    c.titulo = str(d.get("titulo") or "(sin título)")[:300]
    c.descripcion, c.lugar = d.get("descripcion") or None, (str(d.get("lugar"))[:300] if d.get("lugar") else None)
    c.inicio, c.fin, c.todo_el_dia = inicio, fin, todo_el_dia
    c.activo, c.asset_id = (str(d.get("activo") or ev.get("activo") or "")[:40] or None), asset.id if asset else None
    c.unidad = str(d.get("unidad"))[:60] if d.get("unidad") else None
    c.sociedad = str(d.get("sociedad") or ev.get("sociedad") or "")[:10] or None
    c.responsables, c.invitados = _lista(d.get("responsables")), _lista(d.get("invitados"))
    c.estado = estado if estado in ESTADOS else "PENDIENTE"
    c.recordatorio = int(d["recordatorio"]) if isinstance(d.get("recordatorio"), int) and d["recordatorio"] >= 0 else None
    c.repeticion = rep
    c.repetir_hasta = _fecha(d["repetir_hasta"], "repetir_hasta")[0].date() if rep and d.get("repetir_hasta") else None
    c.importe = Decimal(str(d["importe"])) if tipo in FINANCIEROS and d.get("importe") is not None else None
    c.prioridad = str(d.get("prioridad"))[:20] if d.get("prioridad") else None
    c.origen = "PMS" if uid.startswith("PMS-") else "GESTION"
    c.editable_en = editable
    c.solo_lectura = bool(d.get("solo_lectura")) or editable == "GESTION" or tipo in FINANCIEROS
    c.roles = [str(r) for r in (d.get("roles") or [])][:20] or None
    c.url_gestion = _url(d.get("url_gestion"))
    c.datos = {k: d.get(k) for k in ("origen_col", "origen_id", "origen") if d.get(k) is not None} or None
    c.ultimo_cambio, c.cambio_local, c.actualizado = "GESTION", False, datetime.now()
    if uid.startswith("PMS-AG-"):
        _a_agenda(db, c)
    return "aplicado", {"uid": uid, "version": version}


def _a_agenda(db: Session, c: CalendarioEntrada) -> None:
    """Cambio de gestión sobre una cita que nació en el PMS: se aplica a la cita (gestión manda). Cancelada no borra
    la cita (no se tocan datos grabados a mano): queda marcada «cancelada en gestión»."""
    e = db.get(AgendaEvent, c.agenda_id) if c.agenda_id else None
    if e is None:
        return
    e.titulo, e.descripcion, e.lugar = c.titulo[:200], c.descripcion, (c.lugar or "")[:200] or None
    e.inicio, e.todo_el_dia = c.inicio, c.todo_el_dia
    e.fin = c.fin  # día completo: último día incluido a las 00:00, como lo guarda la Agenda del PMS
    if e.tipo == "tarea" and c.estado in ("HECHA", "PENDIENTE"):
        e.hecha = c.estado == "HECHA"


def _activo_pms(db: Session, codigo) -> Asset | None:
    from . import fusion
    return fusion._activo_pms(db, str(codigo)) if codigo else None


# --------------------------------------------------------------------------- PMS → gestión
def datos_de(c: CalendarioEntrada) -> dict:
    return {"uid": c.uid, "version": c.version, "tipo": c.tipo, "subtipo": c.subtipo, "titulo": c.titulo,
            "descripcion": c.descripcion, "lugar": c.lugar, "inicio": _txt(c.inicio, c.todo_el_dia),
            "fin": _txt(c.fin, c.todo_el_dia), "todo_el_dia": c.todo_el_dia, "activo": c.activo, "unidad": c.unidad,
            "sociedad": c.sociedad, "responsables": c.responsables or [], "invitados": c.invitados or [],
            "estado": c.estado, "recordatorio": c.recordatorio, "repeticion": c.repeticion,
            "repetir_hasta": c.repetir_hasta.isoformat() if c.repetir_hasta else None,
            "importe": None, "prioridad": c.prioridad, "origen": c.origen,
            "origen_col": (c.datos or {}).get("origen_col"), "origen_id": (c.datos or {}).get("origen_id"),
            "editable_en": c.editable_en, "solo_lectura": c.solo_lectura, "roles": c.roles,
            "url_gestion": c.url_gestion}


def _huella(uid: str) -> str:
    return hashlib.sha1(uid.encode()).hexdigest()[:16]


def _pendientes(db: Session, uid: str) -> list[GestionEvento]:
    return list(db.scalars(select(GestionEvento).where(GestionEvento.id_evento.like(f"cal-{_huella(uid)}-%"),
                                                       GestionEvento.estado.in_(("pendiente", "aviso")))))


def encolar(db: Session, c: CalendarioEntrada, tipo_ev: str) -> GestionEvento | None:
    """Deja el aviso en la cola de gestión. Nunca vencimientos ni fiscal ni cambios sobre entradas de solo lectura."""
    if not activo(db):
        return None
    if c.tipo in FINANCIEROS or (c.origen == "GESTION" and (c.solo_lectura or c.editable_en != "AMBOS")):
        raise ValueError("Ese tipo de entrada no se manda a gestión")
    sobre = {"version": gestion_version(), "emitido": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "origen": "PMS", "id_evento_causa": None, "activo": c.activo, "sociedad": c.sociedad,
             "datos": datos_de(c), "documentos": [], "_cal": c.uid}
    ev = gestion.encolar(db, tipo_ev, sobre, clave=f"cal-{_huella(c.uid)}-v{c.version}-{uuid.uuid4().hex[:10]}")
    c.cambio_local = True
    return ev


def gestion_version() -> str:
    from . import fusion
    return fusion.VERSION


def es_aviso(ev: GestionEvento) -> bool:
    return ev.tipo in TIPOS_EVENTO


def bloqueado(db: Session, ev: GestionEvento) -> bool:
    """En orden por uid: no sale un aviso mientras otro anterior de la misma entrada siga sin entregar."""
    pref = ev.id_evento.rsplit("-v", 1)[0] + "-v"
    return bool(db.scalar(select(GestionEvento.id).where(GestionEvento.id_evento.like(pref + "%"),
                                                         GestionEvento.id < ev.id,
                                                         GestionEvento.estado.in_(("pendiente", "aviso"))).limit(1)))


def entregado(db: Session, ev: GestionEvento) -> None:
    uid = (ev.datos or {}).get("_cal")
    c = db.scalar(select(CalendarioEntrada).where(CalendarioEntrada.uid == uid)) if uid else None
    if c is None:
        return
    if not _pendientes(db, uid) or all(x.id == ev.id for x in _pendientes(db, uid)):
        c.cambio_local = False
    c.datos = {**(c.datos or {}), "enviada": True}


def _mapa_agenda(db: Session, e: AgendaEvent, c: CalendarioEntrada) -> None:
    creador = db.get(User, e.creador_id)
    a = db.get(Asset, e.asset_id) if e.asset_id else None
    comp = db.get(Company, a.company_id) if a else None
    invitados = [correo(u.email) for u in db.scalars(select(User).where(
        User.id.in_([p.user_id for p in e.participantes] or [-1])))]
    c.tipo = "TAREA" if e.tipo == "tarea" else "CITA"
    c.subtipo = None if e.tipo == "tarea" else e.tipo
    c.titulo, c.descripcion, c.lugar = e.titulo, e.descripcion, e.lugar
    c.todo_el_dia, c.inicio = e.todo_el_dia, e.inicio
    c.fin = (e.fin.replace(hour=0, minute=0, second=0, microsecond=0) if e.todo_el_dia and e.fin else e.fin)
    c.activo, c.asset_id = gestion._codigo_gestion(a), e.asset_id
    from . import fusion
    c.sociedad = fusion.sociedad(comp) if comp else None
    c.responsables = [correo(creador.email)] + (invitados if e.tipo == "tarea" else []) if creador else invitados
    c.invitados = [] if e.tipo == "tarea" else invitados
    c.estado = "HECHA" if e.tipo == "tarea" and e.hecha else "PENDIENTE"
    c.recordatorio = e.aviso_min
    c.repeticion, c.repetir_hasta = e.repeticion or None, e.repetir_hasta
    c.prioridad = e.prioridad
    c.origen, c.editable_en, c.solo_lectura, c.roles = "PMS", "AMBOS", False, None


def _espejo(db: Session, uid: str) -> CalendarioEntrada | None:
    return db.scalar(select(CalendarioEntrada).where(CalendarioEntrada.uid == uid))


def desde_agenda(db: Session, e: AgendaEvent, borrada: bool = False) -> None:
    """Alta, cambio o borrado de una cita de la Agenda. Las privadas no salen (si deja de compartirse, se cancela)."""
    if not activo(db):
        return
    uid = f"PMS-AG-{e.id}"
    c = _espejo(db, uid)
    compartida = not borrada and e.visibilidad in ("compartida", "publica")
    if not compartida:
        if c is not None and c.estado != "CANCELADA":
            c.version += 1
            c.estado, c.ultimo_cambio, c.actualizado = "CANCELADA", "PMS", datetime.now()
            if borrada:
                c.agenda_id = None
            encolar(db, c, "calendario.cancelada")
        return
    nueva = c is None or c.estado == "CANCELADA"
    if c is None:
        c = CalendarioEntrada(uid=uid, version=1, version_remota=0, agenda_id=e.id, historial=[], titulo=e.titulo,
                              inicio=e.inicio, tipo="CITA")
        db.add(c)
    else:
        c.version += 1
    _mapa_agenda(db, e, c)
    c.agenda_id, c.ultimo_cambio, c.actualizado = e.id, "PMS", datetime.now()
    db.flush()
    encolar(db, c, "calendario.creada" if nueva else "calendario.actualizada")


def _mapa_limpieza(db: Session, t: CleaningTask, c: CalendarioEntrada) -> None:
    a = db.get(Asset, t.asset_id)
    u = db.get(Unit, t.unit_id) if t.unit_id else None
    comp = db.get(Company, a.company_id) if a else None
    from . import fusion
    nombres = {"salida": "por salida", "contratada": "contratada", "extra": "extra"}
    c.tipo, c.subtipo = "LIMPIEZA", t.tipo
    c.titulo = f"Limpieza {nombres.get(t.tipo, t.tipo)} · {u.codigo if u else ''}".strip(" ·")
    c.descripcion = t.nota
    c.inicio, c.fin, c.todo_el_dia = datetime.combine(t.fecha, datetime.min.time()), None, True
    c.activo, c.asset_id = gestion._codigo_gestion(a), t.asset_id
    c.unidad = u.codigo if u else None
    c.sociedad = fusion.sociedad(comp) if comp else None
    c.estado = {"hecha": "HECHA", "anulada": "CANCELADA"}.get(t.estado, "PENDIENTE")
    c.prioridad = "alta" if t.urgente else None
    c.origen, c.editable_en, c.solo_lectura, c.roles = "PMS", "PMS", False, None
    c.responsables, c.invitados = [], []


def desde_limpieza(db: Session, t: CleaningTask | None, tid: int, borrada: bool = False) -> None:
    uid = f"PMS-LIM-{tid}"
    c = _espejo(db, uid)
    if borrada or t is None:
        if c is not None and c.estado != "CANCELADA":
            c.version += 1
            c.estado, c.ultimo_cambio, c.actualizado, c.limpieza_id = "CANCELADA", "PMS", datetime.now(), None
            encolar(db, c, "calendario.cancelada")
        return
    if c is None:
        c = CalendarioEntrada(uid=uid, version=1, version_remota=0, limpieza_id=t.id, historial=[], titulo="Limpieza",
                              inicio=datetime.combine(t.fecha, datetime.min.time()), tipo="LIMPIEZA")
        db.add(c)
        tipo_ev = "calendario.creada"
    else:
        c.version += 1
        tipo_ev = "calendario.actualizada"
    _mapa_limpieza(db, t, c)
    if c.estado == "CANCELADA":
        tipo_ev = "calendario.cancelada"
    c.limpieza_id, c.ultimo_cambio, c.actualizado = t.id, "PMS", datetime.now()
    encolar(db, c, tipo_ev)  # sin flush: puede llamarse dentro de un flush (limpiezas)


LIMPIEZA_CAMPOS = ("fecha", "estado", "unit_id", "tipo", "nota", "urgente")


@event.listens_for(SessionLocal, "after_flush")
def _detectar_limpiezas(session: Session, _ctx) -> None:
    from sqlalchemy import inspect as sa_inspect
    pend = session.info.setdefault("calendario_pend", {})
    for obj in session.new:
        if isinstance(obj, CleaningTask):
            pend[obj.id] = False
    for obj in session.dirty:
        if isinstance(obj, CleaningTask):
            st = sa_inspect(obj)
            if any(st.attrs[k].history.has_changes() for k in LIMPIEZA_CAMPOS):
                pend[obj.id] = False
    for obj in session.deleted:
        if isinstance(obj, CleaningTask):
            pend[obj.id] = True


@event.listens_for(SessionLocal, "after_flush_postexec")
def _encolar_limpiezas(session: Session, _ctx) -> None:
    pend = session.info.pop("calendario_pend", None)
    if not pend:
        return
    try:
        if not activo(session):
            return
        for tid, borrada in pend.items():
            desde_limpieza(session, None if borrada else session.get(CleaningTask, tid), tid, borrada)
    except Exception:  # noqa: BLE001 — un fallo al preparar el aviso a gestión no debe impedir la operación
        log.exception("No se pudo preparar el aviso de calendario de una limpieza")


def carga_inicial(db: Session) -> int:
    """Al encender la casilla: las citas compartidas y las limpiezas de los últimos 60 días (y las futuras) que aún
    no tiene gestión."""
    desde = datetime.combine(date.today() - timedelta(days=DIAS_CARGA), datetime.min.time())
    n = 0
    for e in db.scalars(select(AgendaEvent).where(AgendaEvent.visibilidad.in_(("compartida", "publica")),
                                                  (AgendaEvent.inicio >= desde) | AgendaEvent.repeticion.is_not(None))):
        c = _espejo(db, f"PMS-AG-{e.id}")
        if c is None or not (c.datos or {}).get("enviada"):
            if c is None:
                desde_agenda(db, e)
            else:
                encolar(db, c, "calendario.creada")
            n += 1
    for t in db.scalars(select(CleaningTask).where(CleaningTask.fecha >= desde.date(),
                                                   CleaningTask.estado != "anulada")):
        c = _espejo(db, f"PMS-LIM-{t.id}")
        if c is None or not (c.datos or {}).get("enviada"):
            if c is None:
                desde_limpieza(db, t, t.id)
            else:
                encolar(db, c, "calendario.creada")
            n += 1
    return n


# --------------------------------------------------------------------------- pantalla (Agenda del PMS)
def _ocurrencias(c: CalendarioEntrada, desde: date, hasta: date) -> list[datetime]:
    rep = "diaria" if c.repeticion == "laborables" else c.repeticion
    x = agenda.ocurrencias(SimpleNamespace(inicio=c.inicio, repeticion=rep, repetir_hasta=c.repetir_hasta), desde, hasta)
    return [d for d in x if d.weekday() < 5] if c.repeticion == "laborables" else x


def salida(c: CalendarioEntrada, scope: Scope, ocurrencia: datetime | None = None) -> dict:
    ini = ocurrencia or c.inicio
    fin = c.fin + (ini - c.inicio) if c.fin else None
    direccion = en_ambito(c, scope)
    return {"comun": True, "id": c.id, "uid": c.uid, "version": c.version, "tipo": c.tipo, "subtipo": c.subtipo,
            "titulo": c.titulo, "descripcion": c.descripcion, "lugar": c.lugar, "ocurrencia": ini.isoformat(),
            "fin_ocurrencia": fin.isoformat() if fin else None, "inicio": _txt(c.inicio, c.todo_el_dia),
            "fin": _txt(c.fin, c.todo_el_dia), "todo_el_dia": c.todo_el_dia, "activo": c.activo, "unidad": c.unidad,
            "estado": c.estado, "repeticion": c.repeticion, "responsables": c.responsables or [],
            "invitados": c.invitados or [], "solo_lectura": not puede_editar(c, scope),
            "editable": puede_editar(c, scope), "url_gestion": c.url_gestion, "origen": c.origen,
            "importe": float(c.importe) if direccion and c.importe is not None else None,
            "restringida": restringida(c)}


def _visibles(db: Session, scope: Scope, q) -> list[CalendarioEntrada]:
    return [c for c in db.scalars(q) if puede_ver(c, scope)]


@router.get("/agenda")
def en_agenda(desde: date, hasta: date, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Entradas de gestión que ve el usuario entre dos fechas (con sus repeticiones). Las del PMS ya están en la
    Agenda (citas) o en el parte de limpieza."""
    if hasta < desde or (hasta - desde).days > 400:
        bad_request("Rango de fechas no válido (máximo 400 días)")
    q = select(CalendarioEntrada).where(CalendarioEntrada.uid.not_like("PMS-%"),
                                        CalendarioEntrada.inicio < datetime.combine(hasta + timedelta(days=1),
                                                                                    datetime.min.time()))
    out = []
    for c in _visibles(db, scope, q):
        for x in _ocurrencias(c, desde, hasta):
            out.append(salida(c, scope, x))
    return sorted(out, key=lambda x: (x["ocurrencia"][:10], not x["todo_el_dia"], x["ocurrencia"]))


def cancelada_en_gestion(db: Session, ids: list[int]) -> set[int]:
    """Citas del PMS que gestión ha cancelado (siguen en la Agenda, marcadas)."""
    if not ids:
        return set()
    return set(db.scalars(select(CalendarioEntrada.agenda_id).where(
        CalendarioEntrada.agenda_id.in_(ids), CalendarioEntrada.estado == "CANCELADA",
        CalendarioEntrada.ultimo_cambio == "GESTION")))


class CambioIn(BaseModel):
    titulo: str = Field(min_length=2, max_length=300)
    descripcion: str | None = Field(default=None, max_length=4000)
    lugar: str | None = Field(default=None, max_length=300)
    inicio: str
    fin: str | None = None
    todo_el_dia: bool = False
    estado: str = "PENDIENTE"


def _entrada(db: Session, cid: int, scope: Scope) -> CalendarioEntrada:
    c = db.get(CalendarioEntrada, cid)
    if c is None or not puede_ver(c, scope):
        raise HTTPException(404, "No encontrado")
    return c


@router.put("/entradas/{cid}")
def cambiar(cid: int, data: CambioIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Cambio del PMS sobre una cita de gestión que se edita en los dos programas: versión + 1 y aviso a gestión."""
    c = _entrada(db, cid, scope)
    if not puede_editar(c, scope):
        raise HTTPException(403, "Esta entrada se gestiona en gestión: ábrala allí")
    if not activo(db):
        bad_request("La sincronización del calendario con gestión está apagada")
    if data.estado not in ("PENDIENTE", "HECHA"):
        bad_request("Estado no válido (PENDIENTE o HECHA)")
    inicio, dia = _fecha(data.inicio, "inicio")
    fin = _fecha(data.fin, "fin")[0] if data.fin else None
    if fin and fin < inicio:
        bad_request("El final no puede ser anterior al inicio")
    antes = _foto(c)
    c.titulo, c.descripcion, c.lugar = data.titulo, data.descripcion or None, data.lugar or None
    c.inicio, c.fin, c.todo_el_dia, c.estado = inicio, fin, data.todo_el_dia or dia, data.estado
    c.version += 1
    c.ultimo_cambio, c.actualizado = "PMS", datetime.now()
    encolar(db, c, "calendario.actualizada")
    audit(db, scope.user, "editar", "calendario", c.id, {"uid": c.uid, "version": c.version,
                                                         "antes": {k: antes[k] for k in ("titulo", "inicio", "fin", "estado")}})
    db.commit()
    return salida(c, scope)


@router.post("/entradas/{cid}/cancelar")
def cancelar(cid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    c = _entrada(db, cid, scope)
    if not puede_editar(c, scope):
        raise HTTPException(403, "Esta entrada se gestiona en gestión: ábrala allí")
    if not activo(db):
        bad_request("La sincronización del calendario con gestión está apagada")
    c.version += 1
    c.estado, c.ultimo_cambio, c.actualizado = "CANCELADA", "PMS", datetime.now()
    encolar(db, c, "calendario.cancelada")
    audit(db, scope.user, "cancelar", "calendario", c.id, {"uid": c.uid, "version": c.version})
    db.commit()
    return salida(c, scope)


# --------------------------------------------------------------------------- casilla (superadministración)
def _superadmin(scope: Scope) -> None:
    if not scope.user.is_superadmin:
        raise HTTPException(403, "Solo la superadministración")


@router.get("/config")
def ver_config(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _superadmin(scope)
    from .models import FusionEntrada
    from sqlalchemy import func
    a = db.get(Ajuste, AJUSTE)
    return {"activo": activo(db), "cambiado": a.cambiado.isoformat(timespec="seconds") if a else None,
            "entradas": db.scalar(select(func.count()).select_from(CalendarioEntrada).where(
                CalendarioEntrada.uid.not_like("PMS-%"))) or 0,
            "en_cola": db.scalar(select(func.count()).select_from(GestionEvento).where(
                GestionEvento.tipo.in_(TIPOS_EVENTO), GestionEvento.estado.in_(("pendiente", "aviso")))) or 0,
            "sin_tratar": db.scalar(select(func.count()).select_from(FusionEntrada).where(
                FusionEntrada.tipo.in_(TIPOS_EVENTO), FusionEntrada.estado == "sin_tratar")) or 0}


class ConfigIn(BaseModel):
    activo: bool


@router.put("/config")
def guardar_config(data: ConfigIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _superadmin(scope)
    antes = activo(db)
    poner(db, data.activo, scope.user)
    db.flush()
    aplicados = reprocesar_sin_tratar(db) if data.activo and not antes else {"aplicados": 0, "con_error": 0}
    n = carga_inicial(db) if data.activo and not antes else 0
    audit(db, scope.user, "calendario_sync", "ajustes", None, {"antes": antes, "ahora": data.activo, "carga": n,
                                                              **aplicados})
    db.commit()
    return {**ver_config(scope, db), "carga_inicial": n, "sin_tratar_aplicados": aplicados["aplicados"],
            "sin_tratar_con_error": aplicados["con_error"]}


def reprocesar_sin_tratar(db: Session) -> dict:
    """Al encender la casilla: los avisos calendario.* que llegaron con ella apagada se aplican en el orden en que
    llegaron. La versión de cada entrada evita duplicados (uno repetido o más viejo se ignora)."""
    from . import fusion
    from .models import FusionEntrada
    ok = mal = 0
    for x in list(db.scalars(select(FusionEntrada).where(FusionEntrada.tipo.in_(TIPOS_EVENTO),
                                                         FusionEntrada.estado == "sin_tratar")
                              .order_by(FusionEntrada.recibido, FusionEntrada.id))):
        db.info[fusion.DESDE_GESTION] = True
        try:
            with db.begin_nested():
                x.estado, x.resultado = recibir(db, x.cuerpo or {})
                db.flush()
            ok += 1
        except HTTPException as e:
            x.resultado = {"error": str(e.detail)[:300]}  # sigue «sin tratar»: no se pierde
            mal += 1
        finally:
            db.info.pop(fusion.DESDE_GESTION, None)
    return {"aplicados": ok, "con_error": mal}


# --------------------------------------------------------------------------- Outlook (enlace privado .ics)
def _sha(clave: str) -> str:
    return hashlib.sha256(clave.encode()).hexdigest()


def _base(request: Request | None = None) -> str:
    return (settings.url or (str(request.base_url) if request else "")).rstrip("/")


@router.get("/outlook")
def ver_outlook(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    e = db.scalar(select(CalendarioEnlace).where(CalendarioEnlace.user_id == scope.user.id))
    return {"existe": e is not None, "creado": e.creado.isoformat(timespec="seconds") if e else None,
            "ultimo_acceso": e.ultimo_acceso.isoformat(timespec="seconds") if e and e.ultimo_acceso else None,
            "mostrar_importes": bool(e and e.mostrar_importes), "puede_importes": es_direccion(scope)}


@router.post("/outlook", status_code=201)
def crear_outlook(request: Request, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Crea el enlace (o lo cambia: el anterior deja de funcionar). La clave se muestra solo ahora."""
    clave = secrets.token_urlsafe(32)
    e = db.scalar(select(CalendarioEnlace).where(CalendarioEnlace.user_id == scope.user.id))
    cambio = e is not None
    if e is None:
        e = CalendarioEnlace(user_id=scope.user.id, mostrar_importes=False, peticiones=0, avisado=False)
        db.add(e)
    e.clave_sha256, e.creado, e.ultimo_acceso, e.ventana, e.peticiones, e.avisado = \
        _sha(clave), datetime.now(), None, None, 0, False
    audit(db, scope.user, "cambiar_enlace" if cambio else "crear_enlace", "calendario_outlook", scope.user.id, {})
    db.commit()
    url = f"{_base(request)}/cal/{clave}.ics"
    return {"url": url, "webcal": re.sub(r"^https?://", "webcal://", url)}


class ImportesIn(BaseModel):
    mostrar_importes: bool


@router.put("/outlook")
def importes_outlook(data: ImportesIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    e = db.scalar(select(CalendarioEnlace).where(CalendarioEnlace.user_id == scope.user.id))
    if e is None:
        bad_request("Primero cree el enlace")
    if data.mostrar_importes and not es_direccion(scope):
        raise HTTPException(403, "Los importes solo los ven administración y dirección")
    e.mostrar_importes = data.mostrar_importes
    audit(db, scope.user, "importes", "calendario_outlook", scope.user.id, {"mostrar": data.mostrar_importes})
    db.commit()
    return ver_outlook(scope, db)


@router.delete("/outlook")
def quitar_outlook(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    e = db.scalar(select(CalendarioEnlace).where(CalendarioEnlace.user_id == scope.user.id))
    if e is not None:
        db.delete(e)
        audit(db, scope.user, "quitar_enlace", "calendario_outlook", scope.user.id, {})
        db.commit()
    return {"ok": True}


def _esc(s) -> str:
    return (str(s or "")).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n") \
        .replace("\n", "\\n").replace("\r", "")


def plegar(linea: str) -> str:
    """RFC 5545: líneas de 75 octetos como mucho; las siguientes empiezan con un espacio. Sin partir caracteres."""
    out, actual, tam = [], "", 0
    for ch in linea:
        n = len(ch.encode())
        if tam + n > (75 if not out else 74):
            out.append(actual)
            actual, tam = "", 0
        actual += ch
        tam += n
    out.append(actual)
    return "\r\n ".join(out)


def _utc(d: datetime) -> str:
    return d.replace(tzinfo=ZONA).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


RRULE = {"diaria": "FREQ=DAILY", "laborables": "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "semanal": "FREQ=WEEKLY",
         "mensual": "FREQ=MONTHLY", "anual": "FREQ=YEARLY"}


def _vevento(uid: str, secuencia: int, titulo: str, inicio: datetime, fin: datetime | None, todo_el_dia: bool,
             descripcion: str | None = None, lugar: str | None = None, cancelada: bool = False,
             repeticion: str | None = None, repetir_hasta: date | None = None, recordatorio: int | None = None,
             aviso_vispera: bool = False, sello: str = "") -> list[str]:
    li = ["BEGIN:VEVENT", f"UID:{uid}@pms.inversiete.es", f"DTSTAMP:{sello}", f"SEQUENCE:{max(0, secuencia)}"]
    if todo_el_dia:
        ultimo = (fin or inicio).date()
        li += [f"DTSTART;VALUE=DATE:{inicio:%Y%m%d}", f"DTEND;VALUE=DATE:{ultimo + timedelta(days=1):%Y%m%d}"]
    else:
        li += [f"DTSTART:{_utc(inicio)}", f"DTEND:{_utc(fin if fin and fin > inicio else inicio + timedelta(hours=1))}"]
    li.append(f"SUMMARY:{_esc(titulo)}")
    if descripcion:
        li.append(f"DESCRIPTION:{_esc(descripcion)}")
    if lugar:
        li.append(f"LOCATION:{_esc(lugar)}")
    li.append(f"STATUS:{'CANCELLED' if cancelada else 'CONFIRMED'}")
    if repeticion in RRULE:
        regla = RRULE[repeticion]
        if repetir_hasta:
            regla += f";UNTIL={repetir_hasta:%Y%m%d}" if todo_el_dia else \
                f";UNTIL={_utc(datetime.combine(repetir_hasta, datetime.max.time().replace(microsecond=0)))}"
        li.append(f"RRULE:{regla}")
    if not cancelada and aviso_vispera:  # vencimientos y fiscal: el día antes a las 9:00
        disparo = "TRIGGER:-PT15H" if todo_el_dia else \
            f"TRIGGER;VALUE=DATE-TIME:{_utc(datetime.combine(inicio.date() - timedelta(days=1), datetime.min.time()).replace(hour=9))}"
        li += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(titulo)}", disparo, "END:VALARM"]
    elif not cancelada and recordatorio is not None:
        li += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_esc(titulo)}", f"TRIGGER:-PT{int(recordatorio)}M",
               "END:VALARM"]
    li.append("END:VEVENT")
    return li


def _euros(x) -> str:
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " €"


def ics(db: Session, user: User, mostrar_importes: bool) -> str:
    """Lo que el usuario ve en la Agenda del PMS: sus citas y las de gestión, con el mismo filtro de perfiles."""
    scope = Scope(user, db)
    importes = mostrar_importes and es_direccion(scope)
    sello = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    desde = datetime.combine(date.today() - timedelta(days=ANTES_ICS), datetime.min.time())
    li = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//INVERPMS//Calendario comun//ES", "CALSCALE:GREGORIAN",
          "METHOD:PUBLISH", "X-WR-CALNAME:INVERPMS", "X-WR-TIMEZONE:Europe/Madrid"]
    citas = list(db.scalars(select(AgendaEvent).where(agenda.visibles(user),
                                                      (AgendaEvent.inicio >= desde) | AgendaEvent.repeticion.is_not(None))))
    espejos = {c.agenda_id: c for c in db.scalars(select(CalendarioEntrada).where(
        CalendarioEntrada.agenda_id.in_([e.id for e in citas] or [-1])))}
    for e in citas:
        c = espejos.get(e.id)
        fin = e.fin
        if e.todo_el_dia and fin:
            fin = fin.replace(hour=0, minute=0, second=0, microsecond=0)
        li += _vevento(f"PMS-AG-{e.id}", c.version if c else 0, f"{TIPOS_AGENDA.get(e.tipo, '')}: {e.titulo}", e.inicio,
                       fin, e.todo_el_dia, e.descripcion, e.lugar,
                       cancelada=bool(c and c.estado == "CANCELADA" and c.ultimo_cambio == "GESTION"),
                       repeticion=e.repeticion, repetir_hasta=e.repetir_hasta, recordatorio=e.aviso_min, sello=sello)
    limite_canc = datetime.now() - timedelta(days=DIAS_CANCELADAS)
    q = select(CalendarioEntrada).where(CalendarioEntrada.uid.not_like("PMS-%"),
                                        (CalendarioEntrada.inicio >= desde) | CalendarioEntrada.repeticion.is_not(None))
    for c in _visibles(db, scope, q):
        if c.estado == "CANCELADA" and c.actualizado < limite_canc:
            continue
        titulo = c.titulo + (f" · {_euros(c.importe)}" if importes and c.importe is not None and en_ambito(c, scope)
                             else "")
        desc = c.descripcion or ""
        if c.url_gestion:
            desc = (desc + "\n\n" if desc else "") + f"Abrir en gestión: {c.url_gestion}"
        li += _vevento(c.uid, c.version, titulo, c.inicio, c.fin, c.todo_el_dia, desc or None, c.lugar,
                       cancelada=c.estado == "CANCELADA", repeticion=c.repeticion, repetir_hasta=c.repetir_hasta,
                       recordatorio=c.recordatorio if c.tipo in ("CITA", "TAREA") else None,
                       aviso_vispera=c.tipo in FINANCIEROS, sello=sello)
    li.append("END:VCALENDAR")
    return "".join(plegar(x) + "\r\n" for x in li)


def _ip(request: Request) -> str:
    return (request.headers.get("x-forwarded-for") or "").split(",")[0].strip() or \
        (request.client.host if request.client else "")


@publico.get("/cal/{nombre}", include_in_schema=False)
def servir_ics(nombre: str, request: Request, db: Session = Depends(get_db)):
    if not nombre.endswith(".ics"):
        raise HTTPException(404, "No encontrado")
    clave = nombre[:-4]
    e = db.scalar(select(CalendarioEnlace).where(CalendarioEnlace.clave_sha256 == _sha(clave))) if clave else None
    u = db.get(User, e.user_id) if e else None
    if e is None or u is None or not u.activo:
        raise HTTPException(404, "No encontrado")
    ahora = datetime.now()
    hora = ahora.replace(minute=0, second=0, microsecond=0)
    if e.ventana != hora:
        e.ventana, e.peticiones, e.avisado = hora, 0, False
    e.peticiones += 1
    ip = _ip(request)
    db.add(AuditLog(user_id=u.id, accion="acceso_ics", entidad="calendario_outlook", entidad_id=u.id,
                    detalle={"ip": ip, "peticion": e.peticiones}))
    if e.peticiones > MAX_PETICIONES_HORA:
        if not e.avisado:
            e.avisado = True
            _avisar_abuso(db, u, ip)
        db.commit()
        siguiente = hora + timedelta(hours=1)
        return Response("Demasiadas peticiones: vuelva a intentarlo la hora que viene", status_code=429,
                        media_type="text/plain; charset=utf-8",
                        headers={"Retry-After": str(max(1, int((siguiente - ahora).total_seconds())))})
    e.ultimo_acceso = ahora
    cuerpo = ics(db, u, e.mostrar_importes)
    db.commit()
    return Response(cuerpo, media_type="text/calendar; charset=utf-8",
                    headers={"Cache-Control": "private, max-age=300", "Content-Disposition": 'inline; filename="inverpms.ics"'})


def _avisar_abuso(db: Session, u: User, ip: str) -> None:
    if not avisos.configurado():
        return
    texto = (f"El enlace de calendario de Outlook de {u.nombre} ha recibido más de {MAX_PETICIONES_HORA} peticiones en "
             f"una hora (última desde {ip}). Se corta hasta la hora siguiente. Si no es normal, cambie el enlace en "
             "«Mi perfil › Calendario en Outlook».")
    for destino in {settings.mantenimiento_email, u.email} - {None, ""}:
        avisos._enviar_registrado(db, None, destino, f"ics_abuso:{u.id}:{datetime.now():%Y%m%d%H}:{destino}", "seguridad",
                                  "Calendario de Outlook: demasiadas peticiones", texto,
                                  avisos._html("Calendario de Outlook: demasiadas peticiones", f"<p>{texto}</p>"))
