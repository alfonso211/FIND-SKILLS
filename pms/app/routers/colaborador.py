"""Portal del colaborador: acceso de una subcontrata (usuario ligado a un proveedor con el rol «Colaborador»).

Solo ve lo suyo, en los activos que tenga asignados: su personal, las órdenes de trabajo encargadas a su empresa
o a su personal, las líneas de los partes de trabajo validados que son suyas y lo que se ha enviado a su personal
(OT, partes de limpieza). Sube facturas, albaranes y documentación (de personal, legal / CAE), que quedan
pendientes de revisar por Recepción 1 o dirección. Fuera de /api/colaborador/ y /api/auth/ no puede entrar a
ninguna ruta (ver security.RUTAS_COLABORADOR)."""
from datetime import date, datetime, timedelta
from html import escape

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import ausencias, avisos, documentos
from ..database import get_db
from ..models import (AREAS_PERSONAL, TIPOS_DOCUMENTO, Asset, ReceivedDocument, StaffDispatch, StaffMember, Supplier,
                      WorkOrder, WorkReport)
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404
from .gastos import _fichero
from .personal import _lugar, norm_empresa

router = APIRouter(prefix="/api/colaborador", tags=["colaborador"])

# lo que puede subir un colaborador
TIPOS_COLABORADOR = ("factura", "albaran", "presupuesto", "personal", "legal", "otro")
REVISIONES = {"pendiente": "Pendiente de revisar", "aceptado": "Aceptado", "rechazado": "Rechazado"}


class Ctx:
    def __init__(self, db: Session, scope: Scope):
        u = scope.user
        if u.supplier_id is None:
            raise HTTPException(403, "Este acceso es solo para colaboradores")
        self.proveedor = get_or_404(db, Supplier, u.supplier_id)
        ids = scope.asset_ids("colaborador.portal")
        if ids is not None and not ids:
            raise HTTPException(403, "No tiene activos asignados: pídalo a Recepción 1 o a dirección")
        self.activos = {a.id: a for a in db.scalars(select(Asset).where(Asset.id.in_(ids)) if ids is not None
                                                    else select(Asset))}
        # su personal: enlazado a su empresa, o con el mismo nombre de empresa si aún no se enlazó
        k = norm_empresa(self.proveedor.nombre)
        self.personal = [p for p in db.scalars(select(StaffMember).where(or_(
            StaffMember.supplier_id == self.proveedor.id,
            StaffMember.supplier_id.is_(None) & StaffMember.empresa.is_not(None))))
            if (p.supplier_id == self.proveedor.id or norm_empresa(p.empresa) == k)
            and (p.asset_id is None or p.asset_id in self.activos)]
        self.staff_ids = {p.id for p in self.personal}


def ctx(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)) -> Ctx:
    return Ctx(db, scope)


def _ordenes(db: Session, c: Ctx) -> list[WorkOrder]:
    cond = [WorkOrder.proveedor_id == c.proveedor.id]
    if c.staff_ids:
        cond.append(WorkOrder.personal_id.in_(c.staff_ids))
    return list(db.scalars(select(WorkOrder).where(WorkOrder.asset_id.in_(c.activos), or_(*cond))
                           .order_by(WorkOrder.fecha_apertura.desc(), WorkOrder.id.desc()).limit(500)))


# --------------------------------------------------------------------------- consultas
@router.get("/resumen")
def summary(c: Ctx = Depends(ctx), db: Session = Depends(get_db)):
    ots = _ordenes(db, c)
    pend = db.scalar(select(ReceivedDocument.id).where(ReceivedDocument.supplier_id == c.proveedor.id,
                                                       ReceivedDocument.revision == "pendiente").limit(1))
    return {"proveedor": {"id": c.proveedor.id, "nombre": c.proveedor.nombre, "nif": c.proveedor.nif},
            "activos": [{"id": a.id, "nombre": a.nombre, "codigo": a.codigo} for a in c.activos.values()],
            "personal": len(c.personal), "ot_abiertas": sum(1 for w in ots if w.estado not in ("cerrada", "cancelada")),
            "documentos_pendientes": pend is not None,
            "tipos_documento": {t: TIPOS_DOCUMENTO[t] for t in TIPOS_COLABORADOR}}


@router.get("/personal")
def staff(c: Ctx = Depends(ctx)):
    return [{"id": p.id, "nombre": p.nombre, "area": AREAS_PERSONAL.get(p.area, p.area), "email": p.email,
             "telefono": p.telefono, "activo": p.activo,
             "activo_nombre": c.activos[p.asset_id].nombre if p.asset_id else "Todos sus activos"}
            for p in sorted(c.personal, key=lambda p: p.nombre)]


@router.get("/ordenes")
def orders(abiertas: bool = False, c: Ctx = Depends(ctx), db: Session = Depends(get_db)):
    nombres = {p.id: p.nombre for p in c.personal}
    out = []
    for w in _ordenes(db, c):
        if abiertas and w.estado in ("cerrada", "cancelada"):
            continue
        out.append({"id": w.id, "ref": f"OT-{w.id:05d}", "activo": c.activos[w.asset_id].nombre,
                    "lugar": _lugar(db, w.asset_id, w.unit_id, w.zona), "titulo": w.titulo,
                    "descripcion": w.descripcion, "prioridad": w.prioridad, "estado": w.estado,
                    "fecha_apertura": w.fecha_apertura.isoformat(), "fecha_prevista": w.fecha_prevista.isoformat()
                    if w.fecha_prevista else None, "terminada": w.conf_mto_fecha.isoformat()
                    if w.conf_mto_fecha else None, "solucion": w.solucion, "persona": nombres.get(w.personal_id)})
    return out


@router.get("/partes")
def reports(desde: date | None = None, hasta: date | None = None, c: Ctx = Depends(ctx),
            db: Session = Depends(get_db)):
    """Líneas de los partes de trabajo validados que son suyas: sus OT y las actuaciones de su personal."""
    hasta = hasta or date.today()
    desde = desde or hasta - timedelta(days=31)
    suyas = {f"OT-{w.id:05d}" for w in _ordenes(db, c)}
    personas = {norm_empresa(p.nombre) for p in c.personal}
    out = []
    for r in db.scalars(select(WorkReport).where(WorkReport.asset_id.in_(c.activos), WorkReport.estado == "validado",
                                                 WorkReport.fecha >= desde, WorkReport.fecha <= hasta)
                        .order_by(WorkReport.fecha.desc())):
        lineas = [{k: x.get(k) for k in ("hora", "ref", "ubicacion", "trabajo", "detalle", "persona", "horas")}
                  for x in r.lineas or [] if x.get("ref") in suyas or norm_empresa(x.get("persona")) in personas]
        if lineas:
            out.append({"fecha": r.fecha.isoformat(), "area": r.area, "activo": c.activos[r.asset_id].nombre,
                        "validado_en": r.validado_en.isoformat() if r.validado_en else None, "lineas": lineas})
    return out


@router.get("/envios")
def dispatches(dias: int = 60, c: Ctx = Depends(ctx), db: Session = Depends(get_db)):
    if not c.staff_ids:
        return []
    nombres = {p.id: p.nombre for p in c.personal}
    desde = datetime.now() - timedelta(days=min(max(dias, 1), 366))
    return [{"id": e.id, "fecha": e.fecha.isoformat(), "persona": nombres.get(e.staff_id), "tipo": e.tipo,
             "canal": e.canal, "asunto": e.asunto, "texto": e.texto}
            for e in db.scalars(select(StaffDispatch).where(StaffDispatch.staff_id.in_(c.staff_ids),
                                                            StaffDispatch.fecha >= desde)
                                .order_by(StaffDispatch.fecha.desc()).limit(500))]


# --------------------------------------------------------------------------- documentos del colaborador
def _doc(x: ReceivedDocument, c: Ctx, nombres: dict) -> dict:
    return {"id": x.id, "activo": c.activos[x.asset_id].nombre if x.asset_id in c.activos else None,
            "tipo": x.tipo, "tipo_nombre": TIPOS_DOCUMENTO.get(x.tipo, x.tipo), "fecha": x.fecha.isoformat(),
            "referencia": x.referencia, "descripcion": x.descripcion, "nombre": x.nombre, "subido": x.subido.isoformat(),
            "revision": x.revision, "revision_nombre": REVISIONES.get(x.revision or "", ""),
            "revision_nota": x.revision_nota, "persona": nombres.get(x.staff_id),
            "ot": f"OT-{x.work_order_id:05d}" if x.work_order_id else None}


def _mio(db: Session, c: Ctx, did: int) -> ReceivedDocument:
    x = db.get(ReceivedDocument, did)
    if x is None or x.supplier_id != c.proveedor.id:
        raise HTTPException(404, "Documento no encontrado")
    return x


@router.get("/documentos")
def my_documents(c: Ctx = Depends(ctx), db: Session = Depends(get_db)):
    nombres = {p.id: p.nombre for p in c.personal}
    return [_doc(x, c, nombres) for x in db.scalars(select(ReceivedDocument).where(
        ReceivedDocument.supplier_id == c.proveedor.id).order_by(ReceivedDocument.subido.desc()).limit(1000))]


def _avisar_revision(db: Session, a: Asset, x: ReceivedDocument, proveedor: str) -> None:
    if not avisos.configurado():
        return
    destino = [u for u in [ausencias.recepcion_1(db, a)] if u] or ausencias.usuarios_con(db, a.id, "personal.autorizar")
    texto = (f"{proveedor} ha subido desde su portal: {TIPOS_DOCUMENTO.get(x.tipo, x.tipo)} "
             f"{x.referencia or x.nombre} ({a.nombre}). Revíselo en Documentos recibidos.")
    for u in destino:
        if u.email:
            try:
                avisos.enviar(u.email, "Documento de colaborador por revisar", texto,
                              avisos._html("Documento de colaborador", f"<p>{escape(texto)}</p>"))
            except Exception:  # noqa: BLE001 — el aviso no impide guardar el documento
                pass


@router.post("/documentos", status_code=201)
def upload(ficheros: list[UploadFile] = File(...), asset_id: int = Form(...), tipo: str = Form(...),
           fecha: date = Form(...), referencia: str | None = Form(None), descripcion: str | None = Form(None),
           staff_id: int | None = Form(None), work_order_id: int | None = Form(None),
           c: Ctx = Depends(ctx), scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if asset_id not in c.activos:
        raise HTTPException(403, "No trabaja en ese activo")
    if tipo not in TIPOS_COLABORADOR:
        bad_request(f"Tipo no válido. Opciones: {', '.join(TIPOS_COLABORADOR)}")
    if fecha > date.today():
        bad_request("La fecha del documento no puede ser futura")
    if staff_id is not None and staff_id not in c.staff_ids:
        bad_request("Esa persona no es de su empresa")
    if work_order_id is not None and work_order_id not in {w.id for w in _ordenes(db, c)}:
        bad_request("Esa orden de trabajo no es suya")
    if referencia and len(referencia) > 60 or descripcion and len(descripcion) > 1000:
        bad_request("Referencia o descripción demasiado largas")
    datos, mime, nombre = _fichero(ficheros)
    huella = documentos.huella(datos)
    igual = db.scalar(select(ReceivedDocument).where(ReceivedDocument.supplier_id == c.proveedor.id,
                                                     ReceivedDocument.sha256 == huella).limit(1))
    if igual:
        raise HTTPException(409, f"Ese mismo fichero ya lo subió el {igual.subido:%d/%m/%Y}")
    x = ReceivedDocument(asset_id=asset_id, tipo=tipo, fecha=fecha, emisor=c.proveedor.nombre,
                         referencia=referencia or None, descripcion=descripcion or None, nombre=nombre,
                         fichero=documentos.guardar(datos), mime=mime, tamano=len(datos), sha256=huella,
                         user_id=scope.user.id, supplier_id=c.proveedor.id, revision="pendiente", staff_id=staff_id,
                         work_order_id=work_order_id)
    db.add(x)
    db.flush()
    audit(db, scope.user, "subir_colaborador", "documento_recibido", x.id, {"tipo": tipo, "proveedor": c.proveedor.nombre})
    db.commit()
    _avisar_revision(db, c.activos[asset_id], x, c.proveedor.nombre)
    return _doc(x, c, {p.id: p.nombre for p in c.personal})


@router.get("/documentos/{did}/fichero")
def view(did: int, c: Ctx = Depends(ctx), scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    x = _mio(db, c, did)
    audit(db, scope.user, "ver", "documento_recibido", did)
    db.commit()
    return Response(documentos.leer(x.fichero), media_type=x.mime, headers={
        "Content-Disposition": f'inline; filename="{x.nombre}"', "Cache-Control": "private, no-store"})


@router.delete("/documentos/{did}")
def delete(did: int, c: Ctx = Depends(ctx), scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    x = _mio(db, c, did)
    if x.revision != "pendiente":
        bad_request("Ya está revisado: para cambiarlo, hable con Recepción 1")
    audit(db, scope.user, "borrar_colaborador", "documento_recibido", did, {"nombre": x.nombre})
    fichero = x.fichero
    db.delete(x)
    db.commit()
    documentos.borrar(fichero)
    return {"ok": True}


# --------------------------------------------------------------------------- revisión (recepción / dirección)
class RevisionIn(BaseModel):
    aceptar: bool
    nota: str | None = Field(default=None, max_length=300)


revision = APIRouter(prefix="/api/documentos-recibidos", tags=["colaborador"])


@revision.post("/{did}/revisar")
def review(did: int, data: RevisionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    x = get_or_404(db, ReceivedDocument, did)
    scope.require_asset("documentos.editar", x.asset_id)
    if x.revision is None:
        bad_request("Este documento no lo ha subido un colaborador")
    if x.tipo == "personal" and not ausencias.gestiona(db, scope, db.get(Asset, x.asset_id)):
        raise HTTPException(403, "La documentación del personal la revisan Recepción 1 y dirección")
    if not data.aceptar and not (data.nota or "").strip():
        bad_request("Indique el motivo del rechazo (lo verá el colaborador)")
    x.revision = "aceptado" if data.aceptar else "rechazado"
    x.revision_nota = (data.nota or "").strip() or None
    x.revisado_por, x.revisado_en = scope.user.id, datetime.now()
    audit(db, scope.user, "revisar", "documento_recibido", did, {"revision": x.revision, "nota": x.revision_nota})
    db.commit()
    return {"id": x.id, "revision": x.revision, "revision_nota": x.revision_nota}

