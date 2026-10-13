"""Dotación de los apartamentos: catálogo 3 llaves, dotación habitual por tipología (la fija Recepción) y artículos
nuevos («Otra dotación»)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import dotacion as dot
from ..database import get_db
from ..models import Asset, DotacionArticulo, DotacionHabitual, Unit
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/dotacion", tags=["dotación"])


class Item(BaseModel):
    codigo: str = Field(max_length=12)
    zona: str = Field(max_length=20)
    articulo: str = Field(max_length=160)
    cantidad: str = Field(max_length=80)


class HabitualIn(BaseModel):
    asset_id: int
    tipologia: str = Field(max_length=60)
    perfil: str = Field(max_length=10)
    items: list[Item]


class ArticuloIn(BaseModel):
    asset_id: int | None = None
    zona: str = Field(max_length=20)
    articulo: str = Field(min_length=2, max_length=160)


@router.get("/catalogo")
def catalog(asset_id: int | None = None, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    scope.require_any("reservas.ver")
    return {"zonas": dot.ZONAS, "perfiles": dot.PERFILES, "codigos_perfil": dot.CODIGO_PERFIL,
            "articulos": dot.articulos(db, asset_id)}


@router.get("/habitual")
def usual(asset_id: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Tipologías de los apartamentos turísticos del activo con su dotación habitual (o la estándar propuesta)."""
    scope.require_asset("reservas.ver", asset_id)
    filas = db.execute(select(Unit.tipologia, func.count()).where(Unit.asset_id == asset_id, Unit.uso == "apartamento")
                       .group_by(Unit.tipologia).order_by(Unit.tipologia)).all()
    out = []
    for tip, n in filas:
        h = dot.habitual(db, asset_id, tip)
        perfil = h.perfil if h else dot.perfil_de(tip)
        out.append({"tipologia": tip or "", "unidades": n, "perfil": perfil, "fijada": h is not None,
                    "actualizada": h.actualizada.isoformat() if h else None,
                    "items": list(h.items) if h else dot.estandar(perfil)})
    return out


@router.put("/habitual")
def usual_save(data: HabitualIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Recepción fija la dotación habitual de una tipología: es la que se entrega (y se imprime con el contrato)."""
    scope.require_asset("reservas.editar", data.asset_id)
    get_or_404(db, Asset, data.asset_id)
    if data.perfil not in dot.PERFILES:
        bad_request("Perfil de dotación no válido")
    items = dot.limpiar([i.model_dump() for i in data.items])
    if not items:
        bad_request("La dotación está vacía: marque al menos un artículo")
    h = dot.habitual(db, data.asset_id, data.tipologia)
    if h is None:
        h = DotacionHabitual(asset_id=data.asset_id, tipologia=data.tipologia, perfil=data.perfil, items=items)
        db.add(h)
    h.perfil, h.items, h.user_id = data.perfil, items, scope.user.id
    h.actualizada = func.now()
    db.flush()
    audit(db, scope.user, "dotacion_habitual", "activo", data.asset_id,
          {"tipologia": data.tipologia, "perfil": data.perfil, "articulos": len(items)})
    db.commit()
    return {"tipologia": h.tipologia, "perfil": h.perfil, "items": h.items, "fijada": True}


@router.post("/articulos", status_code=201)
def new_item(data: ArticuloIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """«Otra dotación»: crea un artículo nuevo que queda en el catálogo para no volver a escribirlo."""
    if data.asset_id:
        scope.require_asset("reservas.editar", data.asset_id)
    else:
        scope.require_any("reservas.editar")
    if data.zona not in dot.ZONAS:
        bad_request("Zona no válida")
    nombre = " ".join(data.articulo.split())
    existe = next((x for x in dot.articulos(db, data.asset_id) if x["articulo"].lower() == nombre.lower()), None)
    if existe:
        return {k: existe[k] for k in ("codigo", "zona", "articulo")}
    a = DotacionArticulo(asset_id=data.asset_id, codigo=dot.nuevo_codigo(db), zona=data.zona, articulo=nombre,
                         user_id=scope.user.id)
    db.add(a)
    audit(db, scope.user, "crear", "dotacion_articulo", None, {"articulo": nombre})
    db.commit()
    return {"codigo": a.codigo, "zona": a.zona, "articulo": a.articulo}
