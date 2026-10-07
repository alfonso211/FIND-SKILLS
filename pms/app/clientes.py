"""Fichas de clientes separadas por activo: cada recepción tiene las de los clientes que se han alojado (o han
contratado) en su activo y no comparte clientes con las demás. Quien gestiona la sociedad o el grupo los ve todos.

Si un mismo cliente va a otro activo, allí se le abre otra ficha (copia de sus datos, sin los documentos
escaneados), de modo que cada recepción trabaja solo con la suya."""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import nif
from .models import Asset, Contact
from .utils import bad_request, get_or_404

CAMPOS_COPIA = ("nombre", "apellidos", "documento_tipo", "documento_num", "nacionalidad", "fecha_nacimiento", "sexo",
                "num_soporte", "fecha_caducidad_doc", "email", "telefono", "direccion", "cp", "municipio", "provincia",
                "pais", "municipio_ine", "iban")


def del_activo(db: Session, scope, cid: int, asset: Asset, tipo: str) -> Contact:
    """La ficha `cid` para usarla en `asset`. Si es de otro activo se abre una ficha propia (copia de sus datos);
    la de un activo sin asignar (fichas antiguas) pasa a ser de este. Solo con fichas que el usuario puede ver:
    una recepción no puede traerse un cliente de otra."""
    from .routers.estructura import _contact_filter  # import local: el router usa este módulo
    c = get_or_404(db, Contact, cid)
    if c.company_id != asset.company_id or c.tipo != tipo:
        bad_request("El cliente no pertenece a la sociedad del activo")
    cond = _contact_filter(scope, tipo, "ver")
    if cond is not None and not db.scalar(select(Contact.id).where(Contact.id == cid, cond)):
        raise HTTPException(403, "Sin permiso sobre este cliente")
    if c.asset_id is None:
        c.asset_id = asset.id
        return c
    if c.asset_id == asset.id:
        return c
    doc = nif.normalizar(c.documento_num)
    propia = por_documento(db, asset, tipo, doc) if doc else None
    if propia:
        return propia
    copia = Contact(company_id=c.company_id, asset_id=asset.id, tipo=tipo,
                    **{k: getattr(c, k) for k in CAMPOS_COPIA})
    db.add(copia)
    db.flush()
    return copia


def por_documento(db: Session, asset: Asset, tipo: str, doc: str | None) -> Contact | None:
    if not doc:
        return None
    return db.scalar(select(Contact).where(Contact.asset_id == asset.id, Contact.tipo == tipo,
                                           func.upper(Contact.documento_num) == doc).order_by(Contact.id))


def nueva(asset: Asset, tipo: str, **datos) -> Contact:
    return Contact(company_id=asset.company_id, asset_id=asset.id, tipo=tipo, **datos)
