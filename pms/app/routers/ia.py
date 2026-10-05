"""Peticiones IA: endpoints del asistente (dirección y recepción)."""
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import adjuntos, documentos, ia
from ..database import get_db
from ..security import Scope, audit, get_scope
from ..utils import bad_request

router = APIRouter(prefix="/api/ia", tags=["peticiones IA"])


def _puede(scope: Scope) -> None:
    if not scope.has_any("ia.usar"):
        raise HTTPException(403, "Sin permiso para las Peticiones IA")


class Peticion(BaseModel):
    texto: str = Field(default="", max_length=20000)
    historial: list[dict] = Field(default_factory=list, max_length=400)
    adjuntos: list[str] = Field(default_factory=list, max_length=5)


@router.get("/estado")
def estado(scope: Scope = Depends(get_scope)):
    return {"puede": scope.has_any("ia.usar"), "configurado": ia.configurado()}


@router.post("/adjuntos", status_code=201)
def subir_adjunto(fichero: UploadFile = File(...), scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Documento para que el asistente lo lea (y lo archive si se le pide). Foto o PDF; se guarda cifrado."""
    _puede(scope)
    try:
        datos, mime, nombre = adjuntos.normalizar(fichero.file.read(adjuntos.TAM_MAX + 1),
                                                  (fichero.filename or "documento")[-150:])
    except ValueError as e:
        bad_request(str(e))
    ref = documentos.guardar(datos)
    audit(db, scope.user, "ia_adjunto", "ia", None, {"fichero": ref, "nombre": nombre, "mime": mime})
    db.commit()
    return {"ref": ref, "nombre": nombre, "mime": mime}


@router.post("/peticion")
def peticion(data: Peticion, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _puede(scope)
    if not data.texto.strip() and not data.adjuntos:
        bad_request("Escriba la petición o adjunte un documento")
    return ia.conversar(db, scope, data.historial, data.texto, data.adjuntos)


@router.get("/ficheros/{fichero}")
def descargar(fichero: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Excel creado por el asistente: solo lo descarga quien lo pidió."""
    _puede(scope)
    from sqlalchemy import select

    from ..models import AuditLog
    nombre = next((d["nombre"] for d in db.scalars(select(AuditLog.detalle).where(
        AuditLog.user_id == scope.user.id, AuditLog.accion == "ia_excel").order_by(AuditLog.id.desc()).limit(500))
        if d and d.get("fichero") == fichero), None)
    if not nombre:
        raise HTTPException(404, "Fichero no encontrado")
    return Response(documentos.leer(fichero),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
