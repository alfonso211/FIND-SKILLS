"""Facturación: numeración correlativa por serie y año, IVA y huella encadenada.

- Cada activo tiene su serie (B35, SF, SA...) y factura su sociedad gestora. El número se reinicia cada año:
  SF/00001/2026, SF/00002/2026... SF/00001/2027.
- Las rectificativas van en serie propia (la del activo + R: SFR/00001/2026), como exige el reglamento de
  facturación (RD 1619/2012, art. 15).
- Las facturas no se modifican ni se borran. Cada una guarda la huella SHA-256 de la anterior de la misma
  sociedad: si alguien alterase una factura en la base de datos, la cadena dejaría de cuadrar.
"""
import hashlib
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .contratos import MESES
from .models import Company, Contact, Invoice, Lease, User
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


def emitir(db: Session, user: User | None, *, company: Company, serie: str, asset_id: int, cliente: dict,
           contact_id: int | None, concepto: str, total, tipo_iva, fecha_operacion: date,
           forma_pago: str | None = None, charge_id: int | None = None, reservation_id: int | None = None,
           rectifica: Invoice | None = None, motivo: str | None = None, fecha: date | None = None) -> Invoice:
    emisor = datos_emisor(company)
    fecha = fecha or date.today()
    numero, anterior = _siguiente(db, company, serie, fecha.year, fecha)
    codigo = f"{serie}/{numero:05d}/{fecha.year}"
    tipo_iva = Decimal(str(tipo_iva))
    if rectifica:  # anulación exacta de la original
        base, cuota, total = (-dinero(rectifica.base_imponible), -dinero(rectifica.cuota_iva),
                              -dinero(rectifica.total))
    else:
        total = dinero(total)
        base = dinero(total / (1 + tipo_iva / 100))
        cuota = total - base
    f = Invoice(serie=serie, anio=fecha.year, numero=numero, codigo=codigo,
                tipo="rectificativa" if rectifica else "ordinaria", rectifica_id=rectifica.id if rectifica else None,
                motivo=motivo, company_id=company.id, asset_id=asset_id, emisor=emisor, contact_id=contact_id,
                cliente=cliente, fecha_expedicion=fecha, fecha_operacion=fecha_operacion, concepto=concepto,
                base_imponible=base, tipo_iva=tipo_iva, cuota_iva=cuota, total=total,
                exencion=EXENCION_ARRENDAMIENTO if tipo_iva == 0 else None, forma_pago=forma_pago,
                charge_id=charge_id, reservation_id=reservation_id,
                huella=huella(emisor["nif"], codigo, fecha, total, cuota, anterior), huella_anterior=anterior,
                user_id=user.id if user else None)
    db.add(f)
    db.flush()
    return f


def serie_activo(asset) -> str:
    if not asset.serie_factura:
        bad_request(f"El activo {asset.nombre} no tiene serie de facturación (ficha del activo)")
    return asset.serie_factura


def factura_out(f: Invoice, rectificada_por: str | None = None) -> dict:
    d = f.to_dict()
    d["activo"] = f.asset.nombre
    d["forma_pago_nombre"] = FORMAS_PAGO.get(f.forma_pago or "", f.forma_pago)
    d["rectificada_por"] = rectificada_por
    return d
