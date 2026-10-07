"""Mantenimiento correctivo y preventivo (órdenes de trabajo y planes periódicos)."""
import hashlib
import hmac
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Response, UploadFile
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import adjuntos, avisos, documentos, firma_contrato, parte_pdf, planos
from . import personal
from ..config import settings
from ..database import get_db
from ..models import (Asset, EmailLog, PreventivePlan, StaffMember, Supplier, Unit, User, WorkOrder,
                      WorkOrderAttachment)
from ..schemas import PlanIn, PlanUpdate, WorkOrderIn, WorkOrderUpdate
from ..security import Scope, audit, get_scope
from ..utils import apply, bad_request, get_or_404, scoped

router = APIRouter(prefix="/api/mantenimiento", tags=["mantenimiento"])

# Estados editables a mano por mantenimiento
ESTADOS_TRABAJO = ("abierta", "asignada", "en_curso", "pendiente_material")
# Estados que fija el flujo de confirmaciones
ABIERTAS = ESTADOS_TRABAJO + ("trabajo_realizado", "pendiente_cierre")
ESTADOS_OT = set(ABIERTAS) | {"cerrada", "cancelada"}
# Datos de gestión que solo fija mantenimiento (quien solo abre el aviso no los rellena)
CAMPOS_GESTION = ("asignado_a", "proveedor", "coste_estimado", "fecha_prevista", "tipo", "asignacion", "personal_id",
                  "proveedor_id")

# Plantilla de preventivo legal / buenas prácticas. Revisar y ajustar periodicidades a cada instalación
# (potencia térmica, nº de ascensores, uso del edificio...) antes de darla por buena.
PLANTILLA_PREVENTIVO = [
    ("Mantenimiento preventivo instalaciones térmicas", "climatizacion",
     "RD 1027/2007 RITE IT 3 (periodicidad según potencia)", 30),
    ("Revisión trimestral sistemas PCI (extintores, BIE, detección, alumbrado emergencia)", "pci",
     "RD 513/2017 RIPCI Anexo II Tabla I", 90),
    ("Revisión anual PCI por empresa mantenedora habilitada", "pci", "RD 513/2017 RIPCI Anexo II Tabla II", 365),
    ("Control temperaturas ACS en acumuladores y puntos terminales", "acs", "RD 487/2022 legionela (PPCR)", 30),
    ("Limpieza y desinfección instalación ACS", "acs", "RD 487/2022 legionela (PPCR)", 365),
    ("Mantenimiento ascensores por empresa conservadora", "ascensores", "RD 355/2024 ITC AEM 1", 30),
    ("Inspección periódica BT por OCA (verificar plazo 5/10 años según uso)", "electricidad",
     "RD 842/2002 REBT ITC-BT-05", 1825),
    ("Revisión cuadros eléctricos zonas comunes (termografía)", "electricidad", "Buenas prácticas", 180),
    ("Revisión grupo de presión y bombas", "fontaneria", "Buenas prácticas", 180),
    ("Revisión cubiertas, canalones y bajantes", "cubiertas", "Buenas prácticas (antes de otoño)", 365),
    ("Tratamiento control de plagas (DDD)", "plagas", "Buenas prácticas / sanidad", 90),
]


TIPOS_PREVENTIVOS = ("preventivo", "normativo")


def requiere_limpieza(w: WorkOrder) -> bool:
    """Las OT preventivas/normativas de zonas comunes (sin unidad) no pasan por limpieza."""
    return not (w.unit_id is None and w.tipo in TIPOS_PREVENTIVOS)


def _wo_out(w: WorkOrder, db: Session, n_adjuntos: int | None = None) -> dict:
    d = w.to_dict()
    d["n_adjuntos"] = n_adjuntos if n_adjuntos is not None else db.scalar(
        select(func.count()).select_from(WorkOrderAttachment).where(WorkOrderAttachment.work_order_id == w.id))
    d["requiere_limpieza"] = requiere_limpieza(w)
    quien = (db.get(StaffMember, w.personal_id) if w.asignacion == "propio" and w.personal_id
             else _subcontrata(db, w) if w.asignacion == "subcontrata" else None)
    d["contacto"] = {"nombre": quien.nombre, "email": quien.email,
                     "whatsapp": bool(firma_contrato.movil_whatsapp(quien.telefono or ""))} if quien else None
    d["unidad"] = db.get(Unit, w.unit_id).codigo if w.unit_id else None
    d["zona_nombre"] = planos.zonas(db.get(Asset, w.asset_id).codigo).get(w.zona, w.zona) if w.zona else None
    for campo in ("abierta_por", "conf_mto_por", "conf_limpieza_por", "cerrada_por"):
        uid = getattr(w, campo)
        d[campo + "_nombre"] = db.get(User, uid).nombre if uid else None
    return d


def _open_order(db: Session, wid: int) -> WorkOrder:
    w = get_or_404(db, WorkOrder, wid)
    if w.estado not in ABIERTAS:
        bad_request("La orden ya está cerrada o cancelada")
    return w


# --------------------------------------------------------------------------- órdenes de trabajo
@router.get("/ordenes")
def list_orders(asset_id: int | None = None, estado: str | None = None, abiertas: bool = False,
                tipo: str | None = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = scope.asset_ids("mantenimiento.ver")
    stmt = scoped(select(WorkOrder), WorkOrder.asset_id, ids)
    if asset_id:
        stmt = stmt.where(WorkOrder.asset_id == asset_id)
    if estado:
        stmt = stmt.where(WorkOrder.estado == estado)
    if abiertas:
        stmt = stmt.where(WorkOrder.estado.in_(ABIERTAS))
    if tipo:
        stmt = stmt.where(WorkOrder.tipo == tipo)
    stmt = stmt.order_by(WorkOrder.fecha_apertura.desc(), WorkOrder.id.desc())
    filas = list(db.scalars(stmt.limit(2000)))
    n = dict(db.execute(select(WorkOrderAttachment.work_order_id, func.count()).where(
        WorkOrderAttachment.work_order_id.in_([w.id for w in filas] or [-1]))
        .group_by(WorkOrderAttachment.work_order_id)).all())
    return [_wo_out(w, db, n.get(w.id, 0)) for w in filas]


def _subcontrata(db: Session, w: WorkOrder) -> Supplier | None:
    """Ficha de Proveedores de la subcontrata (por su id o, si se dio de alta después, por su nombre)."""
    s = db.get(Supplier, w.proveedor_id) if w.proveedor_id else None
    if s is None and w.proveedor:
        s = db.scalar(select(Supplier).where(func.lower(Supplier.nombre) == w.proveedor.strip().lower()))
    return s


def _asignar(db: Session, w: WorkOrder) -> None:
    """Personal propio (ficha de Personal) o subcontrata (ficha de Proveedores, por su id o por su nombre)."""
    if w.asignacion == "propio":
        p = db.get(StaffMember, w.personal_id) if w.personal_id else None
        if w.personal_id and (p is None or p.area != "mantenimiento" or p.asset_id not in (None, w.asset_id)):
            bad_request("Elija una persona de mantenimiento de este activo (Mantenimiento → Personal)")
        w.proveedor_id = None
        if p:
            w.asignado_a = p.nombre[:120]
    elif w.asignacion == "subcontrata":
        s = _subcontrata(db, w)
        w.personal_id = None
        w.proveedor_id = s.id if s else None
        if s:
            w.proveedor = s.nombre[:160]
        if w.proveedor:
            w.asignado_a = f"Subcontrata: {w.proveedor}"[:120]


@router.post("/ordenes", status_code=201)
def create_order(data: WorkOrderIn, tareas: BackgroundTasks, scope: Scope = Depends(get_scope),
                 db: Session = Depends(get_db)):
    gestiona = scope.can_asset("mantenimiento.editar", data.asset_id)
    if not (gestiona or scope.can_asset("mantenimiento.abrir", data.asset_id)):
        raise HTTPException(403, "Sin permiso para abrir órdenes de trabajo en este activo")
    asset = get_or_404(db, Asset, data.asset_id)
    if data.zona:
        if data.unit_id:
            bad_request("Una incidencia es de un apartamento o de una zona común, no de ambos")
        if data.zona not in planos.zonas(asset.codigo):
            bad_request("Zona común no válida para este activo")
    unit = None
    if data.unit_id:
        unit = get_or_404(db, Unit, data.unit_id)
        if unit.asset_id != data.asset_id:
            bad_request("La unidad no pertenece al activo indicado")
    valores = data.model_dump()
    if not gestiona:
        for campo in CAMPOS_GESTION:
            valores.pop(campo, None)
    w = WorkOrder(**valores, abierta_por=scope.user.id)
    _asignar(db, w)
    db.add(w)
    if unit and data.bloquea_unidad and unit.estado in ("disponible", "pendiente_limpieza"):
        unit.estado = "mantenimiento"
    db.flush()
    audit(db, scope.user, "crear", "orden_trabajo", w.id, {"titulo": w.titulo, "prioridad": w.prioridad})
    db.commit()
    if w.prioridad == "urgente":
        tareas.add_task(avisos.ot_urgente, w.id, scope.user.id)
    return _wo_out(w, db)


@router.put("/ordenes/{wid}")
def update_order(wid: int, data: WorkOrderUpdate, tareas: BackgroundTasks, scope: Scope = Depends(get_scope),
                 db: Session = Depends(get_db)):
    w = get_or_404(db, WorkOrder, wid)
    scope.require_asset("mantenimiento.editar", w.asset_id)
    if w.estado not in ESTADOS_TRABAJO:
        bad_request("La orden ya tiene el trabajo confirmado; si hay que rehacerlo, debe rechazarse")
    if data.estado is not None and data.estado not in ESTADOS_TRABAJO:
        bad_request(f"Estado no válido. Opciones: {', '.join(ESTADOS_TRABAJO)}")
    ch = apply(w, data)
    if {"asignacion", "personal_id", "proveedor_id", "proveedor"} & set(ch):
        _asignar(db, w)
    audit(db, scope.user, "editar", "orden_trabajo", wid, ch)
    db.commit()
    if "prioridad" in ch and w.prioridad == "urgente":
        tareas.add_task(avisos.ot_urgente, w.id, scope.user.id)
    return _wo_out(w, db)


# --------------------------------------------------------------------------- fotos y documentos de la OT
def _adjunto_out(a: WorkOrderAttachment, usuario: str | None) -> dict:
    d = a.to_dict(exclude=("fichero", "sha256"))
    d["tipo_nombre"] = adjuntos.TIPOS_ADJUNTO.get(a.tipo, a.tipo)
    d["usuario"] = usuario
    return d


@router.get("/ordenes/{wid}/adjuntos")
def list_attachments(wid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    w = get_or_404(db, WorkOrder, wid)
    scope.require_asset("mantenimiento.ver", w.asset_id)
    filas = db.execute(select(WorkOrderAttachment, User.nombre).outerjoin(User, User.id == WorkOrderAttachment.user_id)
                       .where(WorkOrderAttachment.work_order_id == wid).order_by(WorkOrderAttachment.id)).all()
    return [_adjunto_out(a, n) for a, n in filas]


@router.post("/ordenes/{wid}/adjuntos", status_code=201)
def upload_attachments(wid: int, ficheros: list[UploadFile] = File(...), tipo: str = Form("averia"),
                       descripcion: str | None = Form(None), scope: Scope = Depends(get_scope),
                       db: Session = Depends(get_db)):
    """Sube fotos (se reducen y orientan solas) o PDF. Recepción y limpieza pueden subir fotos de la avería;
    fotos del trabajo, certificados, facturas y presupuestos son de mantenimiento."""
    w = get_or_404(db, WorkOrder, wid)
    if tipo not in adjuntos.TIPOS_ADJUNTO:
        bad_request("Tipo de adjunto no válido")
    if not scope.can_asset("mantenimiento.editar", w.asset_id):
        if tipo not in adjuntos.TIPOS_AVISO or not scope.can_asset("mantenimiento.abrir", w.asset_id):
            raise HTTPException(403, "Sin permiso para adjuntar este tipo de documento")
    if len(ficheros) > 10:
        bad_request("Máximo 10 ficheros por envío")
    nuevos = []
    for f in ficheros:
        datos = f.file.read(adjuntos.TAM_MAX + 1)
        try:
            datos, mime, nombre = adjuntos.normalizar(datos, (f.filename or "fichero")[-150:])
        except ValueError as e:
            bad_request(f"{f.filename}: {e}")
        a = WorkOrderAttachment(work_order_id=wid, tipo=tipo, nombre=nombre, descripcion=descripcion,
                                fichero=documentos.guardar(datos), mime=mime, tamano=len(datos),
                                sha256=documentos.huella(datos), user_id=scope.user.id)
        db.add(a)
        nuevos.append(a)
    db.flush()
    audit(db, scope.user, "adjuntar", "orden_trabajo", wid, {"tipo": tipo, "adjuntos": [a.id for a in nuevos]})
    db.commit()
    return [_adjunto_out(a, scope.user.nombre) for a in nuevos]


def _adjunto(db: Session, scope: Scope, aid: int, perm: str) -> tuple[WorkOrderAttachment, WorkOrder]:
    a = get_or_404(db, WorkOrderAttachment, aid)
    w = db.get(WorkOrder, a.work_order_id)
    scope.require_asset(perm, w.asset_id)
    return a, w


@router.get("/adjuntos/{aid}")
def view_attachment(aid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a, _ = _adjunto(db, scope, aid, "mantenimiento.ver")
    return Response(documentos.leer(a.fichero), media_type=a.mime, headers={
        "Content-Disposition": f'inline; filename="{a.nombre}"', "Cache-Control": "private, max-age=3600"})


@router.delete("/adjuntos/{aid}")
def delete_attachment(aid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Lo borra mantenimiento, o quien lo subió mientras la OT siga abierta."""
    a, w = _adjunto(db, scope, aid, "mantenimiento.ver")
    propio = a.user_id == scope.user.id and w.estado in ABIERTAS
    if not (propio or scope.can_asset("mantenimiento.editar", w.asset_id)):
        raise HTTPException(403, "Sin permiso para borrar este adjunto")
    documentos.borrar(a.fichero)
    audit(db, scope.user, "borrar_adjunto", "orden_trabajo", w.id, {"adjunto": aid, "nombre": a.nombre})
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.get("/ordenes/{wid}/parte")
def work_order_sheet(wid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Parte de incidencia en PDF para entregar a la subcontrata (con las fotos de la avería)."""
    w = get_or_404(db, WorkOrder, wid)
    scope.require_asset("mantenimiento.ver", w.asset_id)
    pdf = parte(db, w)
    audit(db, scope.user, "imprimir_parte", "orden_trabajo", wid)
    db.commit()
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="Parte_OT-{w.id:05d}.pdf"'})


def parte(db: Session, w: WorkOrder) -> bytes:
    asset = db.get(Asset, w.asset_id)
    fotos = [documentos.leer(a.fichero) for a in db.scalars(
        select(WorkOrderAttachment).where(WorkOrderAttachment.work_order_id == w.id, WorkOrderAttachment.tipo == "averia",
                                          WorkOrderAttachment.mime == "image/jpeg")
        .order_by(WorkOrderAttachment.id).limit(4))]
    abierta = db.get(User, w.abierta_por).nombre if w.abierta_por else None
    pdf = parte_pdf.generar(w, asset, asset.company, db.get(Unit, w.unit_id) if w.unit_id else None, abierta, fotos,
                            w.categoria.replace("_", " ").capitalize(),
                            planos.zonas(asset.codigo).get(w.zona) if w.zona else None)
    return pdf


@router.post("/ordenes/{wid}/enviar")
def send_order(wid: int, data: personal.SendIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Envía la OT a las personas de mantenimiento elegidas: por correo, con el parte en PDF (fotos de la avería y
    hoja para anotar el trabajo); por WhatsApp, el resumen. Si la OT estaba abierta pasa a «asignada»."""
    w = _open_order(db, wid)
    if not (scope.can_asset("mantenimiento.editar", w.asset_id) or scope.can_asset("mantenimiento.cerrar", w.asset_id)):
        raise HTTPException(403, "Sin permiso para enviar órdenes de trabajo en este activo")
    personas = personal.destinatarios(db, data.personal_ids, w.asset_id, data.canal)
    asunto, texto, html = mensaje_ot(db, w, data.nota)
    adj = [(f"Parte_OT-{w.id:05d}.pdf", parte(db, w), "application/pdf")] if data.canal == "email" else None
    res = personal.despachar(db, personas, data.canal, f"ot_enviada:{w.id}", asunto, texto, html, adj)
    personal.registrar_envio_ot(w, res, scope.user.nombre)
    if any(r["ok"] for r in res):
        if not w.asignado_a:
            w.asignado_a = ", ".join(p.nombre for p in personas)[:120]
        if w.estado == "abierta":
            w.estado = "asignada"
    audit(db, scope.user, "enviar", "orden_trabajo", wid, {"canal": data.canal, "personal": [p.nombre for p in personas]})
    db.commit()
    return {"enviados": res, "orden": _wo_out(w, db)}


# --------------------------------------------------------------------------- envío a quien la tiene asignada
DIAS_ENLACE = 15


def _firma(wid: int, caduca: int) -> str:
    return hmac.new(settings.secret_key.encode(), f"ot:{wid}:{caduca}".encode(), hashlib.sha256).hexdigest()[:32]


def enlace_parte(wid: int) -> str | None:
    """Enlace de descarga del parte en PDF para WhatsApp (firmado, caduca a los 15 días)."""
    if not settings.url:
        return None
    caduca = int(time.time()) + DIAS_ENLACE * 86400
    return f"{settings.url}/api/publico/ot/{wid}?c={caduca}&f={_firma(wid, caduca)}"


publico = APIRouter(prefix="/api/publico", tags=["público"])


@publico.get("/ot/{wid}")
def public_sheet(wid: int, c: int, f: str, db: Session = Depends(get_db)):
    if c < time.time() or not hmac.compare_digest(f, _firma(wid, c)):
        raise HTTPException(404, "Enlace no válido o caducado. Pida la orden de trabajo de nuevo.")
    w = get_or_404(db, WorkOrder, wid)
    return Response(parte(db, w), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Parte_OT-{w.id:05d}.pdf"'})


class EnvioAsignadoIn(BaseModel):
    canales: list[Literal["email", "whatsapp"]] = Field(min_length=1)
    copia_mantenimiento: bool = True  # copia al personal de mantenimiento propio
    nota: str | None = Field(default=None, max_length=1000)


def _destino(nombre: str, email: str | None, telefono: str | None, canales, asunto, texto, html, adj, db, clave,
             obligatorio: bool) -> list[dict]:
    out = []
    for canal in canales:
        if canal == "email":
            if not email:
                if obligatorio:
                    bad_request(f"{nombre} no tiene correo electrónico en su ficha")
                continue
            if not avisos.configurado():
                if obligatorio:
                    bad_request("El correo no está configurado en el servidor: envíela por WhatsApp")
                continue
            r = {"nombre": nombre, "canal": "email", "destino": email}
            try:
                avisos.enviar(email, asunto, texto, html, adj)
                r["ok"] = True
            except Exception as e:  # noqa: BLE001
                r["ok"], r["error"] = False, str(e)[:200]
            db.add(EmailLog(clave=clave, tipo="ot_enviada", destinatario=email, asunto=asunto[:200], ok=r["ok"],
                            error=r.get("error")))
            out.append(r)
        else:
            movil = firma_contrato.movil_whatsapp(telefono or "")
            if not movil:
                if obligatorio:
                    bad_request(f"{nombre} no tiene un móvil válido para WhatsApp en su ficha")
                continue
            out.append({"nombre": nombre, "canal": "whatsapp", "destino": movil, "ok": True,
                        "whatsapp": f"https://wa.me/{movil}?text={quote(texto)}"})
    return out


@router.post("/ordenes/{wid}/enviar-asignado")
def send_assigned(wid: int, data: EnvioAsignadoIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Envía la OT a quien la tiene asignada: personal propio (WhatsApp y/o correo) o la subcontrata (correo con el
    parte en PDF y/o WhatsApp con enlace al PDF, según los datos de su ficha de proveedor). Con copia al personal de
    mantenimiento propio para que sepa qué trabajos se van a hacer."""
    w = _open_order(db, wid)
    if not (scope.can_asset("mantenimiento.editar", w.asset_id) or scope.can_asset("mantenimiento.cerrar", w.asset_id)):
        raise HTTPException(403, "Sin permiso para enviar órdenes de trabajo en este activo")
    asunto, texto, html = mensaje_ot(db, w, data.nota)
    url = enlace_parte(w.id)
    texto_wa = texto + (f"\n\nParte en PDF: {url}" if url else "")
    adj = [(f"Parte_OT-{w.id:05d}.pdf", parte(db, w), "application/pdf")]
    clave = f"ot_enviada:{w.id}"
    if w.asignacion == "propio":
        p = db.get(StaffMember, w.personal_id) if w.personal_id else None
        if p is None:
            bad_request("Indique en la orden qué persona de mantenimiento la realiza")
        res = _destino(p.nombre, p.email, p.telefono, data.canales, asunto, texto_wa, html, adj, db, clave, True)
        asignado = p.id
    elif w.asignacion == "subcontrata":
        s = _subcontrata(db, w)
        if s is None:
            bad_request("La subcontrata no está en Proveedores: dela de alta con su correo o teléfono")
        w.proveedor_id = s.id
        res = _destino(s.nombre, s.email, s.telefono, data.canales, asunto, texto_wa, html, adj, db, clave, True)
        asignado = None
    else:
        bad_request("Indique en la orden si la realiza personal propio o una subcontrata")
    if data.copia_mantenimiento:
        cab = f"COPIA para su conocimiento (la realiza {w.asignado_a}). "
        for p in db.scalars(select(StaffMember).where(StaffMember.area == "mantenimiento", StaffMember.activo.is_(True),
                                                      (StaffMember.asset_id.is_(None)) | (StaffMember.asset_id == w.asset_id))):
            if p.id == asignado:
                continue
            canal = ["email"] if p.email and avisos.configurado() else ["whatsapp"]  # la copia, por donde se pueda
            for r in _destino(p.nombre, p.email, p.telefono, canal, f"Copia · {asunto}"[:200], cab + texto_wa,
                              html.replace("<h2", f"<p><b>{cab}</b></p><h2", 1), adj, db, clave, False):
                res.append({**r, "copia": True})
    personal.registrar_envio_ot(w, res, scope.user.nombre)
    if any(r["ok"] and not r.get("copia") for r in res) and w.estado == "abierta":
        w.estado = "asignada"
    audit(db, scope.user, "enviar", "orden_trabajo", wid, {"asignado": w.asignado_a, "canales": data.canales,
                                                           "destinos": [r["destino"] for r in res]})
    db.commit()
    return {"enviados": res, "orden": _wo_out(w, db)}


def mensaje_ot(db: Session, w: WorkOrder, nota: str | None = None) -> tuple[str, str, str]:
    a = db.get(Asset, w.asset_id)
    lugar = personal._lugar(db, w.asset_id, w.unit_id, w.zona)
    filas = [("Orden", f"OT-{w.id:05d}"), ("Activo", a.nombre), ("Ubicación", lugar), ("Avería / trabajo", w.titulo),
             ("Prioridad", w.prioridad.upper() if w.prioridad == "urgente" else w.prioridad),
             ("Instalación", w.categoria), ("Descripción", w.descripcion or "—")]
    if w.fecha_prevista:
        filas.append(("Fecha prevista", f"{w.fecha_prevista:%d/%m/%Y}"))
    if w.bloquea_unidad:
        filas.append(("Unidad", "Bloqueada hasta terminar el trabajo"))
    if nota:
        filas.append(("Nota", nota))
    asunto = f"{'URGENTE · ' if w.prioridad == 'urgente' else ''}OT-{w.id:05d} · {a.nombre} · {lugar}: {w.titulo}"[:200]
    texto = "\n".join(f"{k}: {v}" for k, v in filas) + "\n\nAl terminar, avise a recepción indicando el trabajo realizado."
    html = avisos._html(f"Orden de trabajo OT-{w.id:05d}", avisos._tabla([], [[k, v] for k, v in filas])
                        + "<p>Se adjunta el parte en PDF. Al terminar, avise a recepción indicando el trabajo "
                          "realizado.</p>")
    return asunto, texto, html


class ConfirmWork(BaseModel):
    solucion: str = Field(min_length=3)
    coste_real: float | None = Field(default=None, ge=0)


@router.post("/ordenes/{wid}/confirmar-mantenimiento")
def confirm_work(wid: int, data: ConfirmWork, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Mantenimiento da el trabajo por realizado."""
    w = _open_order(db, wid)
    scope.require_asset("mantenimiento.editar", w.asset_id)
    if w.conf_mto_por:
        bad_request("El trabajo ya está confirmado por mantenimiento")
    w.solucion = data.solucion
    if data.coste_real is not None:
        w.coste_real = data.coste_real
    w.conf_mto_por, w.conf_mto_fecha = scope.user.id, datetime.now()
    w.estado = "trabajo_realizado" if requiere_limpieza(w) else "pendiente_cierre"
    audit(db, scope.user, "confirmar_mantenimiento", "orden_trabajo", wid, data.model_dump())
    db.commit()
    return _wo_out(w, db)


@router.post("/ordenes/{wid}/confirmar-limpieza")
def confirm_cleaning(wid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Limpieza revisa la unidad / zona tras el trabajo y la da por correcta."""
    w = _open_order(db, wid)
    scope.require_asset("limpieza.confirmar_ot", w.asset_id)
    if not requiere_limpieza(w):
        bad_request("Las OT preventivas de zonas comunes no requieren confirmación de limpieza")
    if not w.conf_mto_por:
        bad_request("Mantenimiento aún no ha confirmado el trabajo")
    if w.conf_limpieza_por:
        bad_request("Ya está confirmada por limpieza")
    w.conf_limpieza_por, w.conf_limpieza_fecha = scope.user.id, datetime.now()
    w.estado = "pendiente_cierre"
    audit(db, scope.user, "confirmar_limpieza", "orden_trabajo", wid)
    db.commit()
    return _wo_out(w, db)


class Reject(BaseModel):
    motivo: str = Field(min_length=3)


@router.post("/ordenes/{wid}/rechazar")
def reject_work(wid: int, data: Reject, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Limpieza o recepción devuelven la orden a mantenimiento (trabajo no conforme)."""
    w = _open_order(db, wid)
    puede_limpieza = requiere_limpieza(w) and scope.can_asset("limpieza.confirmar_ot", w.asset_id)
    if not (puede_limpieza or scope.can_asset("mantenimiento.cerrar", w.asset_id)):
        raise HTTPException(403, "Sin permiso para rechazar el trabajo")
    if not w.conf_mto_por:
        bad_request("No hay trabajo confirmado que rechazar")
    w.conf_mto_por = w.conf_mto_fecha = w.conf_limpieza_por = w.conf_limpieza_fecha = None
    w.estado = "en_curso"
    w.descripcion = f"{w.descripcion or ''}\n[Rechazada {date.today():%d/%m/%Y} por {scope.user.nombre}] {data.motivo}".strip()
    audit(db, scope.user, "rechazar", "orden_trabajo", wid, data.model_dump())
    db.commit()
    return _wo_out(w, db)


class CloseOrder(BaseModel):
    cancelar: bool = False
    motivo: str | None = None


def _release_unit(db: Session, w: WorkOrder, cancelada: bool) -> None:
    if not (w.unit_id and w.bloquea_unidad):
        return
    unit = db.get(Unit, w.unit_id)
    others = db.scalar(select(WorkOrder.id).where(WorkOrder.unit_id == unit.id, WorkOrder.id != w.id,
                                                  WorkOrder.bloquea_unidad, WorkOrder.estado.in_(ABIERTAS)))
    if unit.estado == "mantenimiento" and not others:
        # cerrada: limpieza ya confirmó la unidad -> disponible; cancelada: hay que revisarla
        unit.estado = "pendiente_limpieza" if cancelada else "disponible"


@router.post("/ordenes/{wid}/cerrar")
def close_order(wid: int, data: CloseOrder, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Recepción cierra la orden cuando mantenimiento y limpieza la han confirmado (o la cancela)."""
    w = _open_order(db, wid)
    scope.require_asset("mantenimiento.cerrar", w.asset_id)
    if data.cancelar:
        if not data.motivo:
            bad_request("Indique el motivo de la cancelación")
        w.estado = "cancelada"
        w.solucion = f"{w.solucion or ''}\n[Cancelada] {data.motivo}".strip()
    else:
        if not w.conf_mto_por:
            bad_request("Falta la confirmación de mantenimiento")
        if requiere_limpieza(w) and not w.conf_limpieza_por:
            bad_request("Falta la confirmación de limpieza")
        w.estado = "cerrada"
    w.fecha_cierre = date.today()
    w.cerrada_por = scope.user.id
    _release_unit(db, w, cancelada=data.cancelar)
    audit(db, scope.user, w.estado, "orden_trabajo", wid, data.model_dump())
    db.commit()
    return _wo_out(w, db)


# --------------------------------------------------------------------------- planes preventivos
@router.get("/planes")
def list_plans(asset_id: int | None = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    ids = scope.asset_ids("mantenimiento.ver")
    stmt = scoped(select(PreventivePlan), PreventivePlan.asset_id, ids)
    if asset_id:
        stmt = stmt.where(PreventivePlan.asset_id == asset_id)
    return [p.to_dict() for p in db.scalars(stmt.order_by(PreventivePlan.proxima_fecha))]


@router.post("/planes", status_code=201)
def create_plan(data: PlanIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_asset("mantenimiento.editar", data.asset_id)
    get_or_404(db, Asset, data.asset_id)
    p = PreventivePlan(**data.model_dump())
    db.add(p)
    db.flush()
    audit(db, scope.user, "crear", "plan_preventivo", p.id, {"titulo": p.titulo})
    db.commit()
    return p.to_dict()


@router.put("/planes/{pid}")
def update_plan(pid: int, data: PlanUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = get_or_404(db, PreventivePlan, pid)
    scope.require_asset("mantenimiento.editar", p.asset_id)
    ch = apply(p, data)
    audit(db, scope.user, "editar", "plan_preventivo", pid, ch)
    db.commit()
    return p.to_dict()


class TemplateReq(BaseModel):
    asset_id: int
    primera_fecha: date | None = None


@router.post("/planes/plantilla", status_code=201)
def load_template(data: TemplateReq, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Carga la plantilla normativa en un activo (omite planes con el mismo título ya existentes)."""
    scope.require_asset("mantenimiento.editar", data.asset_id)
    get_or_404(db, Asset, data.asset_id)
    existing = set(db.scalars(select(PreventivePlan.titulo).where(PreventivePlan.asset_id == data.asset_id)))
    start = data.primera_fecha or date.today() + timedelta(days=7)
    n = 0
    for titulo, cat, norma, dias in PLANTILLA_PREVENTIVO:
        if titulo in existing:
            continue
        db.add(PreventivePlan(asset_id=data.asset_id, titulo=titulo, categoria=cat, normativa=norma,
                              periodicidad_dias=dias, proxima_fecha=start))
        n += 1
    audit(db, scope.user, "cargar_plantilla", "plan_preventivo", None, {"asset_id": data.asset_id, "creados": n})
    db.commit()
    return {"creados": n}


class GenerateReq(BaseModel):
    dias_antelacion: int = Field(default=7, ge=0, le=90)
    asset_id: int | None = None


@router.post("/planes/generar")
def generate_orders(data: GenerateReq, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Crea las OT preventivas cuyo vencimiento cae dentro de la antelación indicada y avanza la próxima fecha."""
    ids = scope.asset_ids("mantenimiento.editar")
    if data.asset_id:
        scope.require_asset("mantenimiento.editar", data.asset_id)
        ids = {data.asset_id}
    limite = date.today() + timedelta(days=data.dias_antelacion)
    plans = db.scalars(scoped(select(PreventivePlan), PreventivePlan.asset_id, ids).where(
        PreventivePlan.activo, PreventivePlan.proxima_fecha <= limite))
    created = 0
    for p in plans:
        open_wo = db.scalar(select(WorkOrder.id).where(WorkOrder.plan_id == p.id, WorkOrder.estado.in_(ABIERTAS)))
        if open_wo:
            continue
        db.add(WorkOrder(asset_id=p.asset_id, plan_id=p.id, tipo="preventivo", categoria=p.categoria,
                         prioridad="media", titulo=p.titulo, descripcion=p.normativa, proveedor=p.proveedor,
                         fecha_prevista=p.proxima_fecha))
        p.proxima_fecha = p.proxima_fecha + timedelta(days=p.periodicidad_dias)
        created += 1
    audit(db, scope.user, "generar_preventivo", "orden_trabajo", None, {"creadas": created})
    db.commit()
    return {"creadas": created}
