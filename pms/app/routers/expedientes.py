"""Expediente del contrato de vivienda (LAU): datos para el contrato, checklist de la hoja de control, inventario
que se entrega, entregas de dinero con su recibo, carpeta de documentos y citas de la agenda."""
import copy
from datetime import date, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import contrato_vivienda as cv
from .. import documentos, recibo_entrega
from ..database import get_db
from ..models import AgendaEvent, Contact, Lease, LeaseDocument, Unit, User
from ..security import Scope, audit, get_scope
from ..utils import bad_request, get_or_404
from .alquiler import _lease_out

router = APIRouter(prefix="/api", tags=["expediente de alquiler"])

TAM_MAX = 20 * 1024 * 1024
CLAVES_DOC = {c[0]: c[2] for c in cv.CHECKLIST if c[5]} | {"recibo": "Recibo firmado de entrega de dinero",
                                                            "otro": "Otro documento"}
CAMPOS_DATOS = {
    "fecha_firma", "hora_firma", "fecha_entrega", "hora_entrega", "presentes", "arrendatario2_id", "fiador_id",
    "garantia_modalidad", "aval_vencimiento", "forma_pago", "iban_arrendatario", "importe_inicial", "periodo_desde",
    "periodo_hasta", "convivientes", "max_ocupantes", "anejos", "animales", "animales_detalle", "seguro_capital",
    "domicilio_anterior", "fotos", "otros_docs", "paginas", "acta"}


def _lease(db: Session, scope: Scope, lid: int, perm: str) -> Lease:
    lease = get_or_404(db, Lease, lid)
    scope.require_asset(perm, lease.unit.asset_id)
    return lease


def _exp(lease: Lease) -> dict:
    return copy.deepcopy(lease.expediente or {})


def _guardar_exp(lease: Lease, exp: dict) -> None:
    lease.expediente = exp  # se reasigna para que SQLAlchemy detecte el cambio del JSON


def _docs(db: Session, lid: int) -> list[LeaseDocument]:
    return list(db.scalars(select(LeaseDocument).where(LeaseDocument.lease_id == lid).order_by(LeaseDocument.id)))


def _nombre(c: Contact | None) -> str | None:
    return f"{c.nombre} {c.apellidos or ''}".strip() if c else None


def _salida(db: Session, lease: Lease) -> dict:
    exp = lease.expediente or {}
    docs = _docs(db, lease.id)
    usuarios = {u.id: u.nombre for u in db.scalars(select(User).where(User.id.in_({d.user_id for d in docs} or {-1})))}
    por_clave: dict[str, int] = {}
    for d in docs:
        por_clave[d.clave] = por_clave.get(d.clave, 0) + 1
    d = exp.get("datos") or {}
    eventos = {e.id: e for e in db.scalars(select(AgendaEvent).where(
        AgendaEvent.id.in_(set((exp.get("agenda") or {}).values()) or {-1})))}
    agenda = [{"clave": k, "id": eid, "titulo": eventos[eid].titulo, "inicio": eventos[eid].inicio.isoformat(),
               "hecha": eventos[eid].hecha, "repeticion": eventos[eid].repeticion,
               "todo_el_dia": eventos[eid].todo_el_dia}
              for k, eid in (exp.get("agenda") or {}).items() if eid in eventos]
    inventario = exp.get("inventario")
    return {
        "contrato": _lease_out(lease), "referencia": cv.referencia(lease), "vivienda": cv.vivienda_texto(lease),
        "datos": d,
        "arrendatario2": _nombre(db.get(Contact, d["arrendatario2_id"])) if d.get("arrendatario2_id") else None,
        "fiador": _nombre(db.get(Contact, d["fiador_id"])) if d.get("fiador_id") else None,
        "checklist": cv.checklist(lease, lease.unit, por_clave),
        "inventario": inventario if inventario is not None else (lease.unit.inventario or cv.inventario_tipo()),
        "inventario_propio": inventario is not None,
        "entregas": [{**e, "n": i + 1} for i, e in enumerate(exp.get("entregas") or [])],
        "pendiente_cobro": cv.cobros_pendientes(lease),
        "documentos": [{"id": x.id, "clave": x.clave, "nombre": x.nombre, "mime": x.mime, "tamano": x.tamano,
                        "subido": x.subido.isoformat() if x.subido else None, "usuario": usuarios.get(x.user_id)}
                       for x in docs],
        "agenda": agenda, "faltan": cv.faltan(db, lease),
        "opciones": {"garantia": cv.MODALIDADES_GARANTIA, "formas": cv.FORMAS_PAGO, "conceptos": cv.CONCEPTOS,
                     "claves_doc": CLAVES_DOC, "limite_efectivo": float(cv.LIMITE_EFECTIVO)},
    }


@router.get("/alquiler/contratos/{lid}/expediente")
def get_file(lid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    return _salida(db, _lease(db, scope, lid, "alquiler.ver"))


# --------------------------------------------------------------------------- datos
@router.put("/alquiler/contratos/{lid}/expediente/datos")
def put_data(lid: int, datos: dict, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    lease = _lease(db, scope, lid, "alquiler.editar")
    raros = set(datos) - CAMPOS_DATOS
    if raros:
        bad_request(f"Campos no reconocidos: {', '.join(sorted(raros))}")
    if datos.get("garantia_modalidad") not in (None, "", *cv.MODALIDADES_GARANTIA):
        bad_request("Modalidad de garantía no válida")
    if datos.get("forma_pago") not in (None, "", "sepa", "transferencia"):
        bad_request("Forma de pago de la renta no válida (domiciliación SEPA o transferencia; nunca efectivo)")
    for k in ("fecha_firma", "fecha_entrega", "periodo_desde", "periodo_hasta", "aval_vencimiento"):
        if datos.get(k):
            try:
                date.fromisoformat(str(datos[k]))
            except ValueError:
                bad_request(f"Fecha no válida: {k}")
    for k in ("arrendatario2_id", "fiador_id"):
        if datos.get(k):
            c = get_or_404(db, Contact, int(datos[k]))
            if c.id == lease.tenant_id:
                bad_request("El segundo arrendatario o el fiador no puede ser el propio arrendatario")
            if c.asset_id not in (None, lease.unit.asset_id) and not scope.can_asset("alquiler.ver", c.asset_id):
                bad_request("Ese tercero no pertenece a este activo")
    exp = _exp(lease)
    exp["datos"] = {k: v for k, v in datos.items() if v not in (None, "")}
    _guardar_exp(lease, exp)
    audit(db, scope.user, "editar_expediente", "contrato", lid, {"datos": sorted(exp["datos"])})
    db.commit()
    return _salida(db, lease)


class MarcaIn(BaseModel):
    estado: str | None = None  # hecho | no_aplica | pendiente | None (automático)
    nota: str | None = Field(None, max_length=500)


@router.put("/alquiler/contratos/{lid}/expediente/checklist/{clave}")
def put_check(lid: int, clave: str, data: MarcaIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    lease = _lease(db, scope, lid, "alquiler.editar")
    if clave not in {c[0] for c in cv.CHECKLIST}:
        bad_request("Punto del checklist no válido")
    if data.estado not in (None, "hecho", "no_aplica", "pendiente"):
        bad_request("Estado no válido")
    exp = _exp(lease)
    marcas = exp.setdefault("checklist", {})
    if data.estado is None and not data.nota:
        marcas.pop(clave, None)
    else:
        marcas[clave] = {"estado": data.estado, "nota": data.nota, "usuario": scope.user.nombre,
                         "fecha": datetime.now().isoformat(timespec="minutes")}
    # La tarea de la agenda del mismo punto se da por hecha (o se reabre)
    eid = (exp.get("agenda") or {}).get(clave)
    e = db.get(AgendaEvent, eid) if eid else None
    if e is not None:
        e.hecha = data.estado in ("hecho", "no_aplica")
        e.hecha_por, e.hecha_en = (scope.user.id, datetime.now()) if e.hecha else (None, None)
    _guardar_exp(lease, exp)
    audit(db, scope.user, "checklist_expediente", "contrato", lid, {"punto": clave, "estado": data.estado})
    db.commit()
    return _salida(db, lease)


# --------------------------------------------------------------------------- inventario
class ElementoIn(BaseModel):
    estancia: str = Field("", max_length=60)
    elemento: str = Field(..., min_length=1, max_length=200)
    uds: int | None = Field(1, ge=0, le=999)
    estado: str | None = Field("B", max_length=20)
    obs: str | None = Field("", max_length=300)
    entrega: bool = True


@router.put("/alquiler/contratos/{lid}/expediente/inventario")
def put_inventory(lid: int, items: list[ElementoIn] | None, scope: Scope = Depends(get_scope),
                  db: Session = Depends(get_db)):
    """Inventario de este contrato. null = volver al de la ficha de la vivienda."""
    lease = _lease(db, scope, lid, "alquiler.editar")
    exp = _exp(lease)
    if items is None:
        exp.pop("inventario", None)
    else:
        exp["inventario"] = [i.model_dump() for i in items]
    _guardar_exp(lease, exp)
    audit(db, scope.user, "inventario_expediente", "contrato", lid,
          {"elementos": None if items is None else len(items)})
    db.commit()
    return _salida(db, lease)


# --------------------------------------------------------------------------- entregas de dinero y recibos
class EntregaIn(BaseModel):
    concepto: str
    concepto_texto: str | None = Field(None, max_length=200)
    importe: Decimal = Field(..., gt=0, max_digits=10, decimal_places=2)
    forma: str
    referencia: str | None = Field(None, max_length=80)  # ref. transferencia / nº cheque / nº aval
    entidad: str | None = Field(None, max_length=120)  # banco del cheque o del aval
    cuenta: str | None = Field(None, max_length=40)
    vencimiento: date | None = None  # del aval
    fecha: date
    periodo: str | None = Field(None, max_length=80)
    pagador: str | None = Field(None, max_length=160)  # si paga un tercero (otro arrendatario, fiador...)
    pagador_doc: str | None = Field(None, max_length=40)
    observaciones: str | None = Field(None, max_length=500)


def _validar_entrega(lease: Lease, e: EntregaIn, previas: list[dict]) -> None:
    d = (lease.expediente or {}).get("datos") or {}
    if e.concepto not in cv.CONCEPTOS:
        bad_request("Concepto no válido")
    if e.forma not in cv.FORMAS_PAGO:
        bad_request("Forma de entrega no válida")
    if e.concepto == "otro" and not e.concepto_texto:
        bad_request("Describa el concepto")
    if e.forma == "efectivo":
        if e.concepto == "renta_inicial":
            bad_request("La renta no se puede pagar en efectivo (cláusula 4.2 del contrato): use transferencia")
        efectivo = sum(cv.dinero(x["importe"]) for x in previas if x.get("forma") == "efectivo" and not x.get("anulada"))
        if efectivo + e.importe >= cv.LIMITE_EFECTIVO:
            bad_request("No se admiten pagos en efectivo de 1.000 € o más en la misma operación (Ley 7/2012): "
                        "use transferencia o cheque")
    if e.forma == "aval" and e.concepto != "garantia":
        bad_request("El aval bancario solo sirve para la garantía adicional")
    if e.concepto == "garantia":
        modalidad = d.get("garantia_modalidad", "deposito")
        if modalidad in ("fiador", "ninguna"):
            bad_request("Con fiador o sin garantía adicional no se entrega dinero por la garantía")
        if (modalidad == "aval") != (e.forma == "aval"):
            bad_request("La forma de entrega no coincide con la modalidad de garantía elegida en los datos del contrato")
    pactado = {"renta_inicial": d.get("importe_inicial"), "fianza": lease.fianza,
               "garantia": lease.garantia_adicional}.get(e.concepto)
    if pactado not in (None, ""):
        ya = sum(cv.dinero(x["importe"]) for x in previas if x["concepto"] == e.concepto and not x.get("anulada"))
        if ya + e.importe > cv.dinero(pactado):
            bad_request(f"Supera lo pactado para «{cv.CONCEPTOS[e.concepto]}»: {cv.euros(pactado)} € "
                        f"(ya entregado {cv.euros(ya)} €)")


@router.post("/alquiler/contratos/{lid}/expediente/entregas", status_code=201)
def add_payment(lid: int, data: EntregaIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    lease = _lease(db, scope, lid, "alquiler.editar")
    exp = _exp(lease)
    previas = exp.setdefault("entregas", [])
    _validar_entrega(lease, data, previas)
    e = data.model_dump(mode="json")
    e["importe"] = str(cv.dinero(data.importe))
    e.update(numero=f"{cv.referencia(lease)}-R{len(previas) + 1:02d}", usuario=scope.user.nombre,
             registrado=datetime.now().isoformat(timespec="minutes"))
    previas.append(e)
    _guardar_exp(lease, exp)
    audit(db, scope.user, "entrega_dinero", "contrato", lid,
          {"numero": e["numero"], "concepto": e["concepto"], "importe": e["importe"], "forma": e["forma"]})
    db.commit()
    return _salida(db, lease)


class AnulaIn(BaseModel):
    motivo: str = Field(..., min_length=3, max_length=300)


@router.post("/alquiler/contratos/{lid}/expediente/entregas/{n}/anular")
def void_payment(lid: int, n: int, data: AnulaIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Las entregas no se borran: se anulan con su motivo (el recibo queda marcado como anulado)."""
    lease = _lease(db, scope, lid, "alquiler.editar")
    exp = _exp(lease)
    lista = exp.get("entregas") or []
    if not 1 <= n <= len(lista):
        bad_request("Entrega no encontrada")
    lista[n - 1].update(anulada=True, motivo_anulacion=data.motivo, anulada_por=scope.user.nombre)
    _guardar_exp(lease, exp)
    audit(db, scope.user, "anular_entrega", "contrato", lid, {"numero": lista[n - 1]["numero"], "motivo": data.motivo})
    db.commit()
    return _salida(db, lease)


@router.get("/alquiler/contratos/{lid}/expediente/entregas/{n}/recibo")
def receipt(lid: int, n: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    lease = _lease(db, scope, lid, "alquiler.ver")
    lista = (lease.expediente or {}).get("entregas") or []
    if not 1 <= n <= len(lista):
        bad_request("Entrega no encontrada")
    e = dict(lista[n - 1])
    if e.get("anulada"):
        e["observaciones"] = f"ANULADO: {e.get('motivo_anulacion')}"
    a = lease.unit.asset
    soc = a.propietaria or a.company
    e.setdefault("firma_receptor", (soc.contratos or {}).get("representante"))
    pdf = recibo_entrega.generar(lease, e, e["numero"], soc, cv.referencia(lease), cv.vivienda_texto(lease))
    return Response(pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="recibo_{e["numero"]}.pdf"', "Cache-Control": "no-store"})


# --------------------------------------------------------------------------- contrato Word
@router.get("/alquiler/contratos/{lid}/expediente/contrato.docx")
def contract(lid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    lease = _lease(db, scope, lid, "alquiler.ver")
    if lease.unit.uso not in ("vivienda", "apartamento"):
        bad_request("Este modelo de contrato es solo para viviendas")
    datos = cv.generar_final(db, lease)
    audit(db, scope.user, "generar_contrato", "contrato", lid, {"faltan": len(cv.faltan(db, lease))})
    db.commit()
    return Response(datos, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    headers={"Content-Disposition": f'attachment; filename="contrato_{cv.referencia(lease)}.docx"',
                             "Cache-Control": "no-store"})


# --------------------------------------------------------------------------- carpeta del expediente
def _tipo(datos: bytes) -> str | None:
    if datos[:5] == b"%PDF-":
        return "application/pdf"
    if datos[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if datos[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if datos[:4] == b"PK\x03\x04":
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    return None


@router.post("/alquiler/contratos/{lid}/expediente/documentos", status_code=201)
def upload(lid: int, fichero: UploadFile = File(...), clave: str = Form("otro"), nombre: str | None = Form(None),
           scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    lease = _lease(db, scope, lid, "alquiler.editar")
    if clave not in CLAVES_DOC:
        bad_request("Tipo de documento no válido")
    datos = fichero.file.read(TAM_MAX + 1)
    if len(datos) > TAM_MAX:
        bad_request("El fichero supera 20 MB")
    mime = _tipo(datos)
    if mime is None:
        bad_request("Formato no admitido: suba PDF, JPG, PNG o Word")
    nombre = (nombre or fichero.filename or CLAVES_DOC[clave]).strip()[:200]
    d = LeaseDocument(lease_id=lid, clave=clave, nombre=nombre, fichero=documentos.guardar(datos), mime=mime,
                      tamano=len(datos), sha256=documentos.huella(datos), user_id=scope.user.id)
    db.add(d)
    db.flush()
    audit(db, scope.user, "subir_documento", "contrato", lid, {"documento": d.id, "clave": clave})
    db.commit()
    return _salida(db, lease)


def _doc(db: Session, scope: Scope, lid: int, did: int, perm: str) -> tuple[Lease, LeaseDocument]:
    lease = _lease(db, scope, lid, perm)
    d = get_or_404(db, LeaseDocument, did)
    if d.lease_id != lid:
        bad_request("El documento no es de este contrato")
    return lease, d


@router.get("/alquiler/contratos/{lid}/expediente/documentos/{did}")
def view(lid: int, did: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _, d = _doc(db, scope, lid, did, "alquiler.ver")
    contenido = documentos.leer(d.fichero)
    audit(db, scope.user, "ver_documento", "contrato", lid, {"documento": did})
    db.commit()
    ext = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpg"}.get(d.mime, "docx")
    disp = "inline" if ext != "docx" else "attachment"
    return Response(contenido, media_type=d.mime, headers={
        "Content-Disposition": f'{disp}; filename="expediente_{lid}_{d.id}.{ext}"', "Cache-Control": "no-store"})


@router.delete("/alquiler/contratos/{lid}/expediente/documentos/{did}")
def delete(lid: int, did: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    lease, d = _doc(db, scope, lid, did, "alquiler.editar")
    documentos.borrar(d.fichero)
    audit(db, scope.user, "borrar_documento", "contrato", lid, {"documento": did, "clave": d.clave})
    db.delete(d)
    db.commit()
    return _salida(db, lease)


# --------------------------------------------------------------------------- agenda
@router.post("/alquiler/contratos/{lid}/expediente/agenda")
def schedule(lid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Crea (o actualiza si cambiaron las fechas) las citas y tareas del expediente en la agenda de quien prepara el
    contrato. Son privadas; desde la agenda se pueden compartir o asignar a otra persona."""
    lease = _lease(db, scope, lid, "alquiler.editar")
    exp = _exp(lease)
    ids = exp.setdefault("agenda", {})
    plan = cv.agenda(lease)
    if not plan:
        bad_request("Indique al menos la fecha de firma en los datos del contrato")
    marcas = exp.get("checklist") or {}
    planificadas = set()
    for p in plan:
        clave = p.pop("clave")
        planificadas.add(clave)
        e = db.get(AgendaEvent, ids[clave]) if ids.get(clave) else None
        if e is None:
            e = AgendaEvent(creador_id=scope.user.id, visibilidad="privada", asset_id=lease.unit.asset_id,
                            participantes=[])
            db.add(e)
        for k, v in p.items():
            setattr(e, k, v)
        if (marcas.get(clave) or {}).get("estado") in ("hecho", "no_aplica"):
            e.hecha = True
        db.flush()
        ids[clave] = e.id
    # Lo que ya no procede: la tarea se da por hecha (p. ej. cobros completados); la cita se quita
    for clave in set(ids) - planificadas:
        e = db.get(AgendaEvent, ids[clave])
        if e is not None and e.tipo == "tarea":
            e.hecha = True
            continue
        if e is not None:
            db.delete(e)
        ids.pop(clave)
    _guardar_exp(lease, exp)
    audit(db, scope.user, "agenda_expediente", "contrato", lid, {"citas": len(ids)})
    db.commit()
    return _salida(db, lease)


# --------------------------------------------------------------------------- ficha de la vivienda
class FichaIn(BaseModel):
    ficha: dict
    inventario: list[ElementoIn] | None = None


CAMPOS_FICHA = {"puerta", "cp", "superficie_util", "distribucion", "registro_propiedad", "finca", "cee_letra",
                "cee_registro", "cee_vigencia", "ibi_anual", "tasa_residuos_anual", "sin_contador",
                "sin_contador_importe", "bombin", "contadores", "llaves"}


@router.get("/unidades/{uid}/ficha-alquiler")
def get_sheet(uid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    u = get_or_404(db, Unit, uid)
    scope.require_asset("activos.ver", u.asset_id)
    f = u.ficha or {}
    llaves = {x.get("elemento"): x for x in f.get("llaves") or []}
    cont = {x.get("suministro"): x for x in f.get("contadores") or []}
    return {"ficha": f, "inventario": u.inventario or cv.inventario_tipo(), "inventario_propio": bool(u.inventario),
            "llaves": [llaves.get(n) or {"elemento": n, "uds": None, "obs": ""} for n in cv.LLAVES_TIPO],
            "contadores": [cont.get(n) or {"suministro": n, "cups": "", "titular": ""} for n in cv.CONTADORES_TIPO]}


@router.put("/unidades/{uid}/ficha-alquiler")
def put_sheet(uid: int, data: FichaIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    u = get_or_404(db, Unit, uid)
    scope.require_asset("activos.editar", u.asset_id)
    raros = set(data.ficha) - CAMPOS_FICHA
    if raros:
        bad_request(f"Campos no reconocidos: {', '.join(sorted(raros))}")
    if data.ficha.get("cee_letra") and str(data.ficha["cee_letra"]).upper() not in set("ABCDEFG"):
        bad_request("La calificación energética va de la A a la G")
    for k in ("ibi_anual", "tasa_residuos_anual", "superficie_util", "sin_contador_importe"):
        if data.ficha.get(k) not in (None, ""):
            try:
                if Decimal(str(data.ficha[k])) < 0:
                    raise ValueError
            except Exception:  # noqa: BLE001
                bad_request(f"Importe no válido: {k}")
    u.ficha = {k: v for k, v in data.ficha.items() if v not in (None, "", [])}
    if data.inventario is not None:
        u.inventario = [i.model_dump() for i in data.inventario] or None
    audit(db, scope.user, "ficha_alquiler", "unidad", uid, {"campos": sorted(u.ficha)})
    db.commit()
    return get_sheet(uid, scope, db)
