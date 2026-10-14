"""Acceso a un apartamento con cliente para hacer una orden de trabajo.

- Con cliente dentro hay que indicar cómo se entra: con la llave de recepción (el cliente lo autoriza: se anota quién
  autoriza, cómo, quién lo registra y cuándo) o contactando con él (su teléfono sale de su ficha).
- La autorización vale para esa estancia: si el cliente se va y entra otro con la OT todavía abierta, caduca y hay que
  volver a pedirla (lo avisa el check-in del nuevo cliente y la lista de OT).
- Apartamento libre con un cliente que llega pronto: se avisa para hacer la OT antes de su llegada.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Reservation, User, WorkOrder

MEDIOS = {"en_persona": "en persona", "telefono": "por teléfono", "whatsapp": "por WhatsApp", "correo": "por correo"}
LLEGADA_DIAS = 7  # «llega pronto»: dentro de estos días (o antes de la fecha prevista de la OT)


def alojado(db: Session, unit_id: int | None) -> Reservation | None:
    """Reserva con el cliente dentro del apartamento (check-in hecho), si la hay."""
    if not unit_id:
        return None
    return db.scalar(select(Reservation).where(Reservation.unit_id == unit_id, Reservation.estado == "checkin")
                     .order_by(Reservation.fecha_entrada.desc()).limit(1))


def proxima_llegada(db: Session, unit_id: int | None, hasta: date | None = None) -> Reservation | None:
    """Siguiente reserva confirmada que entra en el apartamento dentro de LLEGADA_DIAS (o hasta `hasta`)."""
    if not unit_id:
        return None
    hoy = date.today()
    tope = max(hoy + timedelta(days=LLEGADA_DIAS), hasta or hoy)
    return db.scalar(select(Reservation).where(
        Reservation.unit_id == unit_id, Reservation.estado == "confirmada", Reservation.fecha_entrada >= hoy,
        Reservation.fecha_entrada <= tope).order_by(Reservation.fecha_entrada).limit(1))


class Contexto:
    """Alojados y próximas llegadas de muchos apartamentos de golpe (lista de OT): dos consultas en total."""

    def __init__(self, db: Session, unit_ids: set[int], hasta: date | None = None):
        hoy = date.today()
        tope = max(hoy + timedelta(days=LLEGADA_DIAS), hasta or hoy)
        ids = unit_ids or {-1}
        self._alojado: dict[int, Reservation] = {}
        for r in db.scalars(select(Reservation).where(Reservation.unit_id.in_(ids), Reservation.estado == "checkin")
                            .order_by(Reservation.fecha_entrada.desc())):
            self._alojado.setdefault(r.unit_id, r)
        self._llegadas: dict[int, list[Reservation]] = {}
        for r in db.scalars(select(Reservation).where(
                Reservation.unit_id.in_(ids), Reservation.estado == "confirmada", Reservation.fecha_entrada >= hoy,
                Reservation.fecha_entrada <= tope).order_by(Reservation.fecha_entrada)):
            self._llegadas.setdefault(r.unit_id, []).append(r)

    def alojado(self, unit_id: int | None) -> Reservation | None:
        return self._alojado.get(unit_id) if unit_id else None

    def llegada(self, unit_id: int | None, hasta: date | None) -> Reservation | None:
        tope = max(date.today() + timedelta(days=LLEGADA_DIAS), hasta or date.today())
        return next((r for r in self._llegadas.get(unit_id, []) if r.fecha_entrada <= tope), None) if unit_id else None


def _huesped(r: Reservation) -> str:
    return f"{r.guest.nombre} {r.guest.apellidos or ''}".strip() if r and r.guest else ""


def situacion(db: Session, unit_id: int, hasta: date | None = None) -> dict:
    """Para el formulario de la OT: cliente dentro, cliente que llega pronto o apartamento libre."""
    r = alojado(db, unit_id)
    if r:
        return {"situacion": "alojado", "alojado": True, "huesped": _huesped(r),
                "telefono": r.guest.telefono if r.guest else None, "salida": r.fecha_salida.isoformat()}
    n = proxima_llegada(db, unit_id, hasta)
    if n:
        return {"situacion": "llegada", "alojado": False, "llegada": n.fecha_entrada.isoformat(),
                "dias": (n.fecha_entrada - date.today()).days, "salida": n.fecha_salida.isoformat()}
    return {"situacion": "libre", "alojado": False}


def registrar(db: Session, w: WorkOrder, acceso: str | None, autoriza: str | None, medio: str | None,
              user: User) -> None:
    """Anota cómo se entra. Con la llave de recepción es obligatorio quién lo autoriza y cómo."""
    if acceso is None:
        return
    if not w.unit_id:
        raise ValueError("El acceso se indica solo en las órdenes de un apartamento")
    r = alojado(db, w.unit_id) or proxima_llegada(db, w.unit_id, w.fecha_prevista)
    autoriza = (autoriza or "").strip() or None
    if acceso == "llave":
        if not autoriza:
            raise ValueError("Indique quién autoriza entrar con la llave de recepción (el cliente u otra persona)")
        if medio not in MEDIOS:
            raise ValueError("Indique cómo lo ha autorizado: en persona, por teléfono, por WhatsApp o por correo")
    else:
        autoriza, medio = None, None
    w.acceso, w.acceso_autoriza, w.acceso_medio = acceso, autoriza, medio
    w.acceso_user_id, w.acceso_fecha, w.acceso_reserva_id = user.id, datetime.now(), r.id if r else None


def estado(db: Session, w: WorkOrder, abiertas, ctx: Contexto | None = None) -> dict | None:
    """Estado del acceso de una OT abierta de apartamento:
    vigente (anotado para el cliente de ahora) · falta (cliente dentro sin indicar) · caducado (anotado para otra
    estancia) · llegada (libre ahora, llega un cliente pronto) · None (nada que avisar)."""
    if not w.unit_id or w.estado not in abiertas:
        return None
    r = ctx.alojado(w.unit_id) if ctx else alojado(db, w.unit_id)
    if r:
        if not w.acceso:
            return {"estado": "falta", "texto": "Cliente alojado: pedir acceso (llave o contactar)"}
        if w.acceso_reserva_id and w.acceso_reserva_id != r.id:
            return {"estado": "caducado", "texto": "Acceso anotado para otro cliente: volver a pedirlo"}
        return {"estado": "vigente", "texto": None}
    n = ctx.llegada(w.unit_id, w.fecha_prevista) if ctx else proxima_llegada(db, w.unit_id, w.fecha_prevista)
    if n:
        return {"estado": "llegada", "llegada": n.fecha_entrada.isoformat(),
                "texto": f"Llega un cliente el {n.fecha_entrada:%d/%m}: mejor hacerla antes"}
    return None


def texto(db: Session, w: WorkOrder, interno: bool = False, ctx: Contexto | None = None,
          usuarios: dict[int, str] | None = None) -> str | None:
    """Cómo se entra, para el técnico (enlace, WhatsApp, correo, parte en PDF) o, con `interno`, con quién lo autorizó
    y quién lo anotó (solo dentro del PMS)."""
    if not w.acceso:
        return None
    r = ctx.alojado(w.unit_id) if ctx else alojado(db, w.unit_id)
    if r and w.acceso_reserva_id and w.acceso_reserva_id != r.id:
        return "Apartamento con otro cliente: pedir a recepción cómo se entra antes de ir"
    if w.acceso == "llave":
        cuando = f" el {w.acceso_fecha:%d/%m/%Y}" if w.acceso_fecha else ""
        base = f"Llave de recepción (el cliente autorizó el acceso{cuando})"
        if not interno or not w.acceso_autoriza:
            return base
        quien = (usuarios.get(w.acceso_user_id) if usuarios is not None
                 else db.scalar(select(User.nombre).where(User.id == w.acceso_user_id))) if w.acceso_user_id else None
        return (f"Llave de recepción · autoriza {w.acceso_autoriza} {MEDIOS.get(w.acceso_medio, '')}"
                f"{f' el {w.acceso_fecha:%d/%m/%Y %H:%M}' if w.acceso_fecha else ''}"
                f"{f' · anotó {quien}' if quien else ''}").replace("  ", " ")
    tel = r.guest.telefono if r and r.guest else None
    return f"Contactar con el cliente antes de entrar · tel. {tel or 'sin teléfono en su ficha: pedirlo a recepción'}"
