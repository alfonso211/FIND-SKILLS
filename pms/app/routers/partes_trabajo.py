"""Parte de trabajo diario de mantenimiento y limpieza (ver app/partes_trabajo.py) e informe quincenal."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import documentos
from .. import partes_trabajo as pt
from ..database import get_db
from ..models import AREAS_PARTE, Asset, Company, ReceivedDocument, Unit, User, WorkEntry, WorkReport
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/partes-trabajo", tags=["parte de trabajo"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ANOTAR = {"mantenimiento": ("mantenimiento.editar",), "limpieza": ("limpieza.editar",)}


def _area(area: str) -> str:
    if area not in AREAS_PARTE:
        bad_request("Área no válida (mantenimiento o limpieza)")
    return area


def _ver(scope: Scope, asset_id: int) -> None:
    if not any(scope.can_asset(p, asset_id) for p in ("mantenimiento.ver", "limpieza.editar", "partes.validar")):
        raise HTTPException(403, "Sin permiso para ver los partes de trabajo de este activo")


def _puede_anotar(scope: Scope, asset_id: int, area: str) -> bool:
    return any(scope.can_asset(p, asset_id) for p in (*ANOTAR[area], "partes.validar"))


def _validador(scope: Scope, asset_id: int) -> bool:
    return scope.can_asset("partes.validar", asset_id)


def _out(db: Session, scope: Scope, asset_id: int, area: str, f: date) -> dict:
    r, filas = pt.parte(db, asset_id, area, f)
    validado = r is not None and r.estado == "validado"
    nombre = db.get(User, r.validado_por).nombre if validado and r.validado_por else None
    return {"asset_id": asset_id, "area": area, "area_nombre": AREAS_PARTE[area], "fecha": f.isoformat(),
            "estado": "validado" if validado else "abierto", "validado_por": nombre,
            "validado_en": r.validado_en.isoformat(timespec="minutes") if validado and r.validado_en else None,
            "observaciones": r.observaciones if r else None, "lineas": filas,
            "puede_anotar": not validado and _puede_anotar(scope, asset_id, area),
            "puede_validar": _validador(scope, asset_id)}


@router.get("")
def daily(asset_id: int, area: str, fecha: date | None = None, scope: Scope = Depends(get_scope),
          db: Session = Depends(get_db)):
    _ver(scope, asset_id)
    return _out(db, scope, asset_id, _area(area), fecha or date.today())


@router.get("/dias")
def days(asset_id: int, area: str, dias: int = Query(15, ge=1, le=62), scope: Scope = Depends(get_scope),
         db: Session = Depends(get_db)):
    """Los últimos días con su número de trabajos y si están validados (para ver qué falta por validar)."""
    _ver(scope, asset_id)
    _area(area)
    hoy = date.today()
    out = []
    for i in range(dias):
        f = hoy - timedelta(days=i)
        r, filas = pt.parte(db, asset_id, area, f)
        out.append({"fecha": f.isoformat(), "trabajos": len(filas), "validado": bool(r and r.estado == "validado")})
    return out


class EntryIn(BaseModel):
    asset_id: int
    area: str
    fecha: date
    descripcion: str = Field(min_length=3, max_length=2000)
    unit_id: int | None = None
    ubicacion: str | None = Field(default=None, max_length=160)
    persona: str | None = Field(default=None, max_length=160)
    horas: float | None = Field(default=None, ge=0, le=24)


def _abierto(db: Session, asset_id: int, area: str, f: date) -> None:
    r = db.scalar(select(WorkReport).where(WorkReport.asset_id == asset_id, WorkReport.area == area,
                                           WorkReport.fecha == f))
    if r is not None and r.estado == "validado":
        bad_request(f"El parte de {AREAS_PARTE[area].lower()} del {f:%d/%m/%Y} ya está validado: pida a recepción "
                    "que lo reabra para añadir o quitar actuaciones")


@router.post("/actuaciones", status_code=201)
def add_entry(data: EntryIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Actuación que no estaba en ningún parte (zona común según el programa, tarea sin OT…)."""
    area = _area(data.area)
    if not _puede_anotar(scope, data.asset_id, area):
        raise HTTPException(403, f"Sin permiso para anotar en el parte de {AREAS_PARTE[area].lower()}")
    if data.fecha > date.today():
        bad_request("No se anotan trabajos de días futuros")
    if data.unit_id is not None and get_or_404(db, Unit, data.unit_id).asset_id != data.asset_id:
        bad_request("La unidad no es de este activo")
    _abierto(db, data.asset_id, area, data.fecha)
    e = WorkEntry(**data.model_dump(), user_id=scope.user.id)
    e.persona = (data.persona or "").strip() or scope.user.nombre
    db.add(e)
    db.flush()
    audit(db, scope.user, "anotar", "parte_trabajo", e.id, {"area": area, "fecha": str(data.fecha)})
    db.commit()
    return _out(db, scope, data.asset_id, area, data.fecha)


@router.delete("/actuaciones/{eid}")
def delete_entry(eid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    e = get_or_404(db, WorkEntry, eid)
    if not (e.user_id == scope.user.id or _validador(scope, e.asset_id)):
        raise HTTPException(403, "Solo la quita quien la anotó (o recepción)")
    _abierto(db, e.asset_id, e.area, e.fecha)
    asset_id, area, f = e.asset_id, e.area, e.fecha
    db.delete(e)
    audit(db, scope.user, "quitar_actuacion", "parte_trabajo", eid)
    db.commit()
    return _out(db, scope, asset_id, area, f)


class ValidateIn(BaseModel):
    asset_id: int
    area: str
    fecha: date
    observaciones: str | None = Field(default=None, max_length=2000)


def _archivar(db: Session, scope: Scope, a: Asset, r: WorkReport, nombre: str, datos: bytes, mime: str,
              descripcion: str) -> ReceivedDocument:
    doc = ReceivedDocument(asset_id=a.id, tipo="parte_trabajo", fecha=r.fecha,
                           emisor="INVERPMS", referencia=nombre.rsplit(".", 1)[0][:60], descripcion=descripcion,
                           nombre=nombre, fichero=documentos.guardar(datos), mime=mime, tamano=len(datos),
                           sha256=documentos.huella(datos), user_id=scope.user.id)
    db.add(doc)
    db.flush()
    return doc


def _borrar_docs(db: Session, *ids) -> None:
    for i in ids:
        d = db.get(ReceivedDocument, i) if i else None
        if d is not None:
            documentos.borrar(d.fichero)
            db.delete(d)


@router.post("/validar")
def validate(data: ValidateIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Recepción valida el parte del día: se congela, y su PDF y su Excel quedan en los documentos del activo."""
    area = _area(data.area)
    if not _validador(scope, data.asset_id):
        raise HTTPException(403, "Los partes los valida recepción")
    if data.fecha > date.today():
        bad_request("No se valida un parte de un día futuro")
    a = get_or_404(db, Asset, data.asset_id)
    r = db.scalar(select(WorkReport).where(WorkReport.asset_id == a.id, WorkReport.area == area,
                                           WorkReport.fecha == data.fecha))
    if r is not None and r.estado == "validado":
        bad_request("Este parte ya está validado")
    if r is None:
        r = WorkReport(asset_id=a.id, area=area, fecha=data.fecha)
        db.add(r)
    r.lineas = pt.lineas(db, a.id, area, data.fecha)
    r.estado, r.observaciones = "validado", data.observaciones
    r.validado_por, r.validado_en = scope.user.id, datetime.now()
    db.flush()
    comp = db.get(Company, a.company_id)
    base = f"Parte_{area}_{a.codigo}_{data.fecha.isoformat()}"
    desc = f"Parte de trabajo de {AREAS_PARTE[area].lower()} del {data.fecha:%d/%m/%Y} ({len(r.lineas)} trabajos)"
    _borrar_docs(db, r.pdf_id, r.xlsx_id)
    r.pdf_id = _archivar(db, scope, a, r, f"{base}.pdf", pt.pdf_parte(a, comp, r, r.lineas, scope.user.nombre),
                         "application/pdf", desc).id
    r.xlsx_id = _archivar(db, scope, a, r, f"{base}.xlsx", pt.excel_parte(a, r, r.lineas, scope.user.nombre),
                          XLSX, desc).id
    audit(db, scope.user, "validar", "parte_trabajo", r.id, {"area": area, "fecha": str(data.fecha),
                                                             "trabajos": len(r.lineas)})
    db.commit()
    return _out(db, scope, a.id, area, data.fecha)


@router.post("/reabrir")
def reopen(data: ValidateIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Reabre un parte validado para corregirlo (se borran sus documentos archivados hasta validarlo de nuevo)."""
    area = _area(data.area)
    if not _validador(scope, data.asset_id):
        raise HTTPException(403, "Los partes los reabre recepción")
    r = db.scalar(select(WorkReport).where(WorkReport.asset_id == data.asset_id, WorkReport.area == area,
                                           WorkReport.fecha == data.fecha))
    if r is None or r.estado != "validado":
        bad_request("El parte no está validado")
    _borrar_docs(db, r.pdf_id, r.xlsx_id)
    r.estado, r.lineas, r.pdf_id, r.xlsx_id = "abierto", None, None, None
    audit(db, scope.user, "reabrir", "parte_trabajo", r.id)
    db.commit()
    return _out(db, scope, data.asset_id, area, data.fecha)


@router.get("/descargar")
def download(asset_id: int, area: str, fecha: date, formato: str = "pdf", scope: Scope = Depends(get_scope),
             db: Session = Depends(get_db)):
    """PDF o Excel del parte: solo si está validado (es el archivado)."""
    _ver(scope, asset_id)
    r = db.scalar(select(WorkReport).where(WorkReport.asset_id == asset_id, WorkReport.area == _area(area),
                                           WorkReport.fecha == fecha))
    if r is None or r.estado != "validado":
        bad_request("El parte tiene que estar validado por recepción antes de imprimirlo")
    d = db.get(ReceivedDocument, r.xlsx_id if formato == "xlsx" else r.pdf_id)
    if d is None:
        bad_request("No se encuentra el documento archivado: reabra y valide de nuevo el parte")
    return Response(documentos.leer(d.fichero), media_type=d.mime,
                    headers={"Content-Disposition": f'attachment; filename="{d.nombre}"'})


# --------------------------------------------------------------------------- informe quincenal
def _periodo(anio: int | None, mes: int | None, quincena: int | None) -> tuple[date, date, int, int, int]:
    if anio is None or mes is None or quincena is None:
        anio, mes, quincena = pt.quincena_anterior(date.today())
    if quincena not in (1, 2) or not 1 <= mes <= 12:
        bad_request("Quincena no válida")
    d0, d1 = pt.quincena(anio, mes, quincena)
    return d0, d1, anio, mes, quincena


@router.get("/quincenal")
def fortnight(asset_id: int, anio: int | None = None, mes: int | None = None, quincena: int | None = None,
              scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _ver(scope, asset_id)
    d0, d1, anio, mes, q = _periodo(anio, mes, quincena)
    inf = pt.informe(db, asset_id, d0, min(d1, date.today()))
    nombre = f"Informe_quincenal_{get_or_404(db, Asset, asset_id).codigo}_{d0.isoformat()}"
    archivado = db.scalar(select(ReceivedDocument.id).where(ReceivedDocument.asset_id == asset_id,
                                                            ReceivedDocument.nombre == f"{nombre}.pdf"))
    for a in inf["areas"].values():
        a.pop("trabajos")
    return {**inf, "anio": anio, "mes": mes, "quincena": q, "archivado": bool(archivado)}


@router.get("/quincenal/descargar")
def fortnight_file(asset_id: int, anio: int, mes: int, quincena: int, formato: str = "pdf", archivar: bool = False,
                   scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """PDF o Excel del informe quincenal. `archivar`: guarda los dos en los documentos del activo (sustituye al
    archivado antes de esa quincena)."""
    _ver(scope, asset_id)
    d0, d1, *_ = _periodo(anio, mes, quincena)
    a = get_or_404(db, Asset, asset_id)
    comp = db.get(Company, a.company_id)
    inf = pt.informe(db, asset_id, d0, min(d1, date.today()))
    pdf, xl = pt.pdf_informe(a, comp, inf), pt.excel_informe(a, inf)
    base = f"Informe_quincenal_{a.codigo}_{d0.isoformat()}"
    if archivar:
        if not _validador(scope, asset_id):
            raise HTTPException(403, "El informe quincenal lo archiva recepción")
        for viejo in db.scalars(select(ReceivedDocument).where(ReceivedDocument.asset_id == a.id,
                                                               ReceivedDocument.nombre.in_([f"{base}.pdf", f"{base}.xlsx"]))):
            documentos.borrar(viejo.fichero)
            db.delete(viejo)
        db.flush()
        desc = f"Informe quincenal de trabajos de mantenimiento y limpieza del {d0:%d/%m/%Y} al {d1:%d/%m/%Y}"
        for nombre, datos, mime in ((f"{base}.pdf", pdf, "application/pdf"), (f"{base}.xlsx", xl, XLSX)):
            db.add(ReceivedDocument(asset_id=a.id, tipo="parte_trabajo", fecha=d1, emisor="INVERPMS",
                                    referencia=base[:60], descripcion=desc, nombre=nombre,
                                    fichero=documentos.guardar(datos), mime=mime, tamano=len(datos),
                                    sha256=documentos.huella(datos), user_id=scope.user.id))
        audit(db, scope.user, "archivar_informe_quincenal", "parte_trabajo", None, {"activo": a.codigo, "desde": str(d0)})
        db.commit()
    datos, mime, ext = (xl, XLSX, "xlsx") if formato == "xlsx" else (pdf, "application/pdf", "pdf")
    return Response(datos, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{base}.{ext}"'})
