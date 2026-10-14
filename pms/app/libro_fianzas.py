"""Libro de fianzas y contabilidad de las fianzas desde los avisos a gestión (versión 1.58).

Las fianzas no son ingresos: son dinero del cliente que se custodia hasta su salida.
- Cobro al llegar (efectivo, tarjeta, Bizum o transferencia): entra en caja o bancos contra la cuenta de fianzas
  recibidas (560). Una preautorización de tarjeta no mueve dinero: no hay asiento hasta la salida.
- Devolución: sale de caja o bancos contra la 560. Lo retenido por roturas o faltas deja de ser del cliente y pasa a
  ingreso del activo (778). Si se devuelve por transferencia, lo devuelto sigue en la 560 hasta que la Dirección hace
  la transferencia (aviso fianza.transferida).

Con PMS_FIANZAS_ORIGEN=avisos, gestión contabiliza desde los avisos fianza.* (llevan la empresa, el asiento sugerido
y el saldo en custodia del activo) a partir de PMS_FIANZAS_AVISOS_DESDE; el CSV de la exportación queda como control.
Las cuentas son una sugerencia (Plan General Contable): gestión puede usar las suyas.
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import Asset, DepositRefund, GestionEvento, Reservation, Unit

CUENTAS = {"fianzas": ("560", "Fianzas recibidas a corto plazo"), "caja": ("570", "Caja"),
           "bancos": ("572", "Bancos"), "retenido": ("778", "Ingresos excepcionales (fianza retenida)")}
TIPOS = ("fianza.cobrada", "fianza.devolucion", "fianza.transferida")
NOMBRES = {"fianza.cobrada": "Cobro", "fianza.devolucion": "Devolución", "fianza.transferida": "Transferencia hecha"}
ESTADOS_AVISO = {"enviado": "recibido por gestión", "pendiente": "en cola", "aviso": "falla el envío",
                 None: "sin aviso"}


def origen() -> str:
    return settings.fianzas_origen


def corte() -> date | None:
    try:
        return date.fromisoformat(settings.fianzas_avisos_desde) if settings.fianzas_avisos_desde else None
    except ValueError:
        return None


def _r2(x) -> float:
    return round(float(x or 0), 2)


def _tesoreria(forma: str | None) -> str:
    return "caja" if forma == "efectivo" else "bancos"


def _linea(cuenta: str, debe: float = 0, haber: float = 0) -> dict:
    num, nombre = CUENTAS[cuenta]
    return {"cuenta": num, "nombre": nombre, "debe": _r2(debe), "haber": _r2(haber)}


def _cobro(r: Reservation) -> dict | None:
    c = r.fianza_cobro
    return c if isinstance(c, dict) and c.get("importe") is not None else None


def _preautorizada(r: Reservation) -> bool:
    return (_cobro(r) or {}).get("forma") == "preautorizacion"


def asiento(tipo: str, r: Reservation, d: DepositRefund | None = None) -> list[dict]:
    """Asiento sugerido del movimiento (vacío si no mueve dinero)."""
    c = _cobro(r)
    if tipo == "fianza.cobrada":
        if not c or c.get("forma") == "preautorizacion":
            return []
        return [_linea(_tesoreria(c.get("forma")), debe=c["importe"]), _linea("fianzas", haber=c["importe"])]
    if d is None:
        return []
    fianza, devuelto = _r2(d.fianza), _r2(d.importe)
    retenido = _r2(fianza - devuelto)
    if tipo == "fianza.transferida":
        if c and c.get("forma") == "preautorizacion":
            return []
        return [_linea("fianzas", debe=devuelto), _linea("bancos", haber=devuelto)] if devuelto else []
    # fianza.devolucion
    if c and c.get("forma") == "preautorizacion":  # se cobra solo lo retenido; lo demás se libera
        return [_linea("bancos", debe=retenido), _linea("retenido", haber=retenido)] if retenido else []
    out = []
    if retenido:
        out += [_linea("fianzas", debe=retenido), _linea("retenido", haber=retenido)]
    if devuelto and d.forma != "transferencia":  # en efectivo o a la tarjeta: sale ahora
        out += [_linea("fianzas", debe=devuelto), _linea(_tesoreria(d.forma), haber=devuelto)]
    return out


def saldo(db: Session, asset_id: int) -> dict:
    """Fianzas que se custodian ahora en el activo: cobradas a clientes que no han salido y devoluciones por
    transferencia aún sin hacer (dinero) y preautorizaciones de tarjeta abiertas (no es dinero)."""
    custodia = preaut = por_transferir = 0.0
    n = 0
    devueltas = set(db.scalars(select(DepositRefund.reservation_id).join(Reservation, Reservation.id == DepositRefund.reservation_id)
                               .where(DepositRefund.asset_id == asset_id, Reservation.estado.in_(("confirmada", "checkin")))))
    for r in db.scalars(select(Reservation).join(Unit, Unit.id == Reservation.unit_id).where(
            Unit.asset_id == asset_id, Reservation.estado.in_(("confirmada", "checkin")))):
        c = _cobro(r)
        if not c or r.id in devueltas:  # con la devolución registrada ya no es de un cliente alojado
            continue
        if c.get("forma") == "preautorizacion":
            preaut += float(c["importe"])
        else:
            custodia += float(c["importe"])
            n += 1
    for d, r in db.execute(select(DepositRefund, Reservation).join(Reservation, Reservation.id == DepositRefund.reservation_id)
                           .where(DepositRefund.asset_id == asset_id, DepositRefund.estado == "pendiente")):
        if not _preautorizada(r):
            por_transferir += float(d.importe)
    return {"custodia": _r2(custodia + por_transferir), "alojados": _r2(custodia), "clientes": n,
            "por_transferir": _r2(por_transferir), "preautorizado": _r2(preaut)}


def contabiliza(fecha: date) -> bool:
    """¿Este movimiento lo contabiliza gestión desde el aviso? (no si sigue el CSV o es anterior al corte)."""
    k = corte()
    return origen() == "avisos" and (k is None or fecha >= k)


def contable(db: Session, tipo: str, r: Reservation, d: DepositRefund | None = None,
             fecha: date | None = None) -> dict:
    """Campos que se añaden a los avisos fianza.* para contabilizarlos en gestión (no cambian los que ya había)."""
    db.flush()
    a = db.get(Asset, r.unit.asset_id)
    s = saldo(db, a.id)
    fecha = fecha or date.today()
    return {"empresa": {"nombre": a.company.nombre, "cif": a.company.cif} if a.company else None,
            "origen_contable": origen(), "contabilizar": contabiliza(fecha),
            "cobro_registrado": _cobro(r) is not None, "asiento": asiento(tipo, r, d),
            "saldo_activo": s["custodia"], "preautorizado_activo": s["preautorizado"]}


# --------------------------------------------------------------------------- libro
def _avisos(db: Session, desde: date) -> dict[tuple[str, int], GestionEvento]:
    out = {}
    for e in db.scalars(select(GestionEvento).where(GestionEvento.tipo.in_(TIPOS),
                                                    GestionEvento.creado >= datetime.combine(desde, datetime.min.time())
                                                    - timedelta(days=60)).order_by(GestionEvento.id)):
        rid = (e.datos or {}).get("reserva_id")
        if rid is not None:
            out[(e.tipo, int(rid))] = e
    return out


def _estado_aviso(e: GestionEvento | None) -> str:
    if e is not None and e.estado == "pendiente":
        from .gestion import V2
        if not V2:
            return "guardado (avisos v2 sin activar)"
    return ESTADOS_AVISO.get(e.estado if e else None, e.estado if e else "sin aviso")


def movimientos(db: Session, asset_ids: set[int], desde: date, hasta: date) -> list[dict]:
    """Cobros, devoluciones y transferencias de fianza del periodo, con su asiento y el estado del aviso."""
    ini, fin = datetime.combine(desde, datetime.min.time()), datetime.combine(hasta, datetime.max.time())
    ids = asset_ids or {-1}
    avisos = _avisos(db, desde)
    unidades = {u.id: u for u in db.scalars(select(Unit).where(Unit.asset_id.in_(ids)))}
    activos = {a.id: a.nombre for a in db.scalars(select(Asset).where(Asset.id.in_(ids)))}
    out = []

    def mov(tipo, fecha, r, d, importe, forma):
        u = unidades.get(r.unit_id)
        e = avisos.get((tipo, r.id))
        out.append({"fecha": fecha.isoformat(), "tipo": tipo, "tipo_nombre": NOMBRES[tipo],
                    "asset_id": u.asset_id if u else None, "activo": activos.get(u.asset_id) if u else None,
                    "unidad": u.codigo if u else None, "reserva_id": r.id, "localizador": r.localizador,
                    "titular": " ".join(x for x in (r.guest.nombre, r.guest.apellidos) if x) if r.guest else "",
                    "importe": _r2(importe), "forma": forma,
                    "retenido": _r2(float(d.fianza) - float(d.importe)) if d is not None and tipo == "fianza.devolucion" else 0,
                    "asiento": asiento(tipo, r, d), "aviso": _estado_aviso(e), "aviso_estado": e.estado if e else None,
                    "contabiliza_gestion": contabiliza(fecha), "devolucion_id": d.id if d is not None else None})

    # cobros: la fecha está en la reserva (las estancias que tocan el periodo, con margen para cobros anticipados)
    for r in db.scalars(select(Reservation).join(Unit, Unit.id == Reservation.unit_id).where(
            Unit.asset_id.in_(ids), Reservation.fecha_salida >= desde,
            Reservation.fecha_entrada <= hasta + timedelta(days=60))):
        c = _cobro(r)
        if c and c.get("fecha"):
            f = datetime.fromisoformat(c["fecha"])
            if ini <= f <= fin:
                mov("fianza.cobrada", f.date(), r, None, c["importe"], c.get("forma"))
    for d, r in db.execute(select(DepositRefund, Reservation).join(Reservation, Reservation.id == DepositRefund.reservation_id)
                           .where(DepositRefund.asset_id.in_(ids))):
        if ini <= d.creada <= fin:
            mov("fianza.devolucion", d.creada.date(), r, d, d.importe, d.forma)
        if d.forma == "transferencia" and d.estado == "devuelta" and d.devuelta_fecha and desde <= d.devuelta_fecha <= hasta:
            mov("fianza.transferida", d.devuelta_fecha, r, d, d.importe, "transferencia")
    out.sort(key=lambda x: (x["fecha"], x["reserva_id"], TIPOS.index(x["tipo"])))
    return out


def cuadre(db: Session, asset_ids: set[int], movs: list[dict], hasta: date) -> list[dict]:
    """Lo que no cuadra entre el PMS y lo que ha recibido gestión (o lo que hay que revisar a mano)."""
    k = corte()
    out = []
    for m in movs:
        ref = f"{m['activo']} · {m['unidad']} · {m['localizador'] or 'R-' + str(m['reserva_id'])}"
        if m["aviso_estado"] is None and (k is None or m["fecha"] >= k.isoformat()):
            out.append({"tipo": "sin_aviso", "texto": f"{m['tipo_nombre']} del {m['fecha']} sin aviso a gestión", "ref": ref,
                        "reserva_id": m["reserva_id"], "movimiento": m["tipo"]})
        elif m["aviso_estado"] == "aviso":
            out.append({"tipo": "falla", "texto": f"{m['tipo_nombre']} del {m['fecha']}: el aviso no llega a gestión "
                        "(se sigue reintentando)", "ref": ref, "reserva_id": m["reserva_id"], "movimiento": m["tipo"]})
    ids = asset_ids or {-1}
    for d, r, u in db.execute(select(DepositRefund, Reservation, Unit).join(Reservation, Reservation.id == DepositRefund.reservation_id)
                              .join(Unit, Unit.id == Reservation.unit_id).where(DepositRefund.asset_id.in_(ids))):
        if not _cobro(r) and float(d.fianza) > 0 and (k is None or d.creada.date() >= k):
            out.append({"tipo": "sin_cobro", "texto": f"Devolución del {d.creada:%d/%m/%Y} sin el cobro de la fianza "
                        "registrado en el PMS: comprobar cuándo y cómo se cobró", "ref": f"{u.codigo} · {r.localizador or r.id}",
                        "reserva_id": r.id, "movimiento": "fianza.devolucion"})
    devueltas = set(db.scalars(select(DepositRefund.reservation_id).where(DepositRefund.asset_id.in_(ids))))
    for r, u in db.execute(select(Reservation, Unit).join(Unit, Unit.id == Reservation.unit_id).where(
            Unit.asset_id.in_(ids), Reservation.estado.not_in(("confirmada", "checkin")),
            Reservation.fecha_entrada <= hasta, Reservation.fecha_entrada >= hasta - timedelta(days=400))):
        if _cobro(r) and r.id not in devueltas:
            out.append({"tipo": "sin_devolver", "texto": f"Reserva {r.estado} con la fianza cobrada y sin devolución "
                        "registrada", "ref": f"{u.codigo} · {r.localizador or r.id}", "reserva_id": r.id,
                        "movimiento": None})
    return out


def libro(db: Session, asset_ids: set[int], desde: date, hasta: date) -> dict:
    movs = movimientos(db, asset_ids, desde, hasta)
    resumen = []
    for a in db.scalars(select(Asset).where(Asset.id.in_(asset_ids or {-1})).order_by(Asset.nombre)):
        tot = defaultdict(float)
        for m in movs:
            if m["asset_id"] != a.id:
                continue
            tot[m["tipo"]] += m["importe"]
            tot["retenido"] += m["retenido"]
        if not tot and a.modalidad != "apartamentos_turisticos":
            continue
        resumen.append({"asset_id": a.id, "activo": a.nombre, **saldo(db, a.id),
                        "cobrado": _r2(tot["fianza.cobrada"]), "devuelto": _r2(tot["fianza.devolucion"]),
                        "retenido": _r2(tot["retenido"]), "transferido": _r2(tot["fianza.transferida"])})
    k = corte()
    return {"desde": desde.isoformat(), "hasta": hasta.isoformat(), "origen": origen(),
            "corte": k.isoformat() if k else None, "cuentas": {k2: list(v) for k2, v in CUENTAS.items()},
            "resumen": resumen, "movimientos": movs, "cuadre": cuadre(db, asset_ids, movs, hasta)}


def generar_faltan(db: Session, asset_ids: set[int], desde: date, hasta: date) -> list[str]:
    """Crea los avisos que faltan (movimientos del corte en adelante sin aviso). Id fijo: no se duplican."""
    from . import gestion
    k = corte()
    if origen() != "avisos" or k is None:
        raise ValueError("Primero hay que fijar en el servidor PMS_FIANZAS_ORIGEN=avisos y PMS_FIANZAS_AVISOS_DESDE")
    creados = []
    for m in movimientos(db, asset_ids, max(desde, k), hasta):
        if m["aviso_estado"] is not None:
            continue
        r = db.get(Reservation, m["reserva_id"])
        d = db.get(DepositRefund, m["devolucion_id"]) if m["devolucion_id"] else None
        datos = {**gestion._datos_reserva(r), "fianza": m["importe"] if d is None else _r2(d.fianza),
                 "forma": m["forma"], "fecha": m["fecha"], "generado_desde_libro": True}
        if d is not None:
            datos.update({"devolucion_id": d.id, "devuelto": _r2(d.importe)})
            if m["tipo"] == "fianza.devolucion":
                datos.update({"retenido": m["retenido"], "estado": d.estado, "cargos": d.cargos or [],
                              "cargos_total": _r2(sum(float(c.get("importe") or 0) for c in d.cargos or [])),
                              "cobro": _cobro(r) and {x: _cobro(r).get(x) for x in ("forma", "fecha")},
                              "factura_exceso": None})
        datos.update(contable(db, m["tipo"], r, d, date.fromisoformat(m["fecha"])))
        if gestion.encolar(db, m["tipo"], datos, clave=f"pms-{m['tipo']}-r{r.id}") is not None:
            creados.append(f"{m['tipo_nombre']} · {m['unidad']} · {m['fecha']}")
    return creados


def excel(datos: dict) -> bytes:
    """Libro de fianzas en Excel: resumen por activo, movimientos con su asiento y lo que no cuadra."""
    import io

    from openpyxl import Workbook

    from .routers.informes import EUR, _hoja
    wb = Workbook()
    wb.remove(wb.active)
    _hoja(wb, "Resumen", ["Activo", "En custodia ahora", "De clientes alojados", "Por transferir", "Preautorizado (tarjeta)",
                          "Cobrado en el periodo", "Devuelto en el periodo", "Retenido en el periodo",
                          "Transferido en el periodo"],
          [[x["activo"], x["custodia"], x["alojados"], x["por_transferir"], x["preautorizado"], x["cobrado"],
            x["devuelto"], x["retenido"], x["transferido"]] for x in datos["resumen"]],
          {i: EUR for i in range(1, 9)}, totales=list(range(1, 9)),
          nota=f"Periodo {datos['desde']} a {datos['hasta']}. Contabiliza gestión desde: "
               f"{'los avisos fianza.*' if datos['origen'] == 'avisos' else 'el CSV FIANZAS_*.csv'}"
               f"{' (desde el ' + datos['corte'] + ')' if datos['corte'] else ''}. La preautorización no es dinero.")
    filas = []
    for m in datos["movimientos"]:
        lineas = m["asiento"] or [{"cuenta": "", "nombre": "sin asiento (no mueve dinero)", "debe": None, "haber": None}]
        for i, x in enumerate(lineas):
            filas.append([m["fecha"] if i == 0 else None, m["tipo_nombre"] if i == 0 else None,
                          m["activo"] if i == 0 else None, m["unidad"] if i == 0 else None,
                          (m["localizador"] or f"R-{m['reserva_id']}") if i == 0 else None,
                          m["importe"] if i == 0 else None, m["forma"] if i == 0 else None,
                          x["cuenta"], x["nombre"], x["debe"], x["haber"], m["aviso"] if i == 0 else None])
    _hoja(wb, "Movimientos", ["Fecha", "Movimiento", "Activo", "Apto.", "Reserva", "Importe", "Forma", "Cuenta",
                              "Nombre de la cuenta", "Debe", "Haber", "Aviso a gestión"],
          filas, {5: EUR, 9: EUR, 10: EUR}, totales=[9, 10],
          nota="Asiento sugerido (Plan General Contable): 560 fianzas recibidas, 570 caja, 572 bancos, 778 retenido.")
    _hoja(wb, "Cuadre", ["Qué pasa", "Activo · apto. · reserva"],
          [[x["texto"], x["ref"]] for x in datos["cuadre"]] or [["Todo cuadra", ""]])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()
