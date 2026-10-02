"""Escaneo de documentos de identidad: lectura automática, copia cifrada en la ficha del cliente.

Dos maneras de escanear:
- sobre un cliente que ya existe: POST /api/terceros/{id}/documentos
- antes de que exista (al empezar una reserva o un alta): POST /api/documentos/leer. La copia queda
  pendiente y se adjunta al cliente cuando se crea (campo `documentos` del alta). Las pendientes que nadie
  adjunta se borran a las 24 h.
"""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import documentos, ocr_documentos
from ..database import get_db
from ..models import Contact, ContactDocument, User
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404
from .estructura import _contact_filter

router = APIRouter(prefix="/api", tags=["documentos de identidad"])

CADUCIDAD_PENDIENTES = timedelta(hours=24)


def _tercero(db: Session, scope: Scope, cid: int, accion: str) -> Contact:
    c = get_or_404(db, Contact, cid)
    cond = _contact_filter(scope, c.tipo, accion)
    if cond is not None and not db.scalar(select(Contact.id).where(Contact.id == cid, cond)):
        raise HTTPException(403, "Sin permiso sobre este cliente")
    return c


def _acceso(db: Session, scope: Scope, d: ContactDocument, accion: str) -> None:
    if d.contact_id is None:  # aún sin cliente: solo quien lo escaneó
        if d.user_id != scope.user.id:
            raise HTTPException(403, "Sin permiso sobre este documento")
    else:
        _tercero(db, scope, d.contact_id, accion)


def _doc_out(d: ContactDocument, usuario: str | None = None) -> dict:
    return {"id": d.id, "tipo": d.tipo, "cara": d.cara, "mime": d.mime, "tamano": d.tamano,
            "subido": d.subido.isoformat(), "usuario": usuario}


def _leer_subida(f: UploadFile | None) -> bytes | None:
    if f is None or not f.filename:
        return None
    datos = f.file.read(ocr_documentos.TAM_MAX + 1)
    if len(datos) > ocr_documentos.TAM_MAX:
        bad_request("El fichero supera los 15 MB")
    return datos or None


def _guardar_caras(db: Session, scope: Scope, contact_id: int | None, anverso: UploadFile | None,
                   reverso: UploadFile | None, tipo: str | None) -> tuple[list[ContactDocument], dict]:
    """Valida las caras recibidas, las lee y guarda las copias cifradas."""
    caras = [(nombre, d) for nombre, d in (("anverso", _leer_subida(anverso)),
                                            ("reverso", _leer_subida(reverso))) if d]
    if not caras:
        bad_request("Adjunte al menos una cara del documento")
    mimes = []
    for _, d in caras:
        try:
            mimes.append(ocr_documentos.a_imagenes(d)[0])
        except ValueError as e:
            bad_request(str(e))
    lectura = ocr_documentos.leer([d for _, d in caras])
    tipo_doc = lectura.get("documento_tipo") or tipo
    guardados = []
    for (cara, d), mime in zip(caras, mimes):
        doc = ContactDocument(contact_id=contact_id, tipo=tipo_doc, cara=cara, fichero=documentos.guardar(d),
                              mime=mime, tamano=len(d), sha256=documentos.huella(d), lectura=lectura,
                              user_id=scope.user.id)
        db.add(doc)
        guardados.append(doc)
    db.flush()
    return guardados, lectura


# Campos de la ficha que se toman del documento cuando la lectura es válida (dígitos de control correctos)
DEL_DOCUMENTO = {"documento_tipo": "documento_tipo", "documento_num": "documento_num", "num_soporte": "num_soporte",
                 "nacionalidad": "nacionalidad", "sexo": "sexo", "fecha_nacimiento": "fecha_nacimiento",
                 "fecha_caducidad_doc": "fecha_caducidad"}


def aplicar_lectura(c: Contact, lectura: dict) -> list[str]:
    """Completa la ficha con lo leído. El nombre y el domicilio solo si estaban vacíos (lo tecleado puede
    llevar tildes, que la zona MRZ no tiene)."""
    aplicado: list[str] = []
    if not (lectura.get("leido") and lectura.get("mrz_valido")):
        return aplicado
    for campo, origen in DEL_DOCUMENTO.items():
        valor = lectura.get(origen)
        if campo.startswith("fecha") and valor:
            valor = date.fromisoformat(valor)
        if valor and getattr(c, campo) != valor:
            setattr(c, campo, valor)
            aplicado.append(campo)
    dom = lectura.get("domicilio") or {}
    for campo, valor in (("apellidos", lectura.get("apellidos")), ("direccion", dom.get("direccion")),
                         ("municipio", dom.get("municipio")), ("pais", dom.get("pais"))):
        if valor and not getattr(c, campo):
            setattr(c, campo, valor)
            aplicado.append(campo)
    return aplicado


def adjuntar_pendientes(db: Session, user: User, ids: list[int], c: Contact) -> list[str]:
    """Adjunta al cliente recién creado las copias que el mismo usuario escaneó antes del alta."""
    docs = list(db.scalars(select(ContactDocument).where(
        ContactDocument.id.in_(ids), ContactDocument.contact_id.is_(None), ContactDocument.user_id == user.id)))
    if len(docs) != len(set(ids)):
        bad_request("Alguna copia del documento ya no está disponible: vuelva a escanearlo")
    for d in docs:
        d.contact_id = c.id
    aplicado = aplicar_lectura(c, docs[0].lectura or {})
    audit(db, user, "adjuntar_documento", "tercero", c.id, {"documentos": ids, "aplicado": aplicado})
    return aplicado


def _purgar_pendientes(db: Session) -> None:
    limite = datetime.now() - CADUCIDAD_PENDIENTES
    for d in db.scalars(select(ContactDocument).where(ContactDocument.contact_id.is_(None),
                                                      ContactDocument.subido < limite)):
        documentos.borrar(d.fichero)
        db.delete(d)


@router.post("/documentos/leer", status_code=201)
def read_document(anverso: UploadFile | None = File(None), reverso: UploadFile | None = File(None),
                  tipo: str | None = Form(None), scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Lee un documento antes de que exista el cliente (al empezar una reserva o un alta). La copia queda
    pendiente hasta que se cree el cliente con `documentos: [ids]`."""
    if not (scope.has_any("reservas.editar") or scope.has_any("alquiler.editar")):
        raise HTTPException(403, "Sin permiso para dar de alta clientes")
    _purgar_pendientes(db)
    guardados, lectura = _guardar_caras(db, scope, None, anverso, reverso, tipo)
    audit(db, scope.user, "escanear_documento", "documento", None,
          {"documentos": [g.id for g in guardados], "leido": lectura.get("leido"), "pendiente": True})
    db.commit()
    return {"documentos": [_doc_out(g, scope.user.nombre) for g in guardados], "lectura": lectura}


@router.post("/terceros/{cid}/documentos", status_code=201)
def scan_document(cid: int, anverso: UploadFile | None = File(None), reverso: UploadFile | None = File(None),
                  tipo: str | None = Form(None), aplicar: bool = Form(True),
                  scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Escanea el documento de un cliente que ya existe: guarda la copia cifrada y completa su ficha.
    (Síncrono a propósito: el OCR tarda unos segundos y así va en un hilo aparte sin bloquear a nadie.)"""
    c = _tercero(db, scope, cid, "editar")
    guardados, lectura = _guardar_caras(db, scope, c.id, anverso, reverso, tipo)
    aplicado = aplicar_lectura(c, lectura) if aplicar else []
    audit(db, scope.user, "escanear_documento", "tercero", c.id,
          {"documentos": [g.id for g in guardados], "tipo": guardados[0].tipo, "leido": lectura.get("leido"),
           "valido": lectura.get("mrz_valido"), "aplicado": aplicado})
    db.commit()
    return {"documentos": [_doc_out(g, scope.user.nombre) for g in guardados], "lectura": lectura,
            "aplicado": aplicado, "tercero": c.to_dict()}


@router.get("/terceros/{cid}/documentos")
def list_documents(cid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _tercero(db, scope, cid, "ver")
    filas = db.execute(select(ContactDocument, User.nombre).outerjoin(User, User.id == ContactDocument.user_id)
                       .where(ContactDocument.contact_id == cid).order_by(ContactDocument.id.desc())).all()
    return [_doc_out(d, n) for d, n in filas]


@router.get("/documentos/{did}")
def view_document(did: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    d = get_or_404(db, ContactDocument, did)
    _acceso(db, scope, d, "ver")
    contenido = documentos.leer(d.fichero)
    audit(db, scope.user, "ver_documento", "tercero", d.contact_id, {"documento": did})  # registro de accesos
    db.commit()
    ext = {"application/pdf": "pdf", "image/png": "png"}.get(d.mime, "jpg")
    return Response(contenido, media_type=d.mime, headers={
        "Content-Disposition": f'inline; filename="documento_{d.contact_id or "nuevo"}_{d.cara}.{ext}"',
        "Cache-Control": "no-store"})


@router.delete("/documentos/{did}")
def delete_document(did: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    d = get_or_404(db, ContactDocument, did)
    _acceso(db, scope, d, "editar")
    documentos.borrar(d.fichero)
    audit(db, scope.user, "borrar_documento", "tercero", d.contact_id, {"documento": did, "tipo": d.tipo})
    db.delete(d)
    db.commit()
    return {"ok": True}
