from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session


def get_or_404(db: Session, model, obj_id: int):
    obj = db.get(model, obj_id)
    if obj is None:
        raise HTTPException(404, f"{model.__name__} {obj_id} no encontrado")
    return obj


def apply(obj, data: BaseModel) -> dict:
    """Aplica solo los campos enviados. Devuelve los cambios para auditoría."""
    changes = {}
    for k, v in data.model_dump(exclude_unset=True).items():
        if k not in obj.__table__.columns:
            continue
        old = getattr(obj, k)
        if old != v:
            changes[k] = [str(old) if old is not None else None, str(v) if v is not None else None]
            setattr(obj, k, v)
    return changes


def bad_request(msg: str):
    raise HTTPException(400, msg)


def scoped(stmt, column, ids: set[int] | None):
    """Restringe una consulta a los ids permitidos (None = sin restricción)."""
    return stmt if ids is None else stmt.where(column.in_(ids or {-1}))
