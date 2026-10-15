"""Mantenimiento correctivo y preventivo (órdenes de trabajo y planes periódicos)."""
import hashlib
import hmac
import secrets
from html import escape
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Response, UploadFile
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import acceso_ot, adjuntos, avisos, documentos, firma_contrato, parte_pdf, planos
from ..acceso_ot import texto as acceso_texto_ot
from . import personal
from ..config import settings
from ..database import get_db
from ..models import (RESULTADOS_TECNICO, Asset, EmailLog, PreventivePlan, Reservation, StaffMember, Supplier, Unit,
                      User, WorkOrder, WorkOrderAttachment, WorkOrderVisit)
from ..schemas import AccesoIn, PlanIn, PlanUpdate, WorkOrderIn, WorkOrderUpdate
from ..security import Scope, audit, get_scope
from ..utils import apply, bad_request, get_or_404, scoped

router = APIRouter(prefix="/api/mantenimiento", tags=["mantenimiento"])

# Estados editables a mano por mantenimiento (los tres últimos los fija también el técnico desde su enlace)
ESTADOS_TRABAJO = ("abierta", "asignada", "en_curso", "pendiente_material", "pendiente_visita", "escalada", "revisar")
# Resultados del técnico que dejan la OT en pausa: se recuerdan cada día hasta que alguien actúa
PAUSADAS = ("pendiente_material", "otra_visita", "escalar", "otro")
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
    ("Inspección periódica ascensores por OCA", "ascensores",
     "RD 355/2024 ITC AEM 1 (2 años en pública concurrencia; verificar según uso y antigüedad)", 730),
    ("Inspección periódica PCI por OCA", "pci", "RD 513/2017 RIPCI art. 22 (cada 10 años)", 3650),
    ("Inspección periódica eficiencia energética instalación térmica por OCA", "climatizacion",
     "RD 1027/2007 RITE IT 4 (generadores > 70 kW cada 5 años; verificar potencia)", 1825),
    ("Inspección periódica centro de transformación por OCA (solo si hay CT propio)", "electricidad",
     "RD 337/2014 ITC-RAT 23 (cada 3 años)", 1095),
    ("Inspección periódica instalación receptora de gas", "general",
     "RD 919/2006 ITC-ICG 07 (cada 5 años, por la distribuidora)", 1825),
    ("Revisión cuadros eléctricos zonas comunes (termografía)", "electricidad", "Buenas prácticas", 180),
    ("Revisión grupo de presión y bombas", "fontaneria", "Buenas prácticas", 180),
    ("Revisión cubiertas, canalones y bajantes", "cubiertas", "Buenas prácticas (antes de otoño)", 365),
    ("Tratamiento control de plagas (DDD)", "plagas", "Buenas prácticas / sanidad", 90),
]


TIPOS_PREVENTIVOS = ("preventivo", "normativo")


alojado = acceso_ot.alojado  # se importa desde otros módulos


def acceso_texto(db: Session, w: WorkOrder, interno: bool = False) -> str | None:
    """Cómo se entra en un apartamento con huésped (ver app/acceso_ot.py)."""
    return acceso_texto_ot(db, w, interno)


def atendida(w: WorkOrder) -> None:
    """Recepción o dirección han actuado sobre el resultado del técnico: deja de avisarse y de recordarse."""
    w.alerta_tecnico = w.alerta_fecha = None


# Flujo (1.70): recepción abre la OT y la asigna. El personal propio la cierra él mismo (firma, fecha, foto de la
# reparación y tiempo); la subcontrata la da por finalizada (datos, al menos una foto y tiempo) y la cierran el Director
# Técnico o recepción. Limpieza ya no confirma: al cerrarla, la unidad queda pendiente de limpieza.
REABRIR_DIAS = 7  # días en los que recepción o el Director Técnico pueden reabrir una OT cerrada


def minutos_visitas(visitas) -> int:
    """Tiempo de trabajo de una OT: suma de llegada → salida de sus intervenciones."""
    return sum(round((v.salida - v.llegada).total_seconds() / 60) for v in visitas
               if v.llegada and v.salida and v.salida > v.llegada)


def minutos_ot(db: Session, w: WorkOrder) -> int:
    return minutos_visitas(db.scalars(select(WorkOrderVisit).where(WorkOrderVisit.work_order_id == w.id)))


def fotos_trabajo(db: Session, w: WorkOrder) -> int:
    """Fotos de la reparación (del técnico o subidas como «trabajo terminado»)."""
    return db.scalar(select(func.count()).select_from(WorkOrderAttachment).where(
        WorkOrderAttachment.work_order_id == w.id, WorkOrderAttachment.tipo == "trabajo",
        WorkOrderAttachment.mime.like("image/%"))) or 0


def fotos_antes(db: Session, w: WorkOrder) -> int:
    """Fotos del «antes» (la avería tal como estaba: las sube recepción al abrir, vienen del parte de estado o las
    hace el técnico al llegar)."""
    return db.scalar(select(func.count()).select_from(WorkOrderAttachment).where(
        WorkOrderAttachment.work_order_id == w.id, WorkOrderAttachment.tipo == "averia",
        WorkOrderAttachment.mime.like("image/%"))) or 0


TIPOS_FOTO_ANTES = ("correctivo", "mejora")  # OT con foto del «antes» obligatoria (no preventivo ni normativo)
FALTA_FOTO_ANTES = "Falta la foto del «antes»: cómo estaba la avería antes de la reparación"


def exigir_finalizacion(db: Session, w: WorkOrder) -> None:
    """Para dar por finalizada o cerrar una OT: tiempo de trabajo, al menos una foto de la reparación y, en las
    correctivas y de mejora abiertas desde la 1.70, la foto del «antes»."""
    if w.exige_foto_antes and not fotos_antes(db, w):
        bad_request(FALTA_FOTO_ANTES)
    if minutos_ot(db, w) <= 0:
        bad_request("Falta el tiempo de trabajo: indique la hora de llegada y la de salida")
    if not fotos_trabajo(db, w):
        bad_request("Falta al menos una foto de la reparación")


def cerrar_ot(db: Session, w: WorkOrder, user_id: int | None, cancelada: bool = False,
              motivo: str | None = None) -> None:
    """Cierra (o cancela) la orden: libera la unidad y cierra sus partes de estado."""
    w.estado = "cancelada" if cancelada else "cerrada"
    if not cancelada:
        w.conformidad_en = datetime.now()  # usuario y fecha de quien la cierra
    w.fecha_cierre = date.today()
    w.cerrada_por = user_id
    atendida(w)
    _release_unit(db, w)
    from .partes_estado import cerrar_partes
    cerrar_partes(db, w, motivo)


class _Lote:
    """Lo que necesita cada fila de la lista de OT, cargado de golpe para todas (unas 10 consultas en total en vez de
    una docena por orden)."""

    def __init__(self, db: Session, filas: list[WorkOrder]):
        ids = [w.id for w in filas] or [-1]
        self.n_adjuntos = dict(db.execute(select(WorkOrderAttachment.work_order_id, func.count()).where(
            WorkOrderAttachment.work_order_id.in_(ids)).group_by(WorkOrderAttachment.work_order_id)).all())
        uids = {getattr(w, c) for w in filas for c in ("abierta_por", "conf_mto_por", "cerrada_por",
                                                       "acceso_user_id")} - {None}
        self.usuarios = dict(db.execute(select(User.id, User.nombre).where(User.id.in_(uids or {-1}))).all())
        self.unidades = dict(db.execute(select(Unit.id, Unit.codigo).where(
            Unit.id.in_({w.unit_id for w in filas if w.unit_id} or {-1}))).all())
        self.activos = dict(db.execute(select(Asset.id, Asset.codigo).where(
            Asset.id.in_({w.asset_id for w in filas} or {-1}))).all())
        self.personal = {x.id: x for x in db.scalars(select(StaffMember).where(
            StaffMember.id.in_({w.personal_id for w in filas if w.personal_id} or {-1})))}
        self.proveedores = {x.id: x for x in db.scalars(select(Supplier).where(
            Supplier.id.in_({w.proveedor_id for w in filas if w.proveedor_id} or {-1})))}
        self.fotos = dict(db.execute(select(WorkOrderAttachment.work_order_id, func.count()).where(
            WorkOrderAttachment.work_order_id.in_(ids), WorkOrderAttachment.tipo == "trabajo",
            WorkOrderAttachment.mime.like("image/%")).group_by(WorkOrderAttachment.work_order_id)).all())
        self.fotos_antes = dict(db.execute(select(WorkOrderAttachment.work_order_id, func.count()).where(
            WorkOrderAttachment.work_order_id.in_(ids), WorkOrderAttachment.tipo == "averia",
            WorkOrderAttachment.mime.like("image/%")).group_by(WorkOrderAttachment.work_order_id)).all())
        nombres = {w.proveedor.strip().lower() for w in filas if w.proveedor and not w.proveedor_id}
        self.por_nombre = {x.nombre.lower(): x for x in db.scalars(select(Supplier).where(
            func.lower(Supplier.nombre).in_(nombres or {"-"})))}
        self.visitas: dict[int, WorkOrderVisit] = {}
        todas: dict[int, list] = {}
        for v in db.scalars(select(WorkOrderVisit).where(WorkOrderVisit.work_order_id.in_(ids))
                            .order_by(WorkOrderVisit.enviado.desc())):
            todas.setdefault(v.work_order_id, []).append(v)
            if v.enviado is not None:
                self.visitas.setdefault(v.work_order_id, v)
        self.minutos = {k: minutos_visitas(x) for k, x in todas.items()}
        abiertas = [w for w in filas if w.unit_id and w.estado in ABIERTAS]
        self.acceso = acceso_ot.Contexto(db, {w.unit_id for w in abiertas},
                                         max((w.fecha_prevista for w in abiertas if w.fecha_prevista), default=None))

    def subcontrata(self, w: WorkOrder) -> Supplier | None:
        s = self.proveedores.get(w.proveedor_id) if w.proveedor_id else None
        return s or (self.por_nombre.get(w.proveedor.strip().lower()) if w.proveedor else None)


def _wo_out(w: WorkOrder, db: Session, n_adjuntos: int | None = None, lote: _Lote | None = None) -> dict:
    d = w.to_dict()
    if lote:
        n_adjuntos = lote.n_adjuntos.get(w.id, 0)
    d["n_adjuntos"] = n_adjuntos if n_adjuntos is not None else db.scalar(
        select(func.count()).select_from(WorkOrderAttachment).where(WorkOrderAttachment.work_order_id == w.id))
    d["minutos"] = lote.minutos.get(w.id, 0) if lote else minutos_ot(db, w)
    d["fotos_trabajo"] = lote.fotos.get(w.id, 0) if lote else fotos_trabajo(db, w)
    d["reabrible"] = bool(w.estado == "cerrada" and w.fecha_cierre
                          and w.fecha_cierre >= date.today() - timedelta(days=REABRIR_DIAS))
    d["sin_cerrar_48h"] = bool(w.estado == "pendiente_cierre" and w.conf_mto_fecha
                               and w.conf_mto_fecha <= datetime.now() - timedelta(hours=48))
    d["falta_foto_antes"] = bool(w.exige_foto_antes and w.estado not in ("cerrada", "cancelada")
                                 and not (lote.fotos_antes.get(w.id, 0) if lote else fotos_antes(db, w)))
    if w.asignacion == "propio" and w.personal_id:
        quien = lote.personal.get(w.personal_id) if lote else db.get(StaffMember, w.personal_id)
    elif w.asignacion == "subcontrata":
        quien = lote.subcontrata(w) if lote else _subcontrata(db, w)
    else:
        quien = None
    d["contacto"] = {"nombre": quien.nombre, "email": quien.email,
                     "whatsapp": bool(firma_contrato.movil_whatsapp(quien.telefono or ""))} if quien else None
    d["unidad"] = (lote.unidades.get(w.unit_id) if lote else db.get(Unit, w.unit_id).codigo) if w.unit_id else None
    if w.zona:
        codigo = lote.activos.get(w.asset_id) if lote else db.get(Asset, w.asset_id).codigo
        d["zona_nombre"] = planos.zonas(codigo).get(w.zona, w.zona)
    else:
        d["zona_nombre"] = None
    for campo in ("abierta_por", "conf_mto_por", "cerrada_por"):
        uid = getattr(w, campo)
        d[campo + "_nombre"] = (lote.usuarios.get(uid) if lote else db.get(User, uid).nombre) if uid else None
    ultima = lote.visitas.get(w.id) if lote else db.scalar(
        select(WorkOrderVisit).where(WorkOrderVisit.work_order_id == w.id, WorkOrderVisit.enviado.is_not(None))
        .order_by(WorkOrderVisit.enviado.desc()).limit(1))
    d["tecnico"] = {"nombre": ultima.tecnico, "empresa": ultima.empresa, "resultado": ultima.resultado,
                    "resultado_nombre": RESULTADOS_TECNICO.get(ultima.resultado), "enviado": ultima.enviado.isoformat(),
                    "fecha_propuesta": ultima.fecha_propuesta.isoformat() if ultima.fecha_propuesta else None} \
        if ultima else None
    if w.conf_mto_fecha and not w.conf_mto_por and ultima:  # confirmado por el técnico desde su enlace
        d["conf_mto_por_nombre"] = f"{ultima.tecnico} (enlace)"
    d["alerta_nombre"] = RESULTADOS_TECNICO.get(w.alerta_tecnico)
    ctx = lote.acceso if lote else None
    d["acceso_texto"] = acceso_texto_ot(db, w, True, ctx, lote.usuarios if lote else None)
    d["acceso_estado"] = acceso_ot.estado(db, w, ABIERTAS, ctx)
    from ..automatismos import SIN_RESPUESTA, limite
    lim = limite(w)  # plazo de respuesta por prioridad (urgente 4 h, alta 24 h)
    d["plazo"] = {"limite": lim.isoformat(timespec="minutes"), "vencido": w.estado in SIN_RESPUESTA and ultima is None
                  and lim < datetime.now()} if lim and w.estado in SIN_RESPUESTA else None
    if w.asignacion == "subcontrata" and isinstance(quien, Supplier) and cae_vencida(quien):
        d["cae_vencida"] = quien.cae_vence.isoformat()
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
    lote = _Lote(db, filas)
    return [_wo_out(w, db, lote=lote) for w in filas]


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
            bad_request("Elija una persona de mantenimiento de este activo (Personal → Fichas del personal)")
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


def cae_vencida(s: Supplier | None, dia: date | None = None) -> bool:
    return bool(s and s.cae_vence and s.cae_vence < (dia or date.today()))


def _comprobar_cae(db: Session, w: WorkOrder) -> None:
    """Subcontrata con la documentación CAE/PRL vencida: no se le asignan órdenes hasta que la renueve."""
    if w.asignacion == "subcontrata":
        s = _subcontrata(db, w)
        if cae_vencida(s):
            bad_request(f"{s.nombre} tiene la documentación CAE/PRL vencida desde el {s.cae_vence:%d/%m/%Y}. "
                        "Pídale la documentación actualizada y anote la nueva fecha en su ficha de Proveedores")


@router.get("/acceso")
def unit_access(unit_id: int, hasta: date | None = None, scope: Scope = Depends(get_scope),
                db: Session = Depends(get_db)):
    """Al abrir una OT: si el apartamento tiene un cliente dentro, hay que indicar cómo se entra (llave de recepción
    con su permiso, o contactar con él: se da su teléfono); si llega uno pronto, se avisa para hacerla antes."""
    u = get_or_404(db, Unit, unit_id)
    if not (scope.can_asset("mantenimiento.abrir", u.asset_id) or scope.can_asset("mantenimiento.ver", u.asset_id)):
        raise HTTPException(403, "Sin permiso en este activo")
    return acceso_ot.situacion(db, u.id, hasta)


@router.post("/ordenes", status_code=201)
def create_order(data: WorkOrderIn, tareas: BackgroundTasks, scope: Scope = Depends(get_scope),
                 db: Session = Depends(get_db)):
    # las abren recepción y dirección; mantenimiento y limpieza avisan con un parte de estado
    if not scope.can_asset("mantenimiento.abrir", data.asset_id):
        raise HTTPException(403, "Sin permiso para abrir órdenes de trabajo en este activo: "
                                 "registre un parte de estado y recepción generará la orden")
    gestiona = scope.can_asset("mantenimiento.editar", data.asset_id)
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
    valores = data.model_dump(exclude={"parte_estado_id", "acceso", "acceso_autoriza", "acceso_medio"})
    # recepción (cierra OT) también asigna a personal propio o subcontrata; tipo y coste son de mantenimiento
    asigna = gestiona or scope.can_asset("mantenimiento.cerrar", data.asset_id)
    for campo in CAMPOS_GESTION:
        if not gestiona and (campo in ("coste_estimado", "tipo") or not asigna):
            valores.pop(campo, None)
    w = WorkOrder(**valores, abierta_por=scope.user.id)
    w.exige_foto_antes = (w.tipo or "correctivo") in TIPOS_FOTO_ANTES
    _asignar(db, w)
    _comprobar_cae(db, w)
    try:
        acceso_ot.registrar(db, w, data.acceso, data.acceso_autoriza, data.acceso_medio, scope.user)
    except ValueError as e:
        bad_request(str(e))
    db.add(w)
    parte = None
    if data.parte_estado_id:
        from .partes_estado import vincular_ot
        parte = vincular_ot(db, scope, data.parte_estado_id, w)
    if unit and w.bloquea_unidad and unit.estado in ("disponible", "pendiente_limpieza"):
        unit.estado = "mantenimiento"
    db.flush()
    if parte:
        from .partes_estado import copiar_fotos
        copiar_fotos(db, parte, w, scope.user.id)
    audit(db, scope.user, "crear", "orden_trabajo", w.id, {"titulo": w.titulo, "prioridad": w.prioridad})
    db.commit()
    if w.prioridad == "urgente":
        tareas.add_task(avisos.ot_urgente, w.id, scope.user.id)
    return _wo_out(w, db)


class AsignarIn(BaseModel):
    asignacion: Literal["propio", "subcontrata"]
    personal_id: int | None = None
    proveedor_id: int | None = None
    proveedor: str | None = Field(default=None, max_length=160)
    fecha_prevista: date | None = None


@router.post("/ordenes/{wid}/asignar")
def assign_order(wid: int, data: AsignarIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Recepción o dirección técnica asignan la OT a personal propio o a una subcontrata (también para derivarla
    cuando el personal propio lo pide)."""
    w = _open_order(db, wid)
    if not (scope.can_asset("mantenimiento.editar", w.asset_id) or scope.can_asset("mantenimiento.cerrar", w.asset_id)):
        raise HTTPException(403, "Sin permiso para asignar órdenes de trabajo")
    if w.conf_mto_fecha:
        bad_request("El trabajo ya está confirmado: si hay que rehacerlo, rechácelo antes")
    antes = _quien(w)
    w.asignacion, w.personal_id, w.proveedor_id = data.asignacion, data.personal_id, data.proveedor_id
    w.proveedor = (data.proveedor or "").strip() or None
    if data.asignacion == "propio" and not data.personal_id:
        bad_request("Elija la persona de mantenimiento")
    if data.asignacion == "subcontrata" and not (data.proveedor_id or w.proveedor):
        bad_request("Elija la subcontrata")
    _asignar(db, w)
    _comprobar_cae(db, w)
    if antes != _quien(w) and antes[0]:  # cambia quién la hace: el enlace del anterior deja de valer
        revocar_enlace(w)
    if data.fecha_prevista:
        w.fecha_prevista = data.fecha_prevista
    if w.estado in ("escalada", "revisar", "abierta"):
        w.estado = "asignada"
    atendida(w)
    audit(db, scope.user, "asignar", "orden_trabajo", wid, {"asignado": w.asignado_a, "asignacion": w.asignacion})
    db.commit()
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
    antes = _quien(w)
    ch = apply(w, data)
    if {"asignacion", "personal_id", "proveedor_id", "proveedor"} & set(ch):
        _asignar(db, w)
        _comprobar_cae(db, w)
        if antes != _quien(w) and antes[0]:
            revocar_enlace(w)
    if {"estado", "fecha_prevista", "asignacion", "personal_id", "proveedor_id", "proveedor"} & set(ch):
        atendida(w)
    audit(db, scope.user, "editar", "orden_trabajo", wid, ch)
    db.commit()
    if "prioridad" in ch and w.prioridad == "urgente":
        tareas.add_task(avisos.ot_urgente, w.id, scope.user.id)
    return _wo_out(w, db)


@router.put("/ordenes/{wid}/acceso")
def set_access(wid: int, data: AccesoIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Anota o cambia cómo se entra (también recepción, p. ej. al hacer el check-in de un cliente con OT abierta)."""
    w = get_or_404(db, WorkOrder, wid)
    if not any(scope.can_asset(p, w.asset_id) for p in ("mantenimiento.editar", "mantenimiento.abrir", "reservas.editar")):
        raise HTTPException(403, "Sin permiso en este activo")
    if w.estado not in ABIERTAS:
        bad_request("La orden ya está cerrada")
    try:
        acceso_ot.registrar(db, w, data.acceso, data.autoriza, data.medio, scope.user)
    except ValueError as e:
        bad_request(str(e))
    audit(db, scope.user, "acceso_ot", "orden_trabajo", wid,
          {"acceso": w.acceso, "autoriza": w.acceso_autoriza, "medio": w.acceso_medio, "reserva": w.acceso_reserva_id})
    db.commit()
    return _wo_out(w, db)


@router.get("/ordenes/{wid}")
def get_work_order(wid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    w = get_or_404(db, WorkOrder, wid)
    scope.require_asset("mantenimiento.ver", w.asset_id)
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
    # la última intervención enviada por el técnico rellena la parte 2 (con su firma) y el cierre, la conformidad
    v = db.scalar(select(WorkOrderVisit).where(WorkOrderVisit.work_order_id == w.id, WorkOrderVisit.enviado.is_not(None))
                  .order_by(WorkOrderVisit.enviado.desc()).limit(1))
    intervencion = None
    if v:
        intervencion = {"empresa": v.empresa, "tecnico": v.tecnico, "llegada": v.llegada, "salida": v.salida,
                        "trabajos": v.trabajos, "materiales": v.materiales or [], "observaciones": v.observaciones,
                        "resultado": RESULTADOS_TECNICO.get(v.resultado), "firma": documentos.leer(v.firma) if v.firma else None}
    conformidad = (f"{db.get(User, w.cerrada_por).nombre} · {w.conformidad_en:%d/%m/%Y %H:%M} (usuario del PMS)"
                   if w.conformidad_en and w.cerrada_por else None)
    pdf = parte_pdf.generar(w, asset, asset.company, db.get(Unit, w.unit_id) if w.unit_id else None, abierta, fotos,
                            w.categoria.replace("_", " ").capitalize(),
                            planos.zonas(asset.codigo).get(w.zona) if w.zona else None, intervencion, conformidad,
                            acceso_texto(db, w))
    return pdf


@router.post("/ordenes/{wid}/enviar")
def send_order(wid: int, data: personal.SendIn, request: Request, scope: Scope = Depends(get_scope),
               db: Session = Depends(get_db)):
    """Envía la OT a las personas de mantenimiento elegidas: por correo, con el parte en PDF (fotos de la avería y
    hoja para anotar el trabajo); por WhatsApp, el resumen. Si la OT estaba abierta pasa a «asignada»."""
    w = _open_order(db, wid)
    if not (scope.can_asset("mantenimiento.editar", w.asset_id) or scope.can_asset("mantenimiento.cerrar", w.asset_id)):
        raise HTTPException(403, "Sin permiso para enviar órdenes de trabajo en este activo")
    personas = personal.destinatarios(db, data.personal_ids, w.asset_id, data.canal)
    asunto, texto, html = mensaje_ot(db, w, data.nota, enlace_tecnico(w, str(request.base_url)))
    if data.canal == "whatsapp":
        texto = mensaje_whatsapp(db, w, str(request.base_url), data.nota)
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
DIAS_ENLACE = 30


def _firma(wid: int, caduca: int, version: int = 0) -> str:
    msg = f"ot:{wid}:{caduca}" + (f":{version}" if version else "")  # versión 0: los enlaces ya enviados siguen valiendo
    return hmac.new(settings.secret_key.encode(), msg.encode(), hashlib.sha256).hexdigest()[:32]


def _token(w: WorkOrder) -> str:
    caduca = int(time.time()) + DIAS_ENLACE * 86400
    return f"c={caduca}&f={_firma(w.id, caduca, w.enlace_version or 0)}"


def token_valido(w: WorkOrder, c: int, f: str) -> bool:
    return c >= time.time() and hmac.compare_digest(f, _firma(w.id, c, w.enlace_version or 0))


def enlace_tecnico(w: WorkOrder, base: str | None = None) -> str | None:
    """Enlace único y firmado a la pantalla del técnico (móvil, sin usuario ni contraseña). Deja de valer al
    reasignar la orden o al revocarlo («Revocar enlace»)."""
    base = settings.url or base
    return f"{base.rstrip('/')}/tecnico/{w.id}?{_token(w)}" if base else None


def revocar_enlace(w: WorkOrder) -> None:
    w.enlace_version = (w.enlace_version or 0) + 1


def _quien(w: WorkOrder) -> tuple:
    return (w.asignacion, w.personal_id, w.proveedor_id, (w.proveedor or "").strip().lower())


publico = APIRouter(prefix="/api/publico", tags=["público"])


@publico.get("/ot/{wid}")
def public_sheet(wid: int, c: int, f: str, db: Session = Depends(get_db)):
    w = db.get(WorkOrder, wid)
    if w is None or not token_valido(w, c, f):
        raise HTTPException(404, "Enlace no válido o caducado. Pida la orden de trabajo de nuevo.")
    return Response(parte(db, w), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="Parte_OT-{w.id:05d}.pdf"'})


class EnvioAsignadoIn(BaseModel):
    canales: list[Literal["email", "whatsapp"]] = Field(min_length=1)
    copia_mantenimiento: bool = True  # copia al personal de mantenimiento propio
    nota: str | None = Field(default=None, max_length=1000)


def _destino(nombre: str, email: str | None, telefono: str | None, canales, asunto, texto, html, adj, db, clave,
             obligatorio: bool) -> list[dict]:
    if obligatorio:  # se comprueba todo antes de enviar nada: así no sale un correo y luego un error
        for canal in canales:
            if canal == "email" and not email:
                bad_request(f"{nombre} no tiene correo electrónico en su ficha")
            if canal == "email" and not avisos.configurado():
                bad_request("El correo no está configurado en el servidor: envíela por WhatsApp")
            if canal != "email" and not firma_contrato.movil_whatsapp(telefono or ""):
                bad_request(f"{nombre} no tiene un móvil válido para WhatsApp en su ficha")
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
def send_assigned(wid: int, data: EnvioAsignadoIn, request: Request, scope: Scope = Depends(get_scope),
                  db: Session = Depends(get_db)):
    """Envía la OT a quien la tiene asignada: personal propio (WhatsApp y/o correo) o la subcontrata (correo con el
    parte en PDF y/o WhatsApp con enlace al PDF, según los datos de su ficha de proveedor). Con copia al personal de
    mantenimiento propio para que sepa qué trabajos se van a hacer."""
    w = _open_order(db, wid)
    if not (scope.can_asset("mantenimiento.editar", w.asset_id) or scope.can_asset("mantenimiento.cerrar", w.asset_id)):
        raise HTTPException(403, "Sin permiso para enviar órdenes de trabajo en este activo")
    asunto, texto, html = mensaje_ot(db, w, data.nota, enlace_tecnico(w, str(request.base_url)))
    texto_wa = mensaje_whatsapp(db, w, str(request.base_url), data.nota)
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
        _comprobar_cae(db, w)
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


def mensaje_whatsapp(db: Session, w: WorkOrder, base: str | None, nota: str | None = None) -> str:
    """«INVERSIETE S.A.: Tiene una nueva orden de trabajo OT-00021 en Suite Florida. Acceda aquí para gestionarla:
    <enlace>» (la sociedad gestora del activo, el número de OT y el activo cambian en cada orden)."""
    a = db.get(Asset, w.asset_id)
    lugar = personal._lugar(db, w.asset_id, w.unit_id, w.zona)
    texto = (f"{a.company.nombre}: Tiene una nueva orden de trabajo OT-{w.id:05d} en {a.nombre}"
             f"{' · URGENTE' if w.prioridad == 'urgente' else ''}. {lugar}: {w.titulo}.")
    if acceso_texto(db, w):
        texto += f" Acceso: {acceso_texto(db, w)}."
    if nota:
        texto += f" Nota: {nota}."
    enlace = enlace_tecnico(w, base)
    return texto + (f" Acceda aquí para gestionarla: {enlace}" if enlace else "")


def mensaje_ot(db: Session, w: WorkOrder, nota: str | None = None, enlace: str | None = None) -> tuple[str, str, str]:
    a = db.get(Asset, w.asset_id)
    lugar = personal._lugar(db, w.asset_id, w.unit_id, w.zona)
    filas = [("Orden", f"OT-{w.id:05d}"), ("Activo", a.nombre), ("Ubicación", lugar), ("Avería / trabajo", w.titulo),
             ("Prioridad", w.prioridad.upper() if w.prioridad == "urgente" else w.prioridad),
             ("Instalación", w.categoria), ("Descripción", w.descripcion or "—")]
    if w.fecha_prevista:
        filas.append(("Fecha prevista", f"{w.fecha_prevista:%d/%m/%Y}"))
    if w.bloquea_unidad:
        filas.append(("Unidad", "Bloqueada hasta terminar el trabajo"))
    if acceso_texto(db, w):
        filas.append(("Acceso", acceso_texto(db, w)))
    if nota:
        filas.append(("Nota", nota))
    asunto = f"{'URGENTE · ' if w.prioridad == 'urgente' else ''}OT-{w.id:05d} · {a.nombre} · {lugar}: {w.titulo}"[:200]
    enlace = enlace or enlace_tecnico(w)
    if enlace:
        texto = "\n".join(f"{k}: {v}" for k, v in filas) + (
            f"\n\nAcceda aquí para gestionarla (llegada, trabajos, materiales y firma): {enlace}")
        pie = (f'<p><a href="{escape(enlace)}" style="background:#c9a45a;color:#0e0e10;padding:10px 18px;'
               'border-radius:8px;text-decoration:none;font-weight:600">Gestionar la orden de trabajo</a></p>'
               "<p>Desde el móvil, sin usuario ni contraseña: indique llegada y salida, trabajos, materiales, el "
               "estado al finalizar y firme. Se adjunta además el parte en PDF como respaldo.</p>")
    else:
        texto = "\n".join(f"{k}: {v}" for k, v in filas) + "\n\nAl terminar, avise a recepción indicando el trabajo realizado."
        pie = "<p>Se adjunta el parte en PDF. Al terminar, avise a recepción indicando el trabajo realizado.</p>"
    html = avisos._html(f"Orden de trabajo OT-{w.id:05d}", avisos._tabla([], [[k, v] for k, v in filas]) + pie)
    return asunto, texto, html


class ConfirmWork(BaseModel):
    solucion: str = Field(min_length=3)
    coste_real: float | None = Field(default=None, ge=0)
    llegada: datetime  # tiempo de trabajo: obligatorio para finalizar
    salida: datetime
    firma: str | None = Field(default=None, max_length=600_000)  # data:image/png;base64 (obligatoria al personal propio)


def _visita_pms(db: Session, w: WorkOrder, scope: Scope, data, empresa: str, tecnico: str,
                firma_png: bytes | None) -> WorkOrderVisit:
    """Intervención anotada desde el PMS (no desde el enlace del técnico): llegada, salida, trabajos y firma."""
    if data.salida <= data.llegada:
        bad_request("La hora de salida tiene que ser posterior a la de llegada")
    if data.salida > datetime.now() + timedelta(minutes=10):
        bad_request("La hora de salida no puede ser futura")
    v = WorkOrderVisit(work_order_id=w.id, empresa=empresa[:160], tecnico=tecnico[:120],
                       llegada=data.llegada.replace(tzinfo=None, microsecond=0),
                       salida=data.salida.replace(tzinfo=None, microsecond=0), trabajos=w.solucion,
                       resultado="resuelta", enviado=datetime.now().replace(microsecond=0),
                       firma=documentos.guardar(firma_png) if firma_png else None)
    db.add(v)
    db.flush()
    return v


@router.post("/ordenes/{wid}/confirmar-mantenimiento")
def confirm_work(wid: int, data: ConfirmWork, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Trabajo realizado. Personal propio: lo cierra él mismo con su firma, la fecha, al menos una foto de la reparación
    y el tiempo (llegada y salida). Subcontrata: queda finalizada para que la cierren el Director Técnico o recepción."""
    w = _open_order(db, wid)
    scope.require_asset("mantenimiento.editar", w.asset_id)
    if w.conf_mto_fecha:
        bad_request("El trabajo ya está dado por finalizado")
    propio = w.asignacion != "subcontrata"
    if w.exige_foto_antes and not fotos_antes(db, w):
        bad_request(FALTA_FOTO_ANTES)
    if not fotos_trabajo(db, w):
        bad_request("Añada al menos una foto de la reparación")
    firma_png = None
    if propio:
        if not data.firma:
            bad_request("Firme el trabajo realizado")
        from .tecnico import _png_firma
        firma_png = _png_firma(data.firma)
    elif data.firma:
        from .tecnico import _png_firma
        firma_png = _png_firma(data.firma)
    w.solucion = data.solucion
    if data.coste_real is not None:
        w.coste_real = data.coste_real
    empresa = "Personal propio" if propio else (w.proveedor or "Subcontrata")
    tecnico = scope.user.nombre if propio else (w.asignado_a or scope.user.nombre)
    _visita_pms(db, w, scope, data, empresa, tecnico, firma_png)
    exigir_finalizacion(db, w)
    w.conf_mto_por, w.conf_mto_fecha = scope.user.id, datetime.now()
    if propio:
        cerrar_ot(db, w, scope.user.id)
    else:
        w.estado = "pendiente_cierre"
    audit(db, scope.user, "cerrar_propio" if propio else "finalizar_subcontrata", "orden_trabajo", wid,
          {"solucion": data.solucion, "coste_real": data.coste_real, "llegada": str(data.llegada),
           "salida": str(data.salida), "firma": bool(firma_png)})
    db.commit()
    return _wo_out(w, db)


class Reject(BaseModel):
    motivo: str = Field(min_length=3)


@router.post("/ordenes/{wid}/rechazar")
def reject_work(wid: int, data: Reject, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """El Director Técnico o recepción devuelven a la subcontrata una OT finalizada que no es conforme."""
    w = _open_order(db, wid)
    scope.require_asset("mantenimiento.cerrar", w.asset_id)
    if not w.conf_mto_fecha:
        bad_request("No hay trabajo finalizado que rechazar")
    w.conf_mto_por = w.conf_mto_fecha = None
    w.estado = "en_curso"
    atendida(w)
    w.descripcion = f"{w.descripcion or ''}\n[Rechazada {date.today():%d/%m/%Y} por {scope.user.nombre}] {data.motivo}".strip()
    audit(db, scope.user, "rechazar", "orden_trabajo", wid, data.model_dump())
    db.commit()
    return _wo_out(w, db)


class CloseOrder(BaseModel):
    cancelar: bool = False
    motivo: str | None = None
    # si la OT no tiene aún el tiempo de trabajo (órdenes antiguas), se anota al cerrar
    llegada: datetime | None = None
    salida: datetime | None = None


@router.post("/ordenes/{wid}/revocar-enlace")
def revoke_link(wid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """El enlace del técnico enviado deja de valer (móvil perdido, enviado a quien no era…). Para seguir, se envía
    de nuevo la orden y sale un enlace nuevo."""
    w = get_or_404(db, WorkOrder, wid)
    if not (scope.can_asset("mantenimiento.editar", w.asset_id) or scope.can_asset("mantenimiento.cerrar", w.asset_id)):
        raise HTTPException(403, "Sin permiso para revocar el enlace de esta orden")
    revocar_enlace(w)
    audit(db, scope.user, "revocar_enlace", "orden_trabajo", wid, {"version": w.enlace_version})
    db.commit()
    return _wo_out(w, db)


def _release_unit(db: Session, w: WorkOrder) -> None:
    """Al cerrar o cancelar: si nada más lo retiene, el apartamento pasa a pendiente de limpieza y entra en el parte de
    limpieza del día (limpieza lo deja listo antes de volver a alquilarlo). El resto de unidades quedan disponibles."""
    if not (w.unit_id and w.bloquea_unidad):
        return
    unit = db.get(Unit, w.unit_id)
    from .partes_estado import bloqueo_por_partes
    others = db.scalar(select(WorkOrder.id).where(WorkOrder.unit_id == unit.id, WorkOrder.id != w.id,
                                                  WorkOrder.bloquea_unidad, WorkOrder.estado.in_(ABIERTAS))) \
        or bloqueo_por_partes(db, unit.id)
    if unit.estado == "mantenimiento" and not others:
        if unit.uso != "apartamento":  # viviendas, garajes, trasteros y locales: disponibles
            unit.estado = "disponible"
            return
        unit.estado = "pendiente_limpieza"
        from ..models import CleaningTask
        if not db.scalar(select(CleaningTask.id).where(CleaningTask.unit_id == unit.id,
                                                       CleaningTask.estado == "pendiente")):
            # entra en el parte de limpieza de hoy; al validarla, el apartamento queda disponible
            db.add(CleaningTask(asset_id=unit.asset_id, unit_id=unit.id, fecha=date.today(), tipo="extra",
                                clave=f"ot:{w.id}:{secrets.token_hex(6)}",  # única aunque se reabra y cierre
                                nota=f"Tras la reparación OT-{w.id:05d}: dejar el apartamento listo"))


@router.post("/ordenes/{wid}/cerrar")
def close_order(wid: int, data: CloseOrder, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """El Director Técnico o recepción cierran la OT finalizada por la subcontrata (o la cancelan)."""
    w = _open_order(db, wid)
    scope.require_asset("mantenimiento.cerrar", w.asset_id)
    if data.cancelar:
        if not data.motivo:
            bad_request("Indique el motivo de la cancelación")
        w.solucion = f"{w.solucion or ''}\n[Cancelada] {data.motivo}".strip()
    else:
        if not w.conf_mto_fecha:
            bad_request("El trabajo aún no está dado por finalizado")
        if minutos_ot(db, w) <= 0 and data.llegada and data.salida:
            _visita_pms(db, w, scope, data, w.proveedor or ("Personal propio" if w.asignacion == "propio" else "—"),
                        w.asignado_a or "—", None)
        exigir_finalizacion(db, w)
    cerrar_ot(db, w, scope.user.id, cancelada=data.cancelar, motivo=data.motivo)
    audit(db, scope.user, w.estado, "orden_trabajo", wid, data.model_dump(mode="json"))
    db.commit()
    return _wo_out(w, db)


@router.post("/ordenes/{wid}/reabrir")
def reopen_order(wid: int, data: Reject, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Recepción o el Director Técnico reabren una OT cerrada en los últimos 7 días que no es conforme: vuelve a
    quien la tenía asignada, con el motivo."""
    w = get_or_404(db, WorkOrder, wid)
    scope.require_asset("mantenimiento.cerrar", w.asset_id)
    if w.estado != "cerrada":
        bad_request("Solo se reabre una orden cerrada")
    if not w.fecha_cierre or w.fecha_cierre < date.today() - timedelta(days=REABRIR_DIAS):
        bad_request(f"Solo se reabre en los {REABRIR_DIAS} días siguientes al cierre: abra una orden nueva")
    w.estado = "en_curso"
    w.conf_mto_por = w.conf_mto_fecha = w.cerrada_por = w.fecha_cierre = w.conformidad_en = None
    w.descripcion = f"{w.descripcion or ''}\n[Reabierta {date.today():%d/%m/%Y} por {scope.user.nombre}] {data.motivo}".strip()
    if w.unit_id and w.bloquea_unidad:
        u = db.get(Unit, w.unit_id)
        if u.estado in ("pendiente_limpieza", "disponible"):
            u.estado = "mantenimiento"
    from ..models import CleaningTask  # la limpieza de después de la reparación espera al nuevo cierre
    for t in db.scalars(select(CleaningTask).where(CleaningTask.clave.like(f"ot:{w.id}:%"),
                                                   CleaningTask.estado == "pendiente")):
        t.estado = "anulada"
    audit(db, scope.user, "reabrir", "orden_trabajo", wid, data.model_dump())
    db.commit()
    return _wo_out(w, db)


class PeticionOT(BaseModel):
    asset_id: int
    unit_id: int | None = None
    ubicacion: str | None = Field(default=None, max_length=160)
    descripcion: str = Field(min_length=5, max_length=1000)
    urgente: bool = False


@router.post("/peticiones")
def request_order(data: PeticionOT, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Mantenimiento ve en sus rondas una avería que necesita una OT: se la pide a recepción (aviso en la campana y por
    correo). La OT la abre recepción."""
    scope.require_asset("mantenimiento.editar", data.asset_id)
    a = get_or_404(db, Asset, data.asset_id)
    u = get_or_404(db, Unit, data.unit_id) if data.unit_id else None
    if u and u.asset_id != a.id:
        bad_request("La unidad no es de este activo")
    lugar = " · ".join(x for x in (f"{u.uso} {u.codigo}" if u else "", (data.ubicacion or "").strip()) if x) or a.nombre
    n = avisos.peticion_ot(db, scope.user, a, lugar, data.descripcion.strip(), data.urgente)
    audit(db, scope.user, "pedir_ot", "activo", a.id, data.model_dump())
    db.commit()
    return {"ok": True, "avisados": n}


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
    if data.proveedor_id:
        get_or_404(db, Supplier, data.proveedor_id)
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
    if data.proveedor_id:
        get_or_404(db, Supplier, data.proveedor_id)
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
                              periodicidad_dias=dias, proxima_fecha=start,
                              tipo="oca" if "OCA" in titulo or titulo.startswith("Inspección periódica") else "mantenimiento"))
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
    from ..automatismos import generar_preventivo
    created = generar_preventivo(db, ids, data.dias_antelacion, scope.user)
    audit(db, scope.user, "generar_preventivo", "orden_trabajo", None, {"creadas": created})
    db.commit()
    return {"creadas": created}
