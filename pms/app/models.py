"""Modelo de datos de INVERPMS (Grupo INVERSIETE).

Jerarquía:  Sociedad -> Activo -> Unidad
Cada activo tiene una *modalidad* de explotación (alquiler residencial,
apartamentos turísticos, ...). Nuevas modalidades se añaden en MODALIDADES.
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base

MODALIDADES = {
    "alquiler_residencial": "Alquiler residencial (LAU)",
    "apartamentos_turisticos": "Apartamentos turísticos",
}

# Qué módulos operativos aplican a cada modalidad (amplíable: oficinas, locales, parking, hotel...)
MODALIDADES_CONTRATO = {"alquiler_residencial"}
MODALIDADES_RESERVA = {"apartamentos_turisticos"}

USOS_UNIDAD = ["vivienda", "apartamento", "garaje", "trastero", "local", "oficina"]

ESTADOS_UNIDAD = ["disponible", "ocupada", "pendiente_limpieza", "mantenimiento", "bloqueada", "fuera_servicio"]
# Situación de las viviendas en alquiler residencial (Babilonia 35): se pide la primera vez que se abre la vivienda
SITUACIONES = {
    "alquilada": "Alquilada",
    "vacia": "Vacía (disponible para alquilar)",
    "reservada": "Reservada (pendiente de firmar)",
    "reforma_menor": "En reforma menor",
    "obra_mayor": "En obra mayor",
    "ocupada_sin_titulo": "Ocupada sin título",
    "en_venta": "En venta",
    "uso_propio": "Uso propio / cedida",
    "otra": "Otra situación",
}


def _now() -> datetime:
    return datetime.now()


# --------------------------------------------------------------------------- estructura
class Company(Base):
    __tablename__ = "sociedades"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200), unique=True)
    cif: Mapped[str | None] = mapped_column(String(20))
    # domicilio fiscal (obligatorio en las facturas que emite la sociedad)
    direccion: Mapped[str | None] = mapped_column(String(300))
    cp: Mapped[str | None] = mapped_column(String(10))
    municipio: Mapped[str | None] = mapped_column(String(100))
    provincia: Mapped[str | None] = mapped_column(String(100))
    pais: Mapped[str | None] = mapped_column(String(60))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sociedades.id"))
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    # Datos para los contratos de arrendamiento: Registro Mercantil (tomo, folio, hoja), representante y poder,
    # IBAN para la renta, correos de notificaciones y de protección de datos, teléfono de averías
    contratos: Mapped[dict | None] = mapped_column(JSON)


class Asset(Base):
    """company_id = sociedad GESTORA (explota el activo; determina accesos y a quién pertenecen
    inquilinos/huéspedes). propietaria_id = sociedad PROPIETARIA del inmueble (puede ser otra)."""
    __tablename__ = "activos"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("sociedades.id"), index=True)
    propietaria_id: Mapped[int | None] = mapped_column(ForeignKey("sociedades.id"))
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    nombre: Mapped[str] = mapped_column(String(200))
    modalidad: Mapped[str] = mapped_column(String(40))
    direccion: Mapped[str | None] = mapped_column(String(300))
    municipio: Mapped[str | None] = mapped_column(String(100))
    provincia: Mapped[str | None] = mapped_column(String(100))
    cp: Mapped[str | None] = mapped_column(String(10))
    pais: Mapped[str | None] = mapped_column(String(60))
    # informe mensual a la presidencia: quién lo revisa y envía (por defecto, «Recepción 1» del activo) y a dónde
    informe_responsable_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    informe_emails: Mapped[str | None] = mapped_column(String(500))
    informe_whatsapp: Mapped[str | None] = mapped_column(String(30))
    ref_catastral: Mapped[str | None] = mapped_column(String(30))
    num_registro_turistico: Mapped[str | None] = mapped_column(String(60))
    # Serie de sus facturas (B35, SF, SA...). Factura la sociedad gestora.
    serie_factura: Mapped[str | None] = mapped_column(String(10))
    # Datos de la empresa para los contratos de alojamiento
    contrato_representante: Mapped[str | None] = mapped_column(String(160))
    contrato_representante_dni: Mapped[str | None] = mapped_column(String(20))
    contrato_email: Mapped[str | None] = mapped_column(String(160))
    # SES.HOSPEDAJE: código del establecimiento que asigna el Ministerio del Interior al darlo de alta
    ses_codigo_establecimiento: Mapped[str | None] = mapped_column(String(20))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    notas: Mapped[str | None] = mapped_column(Text)
    company: Mapped[Company] = relationship(foreign_keys=[company_id])
    propietaria: Mapped[Company | None] = relationship(foreign_keys=[propietaria_id])


class Unit(Base):
    __tablename__ = "unidades"
    __table_args__ = (UniqueConstraint("asset_id", "codigo"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(30))
    bloque: Mapped[str | None] = mapped_column(String(40))  # portal / bloque / escalera
    uso: Mapped[str] = mapped_column(String(20), default="vivienda")
    tipologia: Mapped[str | None] = mapped_column(String(60))
    planta: Mapped[str | None] = mapped_column(String(10))
    superficie_m2: Mapped[float | None] = mapped_column(Numeric(8, 2))
    dormitorios: Mapped[int | None] = mapped_column(Integer)
    capacidad: Mapped[int | None] = mapped_column(Integer)
    ref_catastral: Mapped[str | None] = mapped_column(String(30))
    estado: Mapped[str] = mapped_column(String(30), default="disponible")
    renta_base: Mapped[float | None] = mapped_column(Numeric(10, 2))
    tarifa_base_noche: Mapped[float | None] = mapped_column(Numeric(10, 2))
    coef_participacion: Mapped[float | None] = mapped_column(Numeric(6, 3))  # % en la comunidad
    cuota_comunidad: Mapped[float | None] = mapped_column(Numeric(10, 2))  # cuota ordinaria mensual
    anejos: Mapped[str | None] = mapped_column(String(120))  # trasteros / plazas vinculadas
    notas: Mapped[str | None] = mapped_column(Text)
    # Vivienda en alquiler (LAU): puerta, C.P., superficie útil, distribución, Registro de la Propiedad, certificado
    # energético, IBI y tasa de residuos, contadores (CUPS) y llaves; inventario del mobiliario que se entrega
    ficha: Mapped[dict | None] = mapped_column(JSON)
    inventario: Mapped[list | None] = mapped_column(JSON)
    # Situación de la vivienda (ver SITUACIONES): quién y cuándo la indicó; «otra» lleva su descripción.
    situacion: Mapped[str | None] = mapped_column(String(30))
    situacion_texto: Mapped[str | None] = mapped_column(String(200))
    situacion_fecha: Mapped[datetime | None] = mapped_column(DateTime)
    situacion_user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    # «Completar más tarde» el contrato: no se vuelve a pedir ese día
    contrato_pospuesto: Mapped[date | None] = mapped_column(Date)
    asset: Mapped[Asset] = relationship()


# --------------------------------------------------------------------------- terceros
class Contact(Base):
    """Inquilino, huésped o cliente de garaje. Datos compatibles con parte de viajeros (RD 933/2021)."""
    __tablename__ = "terceros"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("sociedades.id"), index=True)
    # activo al que pertenece la ficha: cada recepción ve solo los clientes de su activo (ver app/clientes.py)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("activos.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # inquilino | huesped | cliente_garaje
    nombre: Mapped[str] = mapped_column(String(120))
    apellidos: Mapped[str | None] = mapped_column(String(160))
    documento_tipo: Mapped[str | None] = mapped_column(String(10))  # DNI | NIE | PAS | CIF
    documento_num: Mapped[str | None] = mapped_column(String(30))
    nacionalidad: Mapped[str | None] = mapped_column(String(60))
    fecha_nacimiento: Mapped[date | None] = mapped_column(Date)
    sexo: Mapped[str | None] = mapped_column(String(1))  # M | F
    num_soporte: Mapped[str | None] = mapped_column(String(20))  # nº de soporte del DNI/NIE (parte de viajeros)
    fecha_caducidad_doc: Mapped[date | None] = mapped_column(Date)
    email: Mapped[str | None] = mapped_column(String(160))
    telefono: Mapped[str | None] = mapped_column(String(40))
    direccion: Mapped[str | None] = mapped_column(String(300))
    cp: Mapped[str | None] = mapped_column(String(10))
    municipio: Mapped[str | None] = mapped_column(String(100))
    provincia: Mapped[str | None] = mapped_column(String(100))
    pais: Mapped[str | None] = mapped_column(String(60))
    municipio_ine: Mapped[str | None] = mapped_column(String(5))  # código INE del municipio (residentes en España)
    iban: Mapped[str | None] = mapped_column(String(40))
    notas: Mapped[str | None] = mapped_column(Text)


TIPOS_PERSONA = {"empresa": "Empresa (CIF)", "autonomo": "Autónomo (DNI/NIE)", "particular": "Persona física (DNI/NIE)"}


class Supplier(Base):
    """Proveedor del grupo: no depende de ninguna sociedad y lo usan todas (OT, preventivo, personal)."""
    __tablename__ = "proveedores"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200))  # razón social o nombre y apellidos
    tipo_persona: Mapped[str] = mapped_column(String(20), default="empresa")  # empresa | autonomo | particular
    nif: Mapped[str | None] = mapped_column(String(20), unique=True)  # CIF, DNI o NIE
    direccion: Mapped[str | None] = mapped_column(String(300))
    cp: Mapped[str | None] = mapped_column(String(10))
    municipio: Mapped[str | None] = mapped_column(String(100))
    provincia: Mapped[str | None] = mapped_column(String(60))
    pais: Mapped[str | None] = mapped_column(String(60))
    email: Mapped[str | None] = mapped_column(String(160))
    telefono: Mapped[str | None] = mapped_column(String(40))
    persona_contacto: Mapped[str | None] = mapped_column(String(160))
    actividad: Mapped[str | None] = mapped_column(String(160))  # gremio: fontanería, PCI, ascensores...
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    notas: Mapped[str | None] = mapped_column(Text)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)


# --------------------------------------------------------------------------- alquiler residencial
class Lease(Base):
    __tablename__ = "contratos"
    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("terceros.id"))
    referencia: Mapped[str | None] = mapped_column(String(40))
    fecha_inicio: Mapped[date] = mapped_column(Date)
    fecha_fin: Mapped[date | None] = mapped_column(Date)
    renta_mensual: Mapped[float] = mapped_column(Numeric(10, 2))
    fianza: Mapped[float | None] = mapped_column(Numeric(10, 2))
    garantia_adicional: Mapped[float | None] = mapped_column(Numeric(10, 2))
    dia_pago: Mapped[int] = mapped_column(Integer, default=5)
    indice_actualizacion: Mapped[str] = mapped_column(String(20), default="IRAV")  # IRAV | IPC | NINGUNO
    estado: Mapped[str] = mapped_column(String(20), default="vigente")  # borrador | vigente | finalizado | rescindido
    # % de IVA. Vacío = según el uso de la unidad (vivienda exenta, resto 21 %)
    tipo_iva: Mapped[float | None] = mapped_column(Numeric(5, 2))
    notas: Mapped[str | None] = mapped_column(Text)
    # Alquiler de plazas de garaje: vehículo autorizado y mandos o tarjetas de acceso entregados
    matricula: Mapped[str | None] = mapped_column(String(20))
    vehiculo: Mapped[str | None] = mapped_column(String(80))
    mandos: Mapped[str | None] = mapped_column(String(80))
    # Expediente del contrato de vivienda: datos del contrato, checklist, inventario entregado, entregas de dinero
    # y citas de la agenda generadas
    expediente: Mapped[dict | None] = mapped_column(JSON)
    unit: Mapped[Unit] = relationship()
    tenant: Mapped[Contact] = relationship()


class Charge(Base):
    __tablename__ = "recibos"
    __table_args__ = (UniqueConstraint("lease_id", "periodo", "concepto"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("contratos.id"), index=True)
    periodo: Mapped[str] = mapped_column(String(7))  # AAAA-MM
    concepto: Mapped[str] = mapped_column(String(60), default="Renta")
    importe: Mapped[float] = mapped_column(Numeric(10, 2))  # IVA incluido
    tipo_iva: Mapped[float | None] = mapped_column(Numeric(5, 2))
    fecha_vencimiento: Mapped[date] = mapped_column(Date)
    importe_pagado: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    fecha_pago: Mapped[date | None] = mapped_column(Date)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")  # pendiente | parcial | pagado | anulado
    lease: Mapped[Lease] = relationship()


# --------------------------------------------------------------------------- turístico
class Reservation(Base):
    __tablename__ = "reservas"
    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("terceros.id"))
    localizador: Mapped[str | None] = mapped_column(String(60))
    canal: Mapped[str] = mapped_column(String(30), default="directo")
    fecha_entrada: Mapped[date] = mapped_column(Date, index=True)
    fecha_salida: Mapped[date] = mapped_column(Date, index=True)
    adultos: Mapped[int] = mapped_column(Integer, default=1)
    ninos: Mapped[int] = mapped_column(Integer, default=0)
    importe_total: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    importe_pagado: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    estado: Mapped[str] = mapped_column(String(20), default="confirmada")  # confirmada | checkin | checkout | cancelada | no_show
    notas: Mapped[str | None] = mapped_column(Text)
    # Datos del contrato de alojamiento tecleados en la reserva (se imprimen cuando llega el cliente)
    datos_contrato: Mapped[dict | None] = mapped_column(JSON)
    creada: Mapped[datetime] = mapped_column(DateTime, default=_now)
    ses_comunicado: Mapped[datetime | None] = mapped_column(DateTime)  # parte de viajeros generado para SES
    renueva_id: Mapped[int | None] = mapped_column(ForeignKey("reservas.id"))  # renovación de esta reserva
    # Servicios extra que pide el cliente (limpieza, plaza extra…): [{concepto, servicio_id, cantidad, precio,
    # tipo_iva, limpieza, factura}]. Se añaden a la factura de la estancia; «factura» = código ya facturado.
    extras: Mapped[list | None] = mapped_column(JSON)
    # Limpieza contratada: {inicio, periodicidad, cada, texto, fechas}. Ver app/limpiezas.py
    limpieza: Mapped[dict | None] = mapped_column(JSON)
    unit: Mapped[Unit] = relationship()
    guest: Mapped[Contact] = relationship()
    ocupantes: Mapped[list["ReservationGuest"]] = relationship(order_by="ReservationGuest.orden",
                                                               cascade="all, delete-orphan")


class ReservationGuest(Base):
    """Ocupante de una reserva (todos, incluidos los menores) para el contrato y el parte de viajeros."""
    __tablename__ = "reserva_ocupantes"
    __table_args__ = (UniqueConstraint("reservation_id", "contact_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("terceros.id"))
    titular: Mapped[bool] = mapped_column(Boolean, default=False)
    parentesco: Mapped[str | None] = mapped_column(String(2))  # código SES (menores de edad)
    orden: Mapped[int] = mapped_column(Integer, default=0)
    contact: Mapped[Contact] = relationship()


class UnitBlock(Base):
    """Bloqueo de un apartamento (lo saca de venta) con su motivo. Al desbloquear se cierra el registro."""
    __tablename__ = "bloqueos_unidad"
    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    motivo: Mapped[str] = mapped_column(Text)
    hasta: Mapped[date | None] = mapped_column(Date)  # fin previsto (orientativo)
    desde: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    levantado: Mapped[datetime | None] = mapped_column(DateTime)
    levantado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    nota_levantado: Mapped[str | None] = mapped_column(String(300))


class ContactDocument(Base):
    """Copia escaneada de un documento de identidad. El fichero se guarda cifrado fuera de la base de datos."""
    __tablename__ = "documentos_terceros"
    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL mientras el cliente no existe (escaneado al empezar una reserva o un alta); se adjunta al crearlo
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("terceros.id"), index=True)
    tipo: Mapped[str | None] = mapped_column(String(10))  # DNI | NIE | PAS | OTRO
    cara: Mapped[str] = mapped_column(String(10))  # anverso | reverso
    fichero: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(60))
    tamano: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    lectura: Mapped[dict | None] = mapped_column(JSON)
    subido: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class AccommodationContract(Base):
    """Contrato de alojamiento generado para una reserva (MOD-ALOJ-001). Se guardan los datos con los que se
    imprimió para poder reimprimirlo idéntico. De la tarjeta solo se guardan titular, últimos 4 dígitos y caducidad."""
    __tablename__ = "contratos_alojamiento"
    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"), index=True)
    plantilla: Mapped[str] = mapped_column(String(80))
    datos: Mapped[dict] = mapped_column(JSON)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    # Firma digital en tablet: PDF firmado (cifrado), su huella y las evidencias de la firma
    firmado: Mapped[datetime | None] = mapped_column(DateTime)
    fichero: Mapped[str | None] = mapped_column(String(80))
    sha256: Mapped[str | None] = mapped_column(String(64))
    evidencias: Mapped[dict | None] = mapped_column(JSON)
    token_hash: Mapped[str | None] = mapped_column(String(64), index=True)  # enlace de descarga para el cliente
    token_expira: Mapped[datetime | None] = mapped_column(DateTime)
    envios: Mapped[list | None] = mapped_column(JSON)  # [{canal, destino, fecha, usuario}]


# --------------------------------------------------------------------------- facturación
class Service(Base):
    """Servicio que se puede facturar (limpieza, plaza de aparcamiento...). Sin activo = para todos."""
    __tablename__ = "servicios"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("activos.id"))
    nombre: Mapped[str] = mapped_column(String(120))
    precio: Mapped[float | None] = mapped_column(Numeric(10, 2))  # IVA incluido; vacío = se indica al facturar
    tipo_iva: Mapped[float] = mapped_column(Numeric(5, 2), default=21)
    unidad: Mapped[str] = mapped_column(String(20), default="ud")  # ud | día | noche | mes | hora
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class Invoice(Base):
    """Factura emitida al registrar un cobro. Numeración correlativa por serie y año (SF/00001/2026).
    No se modifica ni se borra: los errores se corrigen con una factura rectificativa (serie propia, p.ej. SFR).
    Los datos del emisor y del cliente se copian al emitir, para que la factura no cambie si cambia la ficha.
    Cada factura lleva la huella SHA-256 de la anterior de la misma sociedad (cadena antimanipulación)."""
    __tablename__ = "facturas"
    __table_args__ = (UniqueConstraint("serie", "anio", "numero"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    serie: Mapped[str] = mapped_column(String(12))
    anio: Mapped[int] = mapped_column(Integer)
    numero: Mapped[int] = mapped_column(Integer)
    codigo: Mapped[str] = mapped_column(String(30), unique=True)
    tipo: Mapped[str] = mapped_column(String(20), default="ordinaria")  # ordinaria | rectificativa
    rectifica_id: Mapped[int | None] = mapped_column(ForeignKey("facturas.id"))
    motivo: Mapped[str | None] = mapped_column(Text)
    company_id: Mapped[int] = mapped_column(ForeignKey("sociedades.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    emisor: Mapped[dict] = mapped_column(JSON)  # nombre, nif, domicilio
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("terceros.id"))
    cliente: Mapped[dict] = mapped_column(JSON)  # nombre, nif, domicilio
    fecha_expedicion: Mapped[date] = mapped_column(Date, index=True)
    fecha_operacion: Mapped[date] = mapped_column(Date)
    concepto: Mapped[str] = mapped_column(Text)
    # líneas: [{tipo: alojamiento|renta|servicio, concepto, cantidad, precio, tipo_iva, base, cuota, total}]
    # (vacío en las facturas de una sola línea emitidas antes de existir las líneas)
    lineas: Mapped[list | None] = mapped_column(JSON)
    base_imponible: Mapped[float] = mapped_column(Numeric(12, 2))
    tipo_iva: Mapped[float | None] = mapped_column(Numeric(5, 2))  # vacío si hay líneas con distinto IVA
    cuota_iva: Mapped[float] = mapped_column(Numeric(12, 2))
    total: Mapped[float] = mapped_column(Numeric(12, 2))
    exencion: Mapped[str | None] = mapped_column(String(200))
    forma_pago: Mapped[str | None] = mapped_column(String(30))
    charge_id: Mapped[int | None] = mapped_column(ForeignKey("recibos.id"))
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("reservas.id"))
    huella: Mapped[str] = mapped_column(String(64))
    huella_anterior: Mapped[str | None] = mapped_column(String(64))
    # Cobro de la factura. «cobrada»: se emitió al cobrar (lo normal). «pendiente»: emitida sin cobrar (renovación o
    # reserva que pagará por transferencia); recepción la revisa a diario y la marca cobrada al recibir el dinero.
    # «anulada»: pendiente que se rectificó sin llegar a cobrarse.
    cobro: Mapped[str] = mapped_column(String(12), default="cobrada", server_default="cobrada", index=True)
    cobro_fecha: Mapped[date | None] = mapped_column(Date)
    cobro_forma: Mapped[str | None] = mapped_column(String(30))
    cobro_ref: Mapped[str | None] = mapped_column(String(80))
    cobro_user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    cobro_marcado: Mapped[datetime | None] = mapped_column(DateTime)
    creada: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    asset: Mapped[Asset] = relationship()


# --------------------------------------------------------------------------- mantenimiento
class WorkOrder(Base):
    __tablename__ = "ordenes_trabajo"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("planes_preventivos.id"))
    # zona común del plano (p.ej. P4-A-PISCINA) cuando la incidencia no es de un apartamento
    zona: Mapped[str | None] = mapped_column(String(40), index=True)
    tipo: Mapped[str] = mapped_column(String(20), default="correctivo")  # correctivo | preventivo | mejora | normativo
    categoria: Mapped[str] = mapped_column(String(40), default="general")
    prioridad: Mapped[str] = mapped_column(String(20), default="media")  # baja | media | alta | urgente
    estado: Mapped[str] = mapped_column(String(30), default="abierta")
    titulo: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str | None] = mapped_column(Text)
    asignado_a: Mapped[str | None] = mapped_column(String(120))
    proveedor: Mapped[str | None] = mapped_column(String(160))
    coste_estimado: Mapped[float | None] = mapped_column(Numeric(10, 2))
    coste_real: Mapped[float | None] = mapped_column(Numeric(10, 2))
    bloquea_unidad: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_apertura: Mapped[date] = mapped_column(Date, default=date.today)
    fecha_prevista: Mapped[date | None] = mapped_column(Date)
    fecha_cierre: Mapped[date | None] = mapped_column(Date)
    solucion: Mapped[str | None] = mapped_column(Text)
    # Flujo: abre (recepción/limpieza/mantenimiento) -> mantenimiento confirma trabajo -> limpieza confirma
    # la unidad -> recepción cierra.
    abierta_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    conf_mto_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    conf_mto_fecha: Mapped[datetime | None] = mapped_column(DateTime)
    conf_limpieza_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    conf_limpieza_fecha: Mapped[datetime | None] = mapped_column(DateTime)
    cerrada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    # envíos de la orden al personal de mantenimiento: [{fecha, canal, destino, nombre, usuario}]
    envios: Mapped[list | None] = mapped_column(JSON)


AREAS_PERSONAL = {"mantenimiento": "Mantenimiento", "limpieza": "Limpieza"}


class StaffMember(Base):
    """Personal de mantenimiento o limpieza (propio o de una subcontrata) al que se envían las órdenes de trabajo
    y el parte de limpieza por correo o WhatsApp. No necesita usuario en el PMS. Sin activo = todos."""
    __tablename__ = "personal_servicio"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("activos.id"), index=True)
    area: Mapped[str] = mapped_column(String(20))  # mantenimiento | limpieza
    nombre: Mapped[str] = mapped_column(String(160))
    empresa: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(160))
    telefono: Mapped[str | None] = mapped_column(String(40))
    # mantenimiento: recibe por correo, al momento, las OT urgentes de su activo
    avisar_urgentes: Mapped[bool] = mapped_column(Boolean, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    notas: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- documentos recibidos y gastos
TIPOS_DOCUMENTO = {
    "factura": "Factura", "ticket": "Ticket / recibo", "albaran": "Albarán", "presupuesto": "Presupuesto",
    "carta": "Carta", "notificacion": "Notificación / requerimiento", "contrato": "Contrato",
    "seguro": "Póliza / seguro", "informe": "Informe mensual (presidencia)", "limpieza": "Parte de limpieza",
    "otro": "Otro",
}
TIPOS_GASTO = ("factura", "ticket", "albaran")  # tipos que normalmente son un gasto
CATEGORIAS_GASTO = {
    "suministros": "Suministros (luz, agua, gas)", "telecom": "Telefonía e internet",
    "mantenimiento": "Mantenimiento y reparaciones", "limpieza": "Limpieza y lavandería",
    "material": "Material, menaje y mobiliario", "amenities": "Amenities y consumibles",
    "comunidad": "Comunidad de propietarios", "impuestos": "Impuestos y tasas", "seguros": "Seguros",
    "profesionales": "Servicios profesionales (gestoría, abogados…)", "comisiones": "Comisiones (OTA, bancos)",
    "publicidad": "Publicidad y marketing", "personal": "Personal externo", "otros": "Otros",
}
AMBITOS_GASTO = {"general": "General del activo", "apartamento": "Apartamento concreto", "otro": "Otro"}


class ReceivedDocument(Base):
    """Documento recibido y escaneado (factura, ticket, carta…), guardado cifrado en la carpeta de su activo.
    Cada activo ve solo los suyos; quien gestiona la sociedad o el grupo, todos."""
    __tablename__ = "documentos_recibidos"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"))
    tipo: Mapped[str] = mapped_column(String(20))
    fecha: Mapped[date] = mapped_column(Date, index=True)  # fecha del documento (la que figura en la factura)
    vencimiento: Mapped[date | None] = mapped_column(Date)  # vencimiento de la factura recibida
    emisor: Mapped[str | None] = mapped_column(String(200))
    referencia: Mapped[str | None] = mapped_column(String(60))  # nº de factura, expediente…
    descripcion: Mapped[str | None] = mapped_column(Text)
    nombre: Mapped[str] = mapped_column(String(200))
    fichero: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(100))
    tamano: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    subido: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class Expense(Base):
    """Apunte de la cuenta de gastos del activo, normalmente con su documento (factura o ticket) escaneado."""
    __tablename__ = "gastos"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documentos_recibidos.id"), index=True)
    ambito: Mapped[str] = mapped_column(String(20), default="general")  # general | apartamento | otro
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"))
    ambito_detalle: Mapped[str | None] = mapped_column(String(200))  # «otro»: zona, varios apartamentos…
    fecha: Mapped[date] = mapped_column(Date, index=True)
    categoria: Mapped[str] = mapped_column(String(30))
    concepto: Mapped[str] = mapped_column(String(300))
    proveedor: Mapped[str | None] = mapped_column(String(200))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))
    numero_factura: Mapped[str | None] = mapped_column(String(60))
    vencimiento: Mapped[date | None] = mapped_column(Date)  # vencimiento de la factura del proveedor
    base: Mapped[float] = mapped_column(Numeric(12, 2))
    tipo_iva: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    cuota: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2))
    forma_pago: Mapped[str | None] = mapped_column(String(30))
    pagado: Mapped[bool] = mapped_column(Boolean, default=False)
    fecha_pago: Mapped[date | None] = mapped_column(Date)
    notas: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    # retención practicada al proveedor (IRPF de profesionales, arrendamientos…): se descuenta del pago.
    # total = base + cuota (IVA incluido); lo que se paga es total − retencion
    naturaleza: Mapped[str | None] = mapped_column(String(10))  # OPEX (gasto corriente) o CAPEX (inversión)
    retencion_tipo: Mapped[str | None] = mapped_column(String(30))
    retencion_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)
    retencion: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    # pago retenido: la factura no se paga de momento (aviso a quien paga hasta la fecha de revisión)
    pago_retenido: Mapped[bool] = mapped_column(Boolean, default=False)
    pago_retenido_motivo: Mapped[str | None] = mapped_column(String(300))
    pago_retenido_revision: Mapped[date | None] = mapped_column(Date)
    pago_retenido_user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    pago_retenido_fecha: Mapped[datetime | None] = mapped_column(DateTime)


class WorkOrderAttachment(Base):
    """Foto o documento de una orden de trabajo (avería, trabajo terminado, certificado OCA, factura...).
    El fichero se guarda cifrado fuera de la base de datos, como las copias de documentos de identidad."""
    __tablename__ = "adjuntos_ot"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("ordenes_trabajo.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # averia | trabajo | oca | factura | presupuesto | otro
    nombre: Mapped[str] = mapped_column(String(160))
    descripcion: Mapped[str | None] = mapped_column(String(300))
    fichero: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(60))
    tamano: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    subido: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class PreventivePlan(Base):
    __tablename__ = "planes_preventivos"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    categoria: Mapped[str] = mapped_column(String(40))
    normativa: Mapped[str | None] = mapped_column(String(200))
    periodicidad_dias: Mapped[int] = mapped_column(Integer)
    proxima_fecha: Mapped[date] = mapped_column(Date)
    proveedor: Mapped[str | None] = mapped_column(String(160))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


# --------------------------------------------------------------------------- seguridad
class User(Base):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(160), unique=True)
    nombre: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    # contraseña provisional: hasta cambiarla solo puede consultar su perfil y cambiar la contraseña
    debe_cambiar_password: Mapped[bool] = mapped_column(Boolean, default=False)
    # avisos por correo que quiere recibir (None = todos los que le permiten sus permisos)
    avisos: Mapped[list | None] = mapped_column(JSON)
    # presidencia: los demás no pueden asignarle tareas, recordatorios ni convocarle (él sí a ellos)
    no_asignable: Mapped[bool] = mapped_column(Boolean, default=False)
    assignments: Mapped[list["Assignment"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(80), unique=True)
    descripcion: Mapped[str | None] = mapped_column(String(300))
    permisos: Mapped[list] = mapped_column(JSON, default=list)


class Assignment(Base):
    """Asigna un rol a un usuario con un ámbito:
    - sin sociedad ni activo  -> todo el grupo
    - solo sociedad           -> todos los activos (presentes y futuros) de esa sociedad
    - activo                  -> solo ese activo
    """
    __tablename__ = "asignaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("sociedades.id"))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("activos.id"))
    role: Mapped[Role] = relationship(lazy="joined")


class AuditLog(Base):
    __tablename__ = "auditoria"
    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    accion: Mapped[str] = mapped_column(String(40))
    entidad: Mapped[str] = mapped_column(String(40))
    entidad_id: Mapped[int | None] = mapped_column(Integer)
    detalle: Mapped[dict | None] = mapped_column(JSON)


class EmailLog(Base):
    """Registro de avisos enviados por correo (también evita repetir el resumen diario)."""
    __tablename__ = "avisos_enviados"
    id: Mapped[int] = mapped_column(primary_key=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    clave: Mapped[str] = mapped_column(String(80), index=True)  # p.ej. resumen:2026-10-05, ot_urgente:12
    tipo: Mapped[str] = mapped_column(String(30))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    destinatario: Mapped[str | None] = mapped_column(String(160))
    asunto: Mapped[str] = mapped_column(String(200))
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(String(300))


# --------------------------------------------------------------------------- agenda
TIPOS_AGENDA = {"reunion": "Reunión", "tarea": "Tarea", "recordatorio": "Recordatorio", "evento": "Evento"}
VISIBILIDADES = {"privada": "Privada (solo yo)", "compartida": "Solo las personas indicadas",
                 "publica": "Pública (todos los usuarios)"}
REPETICIONES = {"": "No se repite", "diaria": "Cada día", "semanal": "Cada semana", "mensual": "Cada mes",
                "anual": "Cada año"}


class AgendaEvent(Base):
    """Reunión, tarea, recordatorio o evento del calendario. Privada (solo el autor), compartida (autor y
    participantes) o pública (todos los usuarios)."""
    __tablename__ = "agenda"
    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), default="evento")
    titulo: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str | None] = mapped_column(Text)
    lugar: Mapped[str | None] = mapped_column(String(200))
    inicio: Mapped[datetime] = mapped_column(DateTime, index=True)
    fin: Mapped[datetime | None] = mapped_column(DateTime)
    todo_el_dia: Mapped[bool] = mapped_column(Boolean, default=False)
    visibilidad: Mapped[str] = mapped_column(String(20), default="privada")
    prioridad: Mapped[str] = mapped_column(String(10), default="normal")  # normal | alta
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("activos.id"))  # activo relacionado (opcional)
    repeticion: Mapped[str | None] = mapped_column(String(10))  # diaria | semanal | mensual | anual
    repetir_hasta: Mapped[date | None] = mapped_column(Date)
    aviso_min: Mapped[int | None] = mapped_column(Integer)  # aviso por correo X minutos antes
    hecha: Mapped[bool] = mapped_column(Boolean, default=False)  # tarea terminada (también por participantes)
    hecha_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    hecha_en: Mapped[datetime | None] = mapped_column(DateTime)
    creador_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    participantes: Mapped[list["AgendaParticipant"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class AgendaParticipant(Base):
    __tablename__ = "agenda_participantes"
    __table_args__ = (UniqueConstraint("event_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("agenda.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    respuesta: Mapped[str] = mapped_column(String(12), default="pendiente")  # pendiente | acepta | rechaza
    visto: Mapped[bool] = mapped_column(Boolean, default=False)


class LeaseDocument(Base):
    """Carpeta documental del contrato de alquiler (copias cifradas): DNI, solvencia, aval, póliza, CEE,
    justificante del depósito de la fianza, contrato firmado, fotos del inventario…"""
    __tablename__ = "contrato_documentos"
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("contratos.id", ondelete="CASCADE"), index=True)
    clave: Mapped[str] = mapped_column(String(30))  # punto del checklist al que corresponde, u «otro»
    nombre: Mapped[str] = mapped_column(String(200))
    fichero: Mapped[str] = mapped_column(String(80))
    mime: Mapped[str] = mapped_column(String(80))
    tamano: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    subido: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ExternalInvoice(Base):
    """Facturación del programa anterior (SYADE) importada para ver la producción antes de que el PMS facture.
    No forma parte de la numeración ni de la cadena de huellas de las facturas del PMS."""
    __tablename__ = "facturas_externas"
    __table_args__ = (UniqueConstraint("asset_id", "tipo", "serie", "numero"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    origen: Mapped[str] = mapped_column(String(20), default="SYADE")
    tipo: Mapped[str] = mapped_column(String(20))  # alojamiento | servicio | abono | fianza_devuelta
    serie: Mapped[str] = mapped_column(String(12))
    numero: Mapped[str] = mapped_column(String(30))
    fecha: Mapped[date] = mapped_column(Date, index=True)
    localizador: Mapped[str | None] = mapped_column(String(60), index=True)
    nif: Mapped[str | None] = mapped_column(String(30))
    cliente: Mapped[str | None] = mapped_column(String(200))
    base: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    tipo_iva: Mapped[float | None] = mapped_column(Numeric(5, 2))
    cuota: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    fianza: Mapped[float] = mapped_column(Numeric(12, 2), default=0)  # fianza cobrada con la factura / devuelta
    detalle: Mapped[dict | None] = mapped_column(JSON)  # abono: factura rectificada; fianza: recibida, retenida…
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("reservas.id", ondelete="SET NULL"))
    importado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class PresidencyReport(Base):
    """Informe mensual a la presidencia de un activo: quién comprobó los datos y cómo y a quién se envió.
    El Excel queda en los documentos del activo (tipo «informe»)."""
    __tablename__ = "informes_presidencia"
    __table_args__ = (UniqueConstraint("asset_id", "anio", "mes"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    anio: Mapped[int] = mapped_column(Integer)
    mes: Mapped[int] = mapped_column(Integer)
    revisado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    revisado_en: Mapped[datetime | None] = mapped_column(DateTime)
    enviado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    enviado_en: Mapped[datetime | None] = mapped_column(DateTime)
    canal: Mapped[str | None] = mapped_column(String(12))  # email | whatsapp
    destino: Mapped[str | None] = mapped_column(String(500))
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documentos_recibidos.id"))
    resumen: Mapped[dict | None] = mapped_column(JSON)  # totales enviados (ingresos, gastos, resultado, %)


class CleaningTask(Base):
    """Limpieza del parte diario: por salida de un cliente, contratada por el cliente (según su periodicidad) o
    extra añadida por recepción. Queda pendiente (y pasa al día siguiente) hasta que recepción la valida."""
    __tablename__ = "limpiezas"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), index=True)
    fecha: Mapped[date] = mapped_column(Date, index=True)  # día previsto
    tipo: Mapped[str] = mapped_column(String(20))  # salida | contratada | extra
    reservation_id: Mapped[int | None] = mapped_column(ForeignKey("reservas.id"), index=True)
    clave: Mapped[str | None] = mapped_column(String(60), unique=True)  # evita duplicar las generadas solas
    nota: Mapped[str | None] = mapped_column(String(300))
    # recepción ordena el parte del día y marca lo urgente antes de imprimirlo o enviarlo
    orden: Mapped[int | None] = mapped_column(Integer)
    urgente: Mapped[bool] = mapped_column(Boolean, default=False)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")  # pendiente | hecha | anulada
    creada: Mapped[datetime] = mapped_column(DateTime, default=_now)
    creada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    hecha: Mapped[datetime | None] = mapped_column(DateTime)
    validada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    unit: Mapped[Unit] = relationship()
