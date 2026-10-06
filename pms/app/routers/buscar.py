"""Buscador del panel de control: un dato (documento, apartamento, cliente, teléfono, localizador, factura, OT…) y
se muestran todas las coincidencias que el usuario puede ver, sin cambiar de página."""
import re
from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .. import nif
from ..database import get_db
from ..models import Asset, Contact, Invoice, Lease, Reservation, Supplier, Unit, WorkOrder
from ..security import Scope, get_scope
from ..utils import scoped
from .estructura import PERMISO_TERCERO, _contact_filter, unidades_de
from ..facturacion import factura_out
from .facturas import _filtrar
from .mantenimiento import _wo_out
from .turistico import _res_out

router = APIRouter(prefix="/api", tags=["buscador"])

LIMITE = 12
TIPOS_CLIENTE = {"huesped": "Huésped", "inquilino": "Inquilino", "cliente_garaje": "Cliente de garaje"}


def _clave(s: str | None) -> str:
    """Código comparable: sin guiones, espacios ni mayúsculas («a127» = «A-127»)."""
    return re.sub(r"[^A-Z0-9]", "", (s or "").upper())


def _comodin(palabra: str) -> str:
    """Patrón SQL que no distingue tildes: las letras que pueden llevarla valen por cualquier carácter."""
    return "%" + re.sub(r"[aeiouncAEIOUNCáéíóúüñçÁÉÍÓÚÜÑÇ]", "_", palabra) + "%"


def _clientes(db: Session, scope: Scope, q: str) -> list[Contact]:
    palabras = q.split()
    doc, tel = nif.normalizar(q), nif.telefono_clave(q)
    claves = [nif.nombre_clave(p) for p in palabras]
    out = []
    for tipo in PERMISO_TERCERO:
        if not scope.has_any(f"{PERMISO_TERCERO[tipo]}.ver"):
            continue
        nombre = and_(*[or_(Contact.nombre.ilike(_comodin(p)), Contact.apellidos.ilike(_comodin(p))) for p in palabras])
        cond = [nombre, Contact.email.ilike(f"%{q}%")]
        if doc and len(doc) >= 4:
            cond.append(Contact.documento_num.ilike(f"%{doc}%"))
        if tel and len(tel) >= 6:
            cond.append(Contact.telefono.ilike("%" + "%".join(tel[-6:]) + "%"))  # con espacios o guiones
        stmt = select(Contact).where(Contact.tipo == tipo, or_(*cond))
        visible = _contact_filter(scope, tipo, "ver")
        if visible is not None:
            stmt = stmt.where(visible)
        for c in db.scalars(stmt.limit(200)):
            completo = nif.nombre_clave(f"{c.nombre} {c.apellidos or ''}")
            por_nombre = all(k in completo for k in claves)
            por_dato = (doc and c.documento_num and doc in nif.normalizar(c.documento_num)) or \
                (tel and len(tel) >= 6 and tel[-6:] in (nif.telefono_clave(c.telefono) or "")) or \
                (c.email and q.lower() in c.email.lower())
            if por_nombre or por_dato:
                out.append(c)
    return out[:LIMITE]


@router.get("/buscar")
def buscar(q: str, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    q = " ".join(q.split())[:80]
    vacio = {"q": q, "clientes": [], "reservas": [], "unidades": [], "contratos": [], "facturas": [], "ordenes": [],
             "proveedores": []}
    if len(q) < 2:
        return vacio
    hoy = date.today()
    nombres = dict(db.execute(select(Asset.id, Asset.nombre)).all())
    out = dict(vacio)

    # clientes (huéspedes, inquilinos y clientes de garaje), con lo que tienen ahora
    clientes = _clientes(db, scope, q)
    uds = unidades_de(db, [c.id for c in clientes])
    out["clientes"] = [{"id": c.id, "tipo": c.tipo, "tipo_nombre": TIPOS_CLIENTE.get(c.tipo, c.tipo),
                        "nombre": f"{c.nombre} {c.apellidos or ''}".strip(), "documento": c.documento_num,
                        "telefono": c.telefono, "email": c.email, "activo": nombres.get(c.asset_id),
                        "unidades": [u["codigo"] for u in uds.get(c.id, [])]} for c in clientes]

    # apartamentos y plazas por su código
    clave = _clave(q)
    unidades: list[Unit] = []
    ids_unidad = scope.asset_ids("activos.ver")
    if clave:
        for u in db.scalars(scoped(select(Unit), Unit.asset_id, ids_unidad)):
            cu = _clave(u.codigo)
            if cu == clave or (len(clave) >= 3 and cu.startswith(clave)):
                unidades.append(u)
        unidades.sort(key=lambda u: (_clave(u.codigo) != clave, u.codigo))
        unidades = unidades[:LIMITE]
    if unidades:
        ahora = {r.unit_id: r for r in db.scalars(select(Reservation).where(
            Reservation.unit_id.in_([u.id for u in unidades]), Reservation.estado.in_(("confirmada", "checkin")),
            Reservation.fecha_entrada <= hoy, or_(Reservation.fecha_salida > hoy, Reservation.estado == "checkin")))}
        alquiler = {l.unit_id: l for l in db.scalars(select(Lease).where(
            Lease.unit_id.in_([u.id for u in unidades]), Lease.estado == "vigente", Lease.fecha_inicio <= hoy,
            or_(Lease.fecha_fin.is_(None), Lease.fecha_fin >= hoy)))}
        for u in unidades:
            r, l = ahora.get(u.id), alquiler.get(u.id)
            ocupante = (f"{r.guest.nombre} {r.guest.apellidos or ''}".strip() + f" (hasta {r.fecha_salida:%d/%m/%Y})") if r \
                else (f"{l.tenant.nombre} {l.tenant.apellidos or ''}".strip() + " (alquiler)") if l else None
            out["unidades"].append({**u.to_dict(), "activo": nombres.get(u.asset_id),
                                    "modalidad": db.get(Asset, u.asset_id).modalidad, "ocupante": ocupante})

    # reservas: por localizador, de los clientes encontrados o de los apartamentos encontrados
    ids_res = scope.asset_ids("reservas.ver")
    if ids_res is None or ids_res:
        cond = [Reservation.localizador.ilike(f"%{q}%")]
        huespedes = [c.id for c in clientes if c.tipo in ("huesped", "cliente_garaje")]
        if huespedes:
            cond.append(Reservation.guest_id.in_(huespedes))
        if unidades:
            cond.append(and_(Reservation.unit_id.in_([u.id for u in unidades]), Reservation.fecha_salida >= hoy))
        stmt = scoped(select(Reservation).join(Unit), Unit.asset_id, ids_res).where(or_(*cond))
        filas = list(db.scalars(stmt.order_by(Reservation.fecha_entrada.desc()).limit(200)))
        # primero las vigentes y próximas, después el histórico
        filas.sort(key=lambda r: (not (r.estado in ("confirmada", "checkin") and r.fecha_salida >= hoy), -r.fecha_entrada.toordinal()))
        out["reservas"] = [_res_out(r) for r in filas[:LIMITE]]

    # contratos de alquiler
    ids_alq = scope.asset_ids("alquiler.ver")
    if ids_alq is None or ids_alq:
        cond = [Lease.referencia.ilike(f"%{q}%")]
        inquilinos = [c.id for c in clientes if c.tipo in ("inquilino", "cliente_garaje")]
        if inquilinos:
            cond.append(Lease.tenant_id.in_(inquilinos))
        if unidades:
            cond.append(Lease.unit_id.in_([u.id for u in unidades]))
        stmt = scoped(select(Lease).join(Unit), Unit.asset_id, ids_alq).where(or_(*cond))
        for l in db.scalars(stmt.order_by(Lease.fecha_inicio.desc()).limit(LIMITE)):
            out["contratos"].append({**l.to_dict(), "unidad": l.unit.codigo, "asset_id": l.unit.asset_id,
                                     "activo": nombres.get(l.unit.asset_id),
                                     "inquilino": f"{l.tenant.nombre} {l.tenant.apellidos or ''}".strip(),
                                     "tenant_tipo": l.tenant.tipo})

    # facturas: número, cliente, NIF o concepto
    if scope.has_any("facturas.ver"):
        stmt = _filtrar(scope, None, None, None, q)
        out["facturas"] = [{**factura_out(f), "activo": nombres.get(f.asset_id)}
                           for f in db.scalars(stmt.order_by(Invoice.fecha_expedicion.desc()).limit(LIMITE))]

    # órdenes de trabajo: «OT-00012», «12», título o apartamento
    ids_mto = scope.asset_ids("mantenimiento.ver")
    if ids_mto is None or ids_mto:
        cond = [WorkOrder.titulo.ilike(f"%{q}%")]
        num = re.fullmatch(r"(?:OT-?)?0*(\d{1,7})", q.upper().replace(" ", ""))
        if num:
            cond.append(WorkOrder.id == int(num.group(1)))
        if unidades:
            cond.append(WorkOrder.unit_id.in_([u.id for u in unidades]))
        stmt = scoped(select(WorkOrder), WorkOrder.asset_id, ids_mto).where(or_(*cond))
        out["ordenes"] = [{**_wo_out(w, db), "activo": nombres.get(w.asset_id)}
                          for w in db.scalars(stmt.order_by(WorkOrder.fecha_apertura.desc()).limit(LIMITE))]

    # proveedores (fichero común del grupo)
    if scope.has_any("mantenimiento.ver") or scope.has_any("documentos.ver"):
        like, doc = f"%{q}%", nif.normalizar(q)
        cond = [Supplier.nombre.ilike(_comodin(q)), Supplier.actividad.ilike(like), Supplier.telefono.ilike(like),
                Supplier.email.ilike(like)]
        if doc and len(doc) >= 4:
            cond.append(Supplier.nif.ilike(f"%{doc}%"))
        out["proveedores"] = [p.to_dict() for p in db.scalars(select(Supplier).where(or_(*cond))
                                                               .order_by(Supplier.nombre).limit(LIMITE))]
    return out
