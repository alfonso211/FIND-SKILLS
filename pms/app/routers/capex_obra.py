"""CAPEX fase 2 (obra), primera entrega: documentación PRL de cada contrata (con semáforo), condiciones y contrato,
enlace de obra para que el contratista suba su documentación y acta de replanteo (inicio de obra).

Estados: adjudicado → (acta de replanteo) → en_ejecucion. El acta exige, en cada contrata adjudicada, el contrato
firmado y toda la documentación PRL válida y en vigor (o marcada «no aplica»)."""
import hmac
import secrets
from datetime import date, datetime
from html import escape
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import avisos, capex_obra, documentos
from ..database import get_db
from ..models import (TIPOS_PRL_CAPEX, Asset, CapexAward, CapexDocument, CapexPrl, CapexProject, EmailLog, Supplier,
                      SupplierBid, User)
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404
from .capex import _ascii, _base_url, _doc, _fichero_doc, _guardar_doc, _pagina, _proyecto, _resumen, _tocado

router = APIRouter(prefix="/api/capex", tags=["CAPEX obra"])
publico = APIRouter(tags=["CAPEX obra (enlaces)"])
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
OBRA = ("adjudicado", "en_ejecucion")


def _adjudicaciones(db: Session, p: CapexProject) -> list[CapexAward]:
    return list(db.scalars(select(CapexAward).where(CapexAward.project_id == p.id, CapexAward.estado == "aprobada")
                           .order_by(CapexAward.id)))


def _adjudicacion(db: Session, scope: Scope, aid: int) -> tuple[CapexAward, CapexProject]:
    a = get_or_404(db, CapexAward, aid)
    p = _proyecto(db, scope, a.project_id, gestionar=True)
    if a.estado != "aprobada" or p.estado not in OBRA:
        bad_request("Esta adjudicación no está en fase de obra")
    return a, p


def _enlace(base: str, a: CapexAward) -> str:
    return f"{base}/obra/{a.id}?k={a.clave}"


def _prl(db: Session, x: CapexPrl) -> dict:
    color, texto = capex_obra.semaforo(x)
    d = db.get(CapexDocument, x.document_id) if x.document_id else None
    return {"id": x.id, "tipo": x.tipo, "nombre": TIPOS_PRL_CAPEX[x.tipo][0], "caduca": TIPOS_PRL_CAPEX[x.tipo][1],
            "estado": x.estado, "color": color, "texto": texto, "vence": x.vence.isoformat() if x.vence else None,
            "nota": x.nota, "subido_por": x.subido_por, "subido_en": x.subido_en.isoformat() if x.subido_en else None,
            "documento": {"id": d.id, "nombre": d.nombre, "mime": d.mime} if d else None,
            "en_regla": capex_obra.en_regla(x)}


def _award(db: Session, p: CapexProject, a: CapexAward, base: str | None) -> dict:
    s = db.get(Supplier, a.supplier_id)
    if a.plazo_dias is None:  # el plazo ofertado, si lo indicó
        b = db.get(SupplierBid, a.bid_id)
        a.plazo_dias = b.plazo_dias if b else None
    prl = [_prl(db, x) for x in capex_obra.asegurar_prl(db, a)]
    contrato = db.get(CapexDocument, a.contrato_doc_id) if a.contrato_doc_id else None
    return {"id": a.id, "proveedor": s.nombre, "email": s.email, "telefono": s.telefono, "importe": float(a.importe),
            "capitulos": [f"{c} {n}" for c, n in capex_obra.capitulos_adjudicados(db, p, a)],
            "retencion_pct": float(a.retencion_pct), "garantia_meses": a.garantia_meses, "plazo_dias": a.plazo_dias,
            "contrato_firmado": a.contrato_firmado.isoformat() if a.contrato_firmado else None,
            "contrato": {"id": contrato.id, "nombre": contrato.nombre, "mime": contrato.mime} if contrato else None,
            "enlace": _enlace(base, a) if base and a.clave else None,
            "enlace_enviado": a.enlace_enviado.isoformat() if a.enlace_enviado else None,
            "prl": prl, "prl_en_regla": all(x["en_regla"] for x in prl),
            "prl_resumen": {c: sum(1 for x in prl if x["color"] == c) for c in ("verde", "amarillo", "rojo", "gris")}}


@router.get("/{pid}/obra")
def works(pid: int, request: Request, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    p = _proyecto(db, scope, pid)
    awards = _adjudicaciones(db, p) if p.estado in OBRA else []
    datos = [_award(db, p, a, _base_url(request)) for a in awards]
    faltan = capex_obra.pendientes_replanteo(db, p, awards) if p.estado == "adjudicado" else []
    acta = db.get(CapexDocument, p.replanteo_doc_id) if p.replanteo_doc_id else None
    db.commit()  # filas PRL nuevas y plazo ofertado
    return {"proyecto": _resumen(db, p), "adjudicaciones": datos, "tipos_prl": {k: v[0] for k, v in TIPOS_PRL_CAPEX.items()},
            "replanteo": {"fecha": p.replanteo_fecha.isoformat() if p.replanteo_fecha else None, "nota": p.replanteo_nota,
                          "documento": _doc(acta) if acta else None},
            "puede_replanteo": p.estado == "adjudicado" and not faltan, "faltan": faltan,
            "gestionar": scope.can_asset("capex.gestionar", p.asset_id)}


class CondicionesIn(BaseModel):
    retencion_pct: float | None = Field(default=None, ge=0, le=20)
    garantia_meses: int | None = Field(default=None, ge=0, le=120)
    plazo_dias: int | None = Field(default=None, ge=1, le=2000)


@router.put("/obra/adjudicaciones/{aid}")
def update_conditions(aid: int, data: CondicionesIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a, p = _adjudicacion(db, scope, aid)
    cambios = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    if p.estado != "adjudicado" and {"retencion_pct", "garantia_meses"} & cambios.keys():
        bad_request("La retención y la garantía se fijan antes del acta de replanteo")
    for k, v in cambios.items():
        setattr(a, k, v)
    _tocado(p)
    audit(db, scope.user, "condiciones_obra", "capex", p.id, {"adjudicacion": a.id, **cambios})
    db.commit()
    return {"ok": True}


@router.get("/obra/adjudicaciones/{aid}/contrato.docx")
def contract_draft(aid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a, p = _adjudicacion(db, scope, aid)
    s = db.get(Supplier, a.supplier_id)
    return Response(capex_obra.contrato_docx(db, p, a), media_type=DOCX, headers={
        "Content-Disposition": f'attachment; filename="Contrato_{p.codigo}_{_ascii(s.nombre)}.docx"'})


@router.post("/obra/adjudicaciones/{aid}/contrato")
def upload_contract(aid: int, fichero: UploadFile = File(...), fecha: date = Form(...),
                    scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a, p = _adjudicacion(db, scope, aid)
    if fecha > date.today():
        bad_request("La fecha de firma no puede ser futura")
    datos, mime, nombre = _fichero_doc(fichero)
    s = db.get(Supplier, a.supplier_id)
    d = _guardar_doc(db, datos, mime, nombre, scope.user.id, project_id=p.id, etiqueta="contrato",
                     notas=f"Contrato firmado con {s.nombre}"[:300], licitacion=False)
    db.flush()
    a.contrato_doc_id, a.contrato_firmado = d.id, fecha
    _tocado(p)
    audit(db, scope.user, "contrato_obra", "capex", p.id, {"adjudicacion": a.id, "fecha": fecha.isoformat()})
    db.commit()
    return {"ok": True, "documento": d.id}


def _avisar_enlace(db: Session, p: CapexProject, a: CapexAward, url: str) -> dict:
    s = db.get(Supplier, a.supplier_id)
    asset = db.get(Asset, p.asset_id)
    asunto = f"Adjudicación {p.codigo}: documentación para el inicio de obra – {asset.nombre}"
    texto = (f"Estimados señores:\n\nLes comunicamos la adjudicación de los trabajos «{p.titulo}» en {asset.nombre}. "
             "Antes del acta de replanteo necesitamos su documentación de prevención de riesgos laborales y el "
             f"contrato firmado.\n\nEn este enlace pueden ver lo que falta, subir cada documento con su fecha de "
             f"caducidad y descargar el borrador del contrato: {url}\n\nLa obra no podrá comenzar hasta que la "
             "documentación esté completa y en vigor.\n\nAtentamente,\nDirección Técnica · Grupo INVERSIETE")
    html = avisos._html(asunto, "".join(f"<p>{escape(x)}</p>" for x in texto.split("\n\n")).replace(
        escape(url), f'<a href="{escape(url)}" style="font-weight:600">{escape(url)}</a>'))
    r = {"proveedor": s.nombre, "email": s.email, "ok": False, "whatsapp": None, "enlace": url}
    if s.email and avisos.configurado():
        try:
            avisos.enviar(s.email, asunto, texto, html)
            r["ok"] = True
        except Exception as e:  # noqa: BLE001
            r["error"] = str(e)[:300]
        db.add(EmailLog(clave=f"capex_obra:{a.id}:{datetime.now():%Y%m%d%H%M%S}", tipo="capex", destinatario=s.email,
                        asunto=asunto[:200], ok=r["ok"], error=r.get("error")))
    else:
        r["error"] = "Sin correo del proveedor" if not s.email else "Correo saliente no configurado"
    from ..firma_contrato import movil_whatsapp
    movil = movil_whatsapp(s.telefono or "") if s.telefono else None
    if movil:
        r["whatsapp"] = "https://wa.me/{}?text={}".format(movil, quote(
            f"Buenos días, les comunicamos la adjudicación de «{p.titulo}» en {asset.nombre}. Antes del inicio de obra "
            f"necesitamos su documentación PRL y el contrato firmado. Pueden subirla aquí: {url}"))
    return r


@router.post("/obra/adjudicaciones/{aid}/enlace")
def send_link(aid: int, request: Request, nuevo: bool = False, scope: Scope = Depends(get_scope),
              db: Session = Depends(get_db)):
    """Envía (o reenvía) al contratista el enlace de obra. `nuevo`: cambia la clave y el enlace anterior deja de valer."""
    a, p = _adjudicacion(db, scope, aid)
    if nuevo or not a.clave:
        a.clave = secrets.token_urlsafe(24)
    r = _avisar_enlace(db, p, a, _enlace(_base_url(request), a))
    a.enlace_enviado = datetime.now() if r["ok"] else a.enlace_enviado
    audit(db, scope.user, "enlace_obra", "capex", p.id, {"adjudicacion": a.id, "nuevo": nuevo, "correo": r["ok"]})
    db.commit()
    return r


def _subir_prl(db: Session, a: CapexAward, p: CapexProject, tipo: str, fichero: UploadFile, vence: date | None,
               user_id: int | None, quien: str) -> CapexPrl:
    if tipo not in TIPOS_PRL_CAPEX:
        bad_request("Tipo de documento no válido")
    if TIPOS_PRL_CAPEX[tipo][1] and not vence:
        bad_request(f"Indique hasta cuándo es válido: {TIPOS_PRL_CAPEX[tipo][0]}")
    if vence and vence < date.today():
        bad_request("Ese documento ya está caducado: suba uno en vigor")
    x = next(f for f in capex_obra.asegurar_prl(db, a) if f.tipo == tipo)
    datos, mime, nombre = _fichero_doc(fichero)
    s = db.get(Supplier, a.supplier_id)
    d = _guardar_doc(db, datos, mime, nombre, user_id, project_id=p.id, etiqueta="prl",
                     notas=f"{s.nombre} · {TIPOS_PRL_CAPEX[tipo][0]}"[:300], licitacion=False)
    db.flush()
    x.document_id, x.vence, x.subido_en, x.subido_por, x.nota = d.id, vence, datetime.now(), quien, None
    # lo que sube la Dirección Técnica ya está revisado; lo del contratista hay que revisarlo
    x.estado = "valido" if quien == "pms" else "por_revisar"
    if quien == "pms":
        x.revisado_por, x.revisado_en = user_id, datetime.now()
    return x


@router.post("/obra/adjudicaciones/{aid}/prl")
def upload_prl(aid: int, tipo: str = Form(...), vence: date | None = Form(None), fichero: UploadFile = File(...),
               scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    a, p = _adjudicacion(db, scope, aid)
    x = _subir_prl(db, a, p, tipo, fichero, vence, scope.user.id, "pms")
    audit(db, scope.user, "prl_subido", "capex", p.id, {"adjudicacion": a.id, "tipo": tipo})
    db.commit()
    return _prl(db, x)


class RevisionIn(BaseModel):
    decision: str  # validar | rechazar | no_aplica | pendiente
    vence: date | None = None
    nota: str | None = Field(default=None, max_length=300)


@router.post("/obra/prl/{xid}/revisar")
def review_prl(xid: int, data: RevisionIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    x = get_or_404(db, CapexPrl, xid)
    a, p = _adjudicacion(db, scope, x.award_id)
    nota = (data.nota or "").strip() or None
    if data.decision == "validar":
        if not x.document_id:
            bad_request("No hay documento que validar: súbalo primero")
        vence = data.vence or x.vence
        if TIPOS_PRL_CAPEX[x.tipo][1] and not vence:
            bad_request("Indique hasta cuándo es válido")
        x.estado, x.vence = "valido", vence
    elif data.decision == "rechazar":
        if not nota:
            bad_request("Indique el motivo del rechazo (se le muestra al contratista)")
        x.estado = "rechazado"
    elif data.decision == "no_aplica":
        if not nota:
            bad_request("Indique por qué no aplica (queda en el expediente)")
        x.estado = "no_aplica"
    elif data.decision == "pendiente":
        x.estado = "por_revisar" if x.document_id else "falta"
    else:
        bad_request("Decisión no válida")
    x.nota, x.revisado_por, x.revisado_en = nota, scope.user.id, datetime.now()
    audit(db, scope.user, "prl_revision", "capex", p.id, {"adjudicacion": a.id, "tipo": x.tipo,
                                                          "decision": data.decision, "nota": nota})
    db.commit()
    return _prl(db, x)


@router.post("/{pid}/replanteo")
def stakeout(pid: int, fecha: date = Form(...), nota: str | None = Form(None), fichero: UploadFile | None = File(None),
             scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Acta de replanteo: inicio de obra. Solo con el contrato firmado y la documentación PRL en regla."""
    p = _proyecto(db, scope, pid, gestionar=True)
    faltan = capex_obra.pendientes_replanteo(db, p, _adjudicaciones(db, p))
    if faltan:
        bad_request("No se puede firmar el acta de replanteo: " + " · ".join(faltan))
    if fecha > date.today():
        bad_request("La fecha del acta no puede ser futura")
    if fichero is not None and fichero.filename:
        datos, mime, nombre = _fichero_doc(fichero)
        d = _guardar_doc(db, datos, mime, nombre, scope.user.id, project_id=p.id, etiqueta="acta",
                         notas="Acta de replanteo", licitacion=False)
        db.flush()
        p.replanteo_doc_id = d.id
    p.replanteo_fecha, p.replanteo_nota = fecha, (nota or "").strip()[:500] or None
    p.estado = "en_ejecucion"
    p.fecha_inicio = p.fecha_inicio or fecha
    _tocado(p)
    audit(db, scope.user, "acta_replanteo", "capex", p.id, {"fecha": fecha.isoformat()})
    db.commit()
    return _resumen(db, p)


# --------------------------------------------------------------------------- enlace de obra del contratista
def _obra(db: Session, aid: int, k: str) -> tuple[CapexAward, CapexProject]:
    a = db.get(CapexAward, aid)
    if a is None or not a.clave or not hmac.compare_digest(a.clave, k or "") or a.estado != "aprobada":
        raise HTTPException(404, "Enlace no válido. Pida a la Dirección Técnica que se lo reenvíe.")
    p = db.get(CapexProject, a.project_id)
    if p.estado not in OBRA:
        raise HTTPException(404, "Este enlace ya no está activo")
    return a, p


@publico.get("/obra/{aid}", include_in_schema=False)
def works_page(aid: int):
    return _pagina("obra.html")


@publico.get("/api/publico/obra/{aid}")
def works_data(aid: int, k: str, db: Session = Depends(get_db)):
    a, p = _obra(db, aid, k)
    asset = db.get(Asset, p.asset_id)
    prl = capex_obra.asegurar_prl(db, a)
    db.commit()
    return {"proyecto": {"codigo": p.codigo, "titulo": p.titulo, "activo": asset.nombre, "direccion": asset.direccion,
                         "ubicacion": p.ubicacion, "estado": p.estado,
                         "replanteo": p.replanteo_fecha.isoformat() if p.replanteo_fecha else None},
            "proveedor": db.get(Supplier, a.supplier_id).nombre, "importe": float(a.importe),
            "retencion_pct": float(a.retencion_pct), "garantia_meses": a.garantia_meses, "plazo_dias": a.plazo_dias,
            "contrato_firmado": a.contrato_firmado.isoformat() if a.contrato_firmado else None,
            # al contratista: estado y fechas, sin descargar lo ya subido
            "prl": [{k2: v for k2, v in _prl(db, x).items() if k2 not in ("documento", "subido_por")}
                    for x in prl]}


@publico.post("/api/publico/obra/{aid}/prl")
def works_upload(aid: int, k: str, request: Request, tipo: str = Form(...), vence: date | None = Form(None),
                 fichero: UploadFile = File(...), db: Session = Depends(get_db)):
    a, p = _obra(db, aid, k)
    x = next((f for f in capex_obra.asegurar_prl(db, a) if f.tipo == tipo), None)
    if x is not None and x.estado in ("valido", "no_aplica") and capex_obra.en_regla(x):
        bad_request("Ese documento ya está validado. Si necesita cambiarlo, hable con la Dirección Técnica.")
    x = _subir_prl(db, a, p, tipo, fichero, vence, None, "contratista")
    audit(db, None, "prl_contratista", "capex", p.id, {"adjudicacion": a.id, "tipo": tipo,
                                                         "ip": request.client.host if request.client else None})
    _avisar_prl(db, p, a, tipo)
    db.commit()
    return {k2: v for k2, v in _prl(db, x).items() if k2 not in ("documento", "subido_por")}


def _avisar_prl(db: Session, p: CapexProject, a: CapexAward, tipo: str) -> None:
    u = db.get(User, p.creado_por) if p.creado_por else None
    if not (u and u.email and avisos.configurado()):
        return
    s = db.get(Supplier, a.supplier_id)
    asunto = f"Documentación PRL recibida {p.codigo}: {s.nombre}"
    texto = (f"{s.nombre} ha subido «{TIPOS_PRL_CAPEX[tipo][0]}» para «{p.titulo}». Revísela en CAPEX → {p.codigo} → "
             "Obra (validar o rechazar).")
    try:
        avisos.enviar(u.email, asunto, texto, avisos._html(asunto, f"<p>{escape(texto)}</p>"))
        ok, err = True, None
    except Exception as e:  # noqa: BLE001
        ok, err = False, str(e)[:300]
    db.add(EmailLog(clave=f"capex_prl:{a.id}:{tipo}:{datetime.now():%Y%m%d%H%M%S}", tipo="capex",
                    destinatario=u.email, asunto=asunto[:200], ok=ok, error=err))


@publico.get("/api/publico/obra/{aid}/contrato.docx")
def works_contract(aid: int, k: str, db: Session = Depends(get_db)):
    a, p = _obra(db, aid, k)
    return Response(capex_obra.contrato_docx(db, p, a), media_type=DOCX, headers={
        "Content-Disposition": f'attachment; filename="Contrato_{p.codigo}.docx"', "Cache-Control": "private, no-store"})
