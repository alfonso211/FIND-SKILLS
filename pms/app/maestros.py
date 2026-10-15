"""Activos y unidades sincronizados con gestión (INVERGESTION) · contrato «fusion1», instrucción del 15/10/2026
(docs/fusion/INSTRUCCION_PMS_MAESTROS_ACTIVOS.txt; manda su punto 8, que gestión ya tiene desplegado).

Cada programa manda en lo suyo:
- El PMS manda en lo OPERATIVO de las unidades (alta y baja, código, bloque, uso, tipología, planta, superficie,
  dormitorios, capacidad, estado, situación, renta_base, tarifa_base_noche, anejos) y en los datos del activo.
- Gestión manda en lo PATRIMONIAL Y FISCAL (propietaria, referencia y valores catastrales, uso catastral, IBI y TRUA):
  llega en maestro.catastro y se guarda en `ref_catastral` y en el JSON `catastro`, de solo lectura en el PMS.

PMS → gestión (cola de la fusión, mismos reintentos y firma):
- maestro.unidad (creada | actualizada | baja) en cada alta, cambio operativo o baja, con su `version` (sube en cada
  cambio). La baja no borra: la unidad queda con fecha de baja (tiene historial).
- maestro.activo cuando cambian nombre, modalidad, dirección, municipio, provincia, C.P. o nº de registro turístico.
- maestro.cuadre cada noche a las 03:30 (Madrid): por activo, unidades por uso y huella sha256 (punto 8).
Gestión → PMS (POST /api/gestion/eventos, idempotente por id_evento):
- maestro.catastro: guarda ref_catastral y el resto en `catastro` si su versión es mayor que la guardada.
- maestro.pedir: vuelve a mandar maestro.unidad de todas las unidades del activo.
Sin eco (lo que llega de gestión no se reenvía) y un campo que no manda el emisor se ignora y se anota en auditoría.
Casilla «Sincronizar activos y unidades con gestión» (solo superadministración), apagada al desplegar: apagada, no se
manda nada y lo que llega se guarda «sin tratar». Al encenderla se mandan todas las unidades y todos los activos.
"""
import hashlib
import logging
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from . import gestion
from .database import SessionLocal, get_db
from .models import Ajuste, Asset, AuditLog, Company, FusionEntrada, GestionEvento, Lease, Reservation, Unit, User
from .security import Scope, audit, get_scope
from .utils import bad_request, get_or_404

log = logging.getLogger("pms.maestros")
ZONA = ZoneInfo("Europe/Madrid")

AJUSTE = "maestros_sync"
TIPOS_SALIDA = ("maestro.unidad", "maestro.activo", "maestro.cuadre")
TIPOS_ENTRADA = ("maestro.catastro", "maestro.pedir", "maestro.unidad", "maestro.activo")
OPERATIVOS = ("codigo", "bloque", "uso", "tipologia", "planta", "superficie_m2", "dormitorios", "capacidad", "estado",
              "situacion", "renta_base", "tarifa_base_noche", "anejos")
DATOS_ACTIVO = ("nombre", "modalidad", "direccion", "municipio", "provincia", "cp", "num_registro_turistico")
PROPIETARIAS = {"INV", "CDC", "EC", "ETH"}
# lo que manda gestión en maestro.catastro (los años van en el nombre: ibi_2026, trua_2026)
CATASTRO = ("propietaria", "ref_catastral", "valor_suelo", "valor_construccion", "valor_catastral", "uso", "version")
CATASTRO_ACTIVO = CATASTRO + ("incluido_en", "resumen")
CABECERA = ("ambito", "pms_id", "activo_pms", "activo")
ANUAL = re.compile(r"^(ibi|trua)_\d{4}$")
HORA_CUADRE = (3, 30)
SIN_TRATAR = "sin_tratar"

router = APIRouter(prefix="/api/maestros", tags=["maestros"])


# --------------------------------------------------------------------------- casilla
def activo(db: Session) -> bool:
    a = db.get(Ajuste, AJUSTE)
    return bool(a and (a.valor or {}).get("activo"))


def poner(db: Session, valor: bool, user: User | None) -> None:
    a = db.get(Ajuste, AJUSTE)
    if a is None:
        a = Ajuste(clave=AJUSTE)
        db.add(a)
    a.valor, a.cambiado, a.user_id = {"activo": bool(valor)}, datetime.now(), user.id if user else None


def es_aviso(ev: GestionEvento) -> bool:
    return ev.tipo in TIPOS_SALIDA


# --------------------------------------------------------------------------- datos que se mandan
def _num(x):
    if x is None:
        return None
    if isinstance(x, Decimal):
        return float(x)
    return x


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def datos_unidad(u: Unit, codigo_activo: str, accion: str) -> dict:
    d = {"pms_id": u.id, "accion": accion, "version": int(u.maestro_version or 0), "activo_pms": codigo_activo,
         "cambiado": (u.maestro_cambiado or u.baja or datetime.now()).isoformat(timespec="seconds")}
    for c in OPERATIVOS:
        d[c] = _num(getattr(u, c))
    d["uso"] = (u.uso or "").lower() or None
    return d


def datos_activo(a: Asset) -> dict:
    return {"activo_pms": a.codigo, **{c: getattr(a, c) for c in DATOS_ACTIVO}}


def _sobre(db: Session, a: Asset | None, datos: dict) -> dict:
    from . import fusion
    comp = db.get(Company, a.company_id) if a else None
    return {"version": fusion.VERSION, "emitido": _utc(), "origen": "PMS", "id_evento_causa": None,
            "activo": gestion._codigo_gestion(a) if a else None, "sociedad": fusion.sociedad(comp),
            "datos": datos, "documentos": []}


def encolar_unidad(db: Session, u: Unit, accion: str, a: Asset | None = None,
                   causa: str | None = None) -> GestionEvento:
    a = a or db.get(Asset, u.asset_id)
    sobre = _sobre(db, a, datos_unidad(u, a.codigo, accion))
    sobre["id_evento_causa"] = causa
    clave = f"pms-mae-u{u.id}-v{int(u.maestro_version or 0)}-{uuid.uuid4().hex[:10]}"
    return gestion.encolar(db, "maestro.unidad", sobre, clave=clave)


def encolar_activo(db: Session, a: Asset) -> GestionEvento:
    return gestion.encolar(db, "maestro.activo", _sobre(db, a, datos_activo(a)),
                           clave=f"pms-mae-a{a.id}-{uuid.uuid4().hex[:10]}")


# --------------------------------------------------------------------------- versión y detección de cambios
@event.listens_for(SessionLocal, "before_flush")
def _versionar(session: Session, _ctx, _inst) -> None:
    """La versión de la unidad sube en cada cambio operativo (y al darla de baja o reactivarla), esté o no encendida
    la casilla: así la que viaja siempre es la última."""
    from sqlalchemy import inspect as sa_inspect
    ahora = datetime.now().replace(microsecond=0)
    for obj in session.new:
        if isinstance(obj, Unit):
            obj.maestro_version = max(int(obj.maestro_version or 0), 0) + 1
            obj.maestro_cambiado = ahora
    for obj in session.dirty:
        if isinstance(obj, Unit) and obj not in session.new:
            st = sa_inspect(obj)
            if any(st.attrs[c].history.has_changes() for c in OPERATIVOS + ("baja",)):
                obj.maestro_version = int(obj.maestro_version or 0) + 1
                obj.maestro_cambiado = ahora


@event.listens_for(SessionLocal, "after_flush")
def _detectar(session: Session, _ctx) -> None:
    from . import fusion
    if session.info.get(fusion.DESDE_GESTION):
        return  # sin eco: lo que llega de gestión no se reenvía
    from sqlalchemy import inspect as sa_inspect
    pend = session.info.setdefault("maestros_pend", {})
    for obj in session.new:
        if isinstance(obj, Unit):
            pend[("u", obj.id)] = "creada"
        elif isinstance(obj, Asset):
            pend[("a", obj.id)] = "actualizado"
    for obj in session.dirty:
        if obj in session.new:
            continue
        st = sa_inspect(obj)
        if isinstance(obj, Unit):
            if st.attrs["baja"].history.has_changes():
                pend[("u", obj.id)] = "baja" if obj.baja else "actualizada"
            elif any(st.attrs[c].history.has_changes() for c in OPERATIVOS):
                pend.setdefault(("u", obj.id), "actualizada")
        elif isinstance(obj, Asset) and any(st.attrs[c].history.has_changes() for c in DATOS_ACTIVO):
            pend[("a", obj.id)] = "actualizado"
    for obj in session.deleted:  # borrado físico (p. ej. la unidad de prueba de la pasarela): para gestión, baja
        if isinstance(obj, Unit):
            a = session.get(Asset, obj.asset_id)
            pend[("x", obj.id)] = datos_unidad(obj, a.codigo if a else "", "baja") | {
                "version": int(obj.maestro_version or 0) + 1, "_asset": obj.asset_id}


@event.listens_for(SessionLocal, "after_flush_postexec")
def _encolar(session: Session, _ctx) -> None:
    pend = session.info.pop("maestros_pend", None)
    if not pend:
        return
    try:
        if not activo(session):
            return
        for (clase, ref), accion in pend.items():
            if clase == "u":
                u = session.get(Unit, ref)
                if u is not None:
                    encolar_unidad(session, u, accion)
            elif clase == "a":
                a = session.get(Asset, ref)
                if a is not None:
                    encolar_activo(session, a)
            else:
                datos = dict(accion)
                a = session.get(Asset, datos.pop("_asset"))
                gestion.encolar(session, "maestro.unidad", _sobre(session, a, datos),
                                clave=f"pms-mae-u{ref}-v{datos['version']}-{uuid.uuid4().hex[:10]}")
    except Exception:  # noqa: BLE001 — un fallo al preparar el aviso a gestión no debe impedir la operación
        log.exception("No se pudo preparar el aviso de maestros para gestión")


# --------------------------------------------------------------------------- carga inicial y cuadre
def carga_inicial(db: Session, asset: Asset | None = None, causa: str | None = None,
                  con_activos: bool = True) -> int:
    """Todas las unidades (de un activo o de todos) como maestro.unidad «actualizada» con su versión actual; las de
    baja, como «baja». Y maestro.activo de cada activo."""
    n = 0
    q = select(Asset).order_by(Asset.id)
    if asset is not None:
        q = q.where(Asset.id == asset.id)
    for a in db.scalars(q):
        if con_activos:
            encolar_activo(db, a)
        for u in db.scalars(select(Unit).where(Unit.asset_id == a.id).order_by(Unit.id)):
            encolar_unidad(db, u, "baja" if u.baja else "actualizada", a, causa)
            n += 1
    return n


def huella(unidades) -> str:
    """Punto 8: una línea por unidad no dada de baja «pms_id|codigo|uso|situacion» (uso en minúsculas; vacío si no
    hay dato), por pms_id ascendente, unidas con «\\n» sin salto final; sha256 hexadecimal de UTF-8."""
    lineas = [f"{u.id}|{u.codigo or ''}|{(u.uso or '').lower()}|{u.situacion or ''}"
              for u in sorted(unidades, key=lambda x: x.id) if not u.baja]
    return hashlib.sha256("\n".join(lineas).encode("utf-8")).hexdigest()


def datos_cuadre(db: Session) -> dict:
    activos = []
    for a in db.scalars(select(Asset).order_by(Asset.codigo)):
        unidades = [u for u in db.scalars(select(Unit).where(Unit.asset_id == a.id)) if not u.baja]
        por_uso: dict[str, int] = {}
        for u in unidades:
            k = (u.uso or "").lower()
            por_uso[k] = por_uso.get(k, 0) + 1
        activos.append({"activo_pms": a.codigo, "por_uso": dict(sorted(por_uso.items())), "huella": huella(unidades)})
    return {"activos": activos}


def cuadre(db: Session, ahora: datetime | None = None) -> GestionEvento | None:
    """Cada noche a partir de las 03:30 (Madrid), una vez al día y solo con la casilla encendida."""
    ahora = ahora or datetime.now(ZONA)
    if (ahora.hour, ahora.minute) < HORA_CUADRE or not activo(db):
        return None
    ev = gestion.encolar(db, "maestro.cuadre", _sobre(db, None, datos_cuadre(db)),
                         clave=f"pms-mae-cuadre-{ahora.date().isoformat()}")
    if ev is not None:
        db.commit()
    return ev


# --------------------------------------------------------------------------- gestión → PMS
def _anotar_ignorados(db: Session, ide: str, tipo: str, campos: list[str]) -> None:
    if campos:
        db.add(AuditLog(user_id=None, accion="campo_ignorado", entidad="maestros", entidad_id=None,
                        detalle={"id_evento": ide, "tipo": tipo, "campos": sorted(campos),
                                 "motivo": "Campo que no manda gestión: se ignora"}))


def _unidad_de(db: Session, d: dict) -> Unit | None:
    try:
        uid = int(d.get("pms_id"))
    except (TypeError, ValueError):
        return None
    return db.get(Unit, uid)


def _activo_de(db: Session, d: dict) -> Asset | None:
    from . import fusion
    return fusion._activo_pms(db, d.get("activo_pms") or d.get("activo"))


def _aplicar_catastro(db: Session, ev: dict) -> tuple[str, dict | None]:
    d = ev.get("datos") or {}
    ide = str(ev.get("id_evento"))
    ambito = d.get("ambito") or ("unidad" if d.get("pms_id") is not None else "activo")
    permitidos = CATASTRO if ambito == "unidad" else CATASTRO_ACTIVO
    ignorados = [k for k in d if k not in permitidos and k not in CABECERA and not ANUAL.match(str(k))]
    _anotar_ignorados(db, ide, "maestro.catastro", ignorados)
    if ambito == "unidad":
        ficha = _unidad_de(db, d)
        if ficha is None:
            return SIN_TRATAR, {"motivo": "Unidad que no está en el PMS", "pms_id": d.get("pms_id")}
    elif ambito == "activo":
        ficha = _activo_de(db, d)
        if ficha is None:
            return SIN_TRATAR, {"motivo": "Activo que no está en el PMS", "activo_pms": d.get("activo_pms")}
    else:
        return SIN_TRATAR, {"motivo": f"Ámbito no válido: {ambito}"}
    try:
        version = int(d.get("version"))
    except (TypeError, ValueError):
        return SIN_TRATAR, {"motivo": "Sin versión"}
    previa = int((ficha.catastro or {}).get("version") or 0)
    if version <= previa:
        return "ignorado", {"motivo": "Versión repetida o anterior", "version": version, "guardada": previa}
    if d.get("propietaria") and d["propietaria"] not in PROPIETARIAS:
        _anotar_ignorados(db, ide, "maestro.catastro", ["propietaria"])
    nuevo = {k: v for k, v in d.items() if (k in permitidos or ANUAL.match(str(k))) and k != "ref_catastral"}
    if nuevo.get("propietaria") not in PROPIETARIAS:
        nuevo.pop("propietaria", None)
    nuevo["version"] = version
    nuevo["recibido"] = datetime.now().isoformat(timespec="seconds")
    nuevo["id_evento"] = ide
    ficha.catastro = nuevo
    if "ref_catastral" in d:
        ficha.ref_catastral = (str(d["ref_catastral"]).strip()[:30] or None) if d["ref_catastral"] else None
    res = {"ambito": ambito, "version": version, "ref_catastral": ficha.ref_catastral}
    res["pms_id" if ambito == "unidad" else "activo_pms"] = ficha.id if ambito == "unidad" else ficha.codigo
    return "aplicado", res


def _aplicar_pedir(db: Session, ev: dict) -> tuple[str, dict | None]:
    d = ev.get("datos") or {}
    _anotar_ignorados(db, str(ev.get("id_evento")), "maestro.pedir",
                      [k for k in d if k not in ("activo_pms", "activo", "pms_ids")])
    a = _activo_de(db, d)
    if a is None:
        return SIN_TRATAR, {"motivo": "Activo que no está en el PMS", "activo_pms": d.get("activo_pms")}
    ids = d.get("pms_ids", "todos")
    causa = str(ev.get("id_evento"))
    if ids == "todos":
        n = carga_inicial(db, a, causa, con_activos=False)
    elif isinstance(ids, list):
        n = 0
        for x in ids:
            try:
                u = db.get(Unit, int(x))
            except (TypeError, ValueError):
                continue
            if u is not None and u.asset_id == a.id:
                encolar_unidad(db, u, "baja" if u.baja else "actualizada", a, causa)
                n += 1
    else:
        return SIN_TRATAR, {"motivo": "pms_ids no válido"}
    return "aplicado", {"activo_pms": a.codigo, "unidades": n}


def _rechazar_operativo(db: Session, ev: dict) -> tuple[str, dict | None]:
    """maestro.unidad / maestro.activo que llegan de gestión: lo operativo lo manda el PMS. Todo se ignora y se anota."""
    d = ev.get("datos") or {}
    _anotar_ignorados(db, str(ev.get("id_evento")), str(ev.get("tipo")), list(d))
    return "ignorado", {"motivo": "Lo operativo de activos y unidades lo manda el PMS"}


APLICAR = {"maestro.catastro": _aplicar_catastro, "maestro.pedir": _aplicar_pedir,
           "maestro.unidad": _rechazar_operativo, "maestro.activo": _rechazar_operativo}


def recibir(db: Session, ev: dict) -> tuple[str, dict | None]:
    """Llamado desde POST /api/gestion/eventos (fusión). Con la casilla apagada se guarda «sin tratar»."""
    if not activo(db):
        return SIN_TRATAR, None
    return APLICAR[ev["tipo"]](db, ev)


def reprocesar_sin_tratar(db: Session) -> dict:
    """Al encender: los maestro.catastro que llegaron con la casilla apagada se aplican en orden (la versión evita
    duplicados). Los maestro.pedir quedan cubiertos por la carga inicial."""
    from . import fusion
    ok = mal = 0
    for x in list(db.scalars(select(FusionEntrada).where(FusionEntrada.tipo.in_(TIPOS_ENTRADA),
                                                         FusionEntrada.estado == SIN_TRATAR)
                              .order_by(FusionEntrada.recibido, FusionEntrada.id))):
        if x.tipo == "maestro.pedir":
            x.estado, x.resultado = "aplicado", {"nota": "Cubierto por la carga inicial al encender"}
            continue
        db.info[fusion.DESDE_GESTION] = True
        try:
            with db.begin_nested():
                x.estado, x.resultado = APLICAR[x.tipo](db, x.cuerpo or {})
                db.flush()
            ok += 1
        except Exception as e:  # noqa: BLE001 — sigue «sin tratar»: no se pierde
            x.resultado = {"error": str(e)[:300]}
            mal += 1
        finally:
            db.info.pop(fusion.DESDE_GESTION, None)
    return {"aplicados": ok, "con_error": mal}


# --------------------------------------------------------------------------- reglas en el PMS
def comprobar_catastro(ficha, valores: dict) -> None:
    """La referencia catastral la manda gestión: con el catastro recibido no se cambia en el PMS."""
    if ficha.catastro and "ref_catastral" in valores and (valores["ref_catastral"] or None) != (ficha.ref_catastral or None):
        bad_request("La referencia catastral se edita en gestión")


class BajaIn(BaseModel):
    motivo: str = Field(min_length=3, max_length=300)


@router.post("/unidades/{uid}/baja")
def dar_baja(uid: int, data: BajaIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    """Baja de una unidad: no se borra (tiene reservas, contratos y facturas). Queda fuera de servicio y gestión la
    marca BAJA."""
    u = get_or_404(db, Unit, uid)
    scope.require_asset("activos.editar", u.asset_id)
    if u.baja:
        bad_request("La unidad ya está dada de baja")
    hoy = date.today()
    if db.scalar(select(Reservation.id).where(Reservation.unit_id == uid, Reservation.estado.in_(("confirmada", "checkin")),
                                              Reservation.fecha_salida >= hoy).limit(1)):
        bad_request("La unidad tiene reservas pendientes: reubíquelas antes de darla de baja")
    if db.scalar(select(Lease.id).where(Lease.unit_id == uid, Lease.estado.in_(("borrador", "vigente"))).limit(1)):
        bad_request("La unidad tiene un contrato vigente: finalícelo antes de darla de baja")
    u.baja, u.estado = datetime.now().replace(microsecond=0), "fuera_servicio"
    audit(db, scope.user, "baja", "unidad", uid, {"codigo": u.codigo, "motivo": data.motivo})
    db.commit()
    return u.to_dict()


@router.post("/unidades/{uid}/reactivar")
def reactivar(uid: int, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    u = get_or_404(db, Unit, uid)
    scope.require_asset("activos.editar", u.asset_id)
    if not u.baja:
        bad_request("La unidad no está dada de baja")
    u.baja, u.estado = None, "disponible"
    audit(db, scope.user, "reactivar", "unidad", uid, {"codigo": u.codigo})
    db.commit()
    return u.to_dict()


# --------------------------------------------------------------------------- casilla (superadministración)
def _superadmin(scope: Scope) -> None:
    if not scope.user.is_superadmin:
        raise HTTPException(403, "Solo la superadministración")


@router.get("/config")
def ver_config(scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _superadmin(scope)
    a = db.get(Ajuste, AJUSTE)
    contar = lambda q: db.scalar(q) or 0  # noqa: E731
    return {"activo": activo(db), "cambiado": a.cambiado.isoformat(timespec="seconds") if a else None,
            "en_cola": contar(select(func.count()).select_from(GestionEvento).where(
                GestionEvento.tipo.in_(TIPOS_SALIDA), GestionEvento.estado.in_(("pendiente", "aviso")))),
            "sin_tratar": contar(select(func.count()).select_from(FusionEntrada).where(
                FusionEntrada.tipo.in_(TIPOS_ENTRADA), FusionEntrada.estado == SIN_TRATAR)),
            "con_catastro": contar(select(func.count()).select_from(Unit).where(Unit.catastro.is_not(None))),
            "unidades": contar(select(func.count()).select_from(Unit).where(Unit.baja.is_(None))),
            "bajas": contar(select(func.count()).select_from(Unit).where(Unit.baja.is_not(None)))}


class ConfigIn(BaseModel):
    activo: bool


@router.put("/config")
def guardar_config(data: ConfigIn, scope: Scope = Depends(get_scope), db: Session = Depends(get_db)):
    _superadmin(scope)
    antes = activo(db)
    poner(db, data.activo, scope.user)
    db.flush()
    enciende = data.activo and not antes
    aplicados = reprocesar_sin_tratar(db) if enciende else {"aplicados": 0, "con_error": 0}
    n = carga_inicial(db) if enciende else 0
    audit(db, scope.user, "maestros_sync", "ajustes", None, {"antes": antes, "ahora": data.activo, "carga": n,
                                                            **aplicados})
    db.commit()
    return {**ver_config(scope, db), "carga_inicial": n, "sin_tratar_aplicados": aplicados["aplicados"],
            "sin_tratar_con_error": aplicados["con_error"]}
