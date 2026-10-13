"""Partes de estado: mantenimiento y limpieza revisan una vivienda o zona común y señalan deficiencias con listas
encadenadas (app/partes_estado.py). Recepción genera la orden de trabajo (y la encarga a quien considere) o descarta
el parte. Un parte crítico deja la unidad fuera de servicio hasta que se cierra su orden de trabajo.
Indicadores para la dirección técnica: Pareto de elementos, tiempo medio de reparación e intervenciones por unidad."""
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from .. import adjuntos, avisos, documentos, planos
from .. import partes_estado as pe
from ..config import settings
from ..database import get_db
from ..models import Asset, Reservation, StatusReport, StatusReportPhoto, Unit, User, WorkOrder, WorkOrderAttachment
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404, scoped

router = APIRouter(prefix="/api/partes-estado", tags=["partes de estado"])
MAX_FOTOS = 6
LIBRES = ("disponible", "pendiente_limpieza")


def codigo(p: StatusReport) -> str:
    return f"PE-{p.id:05d}"


def _ubicacion(db: Session, p: StatusReport) -> str:
    if p.unit_id:
        u = db.get(Unit, p.unit_id)
        return u.codigo if u else "—"
    a = db.get(Asset, p.asset_id)
    zona = planos.zonas(a.codigo).get(p.zona, p.zona) if p.zona else None
    return f"Zonas comunes{' · ' + zona if zona else ''}"


def _out(db: Session, p: StatusReport, nombres: dict[int, str] | None = None) -> dict:
    d = p.to_dict()
    for k in ("lat", "lon", "precision_m"):
        d[k] = float(d[k]) if d[k] is not None else None
    nombre_est = pe.estancia(p.tipologia, p.estancia)
    w = db.get(WorkOrder, p.work_order_id) if p.work_order_id else None
    usuario = (nombres or {}).get(p.user_id) if nombres else None
    if usuario is None and p.user_id:
        usuario = db.get(User, p.user_id).nombre
    d.update(codigo=codigo(p), activo=db.get(Asset, p.asset_id).nombre, ubicacion=_ubicacion(db, p),
             tipologia_nombre=pe.TIPOLOGIAS.get(p.tipologia), estancia_nombre=nombre_est[0] if nombre_est else p.estancia,
             familia_nombre=pe.FAMILIAS[p.familia][0], elemento_nombre=pe.ELEMENTOS[p.elemento][1],
             deficiencia_nombre=pe.DEF[p.deficiencia][1], departamento_nombre=pe.DEPARTAMENTOS[p.departamento],
             estado_nombre=pe.ESTADOS[p.estado], usuario=usuario,
             fotos=[{"id": f.id, "nombre": f.nombre} for f in p.fotos],
             ot={"id": w.id, "estado": w.estado, "prioridad": w.prioridad, "asignado_a": w.asignado_a} if w else None,
             horas=round((datetime.now() - p.creado).total_seconds() / 3600, 1))
    # propuesta para la orden de trabajo que genera recepción
    d["ot_propuesta"] = {
        "titulo": f"{d['elemento_nombre']}: {d['deficiencia_nombre']} ({d['estancia_nombre']})"[:200],
        "categoria": "limpieza" if p.clase == "D2" else pe.ELEMENTOS[p.elemento][2], "prioridad": p.prioridad,
        "descripcion": "\n".join([f"Parte de estado {codigo(p)} · {d['ubicacion']} · {d['estancia_nombre']}",
                                  f"{d['familia_nombre']} → {d['elemento_nombre']}: {d['deficiencia_nombre']}",
                                  f"Gravedad: {p.gravedad} · Departamento: {d['departamento_nombre']}",
                                  *(p.alertas or []), *([f"Observaciones: {p.observaciones}"] if p.observaciones else [])]),
        "bloquea_unidad": p.bloquea_unidad}
    return d


def _puede_crear(scope: Scope, asset_id: int) -> bool:
    return scope.can_asset("partes_estado.crear", asset_id)


def _gestiona(scope: Scope, asset_id: int) -> bool:
    """Recepción y dirección: generan la orden de trabajo o descartan el parte."""
    return scope.can_asset("mantenimiento.abrir", asset_id)


# --------------------------------------------------------------------------- catálogo y ubicaciones
@router.get("/catalogo")
def catalog(scope: Scope = Depends(get_scope)):
    if not (scope.has_any("partes_estado.crear") or scope.has_any("mantenimiento.ver")):
        raise HTTPException(403, "Sin permiso")
    return pe.catalogo()


@router.get("/ubicaciones")
def locations(asset_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Unidades del activo con su tipología (para el buscador y el código QR) y zonas comunes del plano."""
    if not (_puede_crear(scope, asset_id) or scope.can_asset("mantenimiento.ver", asset_id)):
        raise HTTPException(403, "Sin permiso en este activo")
    a = get_or_404(db, Asset, asset_id)
    unidades = [{"id": u.id, "codigo": u.codigo, "bloque": u.bloque, "planta": u.planta, "estado": u.estado,
                 "tipologia": pe.tipologia_unidad(u.dormitorios, u.tipologia), "descripcion": u.tipologia}
                for u in db.scalars(select(Unit).where(Unit.asset_id == asset_id, Unit.uso != "garaje")
                                    .order_by(Unit.codigo))]
    zonas = [{"zona": z, "nombre": n} for z, n in sorted(planos.zonas(a.codigo).items(), key=lambda x: x[1])]
    return {"asset_id": a.id, "activo": a.nombre, "unidades": unidades, "zonas": zonas}


# --------------------------------------------------------------------------- alta del parte
@router.post("", status_code=201)
def create_report(tareas: BackgroundTasks, asset_id: int = Form(...), unit_id: int | None = Form(None),
                  zona: str | None = Form(None), tipologia: str | None = Form(None), estancia: str = Form(...),
                  elemento: str = Form(...), deficiencia: str = Form(...), gravedad: str = Form(...),
                  observaciones: str | None = Form(None), lat: float | None = Form(None), lon: float | None = Form(None),
                  precision: float | None = Form(None), fotos: list[UploadFile] = File(...),
                  scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    if not _puede_crear(scope, asset_id):
        raise HTTPException(403, "Sin permiso para registrar partes de estado en este activo")
    a = get_or_404(db, Asset, asset_id)
    unit = None
    if unit_id:
        unit = get_or_404(db, Unit, unit_id)
        if unit.asset_id != asset_id or unit.uso == "garaje":
            bad_request("La unidad no pertenece al activo")
        if zona:
            bad_request("Un parte es de una unidad o de una zona común, no de ambas")
        tipologia = pe.tipologia_unidad(unit.dormitorios, unit.tipologia) or tipologia
        if tipologia not in ("T0", "T1", "T2"):
            bad_request("Indique la tipología de la vivienda (estudio, 1 o 2 dormitorios)")
    else:
        tipologia = "ZC"
        if zona and zona not in planos.zonas(a.codigo):
            bad_request("Zona común no válida para este activo")
    est = pe.estancia(tipologia, estancia)
    if not est:
        bad_request("La estancia no corresponde a esta ubicación")
    if elemento not in pe.ELEMENTOS_ESTANCIA[est[1]]:
        bad_request("Ese elemento no se revisa en esta estancia")
    if deficiencia not in pe.DEF:
        bad_request("Deficiencia no válida")
    if gravedad not in pe.GRAVEDADES:
        bad_request("Gravedad no válida: leve, media o crítica")
    fotos = [f for f in fotos if f.filename]
    if not fotos:
        bad_request("La foto es obligatoria: hace falta para prever el repuesto o el material")
    if len(fotos) > MAX_FOTOS:
        bad_request(f"Máximo {MAX_FOTOS} fotos por parte")
    if lat is not None and not (-90 <= lat <= 90 and -180 <= (lon or 0) <= 180):
        lat = lon = precision = None
    r = pe.reglas(elemento, deficiencia, gravedad)
    p = StatusReport(asset_id=asset_id, unit_id=unit.id if unit else None, zona=zona or None, tipologia=tipologia,
                     estancia=estancia, familia=r["familia"], elemento=elemento, clase=r["clase"],
                     deficiencia=deficiencia, gravedad=gravedad, departamento=r["departamento"],
                     prioridad=r["prioridad"], alertas=list(r["alertas"]),
                     observaciones=(observaciones or "").strip()[:2000] or None,
                     lat=lat, lon=lon if lat is not None else None, precision_m=precision if lat is not None else None,
                     user_id=scope.user.id)
    for f in fotos:
        try:
            datos, mime, nombre = adjuntos.normalizar(f.file.read(adjuntos.TAM_MAX + 1), (f.filename or "foto")[-150:])
        except ValueError as e:
            bad_request(f"{f.filename}: {e}")
        p.fotos.append(StatusReportPhoto(nombre=nombre, fichero=documentos.guardar(datos), mime=mime,
                                         tamano=len(datos), sha256=documentos.huella(datos)))
    if gravedad == "critica" and unit:
        # Out of order: fuera de venta hasta que mantenimiento cierre la orden de trabajo
        if unit.estado in LIBRES:
            unit.estado, p.bloquea_unidad = "mantenimiento", True
        elif db.scalar(select(Reservation.id).where(Reservation.unit_id == unit.id, Reservation.estado == "checkin")):
            p.alertas.append("Hay un huésped alojado: recepción debe valorar su traslado. La unidad no se ha "
                             "bloqueado automáticamente.")
    db.add(p)
    db.flush()
    audit(db, scope.user, "crear", "parte_estado", p.id, {"activo": a.codigo, "ubicacion": _ubicacion(db, p),
                                                         "elemento": elemento, "deficiencia": deficiencia,
                                                         "gravedad": gravedad, "bloquea": p.bloquea_unidad})
    db.commit()
    tareas.add_task(avisos.parte_estado, p.id)
    return _out(db, p)


# --------------------------------------------------------------------------- consulta
@router.get("")
def list_reports(asset_id: int | None = None, estado: str | None = None, abiertos: bool = False,
                 scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Recepción y dirección ven los de sus activos; quien solo registra partes ve los suyos."""
    ids = scope.asset_ids("mantenimiento.ver")
    stmt = select(StatusReport)
    if ids is not None and not ids:
        if not scope.has_any("partes_estado.crear"):
            raise HTTPException(403, "Sin permiso")
        stmt = stmt.where(StatusReport.user_id == scope.user.id)
    else:
        stmt = scoped(stmt, StatusReport.asset_id, ids)
        if not scope.has_any("mantenimiento.abrir") and not scope.has_any("mantenimiento.editar"):
            stmt = stmt.where(StatusReport.user_id == scope.user.id)
    if asset_id:
        stmt = stmt.where(StatusReport.asset_id == asset_id)
    if estado:
        stmt = stmt.where(StatusReport.estado == estado)
    if abiertos:
        stmt = stmt.where(StatusReport.estado.in_(pe.ABIERTOS))
    filas = list(db.scalars(stmt.order_by(StatusReport.id.desc()).limit(1000)))
    nombres = dict(db.execute(select(User.id, User.nombre).where(
        User.id.in_({p.user_id for p in filas if p.user_id} or {-1}))).all())
    return [{**_out(db, p, nombres), "puede_gestionar": _gestiona(scope, p.asset_id)} for p in filas]


def _ver(db: Session, scope: Scope, p: StatusReport) -> None:
    if p.user_id != scope.user.id:
        scope.require_asset("mantenimiento.ver", p.asset_id)


@router.get("/fotos/{fid}")
def view_photo(fid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    f = get_or_404(db, StatusReportPhoto, fid)
    _ver(db, scope, db.get(StatusReport, f.parte_id))
    return Response(documentos.leer(f.fichero), media_type=f.mime, headers={
        "Content-Disposition": f'inline; filename="{f.nombre}"', "Cache-Control": "private, max-age=3600"})


# --------------------------------------------------------------------------- recepción: OT o descarte
def bloqueo_por_partes(db: Session, unit_id: int, excepto: int | None = None) -> bool:
    """¿Sigue la unidad fuera de servicio por un parte crítico que aún no tiene orden de trabajo?"""
    return bool(db.scalar(select(exists().where(StatusReport.unit_id == unit_id, StatusReport.bloquea_unidad,
                                                StatusReport.estado == "pendiente", StatusReport.id != (excepto or -1)))))


def _liberar(db: Session, p: StatusReport) -> None:
    if not (p.bloquea_unidad and p.unit_id):
        return
    u = db.get(Unit, p.unit_id)
    otras = db.scalar(select(WorkOrder.id).where(WorkOrder.unit_id == u.id, WorkOrder.bloquea_unidad,
                                                 WorkOrder.estado.notin_(("cerrada", "cancelada"))))
    if u.estado == "mantenimiento" and not otras and not bloqueo_por_partes(db, u.id, excepto=p.id):
        u.estado = "disponible"


def vincular_ot(db: Session, scope: Scope, pid: int, w: WorkOrder) -> StatusReport:
    """La orden de trabajo que recepción genera desde el parte (POST /api/mantenimiento/ordenes con
    parte_estado_id): misma ubicación; si el parte bloqueó la unidad, la OT la mantiene bloqueada hasta cerrarse."""
    p = get_or_404(db, StatusReport, pid)
    if not _gestiona(scope, p.asset_id):
        raise HTTPException(403, "Sin permiso para gestionar este parte")
    if p.estado != "pendiente":
        bad_request(f"El parte {codigo(p)} ya está {pe.ESTADOS[p.estado].lower()}")
    if w.asset_id != p.asset_id or (w.unit_id or None) != p.unit_id:
        bad_request("La orden de trabajo debe ser de la misma unidad o zona que el parte")
    if p.bloquea_unidad:
        w.bloquea_unidad = True
    p.estado, p.gestionado_por, p.gestionado_en = "ot_generada", scope.user.id, datetime.now()
    return p


def copiar_fotos(db: Session, p: StatusReport, w: WorkOrder, user_id: int) -> None:
    p.work_order_id = w.id
    for f in p.fotos:
        datos = documentos.leer(f.fichero)
        db.add(WorkOrderAttachment(work_order_id=w.id, tipo="averia", nombre=f.nombre,
                                   descripcion=f"Foto del parte de estado {codigo(p)}", fichero=documentos.guardar(datos),
                                   mime=f.mime, tamano=f.tamano, sha256=f.sha256, user_id=user_id))


def cerrar_partes(db: Session, w: WorkOrder, motivo: str | None) -> None:
    """Al cerrar la OT su parte queda resuelto (cuenta para el tiempo de reparación); si se cancela, descartado."""
    for p in db.scalars(select(StatusReport).where(StatusReport.work_order_id == w.id,
                                                   StatusReport.estado == "ot_generada")):
        p.resuelto_en = datetime.now()
        if w.estado == "cerrada":
            p.estado = "resuelto"
        else:
            p.estado, p.motivo_descarte = "descartado", f"Orden de trabajo cancelada: {motivo or ''}".strip()[:300]


class Descarte(BaseModel):
    motivo: str = Field(min_length=3, max_length=300)


@router.post("/{pid}/descartar")
def discard(pid: int, data: Descarte, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = get_or_404(db, StatusReport, pid)
    if not _gestiona(scope, p.asset_id):
        raise HTTPException(403, "Solo recepción o dirección descartan partes")
    if p.estado != "pendiente":
        bad_request("Solo se descartan partes pendientes")
    p.estado, p.motivo_descarte = "descartado", data.motivo.strip()
    p.gestionado_por, p.gestionado_en = scope.user.id, datetime.now()
    _liberar(db, p)
    audit(db, scope.user, "descartar", "parte_estado", p.id, {"motivo": p.motivo_descarte})
    db.commit()
    return _out(db, p)


# --------------------------------------------------------------------------- códigos QR de las unidades
def _qr_png(texto: str) -> bytes:
    import segno
    out = io.BytesIO()
    segno.make(texto, error="m").save(out, kind="png", scale=8, border=2)
    return out.getvalue()


@router.get("/qr.pdf")
def qr_sheet(asset_id: int, request: Request, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Hoja de etiquetas con el código QR de cada unidad y zona común: al escanearlo con el móvil se abre el parte
    de estado de esa ubicación."""
    scope.require_asset("mantenimiento.ver", asset_id)
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    ubic = locations(asset_id, scope, db)
    base = settings.url or str(request.base_url).rstrip("/")
    etiquetas = [(u["codigo"], u["descripcion"] or "", f"{base}/#estado?a={asset_id}&u={u['id']}")
                 for u in ubic["unidades"]]
    etiquetas += [(z["nombre"], "Zona común", f"{base}/#estado?a={asset_id}&z={z['zona']}") for z in ubic["zonas"]]
    etiquetas.append(("Zonas comunes", ubic["activo"], f"{base}/#estado?a={asset_id}&z="))
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    c.setTitle(f"QR partes de estado · {ubic['activo']}")
    cols, filas, ancho, alto = 4, 6, 50 * mm, 46 * mm
    x0, y0 = (A4[0] - cols * ancho) / 2, A4[1] - 12 * mm
    for i, (titulo, sub, url) in enumerate(etiquetas):
        if i and i % (cols * filas) == 0:
            c.showPage()
        k = i % (cols * filas)
        x, y = x0 + (k % cols) * ancho, y0 - (k // cols + 1) * alto
        c.drawImage(ImageReader(io.BytesIO(_qr_png(url))), x + 10 * mm, y + 10 * mm, 30 * mm, 30 * mm)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(x + ancho / 2, y + 6 * mm, titulo[:28])
        c.setFont("Helvetica", 7)
        c.drawCentredString(x + ancho / 2, y + 2.5 * mm, f"Parte de estado · {sub}"[:45])
    c.save()
    return Response(out.getvalue(), media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="QR_partes_estado_{date.today():%Y%m%d}.pdf"'})


# --------------------------------------------------------------------------- panel técnico (dirección)
@router.get("/kpis")
def kpis(asset_id: int | None = None, desde: date | None = None, hasta: date | None = None,
         scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Pareto de elementos con fallos, tiempo medio de reparación (del parte al cierre de la OT) e intervenciones
    técnicas por unidad y mes."""
    ids = scope.asset_ids("mantenimiento.ver")
    if ids is not None and not ids:
        raise HTTPException(403, "Sin permiso")
    hasta = hasta or date.today()
    desde = desde or hasta - timedelta(days=365)
    stmt = scoped(select(StatusReport), StatusReport.asset_id, ids).where(
        StatusReport.creado >= datetime.combine(desde, datetime.min.time()),
        StatusReport.creado < datetime.combine(hasta + timedelta(days=1), datetime.min.time()))
    if asset_id:
        stmt = stmt.where(StatusReport.asset_id == asset_id)
    partes = list(db.scalars(stmt))
    validos = [p for p in partes if p.estado != "descartado"]
    total = len(validos)
    acumulado, pareto = 0, []
    for elemento, n in Counter(p.elemento for p in validos).most_common():
        acumulado += n
        pareto.append({"elemento": pe.ELEMENTOS[elemento][1], "familia": pe.FAMILIAS[pe.ELEMENTOS[elemento][0]][0],
                       "partes": n, "pct": round(100 * n / total, 1), "acumulado": round(100 * acumulado / total, 1)})
    familias = Counter(pe.FAMILIAS[p.familia][0] for p in validos)
    deficiencias = Counter(pe.DEF[p.deficiencia][1] for p in validos)

    def mttr(lista):
        horas = [(p.resuelto_en - p.creado).total_seconds() / 3600 for p in lista if p.estado == "resuelto"
                 and p.resuelto_en]
        return {"resueltos": len(horas), "horas": round(sum(horas) / len(horas), 1) if horas else None}
    unidades: dict[str, dict[str, int]] = defaultdict(Counter)
    for p in validos:
        if p.clase == "D1":
            unidades[_ubicacion(db, p)][p.creado.strftime("%Y-%m")] += 1
    meses = sorted({m for c in unidades.values() for m in c})
    return {
        "desde": desde.isoformat(), "hasta": hasta.isoformat(), "total": total,
        "por_estado": {e: sum(p.estado == e for p in partes) for e in pe.ESTADOS},
        "pareto": pareto, "familias": familias.most_common(), "deficiencias": deficiencias.most_common(),
        "mttr": {"global": mttr(validos), **{d: mttr([p for p in validos if p.departamento == d])
                                            for d in pe.DEPARTAMENTOS},
                 **{g: mttr([p for p in validos if p.gravedad == g]) for g in pe.GRAVEDADES}},
        "intervenciones": {"meses": meses, "filas": sorted(
            ({"ubicacion": k, "total": sum(v.values()), "meses": [v.get(m, 0) for m in meses]}
             for k, v in unidades.items()), key=lambda x: -x["total"])},
    }


def fila_aviso(db: Session, p: StatusReport) -> list:
    """Fila para los correos (al momento y resumen diario)."""
    return [db.get(Asset, p.asset_id).nombre, codigo(p), _ubicacion(db, p),
            f"{pe.ELEMENTOS[p.elemento][1]} · {pe.DEF[p.deficiencia][1]}", p.gravedad.capitalize(),
            p.creado.strftime("%d/%m/%Y %H:%M"), pe.ESTADOS[p.estado]]


def partes_panel(db: Session, scope: Scope) -> list[dict]:
    """Panel de control: a recepción y dirección, los partes sin resolver de sus activos (hasta que se resuelven o
    descartan); a quien los registra, los suyos abiertos."""
    ids = scope.asset_ids("mantenimiento.abrir")
    if ids is None or ids:
        stmt = scoped(select(StatusReport), StatusReport.asset_id, ids)
    elif scope.has_any("partes_estado.crear"):
        stmt = select(StatusReport).where(StatusReport.user_id == scope.user.id)
    else:
        return []
    return [{"id": p.id, "codigo": codigo(p), "asset_id": p.asset_id, "ubicacion": _ubicacion(db, p),
             "elemento": pe.ELEMENTOS[p.elemento][1], "deficiencia": pe.DEF[p.deficiencia][1], "gravedad": p.gravedad,
             "estado": p.estado, "estado_nombre": pe.ESTADOS[p.estado], "creado": p.creado.isoformat()}
            for p in db.scalars(stmt.where(StatusReport.estado.in_(pe.ABIERTOS)).order_by(StatusReport.creado)
                                .limit(100))]
