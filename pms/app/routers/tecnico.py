"""Pantalla del técnico (personal propio o subcontrata) para gestionar una orden de trabajo desde el enlace que
recibe por WhatsApp o correo: sin usuario ni contraseña, con un enlace firmado que caduca a los 30 días.

Registra la intervención (llegada y salida, trabajos o diagnóstico, materiales, observaciones, fotos), el estado al
finalizar y la firma táctil del técnico. Según el estado:
  A. resuelta            -> trabajo confirmado por mantenimiento («finalizada por el técnico»)
  B. pendiente_material  -> en pausa, alerta en el panel
  C. otra_visita         -> sigue abierta con la fecha propuesta para la siguiente visita
  D. escalar             -> (solo personal propio) en pausa y aviso en rojo: derivar a una subcontrata
  E. otro                -> en revisión, con la justificación obligatoria
Recepción o dirección reciben el aviso al momento y, al cerrar, dan la conformidad de la propiedad."""
import base64
from datetime import date, datetime
from pathlib import Path

from fastapi import (APIRouter, BackgroundTasks, Depends, File, HTTPException, Request, Response,
                     UploadFile)
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import adjuntos, avisos, documentos
from ..config import BASE_DIR
from ..database import get_db
from ..models import RESULTADOS_TECNICO, Asset, StaffMember, WorkOrder, WorkOrderAttachment, WorkOrderVisit
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404, scoped
from . import personal
from .mantenimiento import ABIERTAS, PAUSADAS, _subcontrata, requiere_limpieza, token_valido

publico = APIRouter(tags=["técnico (enlace)"])
router = APIRouter(prefix="/api/mantenimiento", tags=["mantenimiento"])
PAGINA = Path(BASE_DIR) / "static" / "tecnico.html"
FIRMA_MAX = 400 * 1024
FINALIZADAS = ("trabajo_realizado", "pendiente_cierre", "cerrada", "cancelada")
# Estado de la OT según el resultado del técnico
ESTADO_POR_RESULTADO = {"pendiente_material": "pendiente_material", "otra_visita": "pendiente_visita",
                        "escalar": "escalada", "otro": "revisar"}


def _orden(db: Session, wid: int, c: int, f: str) -> WorkOrder:
    w = db.get(WorkOrder, wid)
    if w is None or not token_valido(w, c, f):
        raise HTTPException(404, "Enlace no válido o caducado. Pida a recepción que le reenvíe la orden.")
    return w


def _abierta(db: Session, w: WorkOrder) -> WorkOrderVisit | None:
    return db.scalar(select(WorkOrderVisit).where(WorkOrderVisit.work_order_id == w.id,
                                                  WorkOrderVisit.enviado.is_(None)).order_by(WorkOrderVisit.id.desc()))


def _quien(db: Session, w: WorkOrder) -> dict:
    """Empresa y técnico que se proponen (autocompletado con lo que ya se sabe de la asignación)."""
    if w.asignacion == "propio" and w.personal_id:
        p = db.get(StaffMember, w.personal_id)
        a = db.get(Asset, w.asset_id)
        return {"empresa": p.empresa or a.company.nombre, "tecnico": p.nombre}
    if w.asignacion == "subcontrata":
        s = _subcontrata(db, w)
        return {"empresa": s.nombre if s else w.proveedor, "tecnico": (s.persona_contacto or "") if s else ""}
    return {"empresa": "", "tecnico": w.asignado_a or ""}


# --------------------------------------------------------------------------- página y datos (públicos)
@publico.get("/tecnico/{wid}", include_in_schema=False)
def page(wid: int):
    return HTMLResponse(PAGINA.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store",
                                                                     "Referrer-Policy": "no-referrer"})


@publico.get("/api/publico/ot/{wid}/datos")
def data(wid: int, c: int, f: str, db: Session = Depends(get_db)):
    w = _orden(db, wid, c, f)
    a = db.get(Asset, w.asset_id)
    abierta = _abierta(db, w)
    ultima = db.scalar(select(WorkOrderVisit).where(WorkOrderVisit.work_order_id == w.id,
                                                    WorkOrderVisit.enviado.is_not(None))
                       .order_by(WorkOrderVisit.enviado.desc()).limit(1))
    fotos = list(db.scalars(select(WorkOrderAttachment.id).where(
        WorkOrderAttachment.work_order_id == w.id, WorkOrderAttachment.tipo == "averia",
        WorkOrderAttachment.mime.like("image/%")).order_by(WorkOrderAttachment.id).limit(6)))
    return {
        "ot": {"id": w.id, "codigo": f"OT-{w.id:05d}", "titulo": w.titulo, "descripcion": w.descripcion,
               "prioridad": w.prioridad, "categoria": w.categoria, "estado": w.estado, "activo": a.nombre,
               "sociedad": a.company.nombre, "ubicacion": personal._lugar(db, w.asset_id, w.unit_id, w.zona),
               "direccion": ", ".join(x for x in (a.direccion, a.cp, a.municipio) if x),
               "fecha_prevista": w.fecha_prevista.isoformat() if w.fecha_prevista else None,
               "asignacion": w.asignacion},
        "propuesta": _quien(db, w), "permite_escalar": w.asignacion == "propio",
        "finalizada": w.estado in FINALIZADAS, "resultados": RESULTADOS_TECNICO,
        "en_curso": {"id": abierta.id, "llegada": abierta.llegada.isoformat() if abierta.llegada else None,
                     "empresa": abierta.empresa, "tecnico": abierta.tecnico} if abierta else None,
        "ultima": {"resultado": ultima.resultado, "resultado_nombre": RESULTADOS_TECNICO[ultima.resultado],
                   "enviado": ultima.enviado.isoformat(), "tecnico": ultima.tecnico} if ultima else None,
        "fotos": fotos,
    }


@publico.get("/api/publico/ot/{wid}/foto/{aid}")
def photo(wid: int, aid: int, c: int, f: str, db: Session = Depends(get_db)):
    w = _orden(db, wid, c, f)
    a = get_or_404(db, WorkOrderAttachment, aid)
    if a.work_order_id != w.id or not a.mime.startswith("image/"):
        raise HTTPException(404, "Foto no encontrada")
    return Response(documentos.leer(a.fichero), media_type=a.mime, headers={"Cache-Control": "private, max-age=3600"})


class InicioIn(BaseModel):
    empresa: str | None = Field(default=None, max_length=160)
    tecnico: str | None = Field(default=None, max_length=120)


def _editable(w: WorkOrder) -> None:
    if w.estado in FINALIZADAS:
        bad_request("Esta orden ya tiene el trabajo terminado o está cerrada. Si hay algo más, avise a recepción.")


@publico.post("/api/publico/ot/{wid}/iniciar")
def start(wid: int, c: int, f: str, body: InicioIn, request: Request, db: Session = Depends(get_db)):
    """«Iniciar trabajo»: anota la hora de llegada."""
    w = _orden(db, wid, c, f)
    _editable(w)
    v = _abierta(db, w)
    if v is None:
        v = WorkOrderVisit(work_order_id=w.id, ip=(request.client.host if request.client else None))
        db.add(v)
    if not v.llegada:
        v.llegada = datetime.now().replace(microsecond=0)
    v.empresa, v.tecnico = (body.empresa or v.empresa), (body.tecnico or v.tecnico)
    if w.estado in ("abierta", "asignada", "pendiente_visita"):
        w.estado = "en_curso"
    audit(db, None, "iniciar_trabajo", "orden_trabajo", w.id, {"tecnico": v.tecnico, "empresa": v.empresa})
    db.commit()
    return {"llegada": v.llegada.isoformat()}


@publico.post("/api/publico/ot/{wid}/fotos", status_code=201)
def upload_photos(wid: int, c: int, f: str, ficheros: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    """Fotos del trabajo terminado (o del material que falta)."""
    w = _orden(db, wid, c, f)
    _editable(w)
    if len(ficheros) > 6:
        bad_request("Máximo 6 fotos por envío")
    n = 0
    for x in ficheros:
        try:
            datos, mime, nombre = adjuntos.normalizar(x.file.read(adjuntos.TAM_MAX + 1), (x.filename or "foto")[-150:])
        except ValueError as e:
            bad_request(f"{x.filename}: {e}")
        db.add(WorkOrderAttachment(work_order_id=w.id, tipo="trabajo", nombre=nombre, descripcion="Foto del técnico",
                                   fichero=documentos.guardar(datos), mime=mime, tamano=len(datos),
                                   sha256=documentos.huella(datos)))
        n += 1
    db.commit()
    return {"fotos": n}


class Material(BaseModel):
    material: str = Field(min_length=1, max_length=160)
    cantidad: str | None = Field(default=None, max_length=30)


class FinIn(BaseModel):
    empresa: str = Field(min_length=2, max_length=160)
    tecnico: str = Field(min_length=2, max_length=120)
    llegada: datetime | None = None
    salida: datetime | None = None
    trabajos: str = Field(min_length=3, max_length=4000)
    materiales: list[Material] = Field(default_factory=list, max_length=40)
    observaciones: str | None = Field(default=None, max_length=2000)
    resultado: str
    fecha_propuesta: date | None = None
    justificacion: str | None = Field(default=None, max_length=2000)
    firma: str = Field(min_length=50)  # data:image/png;base64,...


def _png_firma(texto: str) -> bytes:
    try:
        datos = base64.b64decode(texto.split(",", 1)[-1], validate=True)
    except ValueError:
        bad_request("La firma no es válida: vuelva a firmar")
    if not datos.startswith(b"\x89PNG") or len(datos) > FIRMA_MAX:
        bad_request("La firma no es válida: vuelva a firmar")
    return datos


@publico.post("/api/publico/ot/{wid}/finalizar")
def finish(wid: int, c: int, f: str, body: FinIn, request: Request, tareas: BackgroundTasks,
           db: Session = Depends(get_db)):
    """«Enviar resultado»: datos de la intervención, estado al finalizar y firma del técnico."""
    w = _orden(db, wid, c, f)
    _editable(w)
    if body.resultado not in RESULTADOS_TECNICO:
        bad_request("Elija el estado al finalizar")
    if body.resultado == "escalar" and w.asignacion != "propio":
        bad_request("Derivar a una subcontrata solo lo puede pedir el personal propio")
    if body.resultado == "otra_visita" and not (body.fecha_propuesta and body.fecha_propuesta >= date.today()):
        bad_request("Proponga la fecha de la siguiente visita (hoy o posterior)")
    if body.resultado == "otro" and len((body.justificacion or "").strip()) < 5:
        bad_request("Describa el resultado o el motivo técnico del bloqueo")
    firma = _png_firma(body.firma)
    ahora = datetime.now().replace(microsecond=0)
    v = _abierta(db, w) or WorkOrderVisit(work_order_id=w.id)
    if v.id is None:
        db.add(v)
    v.llegada = body.llegada or v.llegada
    v.salida = body.salida or ahora
    if v.llegada and v.salida < v.llegada:
        bad_request("La hora de salida no puede ser anterior a la de llegada")
    v.empresa, v.tecnico = body.empresa.strip(), body.tecnico.strip()
    v.trabajos, v.observaciones = body.trabajos.strip(), (body.observaciones or "").strip() or None
    v.materiales = [m.model_dump() for m in body.materiales if m.material.strip()]
    v.resultado, v.fecha_propuesta = body.resultado, body.fecha_propuesta if body.resultado == "otra_visita" else None
    v.justificacion = (body.justificacion or "").strip() or None
    v.firma, v.enviado = documentos.guardar(firma), ahora
    v.ip = request.client.host if request.client else v.ip
    if body.resultado == "resuelta":  # A. finalizada por el técnico: confirma el trabajo de mantenimiento
        w.solucion = v.trabajos
        w.conf_mto_por, w.conf_mto_fecha = None, ahora
        w.estado = "trabajo_realizado" if requiere_limpieza(w) else "pendiente_cierre"
    else:
        w.estado = ESTADO_POR_RESULTADO[body.resultado]
        if body.resultado == "otra_visita":
            w.fecha_prevista = body.fecha_propuesta
    w.alerta_tecnico, w.alerta_fecha = body.resultado, ahora
    db.flush()
    audit(db, None, "intervencion", "orden_trabajo", w.id, {"intervencion": v.id, "tecnico": v.tecnico,
                                                            "empresa": v.empresa, "resultado": v.resultado})
    db.commit()
    tareas.add_task(avisos.resultado_tecnico, v.id)
    return {"ok": True, "resultado": RESULTADOS_TECNICO[v.resultado], "estado": w.estado}


# --------------------------------------------------------------------------- consulta en el PMS
def _visita_out(v: WorkOrderVisit) -> dict:
    d = v.to_dict(exclude=("firma", "ip"))
    d["resultado_nombre"] = RESULTADOS_TECNICO.get(v.resultado)
    d["minutos"] = round((v.salida - v.llegada).total_seconds() / 60) if v.llegada and v.salida else None
    d["con_firma"] = bool(v.firma)
    return d


@router.get("/ordenes/{wid}/intervenciones")
def list_visits(wid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    w = get_or_404(db, WorkOrder, wid)
    scope.require_asset("mantenimiento.ver", w.asset_id)
    return [_visita_out(v) for v in db.scalars(select(WorkOrderVisit).where(WorkOrderVisit.work_order_id == wid)
                                               .order_by(WorkOrderVisit.id))]


@router.get("/intervenciones/{iid}/firma")
def visit_signature(iid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    v = get_or_404(db, WorkOrderVisit, iid)
    scope.require_asset("mantenimiento.ver", db.get(WorkOrder, v.work_order_id).asset_id)
    if not v.firma:
        raise HTTPException(404, "Sin firma")
    return Response(documentos.leer(v.firma), media_type="image/png", headers={"Cache-Control": "private, no-store"})


@router.get("/resultados")
def recent_results(desde: datetime, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Resultados enviados por los técnicos desde `desde`: alerta sonora y visual en el PMS de recepción y
    dirección (se consulta cada minuto)."""
    ids = scope.asset_ids("mantenimiento.cerrar")
    if ids is not None and not ids:
        return []
    filas = db.execute(scoped(select(WorkOrderVisit, WorkOrder).join(WorkOrder, WorkOrder.id == WorkOrderVisit.work_order_id),
                              WorkOrder.asset_id, ids).where(WorkOrderVisit.enviado > desde)
                       .order_by(WorkOrderVisit.enviado)).all()
    return [{"ot": w.id, "asset_id": w.asset_id, "titulo": w.titulo, "tecnico": v.tecnico, "resultado": v.resultado,
             "resultado_nombre": RESULTADOS_TECNICO[v.resultado], "enviado": v.enviado.isoformat()} for v, w in filas]


def ot_panel(db: Session, scope: Scope) -> list[dict]:
    """Panel de control: órdenes con un resultado del técnico que aún nadie ha atendido."""
    ids = scope.asset_ids("mantenimiento.cerrar")
    if ids is not None and not ids:
        return []
    return [{"id": w.id, "asset_id": w.asset_id, "titulo": w.titulo, "resultado": w.alerta_tecnico,
             "resultado_nombre": RESULTADOS_TECNICO[w.alerta_tecnico], "desde": w.alerta_fecha.isoformat(),
             "pausada": w.alerta_tecnico in PAUSADAS}
            for w in db.scalars(scoped(select(WorkOrder), WorkOrder.asset_id, ids).where(
                WorkOrder.alerta_tecnico.is_not(None), WorkOrder.estado.in_(ABIERTAS)).order_by(WorkOrder.alerta_fecha))]

