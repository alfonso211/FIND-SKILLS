"""Exportación a INVERGESTION: facturas emitidas y recibidas en CSV, con sus PDF en un .zip junto a cada CSV."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import export_invergestion as ex
from ..database import get_db
from ..models import Asset
from ..security import Scope, audit, get_scope
from ..utils import bad_request

router = APIRouter(prefix="/api/exportacion", tags=["exportación"])
DESDE_HISTORICO = date(2026, 1, 1)  # acuerdo: histórico desde el 1 de enero de 2026


def _activos(db: Session, scope: Scope, perm: str, activo: str | None) -> tuple[set[int], str]:
    """Activos del periodo según permiso y el código pedido (SFLORIDA, SAEROPUERTO, BABILONIA35 o TODOS)."""
    permitidos = scope.asset_ids(perm)
    activos = [a for a in db.scalars(select(Asset).order_by(Asset.id))
               if (permitidos is None or a.id in permitidos)]
    if activo and activo.upper() != "TODOS":
        activos = [a for a in activos if ex.codigo_activo(a) == activo.upper()]
        if not activos:
            raise HTTPException(403, f"Sin acceso al activo {activo}")
    return {a.id for a in activos}, (activo or "TODOS").upper()


def _periodo(desde: date, hasta: date) -> None:
    if desde > hasta:
        bad_request("La fecha inicial es posterior a la final")
    if (hasta - desde).days > 400:
        bad_request("El periodo máximo es de un año: exporte el histórico por trimestres o meses")


def _datos(db: Session, scope: Scope, desde: date, hasta: date, activo: str | None, tipos: str):
    _periodo(desde, hasta)
    out = {}
    if "emitidas" in tipos and scope.has_any("facturas.ver"):
        ids, cod = _activos(db, scope, "facturas.ver", activo)
        out["emitidas"] = (cod, *ex.emitidas(db, ids, desde, hasta))
    if "recibidas" in tipos and scope.has_any("documentos.ver"):
        ids, cod = _activos(db, scope, "documentos.ver", activo)
        out["recibidas"] = (cod, *ex.recibidas(db, ids, desde, hasta))
    if not out:
        raise HTTPException(403, "Sin permiso para exportar facturas")
    return out


@router.get("/invergestion/comprobar")
def check(desde: date, hasta: date, activo: str | None = None, tipos: str = "emitidas,recibidas",
          scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Lo que se va a enviar y lo que INVERGESTION rechazaría (campos obligatorios, NIF, cuadre)."""
    out = {}
    for tipo, (cod, filas, ficheros, avisos) in _datos(db, scope, desde, hasta, activo, tipos).items():
        claves = {(f.get("nif_emisor") or f.get("proveedor_nif"), f.get("serie"), f["numero"]) for f in filas}
        out[tipo] = {"facturas": len(claves), "filas": len(filas), "ficheros": len(ficheros),
                     "total": round(sum(float(f["total"]) for f in {(f.get("nif_emisor") or f.get("proveedor_nif"),
                                                                     f.get("serie"), f["numero"]): f
                                                                    for f in filas}.values()), 2),
                     "avisos": avisos[:200], "n_avisos": len(avisos),
                     "csv": ex.nombre_fichero(tipo.upper(), cod, desde, hasta, "csv")}
        if tipo == "recibidas":  # los documentos escaneados tienen que poder leerse para ir en el paquete
            faltan = ex.documentos_ilegibles(ficheros)
            out[tipo]["avisos"] = faltan + out[tipo]["avisos"]
            out[tipo]["n_avisos"] += len(faltan)
            out[tipo]["bloquea"] = faltan
    out["paquete"] = ex.nombre_fichero("INVERGESTION", (activo or "TODOS").upper(), desde, hasta, "zip")
    return out


@router.get("/invergestion")
def export(desde: date, hasta: date, activo: str | None = None, tipos: str = "emitidas,recibidas",
           pdf: bool = True, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Un solo ZIP: CSV en la raíz, manifest.json y los PDF en pdf/emitidas/ y pdf/recibidas/. Si a alguna fila le
    falta su PDF, no se genera (409) y se dice cuál."""
    datos = _datos(db, scope, desde, hasta, activo, tipos)
    cod = activo.upper() if activo else "TODOS"
    try:
        contenido = ex.paquete(db, datos, cod, desde, hasta, pdf)
    except ex.PaqueteIncompleto as e:
        raise HTTPException(409, f"Exportación no generada: faltan PDF en el paquete. {e}") from e
    audit(db, scope.user, "exportar_invergestion", "facturas", None,
          {"desde": str(desde), "hasta": str(hasta), "activo": cod, "tipos": tipos, "pdf": pdf,
           **{t: len(v[1]) for t, v in datos.items()}})
    db.commit()
    return Response(contenido, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{ex.nombre_fichero("INVERGESTION", cod, desde, hasta, "zip")}"',
        "Cache-Control": "no-store"})
