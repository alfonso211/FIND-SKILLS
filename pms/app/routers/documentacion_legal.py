"""Administración → Documentación legal: checklist por activo, documentos escaneados (PDF cifrado), impresión del
checklist, envío de un documento por correo y resumen de todos los activos."""
import re
from datetime import date, datetime
from html import escape

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import avisos, documentos
from .. import documentacion_legal as dl
from ..database import get_db
from ..models import Asset, EmailLog, LegalFile, LegalItem
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404, scoped
from .gastos import _fichero

router = APIRouter(prefix="/api/documentacion-legal", tags=["documentación legal"])
MAX_ENVIO = 20 * 1024 * 1024  # adjuntos por correo


class ItemIn(BaseModel):
    no_aplica: bool = False
    motivo: str | None = Field(default=None, max_length=300)
    fecha_documento: date | None = None
    vencimiento: date | None = None
    notas: str | None = Field(default=None, max_length=2000)


class ExtraIn(BaseModel):
    titulo: str = Field(min_length=3, max_length=200)


class EnvioIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=160)
    nota: str | None = Field(default=None, max_length=1000)


def _activo(db: Session, scope: Scope, asset_id: int, editar: bool = False) -> Asset:
    scope.require_asset("legal.editar" if editar else "legal.ver", asset_id)
    return get_or_404(db, Asset, asset_id)


def _clave_valida(a: Asset, clave: str) -> None:
    if not (clave.startswith("extra-") or clave in {c[0] for c in dl.aplicables(a.modalidad)}):
        bad_request("Ese documento no está en el checklist de este activo")


def _item(db: Session, a: Asset, clave: str, crear: bool, scope: Scope) -> LegalItem | None:
    it = db.scalar(select(LegalItem).where(LegalItem.asset_id == a.id, LegalItem.clave == clave))
    if it is None and crear:
        _clave_valida(a, clave)
        it = LegalItem(asset_id=a.id, clave=clave, user_id=scope.user.id)
        db.add(it)
        db.flush()
    return it


def _salida(db: Session, a: Asset) -> dict:
    filas = dl.checklist(db, a)
    return {"asset_id": a.id, "activo": a.nombre, "modalidad": a.modalidad, "grupos": dl.GRUPOS,
            "items": filas, "resumen": dl.resumen(filas)}


@router.get("")
def get_checklist(asset_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return _salida(db, _activo(db, scope, asset_id))


@router.get("/resumen")
def summary(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Estado de todos los activos que ve el usuario."""
    scope.require_any("legal.ver")
    out = []
    for a in db.scalars(scoped(select(Asset).where(Asset.activo), Asset.id, scope.asset_ids("legal.ver"))
                        .order_by(Asset.codigo)):
        filas = dl.checklist(db, a)
        out.append({"asset_id": a.id, "activo": a.nombre, "modalidad": a.modalidad, **dl.resumen(filas),
                    "pendientes_lista": [x["titulo"] for x in filas if x["estado"] in dl.PENDIENTES]})
    return out


@router.put("/{asset_id}/{clave}")
def update_item(asset_id: int, clave: str, data: ItemIn, scope: Scope = Depends(get_scope),
                db: Session = Depends(get_db)):
    a = _activo(db, scope, asset_id, editar=True)
    it = _item(db, a, clave, True, scope)
    if data.no_aplica and not (data.motivo or "").strip():
        bad_request("Indique por qué no aplica")
    if data.fecha_documento and data.vencimiento and data.vencimiento < data.fecha_documento:
        bad_request("El vencimiento no puede ser anterior a la fecha del documento")
    it.no_aplica, it.motivo = data.no_aplica, (data.motivo or "").strip() or None
    it.fecha_documento, it.notas = data.fecha_documento, (data.notas or "").strip() or None
    it.vencimiento = data.vencimiento or dl.vencimiento_por_defecto(clave, data.fecha_documento)
    it.actualizado, it.user_id = datetime.now(), scope.user.id
    audit(db, scope.user, "editar", "documentacion_legal", it.id, {"activo": a.codigo, "clave": clave,
                                                                    "no_aplica": it.no_aplica})
    db.commit()
    return _salida(db, a)


@router.post("/{asset_id}/extra", status_code=201)
def add_extra(asset_id: int, data: ExtraIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Punto propio del activo (un documento que no está en el catálogo)."""
    a = _activo(db, scope, asset_id, editar=True)
    usados = [int(m.group(1)) for c in db.scalars(select(LegalItem.clave).where(LegalItem.asset_id == a.id))
              if (m := re.fullmatch(r"extra-(\d+)", c))]
    it = LegalItem(asset_id=a.id, clave=f"extra-{max(usados, default=0) + 1}", titulo=data.titulo.strip(),
                   user_id=scope.user.id)
    db.add(it)
    db.flush()
    audit(db, scope.user, "crear", "documentacion_legal", it.id, {"activo": a.codigo, "titulo": it.titulo})
    db.commit()
    return _salida(db, a)


@router.delete("/{asset_id}/extra/{clave}")
def delete_extra(asset_id: int, clave: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a = _activo(db, scope, asset_id, editar=True)
    it = _item(db, a, clave, False, scope)
    if it is None or not clave.startswith("extra-"):
        raise HTTPException(404, "Punto no encontrado")
    if it.ficheros:
        bad_request("Tiene documentos: bórrelos antes")
    audit(db, scope.user, "borrar", "documentacion_legal", it.id, {"activo": a.codigo, "titulo": it.titulo})
    db.delete(it)
    db.commit()
    return _salida(db, a)


@router.post("/{asset_id}/{clave}/ficheros", status_code=201)
def upload(asset_id: int, clave: str, ficheros: list[UploadFile] = File(...),
           fecha_documento: date | None = Form(None), vencimiento: date | None = Form(None),
           scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Escaneo (PDF o fotos; varias fotos se unen en un PDF)."""
    a = _activo(db, scope, asset_id, editar=True)
    it = _item(db, a, clave, True, scope)
    datos, mime, nombre = _fichero(ficheros)
    huella = documentos.huella(datos)
    if any(f.sha256 == huella for f in it.ficheros):
        raise HTTPException(409, "Ese mismo documento ya está guardado en este punto")
    titulo = it.titulo or dl.POR_CLAVE[clave][2]
    base = re.sub(r"[^\w\-]+", "_", f"{a.codigo}_{titulo}")[:90].strip("_")
    nombre = f"{base}_{date.today():%Y%m%d}.{'pdf' if mime == 'application/pdf' else nombre.rsplit('.', 1)[-1]}"
    it.ficheros.append(LegalFile(nombre=nombre, fichero=documentos.guardar(datos), mime=mime, tamano=len(datos),
                                 sha256=huella, user_id=scope.user.id))
    if fecha_documento:
        it.fecha_documento = fecha_documento
        it.vencimiento = vencimiento or dl.vencimiento_por_defecto(clave, fecha_documento) or it.vencimiento
    elif vencimiento:
        it.vencimiento = vencimiento
    it.no_aplica, it.actualizado = False, datetime.now()
    db.flush()
    audit(db, scope.user, "subir", "documentacion_legal", it.id, {"activo": a.codigo, "clave": clave})
    db.commit()
    return _salida(db, a)


def _fichero_de(db: Session, scope: Scope, fid: int, editar: bool = False) -> tuple[LegalFile, LegalItem, Asset]:
    f = get_or_404(db, LegalFile, fid)
    it = db.get(LegalItem, f.item_id)
    return f, it, _activo(db, scope, it.asset_id, editar)


@router.get("/ficheros/{fid}")
def view(fid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    f, it, a = _fichero_de(db, scope, fid)
    audit(db, scope.user, "ver", "documentacion_legal", it.id, {"fichero": f.nombre})
    db.commit()
    return Response(documentos.leer(f.fichero), media_type=f.mime, headers={
        "Content-Disposition": f'inline; filename="{f.nombre}"', "Cache-Control": "private, no-store"})


@router.delete("/ficheros/{fid}")
def delete_file(fid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    f, it, a = _fichero_de(db, scope, fid, editar=True)
    audit(db, scope.user, "borrar", "documentacion_legal", it.id, {"fichero": f.nombre})
    fichero = f.fichero
    it.ficheros.remove(f)
    db.commit()
    documentos.borrar(fichero)
    return _salida(db, a)


@router.post("/{asset_id}/{clave}/enviar")
def send(asset_id: int, clave: str, data: EnvioIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Envía por correo los documentos de un punto (p. ej. el seguro o la licencia a un inspector o a la gestoría)."""
    a = _activo(db, scope, asset_id)
    it = _item(db, a, clave, False, scope)
    if it is None or not it.ficheros:
        bad_request("Este punto no tiene documentos")
    if not avisos.configurado():
        bad_request("El correo no está configurado en el servidor")
    adjuntos = [(f.nombre, documentos.leer(f.fichero), f.mime) for f in it.ficheros]
    if sum(len(x[1]) for x in adjuntos) > MAX_ENVIO:
        bad_request("Los documentos superan 20 MB: envíelos de uno en uno o descárguelos")
    titulo = it.titulo or dl.POR_CLAVE[clave][2]
    asunto = f"{titulo} · {a.nombre}"
    texto = (f"Le adjuntamos: {titulo} ({a.nombre}).\n" + (f"\n{data.nota}\n" if data.nota else "")
             + f"\n{scope.user.nombre}")
    html = avisos._html(asunto, f"<p>Le adjuntamos: <b>{escape(titulo)}</b> ({escape(a.nombre)}).</p>"
                        + (f"<p>{escape(data.nota)}</p>" if data.nota else "") + f"<p>{escape(scope.user.nombre)}</p>")
    ok, error = True, None
    try:
        avisos.enviar(data.email, asunto, texto, html, adjuntos)
    except Exception as e:  # noqa: BLE001
        ok, error = False, str(e)[:300]
    db.add(EmailLog(clave=f"documentacion_legal_envio:{it.id}", tipo="documentacion_legal_envio",
                    user_id=scope.user.id, destinatario=data.email, asunto=asunto[:200], ok=ok, error=error))
    audit(db, scope.user, "enviar", "documentacion_legal", it.id, {"destino": data.email, "ok": ok})
    db.commit()
    if not ok:
        raise HTTPException(502, f"No se pudo enviar: {error}")
    return {"ok": True, "enviados": len(adjuntos)}


@router.get("/{asset_id}/checklist.pdf")
def checklist_pdf(asset_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a = _activo(db, scope, asset_id)
    pdf = dl.pdf_checklist(db, a, dl.checklist(db, a))
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="Documentacion_legal_{a.codigo}_{date.today():%Y%m%d}.pdf"'})
