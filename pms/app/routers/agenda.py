"""Agenda: calendario de reuniones, tareas, recordatorios y eventos de todos los usuarios."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import agenda, avisos
from ..database import get_db
from ..models import REPETICIONES, TIPOS_AGENDA, VISIBILIDADES, AgendaEvent, AgendaParticipant, Asset, User
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/agenda", tags=["agenda"])


class EventIn(BaseModel):
    tipo: str = "evento"
    titulo: str = Field(min_length=2, max_length=200)
    descripcion: str | None = None
    lugar: str | None = Field(default=None, max_length=200)
    inicio: datetime
    fin: datetime | None = None
    todo_el_dia: bool = False
    visibilidad: str = "privada"
    prioridad: str = "normal"
    asset_id: int | None = None
    repeticion: str | None = None
    repetir_hasta: date | None = None
    aviso_min: int | None = Field(default=None, ge=0, le=60 * 24 * 14)
    participantes: list[int] = []


def _nombres(db: Session) -> dict[int, str]:
    return dict(db.execute(select(User.id, User.nombre)).all())


def _out(e: AgendaEvent, user: User, nombres: dict, ocurrencia: datetime | None = None) -> dict:
    d = e.to_dict()
    yo = next((p for p in e.participantes if p.user_id == user.id), None)
    inicio = ocurrencia or e.inicio
    d.update(
        ocurrencia=inicio.isoformat(), fin_ocurrencia=(e.fin + (inicio - e.inicio)).isoformat() if e.fin else None,
        tipo_nombre=TIPOS_AGENDA.get(e.tipo, e.tipo), creador=nombres.get(e.creador_id),
        hecha_por_nombre=nombres.get(e.hecha_por),
        participantes=[{"user_id": p.user_id, "nombre": nombres.get(p.user_id), "respuesta": p.respuesta}
                       for p in e.participantes],
        mio=e.creador_id == user.id, para_mi=yo is not None, nuevo=bool(yo and not yo.visto),
        mi_respuesta=yo.respuesta if yo else None,
        puede_editar=e.creador_id == user.id or user.is_superadmin,
        vencida=e.tipo == "tarea" and not e.hecha and inicio.date() < date.today())
    return d


def _validar(db: Session, scope: Scope, data: EventIn) -> list[int]:
    if data.tipo not in TIPOS_AGENDA:
        bad_request(f"Tipo no válido. Opciones: {', '.join(TIPOS_AGENDA)}")
    if data.visibilidad not in VISIBILIDADES:
        bad_request(f"Visibilidad no válida. Opciones: {', '.join(VISIBILIDADES)}")
    if data.prioridad not in ("normal", "alta"):
        bad_request("Prioridad no válida (normal o alta)")
    if data.repeticion and data.repeticion not in REPETICIONES:
        bad_request(f"Repetición no válida. Opciones: {', '.join(k for k in REPETICIONES if k)}")
    if data.repeticion and data.tipo == "tarea":
        bad_request("Las tareas no se repiten: use un recordatorio periódico")
    if data.fin and data.fin < data.inicio:
        bad_request("El final no puede ser anterior al inicio")
    if data.asset_id:
        get_or_404(db, Asset, data.asset_id)
    ids = sorted(set(data.participantes) - {scope.user.id})
    if data.visibilidad == "privada" and ids:
        bad_request("Una cita privada no puede tener más personas: elija «Solo las personas indicadas» o «Pública»")
    if data.visibilidad == "compartida" and not ids:
        bad_request("Indique a quién va dirigida")
    usuarios = {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids or [-1])))}
    for uid in ids:
        u = usuarios.get(uid)
        if not u or not u.activo:
            bad_request("Alguna de las personas indicadas no existe o está dada de baja")
        if u.no_asignable and not scope.user.no_asignable:
            bad_request(f"A {u.nombre} no se le pueden enviar tareas, recordatorios ni convocatorias")
    return ids


@router.get("/usuarios")
def users(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Personas a las que se puede enviar una cita (presidencia solo a sí misma no; los demás no a presidencia)."""
    return [{"id": u.id, "nombre": u.nombre, "email": u.email,
             "asignable": u.id != scope.user.id and (not u.no_asignable or scope.user.no_asignable)}
            for u in db.scalars(select(User).where(User.activo).order_by(User.nombre))]


@router.get("")
def list_events(desde: date, hasta: date, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if hasta < desde or (hasta - desde).days > 400:
        bad_request("Rango de fechas no válido (máximo 400 días)")
    stmt = select(AgendaEvent).where(agenda.visibles(scope.user), AgendaEvent.inicio < datetime.combine(
        hasta + timedelta(days=1), datetime.min.time()))
    nombres = _nombres(db)
    out = []
    for e in db.scalars(stmt):
        for x in agenda.ocurrencias(e, desde, hasta):
            out.append(_out(e, scope.user, nombres, x))
    return sorted(out, key=lambda x: (x["ocurrencia"][:10], not x["todo_el_dia"], x["ocurrencia"]))


@router.get("/pendientes")
def pending(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Tareas sin terminar que me tocan (mías o enviadas a mí) y lo nuevo que me han enviado."""
    nombres, u = _nombres(db), scope.user
    mias = select(AgendaParticipant.event_id).where(AgendaParticipant.user_id == u.id)
    tareas = db.scalars(select(AgendaEvent).where(
        AgendaEvent.tipo == "tarea", AgendaEvent.hecha.is_(False),
        (AgendaEvent.creador_id == u.id) | AgendaEvent.id.in_(mias)).order_by(AgendaEvent.inicio))
    nuevas = db.scalars(select(AgendaEvent).join(AgendaParticipant).where(
        AgendaParticipant.user_id == u.id, AgendaParticipant.visto.is_(False)).order_by(AgendaEvent.inicio))
    return {"tareas": [_out(e, u, nombres) for e in tareas], "nuevas": [_out(e, u, nombres) for e in nuevas]}


def _guardar(db: Session, scope: Scope, e: AgendaEvent, data: EventIn, ids: list[int]) -> list[int]:
    for k, v in data.model_dump(exclude={"participantes"}).items():
        setattr(e, k, v or None if k in ("repeticion", "descripcion", "lugar") else v)
    if e.todo_el_dia:
        e.inicio = e.inicio.replace(hour=0, minute=0, second=0, microsecond=0)
    antes = {p.user_id for p in e.participantes}
    e.participantes = [p for p in e.participantes if p.user_id in ids] + \
        [AgendaParticipant(user_id=uid) for uid in ids if uid not in antes]
    return [uid for uid in ids if uid not in antes]


@router.post("", status_code=201)
def create_event(data: EventIn, tareas: BackgroundTasks, scope: Scope = Depends(get_scope),
                 db: Session = Depends(get_db)):
    ids = _validar(db, scope, data)
    e = AgendaEvent(creador_id=scope.user.id, participantes=[])
    nuevos = _guardar(db, scope, e, data, ids)
    db.add(e)
    db.flush()
    audit(db, scope.user, "crear", "agenda", e.id, {"tipo": e.tipo, "titulo": e.titulo, "participantes": ids})
    db.commit()
    if nuevos:
        tareas.add_task(avisos.agenda_enviada, e.id, nuevos)
    return _out(e, scope.user, _nombres(db))


def _propio(db: Session, scope: Scope, eid: int) -> AgendaEvent:
    e = get_or_404(db, AgendaEvent, eid)
    if not (e.creador_id == scope.user.id or scope.user.is_superadmin):
        raise HTTPException(403, "Solo quien la creó puede modificarla")
    return e


def _visible(db: Session, scope: Scope, eid: int) -> AgendaEvent:
    e = get_or_404(db, AgendaEvent, eid)
    if not agenda.puede_ver(e, scope.user):
        raise HTTPException(404, "No encontrado")
    return e


@router.put("/{eid}")
def update_event(eid: int, data: EventIn, tareas: BackgroundTasks, scope: Scope = Depends(get_scope),
                 db: Session = Depends(get_db)):
    e = _propio(db, scope, eid)
    ids = _validar(db, scope, data)
    nuevos = _guardar(db, scope, e, data, ids)
    audit(db, scope.user, "editar", "agenda", e.id, {"titulo": e.titulo, "participantes": ids})
    db.commit()
    if nuevos:
        tareas.add_task(avisos.agenda_enviada, e.id, nuevos)
    return _out(e, scope.user, _nombres(db))


@router.delete("/{eid}")
def delete_event(eid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    e = _propio(db, scope, eid)
    audit(db, scope.user, "borrar", "agenda", e.id, {"titulo": e.titulo})
    db.delete(e)
    db.commit()
    return {"ok": True}


class HechaIn(BaseModel):
    hecha: bool = True


@router.post("/{eid}/hecha")
def mark_done(eid: int, data: HechaIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """La tarea la puede dar por terminada quien la creó o cualquiera de las personas a quien se envió."""
    e = _visible(db, scope, eid)
    if e.tipo != "tarea":
        bad_request("Solo las tareas se marcan como hechas")
    if not (e.creador_id == scope.user.id or any(p.user_id == scope.user.id for p in e.participantes)):
        raise HTTPException(403, "La tarea no es suya")
    e.hecha, e.hecha_por, e.hecha_en = data.hecha, scope.user.id if data.hecha else None, \
        datetime.now() if data.hecha else None
    audit(db, scope.user, "hecha" if data.hecha else "reabrir", "agenda", e.id, {"titulo": e.titulo})
    db.commit()
    return _out(e, scope.user, _nombres(db))


class RespuestaIn(BaseModel):
    respuesta: str


@router.post("/{eid}/respuesta")
def answer(eid: int, data: RespuestaIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    e = get_or_404(db, AgendaEvent, eid)
    p = next((p for p in e.participantes if p.user_id == scope.user.id), None)
    if not p:
        raise HTTPException(403, "No está convocado")
    if data.respuesta not in ("acepta", "rechaza", "pendiente"):
        bad_request("Respuesta no válida (acepta, rechaza)")
    p.respuesta, p.visto = data.respuesta, True
    db.commit()
    return _out(e, scope.user, _nombres(db))


@router.post("/{eid}/visto")
def seen(eid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    e = get_or_404(db, AgendaEvent, eid)
    for p in e.participantes:
        if p.user_id == scope.user.id:
            p.visto = True
    db.commit()
    return {"ok": True}


def _ics_fecha(d: datetime, todo_el_dia: bool) -> str:
    return d.strftime("%Y%m%d") if todo_el_dia else d.strftime("%Y%m%dT%H%M%S")


@router.get("/{eid}/ics")
def ics(eid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Fichero de calendario para añadir la cita al móvil, Outlook o Google Calendar."""
    e = _visible(db, scope, eid)
    esc = lambda s: (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")  # noqa: E731
    fin = e.fin or (e.inicio + (timedelta(days=1) if e.todo_el_dia else timedelta(hours=1)))
    valor = ";VALUE=DATE" if e.todo_el_dia else ";TZID=Europe/Madrid"
    lineas = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//INVERPMS//Agenda//ES", "BEGIN:VEVENT",
              f"UID:agenda-{e.id}@inverpms", f"DTSTAMP:{datetime.utcnow():%Y%m%dT%H%M%SZ}",
              f"DTSTART{valor}:{_ics_fecha(e.inicio, e.todo_el_dia)}", f"DTEND{valor}:{_ics_fecha(fin, e.todo_el_dia)}",
              f"SUMMARY:{esc(TIPOS_AGENDA.get(e.tipo, '') + ': ' + e.titulo)}"]
    if e.descripcion:
        lineas.append(f"DESCRIPTION:{esc(e.descripcion)}")
    if e.lugar:
        lineas.append(f"LOCATION:{esc(e.lugar)}")
    if e.repeticion:
        regla = {"diaria": "DAILY", "semanal": "WEEKLY", "mensual": "MONTHLY", "anual": "YEARLY"}[e.repeticion]
        lineas.append(f"RRULE:FREQ={regla}" + (f";UNTIL={e.repetir_hasta:%Y%m%d}" if e.repetir_hasta else ""))
    if e.aviso_min is not None:
        lineas += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{esc(e.titulo)}", f"TRIGGER:-PT{e.aviso_min}M",
                   "END:VALARM"]
    lineas += ["END:VEVENT", "END:VCALENDAR"]
    return Response("\r\n".join(lineas) + "\r\n", media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="cita_{e.id}.ics"'})
