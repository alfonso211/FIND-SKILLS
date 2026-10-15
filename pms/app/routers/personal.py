"""Personal de mantenimiento y limpieza: fichas con correo y teléfono, y envío de las órdenes de trabajo y del parte
de limpieza a cada persona por correo (con el parte en PDF) o por WhatsApp (enlace con el mensaje preparado; sin
WhatsApp Business de pago, el mensaje lo envía recepción desde su WhatsApp)."""
from datetime import date, datetime
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from .. import ausencias, avisos, documentos, empleados, firma_contrato, planos
from ..config import settings
from ..database import get_db
from ..models import (AREAS_PERSONAL, TIPOS_CONTRATO, TIPOS_DOC_EMPLEADO, Absence, Asset, EmailLog, ReceivedDocument,
                      Reservation, StaffDispatch, StaffDocument, StaffMember, Supplier, TimeEntry, Unit, User, WorkOrder)
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/personal", tags=["personal"])

# permiso para dar de alta y editar el personal de cada área
PERMISO_AREA = {"mantenimiento": "mantenimiento.editar", "limpieza": "limpieza.editar"}
# quien puede consultar el personal (para enviarle trabajo)
PERMISOS_VER = ("mantenimiento.ver", "limpieza.editar")


class StaffIn(BaseModel):
    asset_id: int | None = None
    area: str
    nombre: str = Field(min_length=2, max_length=160)
    empresa: str | None = Field(default=None, max_length=160)
    email: str | None = Field(default=None, max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    telefono: str | None = Field(default=None, max_length=40)
    avisar_urgentes: bool = False
    activo: bool = True
    notas: str | None = None
    # ficha del empleado (los gestiona Recepción 1 del activo o dirección)
    user_id: int | None = None
    dni: str | None = Field(default=None, max_length=20)
    puesto: str | None = Field(default=None, max_length=120)
    tipo_contrato: str | None = None
    fecha_alta: date | None = None
    fecha_baja: date | None = None
    jornada_semanal: float | None = Field(default=None, ge=0, le=60)
    vacaciones_dias: int | None = Field(default=None, ge=0, le=60)
    vacaciones_tipo: str | None = None


CAMPOS_FICHA = ("user_id", "dni", "puesto", "tipo_contrato", "fecha_alta", "fecha_baja", "jornada_semanal",
                "vacaciones_dias", "vacaciones_tipo")


class SendIn(BaseModel):
    personal_ids: list[int] = Field(min_length=1, max_length=30)
    canal: str  # email | whatsapp
    nota: str | None = Field(default=None, max_length=1000)


class CleaningSendIn(SendIn):
    asset_id: int
    fecha: date | None = None
    unit_ids: list[int] = Field(min_length=1, max_length=500)


def _out(p: StaffMember, db: Session, scope: Scope | None = None) -> dict:
    """Los datos laborales (DNI, contrato, vacaciones, usuario) solo los ve quien gestiona a la persona."""
    d = p.to_dict(exclude=("fichaje_clave",))
    d["activo_nombre"] = db.get(Asset, p.asset_id).nombre if p.asset_id else "Todos los activos"
    d["area_nombre"] = AREAS_PERSONAL.get(p.area, p.area)
    d["whatsapp"] = bool(p.telefono and firma_contrato.movil_whatsapp(p.telefono))
    d["propio"] = empleados.es_propio(p)
    d["gestiona"] = bool(scope and empleados.puede_gestionar(db, scope, p))
    d["editable"] = bool(scope and _editable(scope, db, p))
    if d["gestiona"]:
        d["usuario"] = db.get(User, p.user_id).nombre if p.user_id else None
        d["tipo_contrato_nombre"] = TIPOS_CONTRATO.get(p.tipo_contrato)
        d["saldo"] = empleados.saldo(db, p) if d["propio"] else None
        d["fichaje_enlace"] = bool(p.fichaje_clave)
        d["fichado"] = bool(empleados.abierto(db, p))
        d["documentos_vencen"] = sum(1 for x in db.scalars(select(StaffDocument.vence).where(
            StaffDocument.staff_id == p.id, StaffDocument.vence.is_not(None))) if x <= date.today())
    else:
        for k in CAMPOS_FICHA:
            d.pop(k, None)
    return d


def _valida_ficha(db: Session, data: StaffIn, pid: int | None = None) -> None:
    if data.tipo_contrato and data.tipo_contrato not in TIPOS_CONTRATO:
        bad_request(f"Tipo de contrato no válido. Opciones: {', '.join(TIPOS_CONTRATO)}")
    if data.vacaciones_tipo and data.vacaciones_tipo not in ("laborables", "naturales"):
        bad_request("Vacaciones: días laborables o naturales")
    if data.fecha_alta and data.fecha_baja and data.fecha_baja < data.fecha_alta:
        bad_request("La fecha de baja es anterior a la de alta")
    if data.user_id:
        get_or_404(db, User, data.user_id)
        otra = db.scalar(select(StaffMember).where(StaffMember.user_id == data.user_id,
                                                   StaffMember.id != (pid or -1)).limit(1))
        if otra:  # un usuario, una ficha
            bad_request(f"Ese usuario ya está enlazado a la ficha de {otra.nombre}")


def _propio_de(data: StaffIn) -> bool:
    return not (data.empresa or "").strip() and data.tipo_contrato != "autonomo"


def _visibles(scope: Scope) -> set[int] | None:
    ids: set[int] = set()
    for perm in PERMISOS_VER:
        a = scope.asset_ids(perm)
        if a is None:
            return None
        ids |= a
    return ids


def _puede_editar(scope: Scope, db: Session, area: str, asset_id: int | None, propio: bool) -> None:
    """Personal propio de las sociedades: solo el Director Técnico. Subcontratas: Recepción (1 y 2) del activo, quien
    gestiona mantenimiento o limpieza del activo, dirección y el Director Técnico."""
    if area not in AREAS_PERSONAL:
        bad_request(f"Área no válida. Opciones: {', '.join(AREAS_PERSONAL)}")
    dt = empleados.director_tecnico(scope)
    if propio:
        if not dt:
            raise HTTPException(403, "El personal propio de las sociedades lo da de alta el Director Técnico. "
                                     "Recepción solo da de alta personal de subcontratas: indique la empresa.")
        return
    if dt:
        return
    perm = PERMISO_AREA.get(area)
    if asset_id is None:
        if not (scope.is_group_level("personal.autorizar") or (perm and scope.is_group_level(perm))):
            raise HTTPException(403, "Solo dirección del grupo puede dar de alta personal para todos los activos")
        return
    if empleados.es_recepcion(db, scope, asset_id) or ausencias.direccion(scope, asset_id) or \
            (perm and scope.can_asset(perm, asset_id)):
        return
    raise HTTPException(403, "Sin permiso para dar de alta personal de subcontratas en este activo")


def _editable(scope: Scope, db: Session, p: StaffMember) -> bool:
    try:
        _puede_editar(scope, db, p.area, p.asset_id, empleados.es_propio(p))
        return True
    except HTTPException:
        return False


@router.get("")
def list_staff(asset_id: int | None = None, area: str | None = None, solo_activos: bool = False,
               scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = _visibles(scope)
    if ids is not None and not ids:
        raise HTTPException(403, "Sin permiso para ver el personal de mantenimiento y limpieza")
    stmt = select(StaffMember)
    if ids is not None:
        stmt = stmt.where(or_(StaffMember.asset_id.is_(None), StaffMember.asset_id.in_(ids)))
    if asset_id:  # el de ese activo y el que trabaja en todos
        stmt = stmt.where(or_(StaffMember.asset_id.is_(None), StaffMember.asset_id == asset_id))
    if area:
        stmt = stmt.where(StaffMember.area == area)
    if solo_activos:
        stmt = stmt.where(StaffMember.activo)
    return [_out(p, db, scope) for p in db.scalars(stmt.order_by(StaffMember.area, StaffMember.nombre))]


@router.post("", status_code=201)
def create_staff(data: StaffIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _puede_editar(scope, db, data.area, data.asset_id, _propio_de(data))
    if data.asset_id:
        get_or_404(db, Asset, data.asset_id)
    if data.user_id and not data.email and empleados.director_tecnico(scope):  # el correo de su usuario
        u = db.get(User, data.user_id)
        data.email = u.email if u else None
    if data.area in PERMISO_AREA and not (data.email or data.telefono):
        bad_request("Indique al menos un correo electrónico o un teléfono")
    _valida_ficha(db, data)
    valores = data.model_dump()
    p = StaffMember(**{k: v for k, v in valores.items() if k not in CAMPOS_FICHA})
    enlazar_empresa(db, p)
    if empleados.es_propio(p) and empleados.director_tecnico(scope):  # datos laborales: solo personal propio
        for k in CAMPOS_FICHA:
            setattr(p, k, valores[k])
    db.add(p)
    db.flush()
    audit(db, scope.user, "crear", "personal", p.id, {"nombre": p.nombre, "area": p.area})
    db.commit()
    return _out(p, db, scope)


@router.put("/{pid}")
def update_staff(pid: int, data: StaffIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = get_or_404(db, StaffMember, pid)
    _puede_editar(scope, db, p.area, p.asset_id, empleados.es_propio(p))
    _puede_editar(scope, db, data.area, data.asset_id, _propio_de(data))
    if data.asset_id:
        get_or_404(db, Asset, data.asset_id)
    if data.user_id and not data.email and empleados.director_tecnico(scope):  # el correo de su usuario
        u = db.get(User, data.user_id)
        data.email = u.email if u else None
    if data.area in PERMISO_AREA and not (data.email or data.telefono):
        bad_request("Indique al menos un correo electrónico o un teléfono")
    _valida_ficha(db, data, pid)
    antes = p.to_dict()
    ficha = empleados.director_tecnico(scope)  # los datos laborales solo los toca el Director Técnico
    for k, v in data.model_dump().items():
        if k not in CAMPOS_FICHA or ficha:
            setattr(p, k, v)
    enlazar_empresa(db, p)
    cambios = {k: v for k, v in p.to_dict().items() if antes.get(k) != v and k != "fichaje_clave"}
    audit(db, scope.user, "editar", "personal", pid, {k: (str(v) if v is not None else None) for k, v in cambios.items()})
    db.commit()
    return _out(p, db, scope)


@router.delete("/{pid}")
def delete_staff(pid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = get_or_404(db, StaffMember, pid)
    _puede_editar(scope, db, p.area, p.asset_id, empleados.es_propio(p))
    if db.scalar(select(TimeEntry.id).where(TimeEntry.staff_id == pid).limit(1)) or \
            db.scalar(select(StaffDocument.id).where(StaffDocument.staff_id == pid).limit(1)):
        bad_request("Tiene registro de jornada o documentos (se conservan 4 años): desmarque «En activo» para darle de baja")
    audit(db, scope.user, "borrar", "personal", pid, {"nombre": p.nombre, "area": p.area})
    for e in db.scalars(select(StaffDispatch).where(StaffDispatch.staff_id == pid)):
        db.delete(e)
    # lo que la cita se conserva sin ella (en PostgreSQL, si no, el borrado falla por la clave foránea)
    db.execute(update(Absence).where(Absence.staff_id == pid).values(staff_id=None))
    db.execute(update(WorkOrder).where(WorkOrder.personal_id == pid).values(personal_id=None))
    db.execute(update(ReceivedDocument).where(ReceivedDocument.staff_id == pid).values(staff_id=None))
    db.delete(p)
    db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- ficha del empleado
def _gestionada(db: Session, scope: Scope, pid: int) -> StaffMember:
    p = get_or_404(db, StaffMember, pid)
    if not empleados.puede_gestionar(db, scope, p):
        raise HTTPException(403, "La ficha del empleado la gestionan Recepción 1 del activo y la dirección")
    return p


@router.get("/catalogos")
def staff_catalogs():
    return {"areas": AREAS_PERSONAL, "contratos": TIPOS_CONTRATO, "documentos": TIPOS_DOC_EMPLEADO}


@router.get("/{pid}/saldo")
def vacation_balance(pid: int, anio: int | None = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return empleados.saldo(db, _gestionada(db, scope, pid), anio)


# --------------------------------------------------------------------------- vacaciones de la ficha
class PeriodoIn(BaseModel):
    desde: date
    hasta: date


class VacacionesIn(BaseModel):
    periodos: list[PeriodoIn] = Field(min_length=1, max_length=20)
    nota: str | None = Field(default=None, max_length=300)


def _periodos(db: Session, p: StaffMember, anio: int) -> list[dict]:
    from ..models import Absence
    hoy = date.today()
    cond = [Absence.staff_id == p.id] + ([Absence.user_id == p.user_id] if p.user_id else [])
    out = []
    for x in db.scalars(select(Absence).where(or_(*cond), Absence.tipo == "vacaciones",
                                              Absence.estado.in_(("pendiente", "visto_bueno", "aprobada")),
                                              Absence.desde <= date(anio, 12, 31), Absence.hasta >= date(anio, 1, 1))
                        .order_by(Absence.desde)):
        estado = ("por aprobar" if x.estado != "aprobada" else "disfrutada" if x.hasta <= hoy
                  else "en curso" if x.desde <= hoy else "solicitada")
        autor = db.get(User, x.creado_por) if x.creado_por else None
        out.append({"id": x.id, "desde": x.desde.isoformat(), "hasta": x.hasta.isoformat(), "estado": estado,
                    "dias": empleados._computa(x.desde, x.hasta, empleados.saldo(db, p, anio)["tipo"]),
                    "registrada_por": autor.nombre if autor and autor.id != p.user_id else None, "nota": x.motivo})
    return out


@router.get("/{pid}/vacaciones")
def vacations(pid: int, anio: int | None = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = _gestionada(db, scope, pid)
    anio = anio or date.today().year
    return {"saldo": empleados.saldo(db, p, anio), "periodos": _periodos(db, p, anio),
            "registrar": empleados.director_tecnico(scope) and empleados.es_propio(p)}


@router.post("/{pid}/vacaciones", status_code=201)
def register_vacations(pid: int, data: VacacionesIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """El Director Técnico registra en la ficha las vacaciones ya disfrutadas y las ya acordadas (quedan autorizadas),
    para que cuadre el saldo pendiente. Se envía la nueva revisión del calendario a todos."""
    from .. import informe_vacaciones
    from ..models import Absence
    if not empleados.director_tecnico(scope):
        raise HTTPException(403, "Las vacaciones de la ficha las registra el Director Técnico")
    p = get_or_404(db, StaffMember, pid)
    if not empleados.es_propio(p):
        bad_request("Solo se registran vacaciones del personal propio")
    u = db.get(User, p.user_id) if p.user_id else None
    aid = p.asset_id or next((x.asset_id for x in (u.assignments if u else []) if x.asset_id), None) or \
        db.scalar(select(Asset.id).where(Asset.activo).order_by(Asset.id).limit(1))
    a = get_or_404(db, Asset, aid)
    colectivo = ausencias.colectivo_usuario(db, u, a) if u else ausencias.colectivo_staff(p)
    nuevas, cambios, tramos = [], [], []
    for per in data.periodos:
        if per.hasta < per.desde:
            bad_request("La fecha final es anterior a la inicial")
        cond = [Absence.staff_id == p.id] + ([Absence.user_id == p.user_id] if p.user_id else [])
        choque = db.scalar(select(Absence).where(or_(*cond), Absence.estado.in_(("pendiente", "visto_bueno", "aprobada")),
                                                 Absence.desde <= per.hasta, Absence.hasta >= per.desde).limit(1))
        if choque or any(n.desde <= per.hasta and n.hasta >= per.desde for n in nuevas):
            bad_request(f"El periodo del {per.desde:%d/%m/%Y} al {per.hasta:%d/%m/%Y} se solapa con otro ya registrado")
        x = Absence(asset_id=a.id, user_id=p.user_id, staff_id=p.id, persona=p.nombre, colectivo=colectivo,
                    tipo="vacaciones", desde=per.desde, hasta=per.hasta, estado="aprobada", creado_por=scope.user.id,
                    resuelto_por=scope.user.id, resuelto_en=datetime.now(),
                    motivo=(data.nota or "").strip() or "Registrada por la Dirección Técnica")
        db.add(x)
        nuevas.append(x)
        que = "disfrutadas" if per.hasta < date.today() else "acordadas"
        cambios.append(f"{p.nombre}: registradas las vacaciones {que} del {per.desde:%d/%m/%Y} al {per.hasta:%d/%m/%Y}.")
        tramos.append((p.id, per.desde, per.hasta))
    db.flush()
    audit(db, scope.user, "registrar_vacaciones", "personal", p.id,
          {"periodos": [(n.desde.isoformat(), n.hasta.isoformat()) for n in nuevas]})
    db.commit()
    for anio in sorted({n.desde.year for n in nuevas}):
        informe_vacaciones.notificar(anio, [c for c, n in zip(cambios, nuevas) if n.desde.year == anio],
                                     [t for t, n in zip(tramos, nuevas) if n.desde.year == anio], scope.user.id)
    return {"saldo": empleados.saldo(db, p), "periodos": _periodos(db, p, date.today().year)}


@router.get("/{pid}/documentos")
def list_documents(pid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _gestionada(db, scope, pid)
    return [{**d.to_dict(exclude=("fichero", "sha256")), "tipo_nombre": TIPOS_DOC_EMPLEADO.get(d.tipo, d.tipo),
             "vencido": bool(d.vence and d.vence < date.today())}
            for d in db.scalars(select(StaffDocument).where(StaffDocument.staff_id == pid)
                                .order_by(StaffDocument.tipo, StaffDocument.fecha.desc()))]


@router.post("/{pid}/documentos", status_code=201)
def upload_document(pid: int, ficheros: list[UploadFile] = File(...), tipo: str = Form(...),
                    fecha: date | None = Form(None), vence: date | None = Form(None), notas: str | None = Form(None),
                    scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    from .gastos import _fichero
    p = _gestionada(db, scope, pid)
    if tipo not in TIPOS_DOC_EMPLEADO:
        bad_request("Tipo de documento no válido")
    if fecha and vence and vence < fecha:
        bad_request("El vencimiento es anterior a la fecha del documento")
    datos, mime, nombre = _fichero(ficheros)
    d = StaffDocument(staff_id=p.id, tipo=tipo, fecha=fecha, vence=vence, notas=(notas or "").strip()[:300] or None,
                      nombre=f"{TIPOS_DOC_EMPLEADO[tipo]} · {p.nombre}"[:120] + "." + nombre.rsplit(".", 1)[-1],
                      fichero=documentos.guardar(datos), mime=mime, tamano=len(datos), sha256=documentos.huella(datos),
                      user_id=scope.user.id)
    db.add(d)
    db.flush()
    audit(db, scope.user, "subir_documento", "personal", p.id, {"tipo": tipo, "documento": d.id})
    db.commit()
    return {"id": d.id}


def _documento(db: Session, scope: Scope, did: int) -> StaffDocument:
    d = get_or_404(db, StaffDocument, did)
    _gestionada(db, scope, d.staff_id)
    return d


@router.get("/documentos/{did}")
def view_document(did: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    d = _documento(db, scope, did)
    audit(db, scope.user, "ver_documento", "personal", d.staff_id, {"documento": did})  # registro de accesos
    db.commit()
    return Response(documentos.leer(d.fichero), media_type=d.mime, headers={
        "Content-Disposition": f'inline; filename="{empleados.nombre_fichero(d.nombre)}"', "Cache-Control": "private, no-store"})


@router.delete("/documentos/{did}")
def delete_document(did: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    d = _documento(db, scope, did)
    audit(db, scope.user, "borrar_documento", "personal", d.staff_id, {"documento": did, "tipo": d.tipo})
    fichero = d.fichero
    db.delete(d)
    db.commit()
    documentos.borrar(fichero)
    return {"ok": True}


@router.post("/{pid}/enlace-fichaje")
def time_link(pid: int, request: Request, nuevo: bool = False, scope: Scope = Depends(get_scope),
              db: Session = Depends(get_db)):
    """Enlace personal para fichar desde el móvil sin usuario del PMS. «nuevo» lo cambia (el anterior deja de valer)."""
    p = _gestionada(db, scope, pid)
    if not empleados.es_propio(p):
        bad_request("Solo ficha el personal propio (no las subcontratas)")
    if nuevo or not p.fichaje_clave:
        p.fichaje_clave = empleados.clave_nueva()
        audit(db, scope.user, "enlace_fichaje", "personal", p.id, {"nuevo": True})
        db.commit()
    base = (settings.url or str(request.base_url)).rstrip("/")
    url = f"{base}/fichar/{p.id}?k={p.fichaje_clave}"
    movil = firma_contrato.movil_whatsapp(p.telefono or "")
    texto = (f"Hola {p.nombre.split()[0]}, este es tu enlace personal para registrar la jornada (entrada y salida): "
             f"{url} . Guárdalo en la pantalla de inicio del móvil y no lo compartas.")
    return {"url": url, "whatsapp": f"https://wa.me/{movil}?text={quote(texto)}" if movil else None}


# --------------------------------------------------------------------------- usuarios, comprobación y borrado
@router.get("/usuarios")
def users_for_link(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Usuarios activos para enlazar a una ficha, con la ficha que ya tienen (un usuario, una ficha)."""
    if not empleados.director_tecnico(scope):
        raise HTTPException(403, "Las fichas del personal propio las gestiona el Director Técnico")
    fichas = {p.user_id: p for p in db.scalars(select(StaffMember).where(StaffMember.user_id.is_not(None)))}
    return [{"id": u.id, "nombre": u.nombre, "email": u.email, "ficha_id": fichas[u.id].id if u.id in fichas else None,
             "ficha": fichas[u.id].nombre if u.id in fichas else None}
            for u in db.scalars(select(User).where(User.activo, User.supplier_id.is_(None)).order_by(User.nombre))]


def _comprobaciones(db: Session) -> list[dict]:
    from ..models import Absence, Assignment, Role
    out = []

    def add(nivel: str, que: str, texto: str, corregible: bool = False):
        out.append({"nivel": nivel, "que": que, "texto": texto, "corregible": corregible})

    recep = {}  # activo -> usuarios con rol Recepción
    for u, aid in db.execute(select(User, Assignment.asset_id).join(Assignment, Assignment.user_id == User.id)
                             .join(Role, Role.id == Assignment.role_id)
                             .where(Role.nombre == "Recepción", Assignment.asset_id.is_not(None))):
        recep.setdefault(aid, []).append(u)
    for a in db.scalars(select(Asset).where(Asset.activo).order_by(Asset.nombre)):
        usuarios = recep.get(a.id, [])
        if not usuarios:
            continue
        r1 = db.get(User, a.recepcion1_id) if a.recepcion1_id else None
        if a.recepcion1_id is None:
            add("error", "Recepción 1", f"{a.nombre}: no tiene Recepción 1 asignada. Asígnela en Activos → Editar.")
        elif r1 is None or not r1.activo:
            add("error", "Recepción 1", f"{a.nombre}: la Recepción 1 asignada no existe o está desactivada.")
        elif r1.id not in {u.id for u in usuarios}:
            add("error", "Recepción 1", f"{a.nombre}: {r1.nombre} es Recepción 1 pero no tiene el rol Recepción en el activo.")
        for u in usuarios:
            n = (u.nombre or "").lower()
            if r1 and u.id == r1.id and "recepción 2" in n.replace("recepcion", "recepción"):
                add("aviso", "Nombres", f"{a.nombre}: {u.nombre} ({u.email}) es Recepción 1 pero su nombre dice «Recepción 2».")
            if r1 and u.id != r1.id and "recepción 1" in n.replace("recepcion", "recepción"):
                add("aviso", "Nombres", f"{a.nombre}: {u.nombre} ({u.email}) se llama «Recepción 1» pero no es la Recepción 1 del activo.")
    vistos: dict[int, list[str]] = {}
    for p in db.scalars(select(StaffMember).order_by(StaffMember.nombre)):
        if p.user_id:
            vistos.setdefault(p.user_id, []).append(p.nombre)
            u = db.get(User, p.user_id)
            if u is None or not u.activo:
                add("error", "Fichas", f"Ficha de {p.nombre}: su usuario no existe o está desactivado.")
        if empleados.es_propio(p) and p.activo and not p.user_id:
            add("info", "Fichas", f"Ficha de {p.nombre} (personal propio) sin usuario: no podrá pedir vacaciones.")
        if not empleados.es_propio(p) and (p.empresa or "").strip() and not p.supplier_id:
            add("aviso", "Fichas", f"Ficha de {p.nombre}: la empresa «{p.empresa}» no está en Proveedores (su colaborador no la ve).")
    for uid, nombres in vistos.items():
        if len(nombres) > 1:
            add("error", "Fichas", f"El usuario {db.get(User, uid).nombre} está en {len(nombres)} fichas: {', '.join(nombres)}.")
    for x in db.scalars(select(Absence).where(Absence.estado.in_(("pendiente", "visto_bueno")), Absence.user_id.is_not(None))):
        u, a = db.get(User, x.user_id), db.get(Asset, x.asset_id)
        if u and a and ausencias.colectivo_usuario(db, u, a) != x.colectivo:
            add("error", "Ausencias", f"Solicitud de {x.persona} ({x.desde:%d/%m/%Y}) está como «{x.colectivo}» y le corresponde "
                f"«{ausencias.colectivo_usuario(db, u, a)}»: va a quien no debe aprobarla.", corregible=True)
    return out


@router.get("/comprobar")
def check(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if not empleados.director_tecnico(scope):
        raise HTTPException(403, "La comprobación la hace el Director Técnico")
    from .admin import puede_borrar
    return {"resultados": _comprobaciones(db), "fichas": db.scalar(select(func.count(StaffMember.id))),
            "puede_borrar": puede_borrar(scope.user)}


@router.post("/comprobar/corregir")
def fix(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Recoloca las solicitudes pendientes en el colectivo que les corresponde (p. ej. Recepción 1 tomada por R2)."""
    if not empleados.director_tecnico(scope):
        raise HTTPException(403, "La comprobación la hace el Director Técnico")
    from ..models import Absence
    n = 0
    for x in db.scalars(select(Absence).where(Absence.estado.in_(("pendiente", "visto_bueno")), Absence.user_id.is_not(None))):
        u, a = db.get(User, x.user_id), db.get(Asset, x.asset_id)
        col = ausencias.colectivo_usuario(db, u, a) if u and a else x.colectivo
        if col != x.colectivo:
            x.colectivo, n = col, n + 1
            if col != "recepcion2" and x.estado == "visto_bueno":
                x.estado = "pendiente"
    audit(db, scope.user, "corregir_ausencias", "personal", 0, {"corregidas": n})
    db.commit()
    return {"corregidas": n}


AREA_POR_ROL = {"Recepción": "recepcion", "Técnico Mantenimiento": "mantenimiento", "Gobernanta / Limpieza": "limpieza",
                "Administración / Finanzas": "administracion"}


@router.post("/generar-desde-usuarios")
def generate_from_users(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Crea la ficha de personal propio de cada usuario del PMS que aún no la tiene (área y activo según su rol).
    No incluye a la presidencia, a los colaboradores externos ni al administrador del sistema."""
    if not empleados.director_tecnico(scope):
        raise HTTPException(403, "Las fichas del personal propio las genera el Director Técnico")
    con_ficha = set(db.scalars(select(StaffMember.user_id).where(StaffMember.user_id.is_not(None))))
    creadas = []
    for u in db.scalars(select(User).where(User.activo, User.supplier_id.is_(None)).order_by(User.nombre)):
        if u.id in con_ficha or u.no_asignable or (u.email or "").lower() == settings.admin_email.lower():
            continue
        asign = sorted(u.assignments, key=lambda x: x.asset_id is None)  # primero la de un activo concreto
        rol = next((x for x in asign if x.role.nombre in AREA_POR_ROL), asign[0] if asign else None)
        area = AREA_POR_ROL.get(rol.role.nombre, "otros") if rol else "otros"
        p = StaffMember(asset_id=rol.asset_id if rol else None, area=area, nombre=u.nombre, email=u.email,
                        user_id=u.id, activo=True)
        db.add(p)
        creadas.append(u.nombre)
    db.flush()
    audit(db, scope.user, "generar_fichas", "personal", 0, {"creadas": creadas})
    db.commit()
    return {"creadas": creadas}


class BorrarTodoIn(BaseModel):
    confirmacion: str


@router.post("/borrar-todo")
def wipe(data: BorrarTodoIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Borra todas las fichas del personal (y sus fichajes, documentos y envíos) para empezar de nuevo. Las ausencias
    de usuarios se conservan (se desenlazan de la ficha); las del personal sin usuario se borran. Las OT y documentos
    que las citaban quedan sin persona asignada."""
    from ..models import Absence, ReceivedDocument, WorkOrder
    from .admin import puede_borrar
    if not puede_borrar(scope.user):
        raise HTTPException(403, "Solo el Director Técnico y el administrador pueden borrar todo el personal")
    if data.confirmacion.strip().upper() != "BORRAR PERSONAL":
        bad_request("Escriba BORRAR PERSONAL para confirmar")
    ids = list(db.scalars(select(StaffMember.id)))
    n = {"fichas": len(ids)}
    ficheros = list(db.scalars(select(StaffDocument.fichero)))
    n["documentos"] = db.execute(delete(StaffDocument)).rowcount
    n["fichajes"] = db.execute(delete(TimeEntry)).rowcount
    n["envios"] = db.execute(delete(StaffDispatch)).rowcount
    n["ausencias_borradas"] = db.execute(delete(Absence).where(Absence.staff_id.is_not(None), Absence.user_id.is_(None))).rowcount
    db.execute(update(Absence).where(Absence.staff_id.is_not(None)).values(staff_id=None))
    db.execute(update(WorkOrder).where(WorkOrder.personal_id.is_not(None)).values(personal_id=None))
    db.execute(update(ReceivedDocument).where(ReceivedDocument.staff_id.is_not(None)).values(staff_id=None))
    db.execute(delete(StaffMember))
    audit(db, scope.user, "borrar_todo", "personal", 0, n)
    db.commit()
    for f in ficheros:
        documentos.borrar(f)
    return n


# --------------------------------------------------------------------------- envíos
def destinatarios(db: Session, ids: list[int], asset_id: int, canal: str) -> list[StaffMember]:
    if canal not in ("email", "whatsapp"):
        bad_request("Canal no válido: email o whatsapp")
    if canal == "email" and not avisos.configurado():
        bad_request("El correo no está configurado en el servidor: envíelo por WhatsApp")
    out = []
    for pid in dict.fromkeys(ids):
        p = get_or_404(db, StaffMember, pid)
        if not p.activo or p.asset_id not in (None, asset_id):
            bad_request(f"{p.nombre} no trabaja en este activo o está de baja")
        if canal == "email" and not p.email:
            bad_request(f"{p.nombre} no tiene correo electrónico")
        if canal == "whatsapp" and not firma_contrato.movil_whatsapp(p.telefono or ""):
            bad_request(f"{p.nombre} no tiene un móvil válido para WhatsApp")
        out.append(p)
    return out


def norm_empresa(s: str | None) -> str:
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())  # «S.L.», «SL» y «s. l.» son iguales


def enlazar_empresa(db: Session, p: StaffMember) -> None:
    """Enlaza la persona con su empresa de Proveedores por el nombre (si hay una sola con ese nombre)."""
    if not p.empresa:
        p.supplier_id = None
        return
    k = norm_empresa(p.empresa)
    ids = [i for i, n in db.execute(select(Supplier.id, Supplier.nombre)) if norm_empresa(n) == k]
    p.supplier_id = ids[0] if len(ids) == 1 else None


def despachar(db: Session, personas: list[StaffMember], canal: str, clave: str, asunto: str, texto: str, html: str,
              adjuntos: list[tuple[str, bytes, str]] | None = None) -> list[dict]:
    """Envía a cada persona. Correo: se envía ya (un fallo con una persona no impide el resto). WhatsApp: devuelve
    el enlace con el mensaje escrito para abrirlo y pulsar «Enviar»."""
    out = []
    for p in personas:
        r = {"id": p.id, "nombre": p.nombre, "canal": canal}
        if canal == "email":
            r["destino"] = p.email
            try:
                avisos.enviar(p.email, asunto, texto, html, adjuntos)
                r["ok"] = True
            except Exception as e:  # noqa: BLE001
                r["ok"], r["error"] = False, str(e)[:200]
            db.add(EmailLog(clave=clave, tipo=clave.split(":")[0], destinatario=p.email, asunto=asunto[:200],
                            ok=r["ok"], error=r.get("error")))
        else:
            movil = firma_contrato.movil_whatsapp(p.telefono)
            r.update(destino=movil, ok=True, whatsapp=f"https://wa.me/{movil}?text={quote(texto)}")
        if r["ok"]:  # copia para el portal de su colaborador
            db.add(StaffDispatch(staff_id=p.id, tipo=clave.split(":")[0][:30], clave=clave[:80], canal=canal,
                                 asunto=asunto[:200], texto=texto))
        out.append(r)
    return out


def _lugar(db: Session, asset_id: int, unit_id: int | None, zona: str | None) -> str:
    u = db.get(Unit, unit_id) if unit_id else None
    if u:
        return f"{u.uso} {u.codigo}" + (f" ({u.bloque}, planta {u.planta})" if u.bloque and u.planta else "")
    nombre = planos.zonas(db.get(Asset, asset_id).codigo).get(zona) if zona else None
    return f"Zonas comunes · {nombre}" if nombre else "Zonas comunes"


# --------------------------------------------------------------------------- parte de limpieza
def parte_limpieza(db: Session, asset_id: int, f: date) -> list[dict]:
    """Unidades a limpiar el día `f`: las pendientes de limpieza y las que tienen salida ese día. Las que además
    tienen llegada ese día van primero (hay que tenerlas listas antes de la entrada)."""
    unidades = {u.id: u for u in db.scalars(select(Unit).where(
        Unit.asset_id == asset_id, Unit.uso != "garaje", Unit.estado != "fuera_servicio"))}
    salen = {r.unit_id: r for r in db.scalars(select(Reservation).where(
        Reservation.unit_id.in_(unidades), Reservation.fecha_salida == f,
        Reservation.estado.in_(("checkin", "checkout"))))}
    llegan = {r.unit_id: r for r in db.scalars(select(Reservation).where(
        Reservation.unit_id.in_(unidades), Reservation.fecha_entrada == f,
        Reservation.estado.in_(("confirmada", "checkin"))))}
    out = []
    for uid, u in unidades.items():
        pendiente = u.estado == "pendiente_limpieza"
        if not (pendiente or uid in salen):
            continue
        s, ll = salen.get(uid), llegan.get(uid)
        motivo = ("Salida hoy" if s.estado == "checkin" else "Salida realizada") if s else "Pendiente de limpieza"
        out.append({"unit_id": uid, "codigo": u.codigo, "bloque": u.bloque, "planta": u.planta,
                    "tipologia": u.tipologia, "motivo": motivo, "pendiente": pendiente,
                    "llegada": bool(ll), "pax_llegada": (ll.adultos + ll.ninos) if ll else None})
    out.sort(key=lambda x: (not x["llegada"], x["bloque"] or "", x["codigo"]))
    return out


@router.get("/limpieza")
def cleaning_sheet(asset_id: int, fecha: date | None = None, scope: Scope = Depends(get_scope),
                   db: Session = Depends(get_db)):
    scope.require_asset("limpieza.editar", asset_id)
    get_or_404(db, Asset, asset_id)
    f = fecha or date.today()
    return {"fecha": f.isoformat(), "unidades": parte_limpieza(db, asset_id, f)}


@router.post("/limpieza/enviar")
def send_cleaning(data: CleaningSendIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Envía a cada persona de limpieza el parte con las unidades elegidas."""
    scope.require_asset("limpieza.editar", data.asset_id)
    a = get_or_404(db, Asset, data.asset_id)
    f = data.fecha or date.today()
    personas = destinatarios(db, data.personal_ids, a.id, data.canal)
    todas = {x["unit_id"]: x for x in parte_limpieza(db, a.id, f)}
    filas = []
    for uid in dict.fromkeys(data.unit_ids):
        x = todas.get(uid)
        if x is None:  # también se puede mandar una unidad que no figura en el parte (repaso, limpieza a fondo)
            u = get_or_404(db, Unit, uid)
            if u.asset_id != a.id:
                bad_request("La unidad no pertenece al activo")
            x = {"codigo": u.codigo, "bloque": u.bloque, "planta": u.planta, "motivo": "Limpieza solicitada",
                 "llegada": False, "pax_llegada": None}
        filas.append(x)
    prio = lambda x: f"LLEGADA HOY ({x['pax_llegada']} pax)" if x["llegada"] else ""  # noqa: E731
    asunto = f"Parte de limpieza · {a.nombre} · {f:%d/%m/%Y} · {len(filas)} unidad(es)"
    lineas = [f"- {x['codigo']}" + (f" ({x['bloque']}, planta {x['planta']})" if x["bloque"] and x["planta"] else "")
              + f": {x['motivo']}" + (f" · {prio(x)}" if x["llegada"] else "") for x in filas]
    texto = (f"Parte de limpieza {a.nombre} · {f:%d/%m/%Y}\n" + "\n".join(lineas)
             + (f"\n\nNota: {data.nota}" if data.nota else "")
             + "\n\nPrimero las que tienen llegada hoy. Avise a recepción al terminar cada unidad.")
    html = avisos._html(f"Parte de limpieza · {f:%d/%m/%Y}", (
        f"<p><b>{escape(a.nombre)}</b> · {len(filas)} unidad(es). Primero las que tienen llegada hoy.</p>"
        + avisos._tabla(["Unidad", "Bloque", "Planta", "Motivo", "Prioridad"],
                        [[x["codigo"], x["bloque"] or "", x["planta"] or "", x["motivo"], prio(x)] for x in filas])
        + (f"<p><b>Nota:</b> {escape(data.nota)}</p>" if data.nota else "")
        + "<p>Avise a recepción al terminar cada unidad.</p>"))
    res = despachar(db, personas, data.canal, f"parte_limpieza:{a.id}:{f.isoformat()}", asunto, texto, html)
    audit(db, scope.user, "enviar_parte_limpieza", "activo", a.id, {
        "fecha": f.isoformat(), "canal": data.canal, "unidades": [x["codigo"] for x in filas],
        "personal": [p.nombre for p in personas]})
    db.commit()
    return {"enviados": res}


def registrar_envio_ot(w, resultados: list[dict], usuario: str | None) -> None:
    ahora = datetime.now().isoformat(timespec="seconds")
    w.envios = [*(w.envios or []), *({"fecha": ahora, "canal": r["canal"], "destino": r["destino"],
                                      "nombre": r["nombre"], "usuario": usuario} for r in resultados if r["ok"])]
