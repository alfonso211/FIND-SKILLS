"""Personal de mantenimiento y limpieza: fichas con correo y teléfono, y envío de las órdenes de trabajo y del parte
de limpieza a cada persona por correo (con el parte en PDF) o por WhatsApp (enlace con el mensaje preparado; sin
WhatsApp Business de pago, el mensaje lo envía recepción desde su WhatsApp)."""
from datetime import date, datetime
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import ausencias, avisos, firma_contrato, planos
from ..database import get_db
from ..models import AREAS_PERSONAL, Asset, EmailLog, Reservation, StaffMember, Unit
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/personal", tags=["personal"])

# permiso para dar de alta y editar el personal de cada área
PERMISO_AREA = {"mantenimiento": "mantenimiento.editar", "limpieza": "limpieza.editar"}
# quien puede consultar el personal (para enviarle trabajo)
PERMISOS_VER = ("mantenimiento.ver", "limpieza.editar", "limpieza.confirmar_ot")


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


class SendIn(BaseModel):
    personal_ids: list[int] = Field(min_length=1, max_length=30)
    canal: str  # email | whatsapp
    nota: str | None = Field(default=None, max_length=1000)


class CleaningSendIn(SendIn):
    asset_id: int
    fecha: date | None = None
    unit_ids: list[int] = Field(min_length=1, max_length=500)


def _out(p: StaffMember, db: Session) -> dict:
    d = p.to_dict()
    d["activo_nombre"] = db.get(Asset, p.asset_id).nombre if p.asset_id else "Todos los activos"
    d["area_nombre"] = AREAS_PERSONAL.get(p.area, p.area)
    d["whatsapp"] = bool(p.telefono and firma_contrato.movil_whatsapp(p.telefono))
    return d


def _visibles(scope: Scope) -> set[int] | None:
    ids: set[int] = set()
    for perm in PERMISOS_VER:
        a = scope.asset_ids(perm)
        if a is None:
            return None
        ids |= a
    return ids


def _puede_editar(scope: Scope, db: Session, area: str, asset_id: int | None) -> None:
    if area not in AREAS_PERSONAL:
        bad_request(f"Área no válida. Opciones: {', '.join(AREAS_PERSONAL)}")
    perm = PERMISO_AREA.get(area)
    if perm is None:  # conserjería y otros por administración: los gestiona Recepción 1 (o dirección)
        if asset_id is None and not scope.is_group_level("personal.autorizar"):
            raise HTTPException(403, "Solo dirección del grupo puede dar de alta personal para todos los activos")
        if asset_id is not None and not ausencias.gestiona(db, scope, get_or_404(db, Asset, asset_id)):
            raise HTTPException(403, "Este personal lo gestiona Recepción 1 del activo")
        return
    if asset_id is None and not scope.is_group_level(perm):
        raise HTTPException(403, "Solo quien gestiona todo el grupo puede dar de alta personal para todos los activos")
    if asset_id is not None and not scope.can_asset(perm, asset_id):
        raise HTTPException(403, f"Sin permiso '{perm}' sobre este activo")


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
    return [_out(p, db) for p in db.scalars(stmt.order_by(StaffMember.area, StaffMember.nombre))]


@router.post("", status_code=201)
def create_staff(data: StaffIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _puede_editar(scope, db, data.area, data.asset_id)
    if data.asset_id:
        get_or_404(db, Asset, data.asset_id)
    if data.area in PERMISO_AREA and not (data.email or data.telefono):
        bad_request("Indique al menos un correo electrónico o un teléfono")
    p = StaffMember(**data.model_dump())
    db.add(p)
    db.flush()
    audit(db, scope.user, "crear", "personal", p.id, {"nombre": p.nombre, "area": p.area})
    db.commit()
    return _out(p, db)


@router.put("/{pid}")
def update_staff(pid: int, data: StaffIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = get_or_404(db, StaffMember, pid)
    _puede_editar(scope, db, p.area, p.asset_id)
    _puede_editar(scope, db, data.area, data.asset_id)
    if data.asset_id:
        get_or_404(db, Asset, data.asset_id)
    if data.area in PERMISO_AREA and not (data.email or data.telefono):
        bad_request("Indique al menos un correo electrónico o un teléfono")
    antes = p.to_dict()
    for k, v in data.model_dump().items():
        setattr(p, k, v)
    audit(db, scope.user, "editar", "personal", pid, {k: v for k, v in p.to_dict().items() if antes.get(k) != v})
    db.commit()
    return _out(p, db)


@router.delete("/{pid}")
def delete_staff(pid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = get_or_404(db, StaffMember, pid)
    _puede_editar(scope, db, p.area, p.asset_id)
    audit(db, scope.user, "borrar", "personal", pid, {"nombre": p.nombre, "area": p.area})
    db.delete(p)
    db.commit()
    return {"ok": True}


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
