"""Ficha del empleado: quién gestiona a cada persona, saldo de vacaciones y registro de jornada.

- Gestionan la ficha (datos laborales, documentos, fichajes) Recepción 1 del activo y la dirección
  («personal.autorizar»); el personal de todos los activos, solo la dirección del grupo.
- Saldo de vacaciones: los días del convenio (por defecto 22 laborables) prorrateados si entra o sale durante el año,
  menos las vacaciones aprobadas; las pendientes de aprobar se muestran aparte.
- Fichan el personal propio (no las subcontratas): desde su usuario del PMS o con su enlace personal."""
import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from . import ausencias as au
from .models import Absence, Asset, StaffMember, TimeEntry

VACACIONES_DEFECTO = (30, "naturales")  # por defecto 30 días naturales (fines de semana y festivos incluidos)
VIGENTES = ("pendiente", "visto_bueno", "aprobada")


def es_propio(p: StaffMember) -> bool:
    """Personal de las sociedades del grupo (no de una subcontrata ni autónomo)."""
    return p.supplier_id is None and not (p.empresa or "").strip() and p.tipo_contrato != "autonomo"


def director_tecnico(scope) -> bool:
    """Da de alta y edita las fichas del personal propio de las sociedades (y el administrador del PMS)."""
    return scope.user.is_superadmin or scope.has_any("personal.autorizar_mto")


def es_recepcion(db: Session, scope, asset_id: int | None) -> bool:
    """Recepción (1 o 2) del activo: solo da de alta personal de subcontratas."""
    return asset_id is not None and any(x.asset_id == asset_id and x.role.nombre == "Recepción"
                                        for x in scope.user.assignments)


def puede_gestionar(db: Session, scope, p: StaffMember) -> bool:
    if p.asset_id is None:
        return scope.is_group_level("personal.autorizar") or scope.user.is_superadmin
    return au.gestiona(db, scope, db.get(Asset, p.asset_id))


def ficha_de_usuario(db: Session, user_id: int) -> StaffMember | None:
    return db.scalar(select(StaffMember).where(StaffMember.user_id == user_id, StaffMember.activo)
                     .order_by(StaffMember.id).limit(1))


def ficha_de_ausencia(db: Session, x: Absence) -> StaffMember | None:
    if x.staff_id:
        return db.get(StaffMember, x.staff_id)
    return ficha_de_usuario(db, x.user_id) if x.user_id else None


def _ausencias(db: Session, p: StaffMember):
    cond = [Absence.staff_id == p.id]
    if p.user_id:
        cond.append(Absence.user_id == p.user_id)
    return select(Absence).where(or_(*cond), Absence.tipo == "vacaciones", Absence.estado.in_(VIGENTES))


def _computa(desde: date, hasta: date, tipo: str) -> int:
    """Días que consume un periodo: naturales (todos) o laborables (sin fines de semana ni festivos)."""
    from .calendario import laborable
    n = (hasta - desde).days + 1
    return n if tipo == "naturales" else sum(1 for i in range(n) if laborable(desde + timedelta(days=i)))


def saldo(db: Session, p: StaffMember, anio: int | None = None, sin: int | None = None, hoy: date | None = None) -> dict:
    """Vacaciones del año: corresponden, disfrutadas (aprobadas y ya pasadas), solicitadas pendientes de disfrutar
    (aprobadas futuras y las que esperan aprobación) y pendientes de solicitar.
    `sin`: ausencia que no se cuenta (la que se está valorando)."""
    anio = anio or date.today().year
    hoy = hoy or date.today()
    ini, fin = date(anio, 1, 1), date(anio, 12, 31)
    tipo = p.vacaciones_tipo or VACACIONES_DEFECTO[1]
    total = p.vacaciones_dias if p.vacaciones_dias is not None else (30 if tipo == "naturales" else 22)
    desde, hasta = max(ini, p.fecha_alta or ini), min(fin, p.fecha_baja or fin)
    if hasta < desde:
        corresponden = 0.0
    else:  # prorrata por los días del año que está de alta, redondeada a medio día
        corresponden = round(total * ((hasta - desde).days + 1) / ((fin - ini).days + 1) * 2) / 2
    disfrutadas = solicitadas = por_aprobar = 0
    for x in db.scalars(_ausencias(db, p).where(Absence.desde <= fin, Absence.hasta >= ini)):
        if x.id == sin:
            continue
        a, b = max(x.desde, ini), min(x.hasta, fin)
        if x.estado != "aprobada":
            n = _computa(a, b, tipo)
            solicitadas += n
            por_aprobar += n
            continue
        if a <= hoy:  # la parte ya transcurrida está disfrutada
            disfrutadas += _computa(a, min(b, hoy), tipo)
        if b > hoy:
            solicitadas += _computa(max(a, hoy + timedelta(days=1)), b, tipo)
    pendientes_solicitar = corresponden - disfrutadas - solicitadas
    return {"anio": anio, "tipo": tipo, "corresponden": corresponden, "disfrutadas": disfrutadas,
            "solicitadas": solicitadas, "por_aprobar": por_aprobar, "pendientes_solicitar": pendientes_solicitar,
            # compatibilidad
            "aprobadas": disfrutadas + solicitadas - por_aprobar, "pendientes": por_aprobar,
            "restantes": pendientes_solicitar}


def aviso_saldo(db: Session, x: Absence) -> str | None:
    """Si una solicitud de vacaciones supera los días que le quedan a la persona."""
    if x.tipo != "vacaciones":
        return None
    p = ficha_de_ausencia(db, x)
    if p is None:
        return None
    s = saldo(db, p, x.desde.year, sin=x.id)
    pide = _computa(x.desde, min(x.hasta, date(x.desde.year, 12, 31)), s["tipo"])
    if pide > s["restantes"]:
        return (f"Supera el saldo de vacaciones: pide {pide} días {s['tipo']} y le quedan {s['restantes']:g} "
                f"de {s['corresponden']:g} en {s['anio']}.")
    return None


# --------------------------------------------------------------------------- registro de jornada
def clave_nueva() -> str:
    return secrets.token_urlsafe(24)


def abierto(db: Session, p: StaffMember) -> TimeEntry | None:
    return db.scalar(select(TimeEntry).where(TimeEntry.staff_id == p.id, TimeEntry.salida.is_(None))
                     .order_by(TimeEntry.entrada.desc()).limit(1))


def fichar(db: Session, p: StaffMember, origen: str, lat: float | None = None, lon: float | None = None) -> TimeEntry:
    """Entrada si no hay un fichaje abierto; si lo hay, salida."""
    if not es_propio(p) or not p.activo:
        raise ValueError("Solo ficha el personal propio en activo")
    ahora = datetime.now().replace(microsecond=0)
    t = abierto(db, p)
    if t is None:
        t = TimeEntry(staff_id=p.id, entrada=ahora, origen=origen, lat=lat, lon=lon)
        db.add(t)
    else:
        t.salida, t.lat_salida, t.lon_salida = ahora, lat, lon
    db.flush()
    return t


def horas(t: TimeEntry, hasta: datetime | None = None) -> float:
    fin = t.salida or hasta
    return round((fin - t.entrada).total_seconds() / 3600, 2) if fin else 0.0


def del_mes(db: Session, staff_ids: list[int], mes: str) -> list[TimeEntry]:
    y, m = map(int, mes.split("-"))
    ini = datetime(y, m, 1)
    fin = datetime(y + (m == 12), m % 12 + 1, 1)
    return list(db.scalars(select(TimeEntry).where(TimeEntry.staff_id.in_(staff_ids or [-1]), TimeEntry.entrada >= ini,
                                                   TimeEntry.entrada < fin).order_by(TimeEntry.entrada)))


def olvidos(db: Session, dia: date) -> list[TimeEntry]:
    """Fichajes de días anteriores sin salida (se olvidó fichar al salir)."""
    return list(db.scalars(select(TimeEntry).where(TimeEntry.salida.is_(None),
                                                   TimeEntry.entrada < datetime.combine(dia, datetime.min.time()))))


def documentos_por_vencer(db: Session, dia: date, dias: int = 30):
    from .models import StaffDocument
    return list(db.scalars(select(StaffDocument).where(StaffDocument.vence.is_not(None),
                                                       StaffDocument.vence <= dia + timedelta(days=dias))
                           .order_by(StaffDocument.vence)))


def nombre_fichero(texto: str) -> str:
    """Nombre de fichero sin tildes ni símbolos (cabecera Content-Disposition)."""
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^\w.\-]+", "_", t).strip("_")[:120] or "documento"
