"""Mantenimiento correctivo y preventivo (órdenes de trabajo y planes periódicos)."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import MODALIDADES_RESERVA, Asset, PreventivePlan, Unit, WorkOrder
from ..schemas import PlanIn, PlanUpdate, WorkOrderIn, WorkOrderUpdate
from ..security import Scope, audit, get_scope
from ..utils import apply, bad_request, get_or_404, scoped

router = APIRouter(prefix="/api/mantenimiento", tags=["mantenimiento"])

ABIERTAS = ("abierta", "asignada", "en_curso", "pendiente_material")
ESTADOS_OT = set(ABIERTAS) | {"cerrada", "cancelada"}

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


def _wo_out(w: WorkOrder, db: Session) -> dict:
    d = w.to_dict()
    d["unidad"] = db.get(Unit, w.unit_id).codigo if w.unit_id else None
    return d


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
    return [_wo_out(w, db) for w in db.scalars(stmt.limit(2000))]


@router.post("/ordenes", status_code=201)
def create_order(data: WorkOrderIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_asset("mantenimiento.editar", data.asset_id)
    get_or_404(db, Asset, data.asset_id)
    unit = None
    if data.unit_id:
        unit = get_or_404(db, Unit, data.unit_id)
        if unit.asset_id != data.asset_id:
            bad_request("La unidad no pertenece al activo indicado")
    w = WorkOrder(**data.model_dump())
    db.add(w)
    if unit and data.bloquea_unidad and unit.estado in ("disponible", "pendiente_limpieza"):
        unit.estado = "mantenimiento"
    db.flush()
    audit(db, scope.user, "crear", "orden_trabajo", w.id, {"titulo": w.titulo, "prioridad": w.prioridad})
    db.commit()
    return _wo_out(w, db)


@router.put("/ordenes/{wid}")
def update_order(wid: int, data: WorkOrderUpdate, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    w = get_or_404(db, WorkOrder, wid)
    scope.require_asset("mantenimiento.editar", w.asset_id)
    if data.estado is not None and data.estado not in ESTADOS_OT:
        bad_request("Estado no válido")
    if data.estado in ("cerrada", "cancelada"):
        bad_request("Use la acción 'cerrar' para cerrar o cancelar la orden")
    ch = apply(w, data)
    audit(db, scope.user, "editar", "orden_trabajo", wid, ch)
    db.commit()
    return _wo_out(w, db)


class CloseOrder(BaseModel):
    solucion: str | None = None
    coste_real: float | None = Field(default=None, ge=0)
    cancelar: bool = False


@router.post("/ordenes/{wid}/cerrar")
def close_order(wid: int, data: CloseOrder, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    w = get_or_404(db, WorkOrder, wid)
    scope.require_asset("mantenimiento.editar", w.asset_id)
    if w.estado not in ABIERTAS:
        bad_request("La orden ya está cerrada")
    w.estado = "cancelada" if data.cancelar else "cerrada"
    w.fecha_cierre = date.today()
    if data.solucion is not None:
        w.solucion = data.solucion
    if data.coste_real is not None:
        w.coste_real = data.coste_real
    if w.unit_id and w.bloquea_unidad:
        unit = db.get(Unit, w.unit_id)
        others = db.scalar(select(WorkOrder.id).where(WorkOrder.unit_id == unit.id, WorkOrder.id != w.id,
                                                      WorkOrder.bloquea_unidad, WorkOrder.estado.in_(ABIERTAS)))
        if unit.estado == "mantenimiento" and not others:
            unit.estado = "pendiente_limpieza" if unit.asset.modalidad in MODALIDADES_RESERVA else "disponible"
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
