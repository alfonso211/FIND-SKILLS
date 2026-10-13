"""Revisión de salida desde el móvil de limpieza: un enlace firmado por apartamento (sin usuario ni contraseña, caduca
a los 7 días) con la dotación del apartamento. Limpieza marca lo que falta o está roto; Recepción lo ve ya cargado al
dar la salida, para descontarlo de la fianza, y recibe un aviso por correo si hay incidencias."""
import hashlib
import hmac
import time
from datetime import date, datetime
from html import escape
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import ausencias, avisos, dotacion, limpiezas
from ..config import BASE_DIR, settings
from ..database import get_db
from ..models import Asset, CleaningTask, EmailLog, Reservation, Unit
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/revision", tags=["revisión de salida"])
publico = APIRouter(tags=["revisión de salida (enlace)"])
PAGINA = Path(BASE_DIR) / "static" / "revision.html"
DIAS_ENLACE = 7


def _firma(rid: int, caduca: int) -> str:
    return hmac.new(settings.secret_key.encode(), f"rev:{rid}:{caduca}".encode(), hashlib.sha256).hexdigest()[:32]


def token_valido(rid: int, c: int, f: str) -> bool:
    return c >= time.time() and hmac.compare_digest(f, _firma(rid, c))


def enlace(rid: int, base: str) -> str:
    caduca = int(time.time()) + DIAS_ENLACE * 86400
    return f"{(settings.url or base).rstrip('/')}/revision/{rid}?c={caduca}&f={_firma(rid, caduca)}"


def salidas_dia(db: Session, a: Asset, dia: date, filas: list[dict]) -> list[Reservation]:
    """Salidas del día: las ya hechas que están en el parte de limpieza y las previstas (aún alojados)."""
    rids = [t.reservation_id for t in db.scalars(select(CleaningTask).where(
        CleaningTask.id.in_([x["id"] for x in filas if x["tipo"] == "salida"] or [-1]))) if t.reservation_id]
    rids += list(db.scalars(select(Reservation.id).join(Unit, Unit.id == Reservation.unit_id).where(
        Unit.asset_id == a.id, Unit.uso != "garaje", Reservation.estado == "checkin", Reservation.fecha_salida == dia)))
    vistos, out = set(), []
    for rid in rids:
        if rid not in vistos:
            vistos.add(rid)
            out.append(db.get(Reservation, rid))
    return sorted(out, key=lambda r: r.unit.codigo)


# --------------------------------------------------------------------------- Recepción: enlaces para limpieza
@router.get("/reserva/{rid}/enlace")
def stay_link(rid: int, request: Request, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    r = get_or_404(db, Reservation, rid)
    scope.require_asset("reservas.ver", r.unit.asset_id)
    url = enlace(r.id, str(request.base_url))
    texto = f"Revisión de salida del apartamento {r.unit.codigo}: marque lo que falte o esté roto. {url}"
    return {"url": url, "whatsapp": f"https://wa.me/?text={quote(texto)}", "revision": r.revision}


@router.get("/dia")
def day_links(asset_id: int, request: Request, fecha: date | None = None, scope: Scope = Depends(get_scope),
              db: Session = Depends(get_db)):
    """Enlaces de revisión de las salidas del día, para mandarlos juntos a limpieza por WhatsApp."""
    scope.require_asset("reservas.ver", asset_id)
    a = get_or_404(db, Asset, asset_id)
    f = fecha or date.today()
    filas = limpiezas.parte(db, a.id, f)
    db.commit()
    out = [{"reserva_id": r.id, "unidad": r.unit.codigo, "estado": r.estado, "hecha": bool(r.revision),
            "url": enlace(r.id, str(request.base_url))} for r in salidas_dia(db, a, f, filas)]
    texto = (f"Revisión de salidas {a.nombre} · {f:%d/%m/%Y}. Abra cada enlace y marque lo que falte o esté roto:\n"
             + "\n".join(f"{x['unidad']}: {x['url']}" for x in out))
    return {"salidas": out, "whatsapp": f"https://wa.me/?text={quote(texto)}" if out else None}


# --------------------------------------------------------------------------- limpieza: página y datos (públicos)
class MarcaIn(BaseModel):
    codigo: str = Field(max_length=12)
    estado: str = Field(pattern="^(falta|roto)$")
    cantidad: int = Field(default=1, ge=1, le=999)


class RevisionIn(BaseModel):
    nombre: str = Field(min_length=2, max_length=120)
    nota: str | None = Field(default=None, max_length=2000)
    marcas: list[MarcaIn] = Field(default=[], max_length=300)


def _reserva(db: Session, rid: int, c: int, f: str) -> Reservation:
    if not token_valido(rid, c, f):
        raise HTTPException(404, "Enlace no válido o caducado. Pida a recepción que se lo reenvíe.")
    return get_or_404(db, Reservation, rid)


@publico.get("/revision/{rid}", include_in_schema=False)
def page(rid: int):
    return HTMLResponse(PAGINA.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store",
                                                                     "Referrer-Policy": "no-referrer"})


@publico.get("/api/publico/revision/{rid}")
def public_data(rid: int, c: int, f: str, db: Session = Depends(get_db)):
    r = _reserva(db, rid, c, f)
    d = dotacion.de_reserva(db, r)
    return {"activo": r.unit.asset.nombre, "apartamento": r.unit.codigo, "tipologia": r.unit.tipologia,
            "salida": r.fecha_salida.isoformat(), "zonas": dotacion.ZONAS,
            "items": [{k: x.get(k) for k in ("codigo", "zona", "articulo", "cantidad")} for x in d["items"]],
            "revision": r.revision, "cerrada": r.estado not in ("checkin", "checkout")}


@publico.post("/api/publico/revision/{rid}")
def public_save(rid: int, c: int, f: str, data: RevisionIn, db: Session = Depends(get_db)):
    """Guarda lo que limpieza ha encontrado (solo lo que falta o está roto) y avisa a Recepción 1 si hay algo."""
    r = _reserva(db, rid, c, f)
    if r.estado not in ("checkin", "checkout"):
        bad_request("Esta reserva ya no admite revisión")
    d = dotacion.de_reserva(db, r)
    por = {x["codigo"]: x for x in d["items"]}
    items = []
    for m in data.marcas:
        x = por.get(m.codigo.upper())
        if x is None:
            bad_request(f"Artículo desconocido: {m.codigo}")
        items.append({"codigo": x["codigo"], "articulo": x["articulo"], "zona": x["zona"], "estado": m.estado,
                      "cantidad": m.cantidad, "precio": x.get("precio")})
    r.revision = {"fecha": datetime.now().isoformat(timespec="minutes"), "nombre": data.nombre.strip(),
                  "nota": (data.nota or "").strip() or None, "items": items}
    audit(db, None, "revision_salida", "reserva", r.id, {"por": data.nombre, "incidencias": len(items)})
    if items or r.revision["nota"]:
        _avisar(db, r)
    db.commit()
    return {"ok": True, "incidencias": len(items)}


def _avisar(db: Session, r: Reservation) -> None:
    rec = ausencias.recepcion_1(db, r.unit.asset)
    if rec is None or not rec.email:
        return
    v = r.revision
    asunto = f"Revisión de salida · {r.unit.asset.nombre} {r.unit.codigo}: {len(v['items'])} incidencia(s)"
    filas = [[x["estado"].upper(), x["articulo"], x["cantidad"],
              f"{x['precio']:.2f} €" if x.get("precio") is not None else "—"] for x in v["items"]]
    cuerpo = (f"<p>{escape(v['nombre'])} ha revisado el apartamento <b>{escape(r.unit.codigo)}</b> "
              f"(reserva {escape(r.localizador or str(r.id))}). Al dar la salida, lo marcado sale ya cargado para "
              f"descontarlo de la fianza.</p>" + (avisos._tabla(["Estado", "Artículo", "Uds.", "Reposición"], filas)
                                                   if filas else "")
              + (f"<p>Nota: {escape(v['nota'])}</p>" if v.get("nota") else ""))
    texto = asunto + "\n" + "\n".join(f"{a} · {b} · {c} · {d}" for a, b, c, d in filas)
    try:
        avisos.enviar(rec.email, asunto, texto, avisos._html("Revisión de salida", cuerpo))
        ok, err = True, None
    except Exception as e:  # noqa: BLE001 — un fallo de correo no impide guardar la revisión
        ok, err = False, str(e)[:300]
    db.add(EmailLog(clave=f"revision:{r.id}", tipo="revision_salida", user_id=rec.id, destinatario=rec.email,
                    asunto=asunto[:200], ok=ok, error=err))
