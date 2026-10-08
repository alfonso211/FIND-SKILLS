"""Ausencias del personal: quién pertenece a cada colectivo y quién aprueba sus solicitudes.

    Colectivo                         Quién la registra             Quién la aprueba
    Mantenimiento                     el propio técnico (todos       solo el director técnico
                                      la ven en el calendario)      («personal.autorizar_mto»)
    Limpieza, conserjería, otros      Recepción 1 (se lo dicen       Recepción 1 (o dirección)
    (subcontratas por administración) de palabra)
    Recepción 2                       ella misma                     visto bueno de Recepción 1 y
                                                                     después dirección («personal.autorizar»)
    Recepción 1, dirección, oficinas  la propia persona              dirección («personal.autorizar»)

Nadie aprueba su propia solicitud (salvo el administrador del PMS).
"""
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Absence, Asset, Assignment, StaffMember, User

ROL_COLECTIVO = {"Técnico Mantenimiento": "mantenimiento", "Gobernanta / Limpieza": "limpieza"}
PERSONAL_R1 = ("limpieza", "conserjeria", "otros")  # colectivos que gestiona Recepción 1


def recepcion_1(db: Session, a: Asset) -> User | None:
    from .routers.presidencia import responsable
    return responsable(db, a)


def es_r1(db: Session, scope, a: Asset) -> bool:
    r1 = recepcion_1(db, a)
    return r1 is not None and r1.id == scope.user.id


def direccion(scope, asset_id: int) -> bool:
    """Dirección que aprueba ausencias (Director General, Director Técnico…). La presidencia (usuario «no
    asignable») no interviene: ni recibe los avisos ni aprueba."""
    return scope.can_asset("personal.autorizar", asset_id) and (not scope.user.no_asignable or scope.user.is_superadmin)


def gestiona(db: Session, scope, a: Asset) -> bool:
    """Recepción 1 o dirección: dan de alta al personal de subcontratas y registran ausencias de otros."""
    return es_r1(db, scope, a) or direccion(scope, a.id)


def colectivo_usuario(db: Session, u: User, a: Asset) -> str:
    roles = {x.role.nombre for x in u.assignments
             if x.asset_id in (None, a.id) and (x.company_id in (None, a.company_id) or x.asset_id == a.id)}
    for rol, col in ROL_COLECTIVO.items():
        if rol in roles:
            return col
    if "Recepción" in roles:
        r1 = recepcion_1(db, a)
        return "recepcion1" if r1 is not None and r1.id == u.id else "recepcion2"
    return "direccion"


def colectivo_staff(p: StaffMember) -> str:
    return p.area if p.area in ("mantenimiento", "limpieza", "conserjeria") else "otros"


def quien_aprueba(colectivo: str) -> str:
    return {"mantenimiento": "Director técnico",
            "recepcion2": "Recepción 1 (visto bueno) y dirección"}.get(
        colectivo, "Recepción 1 o dirección" if colectivo in PERSONAL_R1 else "Dirección")


def puede_aprobar(db: Session, scope, x: Absence) -> bool:
    """Si el usuario puede aprobar o denegar la ausencia en su estado actual."""
    if x.estado not in ("pendiente", "visto_bueno"):
        return False
    if x.user_id == scope.user.id and not scope.user.is_superadmin:
        return False
    if x.colectivo == "mantenimiento":
        return scope.can_asset("personal.autorizar_mto", x.asset_id)
    if x.colectivo in PERSONAL_R1:
        return gestiona(db, scope, db.get(Asset, x.asset_id))
    if x.colectivo == "recepcion2":  # dirección, una vez que Recepción 1 da el visto bueno
        return x.estado == "visto_bueno" and direccion(scope, x.asset_id)
    return direccion(scope, x.asset_id)  # cualquiera de la dirección: basta con que apruebe uno


def puede_visto_bueno(db: Session, scope, x: Absence) -> bool:
    return x.colectivo == "recepcion2" and x.estado == "pendiente" and x.user_id != scope.user.id \
        and es_r1(db, scope, db.get(Asset, x.asset_id))


def puede_anular(db: Session, scope, x: Absence) -> bool:
    if x.estado in ("denegada", "anulada"):
        return False
    a = db.get(Asset, x.asset_id)
    if x.colectivo == "mantenimiento" and scope.can_asset("personal.autorizar_mto", a.id):
        return True
    if x.colectivo != "mantenimiento" and gestiona(db, scope, a):
        return True
    propia = scope.user.id in (x.user_id, x.creado_por)
    return propia and x.estado in ("pendiente", "visto_bueno")


def ve_detalle(db: Session, scope, x: Absence) -> bool:
    """El tipo y el motivo de una baja médica son datos de salud: solo los ven la persona, quien la registró,
    Recepción 1, dirección y quien la aprueba. Los demás ven «Ausencia» en el calendario."""
    if x.tipo != "baja_medica" and not x.motivo:
        return True
    return scope.user.id in (x.user_id, x.creado_por) or gestiona(db, scope, db.get(Asset, x.asset_id)) \
        or puede_aprobar(db, scope, x) or scope.can_asset("personal.autorizar_mto", x.asset_id)


def dias(desde: date, hasta: date) -> tuple[int, int]:
    """(días naturales, días laborables de lunes a viernes). Los festivos no se descuentan."""
    naturales = (hasta - desde).days + 1
    laborables = sum(1 for i in range(naturales) if (desde + timedelta(days=i)).weekday() < 5)
    return naturales, laborables


def aprobadores_direccion(db: Session, asset_id: int) -> list[User]:
    """A quién se avisa para que apruebe dirección (cualquiera de ellos puede aprobar)."""
    return [u for u in usuarios_con(db, asset_id, "personal.autorizar") if not u.no_asignable]


def pendientes_de(db: Session, scope) -> list[Absence]:
    """Ausencias que esperan una decisión de este usuario (aprobar o dar el visto bueno)."""
    ids = scope.asset_ids("activos.ver")
    stmt = select(Absence).where(Absence.estado.in_(("pendiente", "visto_bueno")))
    if ids is not None:
        stmt = stmt.where(Absence.asset_id.in_(ids or {-1}))
    return [x for x in db.scalars(stmt.order_by(Absence.desde))
            if puede_aprobar(db, scope, x) or puede_visto_bueno(db, scope, x)]


def usuarios_con(db: Session, asset_id: int, perm: str | None = None) -> list[User]:
    """Usuarios activos con acceso al activo (y, si se indica, con ese permiso sobre él)."""
    from .security import Scope
    a = db.get(Asset, asset_id)
    cand = db.scalars(select(User).where(User.activo, User.id.in_(select(Assignment.user_id)))).all()
    out = []
    for u in cand:
        s = Scope(u, db)
        if perm is None:
            if any(x.asset_id == a.id or (x.asset_id is None and x.company_id in (None, a.company_id))
                   for x in u.assignments):
                out.append(u)
        elif not u.is_superadmin and s.can_asset(perm, a.id):
            out.append(u)
    return out
