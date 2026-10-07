"""Parte diario de limpieza: consulta, limpiezas extra, validación por recepción, PDF, Excel y envío.

Ver app/limpiezas.py. El parte se imprime o se envía en PDF (correo) o como mensaje (WhatsApp); cada vez que se
imprime o envía, el Excel del día queda guardado en los documentos del activo (sustituye al anterior del mismo día).
"""
from datetime import date
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import avisos, documentos, firma_contrato, limpiezas
from ..database import get_db
from ..models import Asset, CleaningTask, EmailLog, ReceivedDocument, Unit
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404
from .personal import despachar, destinatarios

router = APIRouter(prefix="/api/limpieza", tags=["limpieza"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _permiso(scope: Scope, asset_id: int) -> None:
    if not (scope.can_asset("limpieza.editar", asset_id) or scope.can_asset("reservas.editar", asset_id)):
        raise HTTPException(403, "Sin permiso para el parte de limpieza de este activo")


def _datos(db: Session, scope: Scope, asset_id: int, fecha: date | None) -> tuple[Asset, date, list[dict]]:
    _permiso(scope, asset_id)
    a = get_or_404(db, Asset, asset_id)
    f = fecha or date.today()
    filas = limpiezas.parte(db, a.id, f)
    db.commit()  # las limpiezas generadas al consultar el parte quedan guardadas
    return a, f, filas


def _nombre(a: Asset, f: date, ext: str) -> str:
    return f"Parte_limpieza_{a.codigo}_{f.isoformat()}.{ext}"


def _guardar_excel(db: Session, scope: Scope, a: Asset, f: date, filas: list[dict]) -> ReceivedDocument:
    """El Excel del parte queda en los documentos del activo (uno por día: el último sustituye al anterior)."""
    nombre = _nombre(a, f, "xlsx")
    anterior = db.scalar(select(ReceivedDocument).where(ReceivedDocument.asset_id == a.id,
                                                        ReceivedDocument.nombre == nombre))
    if anterior:
        documentos.borrar(anterior.fichero)
        db.delete(anterior)
        db.flush()
    xl = limpiezas.excel(a, f, filas)
    doc = ReceivedDocument(asset_id=a.id, tipo="limpieza", fecha=f, emisor="INVERPMS", referencia=f"Limpieza {f.isoformat()}",
                           descripcion=f"Parte de limpieza del {f:%d/%m/%Y}", nombre=nombre,
                           fichero=documentos.guardar(xl), mime=XLSX, tamano=len(xl), sha256=documentos.huella(xl),
                           user_id=scope.user.id)
    db.add(doc)
    db.flush()
    return doc


@router.get("/parte")
def cleaning_report(asset_id: int, fecha: date | None = None, scope: Scope = Depends(get_scope),
                    db: Session = Depends(get_db)):
    a, f, filas = _datos(db, scope, asset_id, fecha)
    unidades = [{"id": u.id, "codigo": u.codigo, "bloque": u.bloque} for u in db.scalars(
        select(Unit).where(Unit.asset_id == a.id, Unit.uso != "garaje").order_by(Unit.codigo))]
    return {"asset": {"id": a.id, "nombre": a.nombre, "codigo": a.codigo}, "fecha": f.isoformat(), "limpiezas": filas,
            "pendientes": sum(1 for x in filas if x["estado"] == "pendiente"), "unidades": unidades,
            "periodicidades": limpiezas.PERIODICIDADES}


class ExtraIn(BaseModel):
    asset_id: int
    unit_id: int
    fecha: date | None = None
    nota: str | None = Field(default=None, max_length=300)


@router.post("/extra", status_code=201)
def add_extra(data: ExtraIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Recepción añade una limpieza no programada (repaso, a fondo, petición del cliente…)."""
    _permiso(scope, data.asset_id)
    u = get_or_404(db, Unit, data.unit_id)
    if u.asset_id != data.asset_id or u.uso == "garaje":
        bad_request("Apartamento no válido para este activo")
    f = data.fecha or date.today()
    if f < date.today():
        bad_request("La limpieza extra no puede ser de un día pasado")
    t = CleaningTask(asset_id=u.asset_id, unit_id=u.id, fecha=f, tipo="extra", nota=(data.nota or "").strip() or None,
                     creada_por=scope.user.id)
    db.add(t)
    db.flush()
    audit(db, scope.user, "limpieza_extra", "unidad", u.id, {"fecha": f.isoformat(), "nota": t.nota})
    db.commit()
    return {"id": t.id}


def _tarea(db: Session, scope: Scope, tid: int) -> CleaningTask:
    t = get_or_404(db, CleaningTask, tid)
    _permiso(scope, t.asset_id)
    return t


@router.post("/{tid}/hecha")
def mark_done(tid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Recepción valida la limpieza (limpieza ha avisado de que está hecha): sale del parte."""
    t = _tarea(db, scope, tid)
    if t.estado != "pendiente":
        bad_request("La limpieza no está pendiente")
    limpiezas.validar(db, t, scope.user)
    audit(db, scope.user, "limpieza_validada", "unidad", t.unit_id, {"limpieza": t.id, "tipo": t.tipo})
    db.commit()
    return {"ok": True, "unidad_estado": t.unit.estado}


@router.post("/{tid}/deshacer")
def undo_done(tid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Vuelve a dejar pendiente una limpieza validada por error."""
    t = _tarea(db, scope, tid)
    if t.estado != "hecha":
        bad_request("La limpieza no está validada")
    t.estado, t.hecha, t.validada_por = "pendiente", None, None
    if t.tipo == "salida" and t.unit.estado == "disponible":
        t.unit.estado = "pendiente_limpieza"
    audit(db, scope.user, "limpieza_deshecha", "unidad", t.unit_id, {"limpieza": t.id})
    db.commit()
    return {"ok": True}


@router.delete("/{tid}")
def cancel_extra(tid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Quita una limpieza extra añadida por error (las de salida y las contratadas dependen de la reserva)."""
    t = _tarea(db, scope, tid)
    if t.tipo != "extra" or t.estado != "pendiente":
        bad_request("Solo se pueden quitar limpiezas extra pendientes")
    t.estado = "anulada"
    audit(db, scope.user, "limpieza_anulada", "unidad", t.unit_id, {"limpieza": t.id})
    db.commit()
    return {"ok": True}


@router.get("/parte.pdf")
def report_pdf(asset_id: int, fecha: date | None = None, nota: str | None = None, scope: Scope = Depends(get_scope),
               db: Session = Depends(get_db)):
    """PDF para imprimir. El Excel del día queda guardado en los documentos del activo."""
    a, f, filas = _datos(db, scope, asset_id, fecha)
    contenido = limpiezas.pdf(a, a.company, f, filas, nota)
    _guardar_excel(db, scope, a, f, filas)
    db.commit()
    return Response(contenido, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{_nombre(a, f, "pdf")}"'})


@router.get("/parte.xlsx")
def report_excel(asset_id: int, fecha: date | None = None, scope: Scope = Depends(get_scope),
                 db: Session = Depends(get_db)):
    a, f, filas = _datos(db, scope, asset_id, fecha)
    return Response(limpiezas.excel(a, f, filas), media_type=XLSX,
                    headers={"Content-Disposition": f'attachment; filename="{_nombre(a, f, "xlsx")}"'})


class EnvioIn(BaseModel):
    asset_id: int
    fecha: date | None = None
    canal: str  # email | whatsapp
    personal_ids: list[int] = Field(default=[], max_length=30)
    telefono: str | None = Field(default=None, max_length=30)  # otro número (WhatsApp)
    email: str | None = Field(default=None, max_length=160)  # otro correo
    nota: str | None = Field(default=None, max_length=1000)


@router.post("/parte/enviar")
def send_report(data: EnvioIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Envía el parte al personal de limpieza elegido o al número / correo indicado. Correo: con el PDF adjunto.
    WhatsApp: enlace con el parte escrito para pulsar «Enviar»."""
    a, f, filas = _datos(db, scope, data.asset_id, data.fecha)
    if not (data.personal_ids or data.telefono or data.email):
        bad_request("Elija a quién se envía el parte")
    personas = destinatarios(db, data.personal_ids, a.id, data.canal) if data.personal_ids else []
    txt = limpiezas.texto(a, f, filas, data.nota)
    pend = [x for x in filas if x["estado"] == "pendiente"]
    asunto = f"Parte de limpieza · {a.nombre} · {f:%d/%m/%Y} · {len(pend)} limpieza(s)"
    html = avisos._html(f"Parte de limpieza · {f:%d/%m/%Y}", (
        f"<p><b>{escape(a.nombre)}</b> · {len(pend)} limpieza(s). Primero las de <b>LLEGADA HOY</b>. "
        "Se adjunta el parte en PDF para imprimirlo.</p>"
        + avisos._tabla(["Apartamento", "Limpieza", "Prioridad"],
                        [[x["codigo"], x["motivo"], limpiezas._prioridad(x, f)] for x in pend])
        + (f"<p><b>Nota:</b> {escape(data.nota)}</p>" if data.nota else "")))
    adjunto = [(_nombre(a, f, "pdf"), limpiezas.pdf(a, a.company, f, filas, data.nota), "application/pdf")]
    clave = f"parte_limpieza:{a.id}:{f.isoformat()}"
    res = despachar(db, personas, data.canal, clave, asunto, txt, html, adjunto if data.canal == "email" else None)
    if data.canal == "whatsapp" and data.telefono:
        movil = firma_contrato.movil_whatsapp(data.telefono)
        if not movil:
            bad_request("El número indicado no es un móvil válido para WhatsApp")
        res.append({"nombre": "Otro número", "canal": "whatsapp", "destino": movil, "ok": True,
                    "whatsapp": f"https://wa.me/{movil}?text={quote(txt)}"})
    if data.canal == "email" and data.email:
        if not avisos.configurado():
            bad_request("El correo no está configurado en el servidor: envíelo por WhatsApp")
        r = {"nombre": "Otro correo", "canal": "email", "destino": data.email}
        try:
            avisos.enviar(data.email, asunto, txt, html, adjunto)
            r["ok"] = True
        except Exception as e:  # noqa: BLE001
            r["ok"], r["error"] = False, str(e)[:200]
        db.add(EmailLog(clave=clave, tipo="parte_limpieza", destinatario=data.email, asunto=asunto[:200], ok=r["ok"],
                        error=r.get("error")))
        res.append(r)
    doc = _guardar_excel(db, scope, a, f, filas)
    audit(db, scope.user, "enviar_parte_limpieza", "activo", a.id, {
        "fecha": f.isoformat(), "canal": data.canal, "destinos": [x["destino"] for x in res],
        "limpiezas": [x["codigo"] for x in pend]})
    db.commit()
    return {"enviados": res, "documento_id": doc.id}
