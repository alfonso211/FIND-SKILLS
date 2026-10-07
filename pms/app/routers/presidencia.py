"""Informe mensual a la presidencia: vista previa, PDF, Excel y envío (correo o WhatsApp) tras revisarlo.
Lo revisa y envía «Recepción 1» de cada activo (o quien se indique en la ficha del activo)."""
import re
from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import avisos, documentos
from .. import informe_presidencia as ip
from ..database import get_db
from ..models import Asset, Assignment, PresidencyReport, ReceivedDocument, Role, User
from ..security import Scope, audit, get_scope
from ..seed import PRESIDENCIA
from ..utils import bad_request, get_or_404

router = APIRouter(prefix="/api/presidencia", tags=["informe a la presidencia"])
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def responsable(db: Session, a: Asset) -> User | None:
    """El indicado en la ficha del activo; si no, «Recepción 1» del activo."""
    if a.informe_responsable_id:
        u = db.get(User, a.informe_responsable_id)
        if u and u.activo:
            return u
    candidatos = db.scalars(select(User).join(Assignment, Assignment.user_id == User.id).join(Role).where(
        User.activo, Assignment.asset_id == a.id, Role.nombre == "Recepción").order_by(User.nombre))
    return next((u for u in candidatos if re.match(r"recepci[oó]n\s*1\b", u.nombre or "", re.I)), None)


def destinatarios(db: Session, a: Asset) -> list[str]:
    if a.informe_emails:
        return [x.strip() for x in re.split(r"[,;\s]+", a.informe_emails) if x.strip()]
    return list(db.scalars(select(User.email).where(User.email.in_(PRESIDENCIA), User.activo)))


def _periodo(anio: int, mes: int) -> None:
    hoy = date.today()
    if not 1 <= mes <= 12 or (anio, mes) > (hoy.year, hoy.month) or anio < 2000:
        bad_request("Mes no válido")


def _activo(db: Session, scope: Scope, asset_id: int) -> Asset:
    scope.require_asset("facturas.ver", asset_id)
    return get_or_404(db, Asset, asset_id)


def _registro(db: Session, asset_id: int, anio: int, mes: int) -> PresidencyReport | None:
    return db.scalar(select(PresidencyReport).where(PresidencyReport.asset_id == asset_id,
                                                    PresidencyReport.anio == anio, PresidencyReport.mes == mes))


def _registro_out(db: Session, r: PresidencyReport | None) -> dict | None:
    if r is None:
        return None
    nombre = lambda uid: db.get(User, uid).nombre if uid and db.get(User, uid) else None  # noqa: E731
    return {**r.to_dict(), "revisado_por_nombre": nombre(r.revisado_por), "enviado_por_nombre": nombre(r.enviado_por)}


@router.get("")
def preview(asset_id: int, anio: int, mes: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a = _activo(db, scope, asset_id)
    _periodo(anio, mes)
    resp = responsable(db, a)
    return {"datos": ip.datos(db, a, anio, mes), "registro": _registro_out(db, _registro(db, a.id, anio, mes)),
            "destinatarios": destinatarios(db, a), "whatsapp": a.informe_whatsapp,
            "responsable": resp.nombre if resp else None}


def _nombre(a: Asset, anio: int, mes: int, ext: str) -> str:
    return f"Informe_presidencia_{a.codigo}_{anio}-{mes:02d}.{ext}"


@router.get("/pdf")
def pdf(asset_id: int, anio: int, mes: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a = _activo(db, scope, asset_id)
    _periodo(anio, mes)
    return Response(ip.pdf(ip.datos(db, a, anio, mes)), media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{_nombre(a, anio, mes, "pdf")}"', "Cache-Control": "no-store"})


@router.get("/excel")
def xlsx(asset_id: int, anio: int, mes: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a = _activo(db, scope, asset_id)
    _periodo(anio, mes)
    return Response(ip.excel(ip.datos(db, a, anio, mes)), media_type=XLSX, headers={
        "Content-Disposition": f'attachment; filename="{_nombre(a, anio, mes, "xlsx")}"', "Cache-Control": "no-store"})


class EnvioIn(BaseModel):
    asset_id: int
    anio: int
    mes: int
    revisado: bool = False  # «he comprobado que todos los datos son correctos»
    canal: str = Field(pattern="^(email|whatsapp)$")
    destinatarios: list[str] = []
    telefono: str | None = None


@router.post("/enviar")
def send(data: EnvioIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Tras revisarlo: guarda el Excel en los documentos del activo y lo envía en PDF por correo; por WhatsApp
    devuelve el enlace (el PDF se adjunta desde el teléfono u ordenador)."""
    a = _activo(db, scope, data.asset_id)
    _periodo(data.anio, data.mes)
    if not data.revisado:
        bad_request("Antes de enviarlo, marque que ha revisado el informe y que los datos son correctos")
    d = ip.datos(db, a, data.anio, data.mes)
    pdf_ = ip.pdf(d)
    if data.canal == "email":
        para = [x.strip() for x in data.destinatarios if x.strip()] or destinatarios(db, a)
        if not para or any(not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", x) for x in para):
            bad_request("Indique uno o varios correos válidos")
        destino = ", ".join(para)
    else:
        tel = re.sub(r"\D", "", data.telefono or a.informe_whatsapp or "")
        if len(tel) < 9:
            bad_request("Indique el teléfono de WhatsApp")
        tel = tel if len(tel) > 9 else "34" + tel
        destino = f"+{tel}"
    # el Excel, a los documentos del activo (si se reenvía, sustituye al anterior)
    r = _registro(db, a.id, data.anio, data.mes) or PresidencyReport(asset_id=a.id, anio=data.anio, mes=data.mes)
    db.add(r)
    xl = ip.excel(d)
    anterior = db.get(ReceivedDocument, r.documento_id) if r.documento_id else None
    if anterior:
        r.documento_id = None
        db.flush()
        documentos.borrar(anterior.fichero)
        db.delete(anterior)
        db.flush()
    doc = ReceivedDocument(asset_id=a.id, tipo="informe", fecha=ip.fin_mes(data.anio, data.mes), emisor="INVERPMS",
                           referencia=f"Presidencia {data.anio}-{data.mes:02d}",
                           descripcion=f"Informe mensual a la presidencia · {d['periodo']}",
                           nombre=_nombre(a, data.anio, data.mes, "xlsx"), fichero=documentos.guardar(xl), mime=XLSX,
                           tamano=len(xl), sha256=documentos.huella(xl), user_id=scope.user.id)
    db.add(doc)
    db.flush()
    ahora = datetime.now()
    r.revisado_por, r.revisado_en, r.enviado_por, r.enviado_en = scope.user.id, ahora, scope.user.id, ahora
    r.canal, r.destino, r.documento_id = data.canal, destino, doc.id
    r.resumen = {k: d[k] for k in ("total_ingresos", "total_gastos", "resultado", "porcentaje", "semaforo",
                                   "total_pernoctaciones")}
    url = None
    asunto = f"Informe mensual a la presidencia · {a.nombre} · {d['periodo']}"
    texto = (f"Informe mensual a la presidencia de {a.nombre}, {d['periodo']} (sin IVA).\n"
             f"Producción: {ip.eur(d['total_ingresos'])} · Gastos: {ip.eur(d['total_gastos'])} · "
             f"Resultado: {ip.eur(d['resultado'])} ({ip.pct(d['porcentaje'])}).\n"
             f"Revisado y enviado por {scope.user.nombre}.")
    if data.canal == "email":
        try:
            for x in para:
                avisos.enviar(x, asunto, texto + "\n\nSe adjunta el informe en PDF.",
                              avisos._html(asunto, "<p>" + texto.replace("\n", "<br>") + "</p><p>Se adjunta el "
                                           "informe en PDF.</p>"),
                              [(_nombre(a, data.anio, data.mes, "pdf"), pdf_, "application/pdf")])
        except Exception as e:  # noqa: BLE001
            db.rollback()
            raise HTTPException(502, f"No se pudo enviar el correo: {str(e)[:200]}") from e
    else:
        url = f"https://wa.me/{destino[1:]}?text={quote(texto + chr(10) + 'Le adjunto el informe en PDF.')}"
    audit(db, scope.user, "enviar_informe_presidencia", "activo", a.id,
          {"periodo": f"{data.anio}-{data.mes:02d}", "canal": data.canal, "destino": destino})
    db.commit()
    return {"ok": True, "registro": _registro_out(db, r), "whatsapp_url": url,
            "pdf": _nombre(a, data.anio, data.mes, "pdf")}


def pendientes(db: Session, scope: Scope, hoy: date | None = None) -> list[dict]:
    """Informes del mes anterior aún sin enviar, a partir del primer día laborable del mes (para el panel)."""
    from ..calendario import primer_laborable
    hoy = hoy or date.today()
    if hoy < primer_laborable(hoy.year, hoy.month):
        return []
    anio, mes = (hoy.year - 1, 12) if hoy.month == 1 else (hoy.year, hoy.month - 1)
    ids = scope.asset_ids("facturas.ver")
    out = []
    for a in db.scalars(select(Asset).where(Asset.activo).order_by(Asset.id)):
        if ids is not None and a.id not in ids:
            continue
        r = _registro(db, a.id, anio, mes)
        if r is None or r.enviado_en is None:
            resp = responsable(db, a)
            if resp is not None:
                out.append({"asset_id": a.id, "activo": a.nombre, "anio": anio, "mes": mes,
                            "periodo": f"{ip.MESES[mes - 1]} {anio}", "responsable": resp.nombre})
    return out
