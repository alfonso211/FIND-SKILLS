"""Facturación: numeración correlativa por serie y año, IVA y huella encadenada.

- Cada activo tiene su serie (B35, SF, SA...) y factura su sociedad gestora. El número se reinicia cada año:
  SF/00001/2026, SF/00002/2026... SF/00001/2027.
- Las rectificativas van en serie propia (la del activo + R: SFR/00001/2026), como exige el reglamento de
  facturación (RD 1619/2012, art. 15).
- Las facturas no se modifican ni se borran. Cada una guarda la huella SHA-256 de la anterior de la misma
  sociedad: si alguien alterase una factura en la base de datos, la cadena dejaría de cuadrar.
"""
import hashlib
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Date, cast, select
from sqlalchemy.orm import Session

from .contratos import MESES
from .models import Charge, Company, Contact, Invoice, Lease, Service, Unit, User
from .utils import bad_request

IVA_GENERAL = Decimal("21")
IVA_ALOJAMIENTO = Decimal("10")  # alojamiento en apartamentos turísticos (art. 91.Uno.2.2º Ley 37/1992)
EXENCION_ARRENDAMIENTO = ("Operación exenta de IVA: arrendamiento de vivienda y, en su caso, de garajes y anexos "
                          "arrendados conjuntamente con ella (art. 20.Uno.23º Ley 37/1992)")
FORMAS_PAGO = {"efectivo": "Efectivo", "tarjeta": "Tarjeta", "transferencia": "Transferencia",
               "domiciliacion": "Domiciliación bancaria", "bizum": "Bizum", "plataforma": "Pago por plataforma"}


def dinero(x) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def iva_contrato(lease: Lease) -> Decimal:
    """IVA de un contrato de alquiler: el indicado en el contrato o, si no, vivienda exenta y resto al 21 %."""
    if lease.tipo_iva is not None:
        return Decimal(str(lease.tipo_iva))
    return Decimal(0) if lease.unit.uso == "vivienda" else IVA_GENERAL


def mes_es(periodo: str) -> str:
    y, m = periodo.split("-")
    return f"{MESES[int(m) - 1]} {y}"


def domicilio(*partes) -> str:
    return ", ".join(str(p).strip() for p in partes if p and str(p).strip())


def datos_emisor(c: Company) -> dict:
    falta = [n for n, v in (("CIF", c.cif), ("domicilio fiscal", c.direccion), ("código postal", c.cp),
                            ("municipio", c.municipio)) if not v]
    if falta:
        bad_request(f"No se puede facturar: falta {', '.join(falta)} de {c.nombre}. "
                    "Complételo en Administración → Sociedades.")
    return {"nombre": c.nombre, "nif": c.cif, "domicilio": domicilio(c.direccion, c.cp, c.municipio, c.provincia)}


def datos_cliente(contact: Contact | None, facturar_a=None) -> dict:
    """Destinatario: el cliente o, si se indica, la empresa a la que se factura (p.ej. la que aloja a su personal)."""
    if facturar_a:
        return {"nombre": facturar_a.nombre.strip(), "nif": facturar_a.nif.strip().upper(),
                "domicilio": facturar_a.domicilio.strip()}
    return {"nombre": f"{contact.nombre} {contact.apellidos or ''}".strip(), "nif": contact.documento_num,
            "domicilio": domicilio(contact.direccion, contact.cp, contact.municipio, contact.pais) or None}


def huella(emisor_nif: str, codigo: str, fecha: date, total: Decimal, cuota: Decimal, anterior: str | None) -> str:
    texto = "|".join([emisor_nif, codigo, fecha.isoformat(), f"{total:.2f}", f"{cuota:.2f}", anterior or ""])
    return hashlib.sha256(texto.encode()).hexdigest()


def _siguiente(db: Session, company: Company, serie: str, anio: int, fecha: date) -> tuple[int, str | None]:
    # Bloquea la fila de la sociedad: dos cobros simultáneos no pueden coger el mismo número ni romper la cadena
    db.execute(select(Company.id).where(Company.id == company.id).with_for_update())
    otra = db.scalar(select(Invoice.company_id).where(Invoice.serie == serie, Invoice.anio == anio,
                                                      Invoice.company_id != company.id).limit(1))
    if otra:
        bad_request(f"La serie {serie} de {anio} ya la usa otra sociedad. Asigne otra serie al activo.")
    ultima = db.execute(select(Invoice.numero, Invoice.fecha_expedicion).where(
        Invoice.serie == serie, Invoice.anio == anio).order_by(Invoice.numero.desc()).limit(1)).first()
    if ultima and ultima.fecha_expedicion > fecha:
        bad_request(f"La serie {serie} ya tiene facturas con fecha posterior al {fecha:%d/%m/%Y}")
    anterior = db.scalar(select(Invoice.huella).where(Invoice.company_id == company.id)
                         .order_by(Invoice.id.desc()).limit(1))
    return (ultima.numero if ultima else 0) + 1, anterior


TIPOS_LINEA = {"alojamiento": "Alojamiento", "garaje": "Plazas de garaje", "renta": "Rentas", "servicio": "Servicios"}


def linea(tipo: str, concepto: str, precio, tipo_iva, cantidad=1, servicio_id: int | None = None) -> dict:
    """Línea de factura. `precio` es unitario con IVA incluido (lo que paga el cliente)."""
    cantidad, iva = Decimal(str(cantidad)), Decimal(str(tipo_iva))
    total = dinero(cantidad * Decimal(str(precio)))
    base = dinero(total / (1 + iva / 100))
    return {"tipo": tipo, "concepto": concepto, "cantidad": float(cantidad), "precio": float(dinero(precio)),
            "tipo_iva": float(iva), "base": float(base), "cuota": float(total - base), "total": float(total),
            **({"servicio_id": servicio_id} if servicio_id else {})}


def lineas_de(f: Invoice) -> list[dict]:
    """Líneas de la factura (las antiguas, de una sola línea, se reconstruyen con sus totales)."""
    if f.lineas:
        return f.lineas
    tipo = "alojamiento" if f.reservation_id else "renta" if f.charge_id else "servicio"
    return [{"tipo": tipo, "concepto": f.concepto, "cantidad": 1.0, "precio": float(f.total),
             "tipo_iva": float(f.tipo_iva or 0), "base": float(f.base_imponible), "cuota": float(f.cuota_iva),
             "total": float(f.total)}]


def bases_por_tipo(db: Session, facturas: list[Invoice]) -> list[tuple[Invoice, dict[str, float]]]:
    """Base imponible de cada factura por tipo de línea, para la producción. El recibo mensual de una plaza de
    garaje se factura como renta, pero cuenta como garaje: las plazas no computan en la producción del edificio."""
    cargos = {f.charge_id for f in facturas if f.charge_id}
    de_garaje = set(db.scalars(select(Charge.id).join(Lease, Lease.id == Charge.lease_id)
                               .join(Unit, Unit.id == Lease.unit_id)
                               .where(Charge.id.in_(cargos or {-1}), Unit.uso == "garaje"))) if cargos else set()
    out = []
    for f in facturas:
        acc: dict[str, float] = {}
        for x in lineas_de(f):
            t = "garaje" if x["tipo"] == "renta" and f.charge_id in de_garaje else x["tipo"]
            acc[t] = acc.get(t, 0) + x["base"]
        out.append((f, acc))
    return out


def desglose(lineas: list[dict]) -> list[dict]:
    """Base y cuota por tipo de IVA (dato obligatorio de la factura)."""
    g: dict[float, list[Decimal]] = {}
    for x in lineas:
        acc = g.setdefault(x["tipo_iva"], [Decimal(0), Decimal(0)])
        acc[0] += dinero(x["base"])
        acc[1] += dinero(x["cuota"])
    return [{"tipo_iva": t, "base": float(b), "cuota": float(c)} for t, (b, c) in sorted(g.items())]


def fin_de_mes(d: date) -> date:
    """Último día del mes de `d`."""
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def emitir(db: Session, user: User | None, *, company: Company, serie: str, asset_id: int, cliente: dict,
           contact_id: int | None, lineas: list[dict] | None, fecha_operacion: date,
           forma_pago: str | None = None, charge_id: int | None = None, reservation_id: int | None = None,
           rectifica: Invoice | None = None, motivo: str | None = None, fecha: date | None = None,
           cobro: str = "cobrada") -> Invoice:
    emisor = datos_emisor(company)
    # Criterio de la gestoría: toda factura emitida lleva como fecha de expedición el último día del mes en que se
    # emite, sea cual sea el día (PDF, libro de facturas y exportaciones). El día real del cobro o del servicio
    # queda como fecha de la operación y el momento real de emisión en `creada`.
    fecha = fin_de_mes(fecha or date.today())
    if rectifica:  # anulación exacta de la original, línea a línea
        lineas = [{**x, "cantidad": -x["cantidad"], "base": -x["base"], "cuota": -x["cuota"], "total": -x["total"]}
                  for x in lineas_de(rectifica)]
    if not lineas:
        bad_request("La factura no tiene ninguna línea")
    numero, anterior = _siguiente(db, company, serie, fecha.year, fecha)
    codigo = f"{serie}/{numero:05d}/{fecha.year}"
    base = sum((dinero(x["base"]) for x in lineas), Decimal(0))
    cuota = sum((dinero(x["cuota"]) for x in lineas), Decimal(0))
    total = base + cuota
    tipos = {x["tipo_iva"] for x in lineas}
    concepto = "\n".join(x["concepto"] for x in lineas)
    if rectifica:
        concepto = f"Anulación de la factura {rectifica.codigo}. {rectifica.concepto}"
    f = Invoice(serie=serie, anio=fecha.year, numero=numero, codigo=codigo,
                tipo="rectificativa" if rectifica else "ordinaria", rectifica_id=rectifica.id if rectifica else None,
                motivo=motivo, company_id=company.id, asset_id=asset_id, emisor=emisor, contact_id=contact_id,
                cliente=cliente, fecha_expedicion=fecha, fecha_operacion=fecha_operacion, concepto=concepto,
                lineas=lineas, base_imponible=base, tipo_iva=next(iter(tipos)) if len(tipos) == 1 else None,
                cuota_iva=cuota, total=total, exencion=EXENCION_ARRENDAMIENTO if 0 in tipos else None,
                forma_pago=forma_pago, charge_id=charge_id, reservation_id=reservation_id,
                huella=huella(emisor["nif"], codigo, fecha, total, cuota, anterior), huella_anterior=anterior,
                user_id=user.id if user else None, cobro=cobro)
    db.add(f)
    db.flush()
    return f


ESTANCIA = ("alojamiento", "garaje")  # líneas que cuentan en lo cobrado de la reserva (los servicios van aparte)


def importe_estancia(f: Invoice) -> Decimal:
    return sum((dinero(x["total"]) for x in lineas_de(f) if x["tipo"] in ESTANCIA), Decimal(0))


def estancia_facturada(db: Session, reservation_id: int) -> Decimal:
    """Lo facturado de la estancia de una reserva (las rectificativas restan): no se puede facturar dos veces."""
    return sum((importe_estancia(f) for f in db.scalars(select(Invoice).where(
        Invoice.reservation_id == reservation_id))), Decimal(0))


def pendientes_cobro(db: Session, asset_ids: set[int] | None, dia: date | None = None) -> list[dict]:
    """Facturas emitidas sin cobrar, con los días que llevan pendientes. Con `dia` en el pasado, las que estaban
    pendientes ese día (las cobradas después también cuentan)."""
    from .models import Asset, Reservation
    hoy = date.today()
    dia = dia or hoy
    emitida = cast(Invoice.creada, Date)  # día real de emisión (la fecha de la factura es el fin de mes)
    stmt = select(Invoice).where(Invoice.tipo == "ordinaria", emitida <= dia)
    if dia >= hoy:
        stmt = stmt.where(Invoice.cobro == "pendiente")
    else:
        stmt = stmt.where((Invoice.cobro == "pendiente") | ((Invoice.cobro == "cobrada") & (Invoice.cobro_fecha > dia)))
    if asset_ids is not None:
        stmt = stmt.where(Invoice.asset_id.in_(asset_ids or {-1}))
    filas = list(db.scalars(stmt.order_by(Invoice.fecha_expedicion, Invoice.id)))
    nombres = dict(db.execute(select(Asset.id, Asset.nombre)).all())
    reservas = {r.id: r for r in db.scalars(select(Reservation).where(
        Reservation.id.in_({f.reservation_id for f in filas if f.reservation_id} or {-1})))}
    contactos = {c.id: c for c in db.scalars(select(Contact).where(
        Contact.id.in_({f.contact_id for f in filas if f.contact_id} or {-1})))}
    out = []
    for f in filas:
        r, c = reservas.get(f.reservation_id), contactos.get(f.contact_id)
        out.append({"id": f.id, "codigo": f.codigo, "fecha": f.fecha_expedicion.isoformat(), "asset_id": f.asset_id,
                    "activo": nombres.get(f.asset_id), "cliente": f.cliente.get("nombre"),
                    "nif": f.cliente.get("nif"), "telefono": c.telefono if c else None,
                    "email": c.email if c else None, "unidad": r.unit.codigo if r else None,
                    "localizador": (r.localizador or f"R-{r.id}") if r else None,
                    "estancia": f"{r.fecha_entrada:%d/%m/%Y} - {r.fecha_salida:%d/%m/%Y}" if r else None,
                    "concepto": f.concepto, "total": float(f.total), "forma_pago": f.forma_pago,
                    "emitida": f.creada.date().isoformat(), "dias": (dia - f.creada.date()).days})
    return out


def lineas_servicios(db: Session, asset_id: int, servicios) -> list[dict]:
    """Líneas de servicios pedidas en un cobro o factura (del catálogo o escritas a mano)."""
    out = []
    for s in servicios or []:
        cat = db.get(Service, s.servicio_id) if s.servicio_id else None
        if s.servicio_id and (not cat or not cat.activo or cat.asset_id not in (None, asset_id)):
            bad_request("Servicio no disponible para este activo")
        concepto = (s.concepto or (f"{cat.nombre} ({cat.unidad})" if cat and cat.unidad != "ud" else
                                   cat.nombre if cat else "")).strip()
        precio = s.precio if s.precio is not None else (float(cat.precio) if cat and cat.precio is not None else None)
        if not concepto:
            bad_request("Indique el concepto del servicio")
        if precio is None:
            bad_request(f"Indique el precio de «{concepto}»")
        iva = s.tipo_iva if s.tipo_iva is not None else (float(cat.tipo_iva) if cat else float(IVA_GENERAL))
        out.append(linea("servicio", concepto, precio, iva, s.cantidad, cat.id if cat else None))
    return out


def serie_activo(asset) -> str:
    if not asset.serie_factura:
        bad_request(f"El activo {asset.nombre} no tiene serie de facturación (ficha del activo)")
    return asset.serie_factura


def factura_out(f: Invoice, rectificada_por: str | None = None) -> dict:
    d = f.to_dict()
    d["lineas"] = lineas_de(f)
    d["desglose"] = desglose(d["lineas"])
    d["activo"] = f.asset.nombre
    d["forma_pago_nombre"] = FORMAS_PAGO.get(f.forma_pago or "", f.forma_pago)
    d["rectificada_por"] = rectificada_por
    return d
