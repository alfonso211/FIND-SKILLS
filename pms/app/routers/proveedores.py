"""Fichero de proveedores del grupo. No depende de ninguna sociedad: lo usan todas (órdenes de trabajo, plan
preventivo, personal de subcontratas)."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .. import nif
from ..database import get_db
from ..models import TIPOS_PERSONA, Expense, Supplier
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/proveedores", tags=["proveedores"])

ESPANA = ("", "españa", "espana", "es", "esp", "spain")


class SupplierIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=200)
    tipo_persona: str = "empresa"
    nif: str | None = Field(default=None, max_length=20)
    direccion: str | None = Field(default=None, max_length=300)
    cp: str | None = Field(default=None, max_length=10)
    municipio: str | None = Field(default=None, max_length=100)
    provincia: str | None = Field(default=None, max_length=60)
    pais: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    telefono: str | None = Field(default=None, max_length=40)
    persona_contacto: str | None = Field(default=None, max_length=160)
    actividad: str | None = Field(default=None, max_length=160)
    activo: bool = True
    notas: str | None = None


def _out(p: Supplier) -> dict:
    d = p.to_dict()
    d["tipo_persona_nombre"] = TIPOS_PERSONA.get(p.tipo_persona, p.tipo_persona)
    return d


def _validar(db: Session, data: SupplierIn, pid: int | None = None) -> dict:
    if data.tipo_persona not in TIPOS_PERSONA:
        bad_request(f"Tipo no válido. Opciones: {', '.join(TIPOS_PERSONA)}")
    v = data.model_dump()
    v["nombre"] = " ".join(data.nombre.split())
    v["nif"] = nif.normalizar(data.nif)
    if v["nif"] and (data.pais or "").strip().lower() in ESPANA:
        t = nif.tipo(v["nif"])
        if t is None:
            bad_request(f"El NIF {v['nif']} no es válido (revise la letra o el dígito de control)")
        if data.tipo_persona == "empresa" and t != "CIF":
            bad_request("Una empresa se identifica con CIF; un autónomo o una persona física, con DNI o NIE")
        if data.tipo_persona != "empresa" and t == "CIF":
            bad_request("Con CIF, el tipo debe ser «Empresa»")
    otros = select(Supplier).where(Supplier.id != pid) if pid else select(Supplier)
    if v["nif"]:
        dup = db.scalar(otros.where(Supplier.nif == v["nif"]))
        if dup:
            bad_request(f"Ya existe el proveedor «{dup.nombre}» con el NIF {v['nif']}")
    clave = nif.nombre_clave(v["nombre"])
    for p in db.scalars(otros):  # sin tildes ni mayúsculas: se compara aquí (el fichero es pequeño)
        if nif.nombre_clave(p.nombre) == clave and not (v["nif"] and p.nif and p.nif != v["nif"]):
            bad_request(f"Ya existe el proveedor «{p.nombre}»: edite esa ficha en lugar de crear otra")
    return v


def _puede_ver(scope: Scope) -> None:
    if not (scope.has_any("mantenimiento.ver") or scope.has_any("documentos.ver")):
        raise HTTPException(403, "Sin permiso para ver proveedores")


def _puede_editar(scope: Scope) -> None:
    """Dan de alta proveedores mantenimiento y quien registra documentos y gastos (recepción, administración…):
    el fichero es común a todos los activos y se va completando según llegan facturas."""
    if not (scope.has_any("mantenimiento.editar") or scope.has_any("documentos.editar")):
        raise HTTPException(403, "Sin permiso para gestionar proveedores")


def _puede_borrar(scope: Scope) -> None:
    comp = scope.company_level_ids("documentos.editar")
    if not (scope.has_any("mantenimiento.editar") or comp is None or comp):
        raise HTTPException(403, "Solo mantenimiento o la dirección pueden borrar proveedores")


def _enlazar_gastos(db: Session, p: Supplier) -> None:
    """Los gastos anotados con ese proveedor antes de tener ficha quedan enlazados a ella."""
    for g in db.scalars(select(Expense).where(Expense.supplier_id.is_(None), Expense.proveedor.is_not(None))):
        if nif.nombre_clave(g.proveedor) == nif.nombre_clave(p.nombre):
            g.supplier_id = p.id


@router.get("")
def list_suppliers(q: str | None = None, solo_activos: bool = False, scope: Scope = Depends(get_scope),
                   db: Session = Depends(get_db)):
    _puede_ver(scope)
    stmt = select(Supplier)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Supplier.nombre.ilike(like), Supplier.nif.ilike(like), Supplier.actividad.ilike(like),
                              Supplier.email.ilike(like), Supplier.telefono.ilike(like),
                              Supplier.municipio.ilike(like)))
    if solo_activos:
        stmt = stmt.where(Supplier.activo)
    return [_out(p) for p in db.scalars(stmt.order_by(Supplier.nombre).limit(1000))]


@router.get("/{pid}")
def get_supplier(pid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _puede_ver(scope)
    return _out(get_or_404(db, Supplier, pid))


@router.post("", status_code=201)
def create_supplier(data: SupplierIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _puede_editar(scope)
    p = Supplier(**_validar(db, data))
    db.add(p)
    db.flush()
    _enlazar_gastos(db, p)
    audit(db, scope.user, "crear", "proveedor", p.id, {"nombre": p.nombre, "nif": p.nif})
    db.commit()
    return _out(p)


@router.put("/{pid}")
def update_supplier(pid: int, data: SupplierIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _puede_editar(scope)
    p = get_or_404(db, Supplier, pid)
    antes = p.to_dict()
    for k, v in _validar(db, data, pid).items():
        setattr(p, k, v)
    _enlazar_gastos(db, p)
    audit(db, scope.user, "editar", "proveedor", pid, {k: v for k, v in p.to_dict().items() if antes.get(k) != v})
    db.commit()
    return _out(p)


@router.delete("/{pid}")
def delete_supplier(pid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Las órdenes de trabajo y los gastos guardan el nombre del proveedor: borrar la ficha no cambia el histórico."""
    _puede_borrar(scope)
    p = get_or_404(db, Supplier, pid)
    for g in db.scalars(select(Expense).where(Expense.supplier_id == pid)):
        g.supplier_id = None  # el gasto conserva el nombre del proveedor
    audit(db, scope.user, "borrar", "proveedor", pid, {"nombre": p.nombre, "nif": p.nif})
    db.delete(p)
    db.commit()
    return {"ok": True}
