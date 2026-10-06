"""Agenda compartida: reuniones, tareas, recordatorios y eventos.

Visibilidad: privada (solo el autor), compartida (el autor y las personas indicadas) o pública (todos los usuarios).
Cualquier usuario puede enviar tareas, recordatorios o convocar reuniones a otros, salvo a quien tenga
`no_asignable` (presidencia), que sí puede enviarlas a los demás.
"""
import calendar
from datetime import date, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import AgendaEvent, AgendaParticipant, User

MAX_OCURRENCIAS = 400


def visibles(user: User):
    """Condición SQL de los eventos que ve el usuario."""
    mios = select(AgendaParticipant.event_id).where(AgendaParticipant.user_id == user.id)
    return or_(AgendaEvent.creador_id == user.id, AgendaEvent.visibilidad == "publica",
               AgendaEvent.id.in_(mios))


def puede_ver(e: AgendaEvent, user: User) -> bool:
    return e.creador_id == user.id or e.visibilidad == "publica" or any(p.user_id == user.id for p in e.participantes)


def _suma_meses(d: datetime, n: int) -> datetime:
    m = d.month - 1 + n
    anio, mes = d.year + m // 12, m % 12 + 1
    return d.replace(year=anio, month=mes, day=min(d.day, calendar.monthrange(anio, mes)[1]))


def ocurrencias(e: AgendaEvent, desde: date, hasta: date) -> list[datetime]:
    """Inicios de las repeticiones del evento entre `desde` y `hasta` (ambos incluidos)."""
    if not e.repeticion:
        return [e.inicio] if desde <= e.inicio.date() <= hasta else []
    fin = min(hasta, e.repetir_hasta) if e.repetir_hasta else hasta
    out, n = [], 0
    while n < 5000:
        if e.repeticion == "diaria":
            x = e.inicio + timedelta(days=n)
        elif e.repeticion == "semanal":
            x = e.inicio + timedelta(weeks=n)
        elif e.repeticion == "mensual":
            x = _suma_meses(e.inicio, n)
        else:
            x = _suma_meses(e.inicio, 12 * n)
        if x.date() > fin:
            break
        if x.date() >= desde:
            out.append(x)
            if len(out) >= MAX_OCURRENCIAS:
                break
        n += 1
    return out


def destinatarios(db: Session, e: AgendaEvent) -> list[User]:
    """Autor y participantes (sin quien ha rechazado la reunión)."""
    ids = {e.creador_id} | {p.user_id for p in e.participantes if p.respuesta != "rechaza"}
    return [u for u in db.scalars(select(User).where(User.id.in_(ids), User.activo))]


def recordatorios_pendientes(db: Session, ahora: datetime) -> list[tuple[AgendaEvent, datetime]]:
    """Citas cuyo aviso previo toca ya (hasta una hora después del inicio, por si el servidor estuvo parado)."""
    out = []
    for e in db.scalars(select(AgendaEvent).where(AgendaEvent.aviso_min.is_not(None), AgendaEvent.hecha.is_(False),
                                                  AgendaEvent.inicio <= ahora + timedelta(days=8))):
        for x in ocurrencias(e, (ahora - timedelta(days=1)).date(), (ahora + timedelta(days=8)).date()):
            if x - timedelta(minutes=e.aviso_min) <= ahora <= x + timedelta(hours=1):
                out.append((e, x))
    return out
