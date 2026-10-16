"""Modelo de datos de INVERPMS (Grupo INVERSIETE).

Jerarquía:  Sociedad -> Activo -> Unidad
Cada activo tiene una *modalidad* de explotación (alquiler residencial,
apartamentos turísticos, ...). Nuevas modalidades se añaden en MODALIDADES.
"""
from datetime import date, datetime, time

from sqlalchemy import false as sa_false
from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, Time, UniqueConstraint
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
    # Recepción 1 del activo (aprueba ausencias de su personal, valida partes…): asignada expresamente
    recepcion1_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
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
    # Comisión de cada canal en % del bruto (booking, airbnb…) para la liquidación mensual que se manda a gestión
    comisiones_canal: Mapped[dict | None] = mapped_column(JSON)
    # Fusión con gestión (contrato «fusion1»): sus facturas, pagos y cobros se sincronizan con INVERGESTION
    sync_facturas: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    # Maestros con gestión (maestro.catastro): datos patrimoniales y fiscales de su finca principal (propietaria,
    # valores catastrales, uso catastral, IBI y TRUA del año, versión…). Solo lectura en el PMS: se editan en gestión.
    catastro: Mapped[dict | None] = mapped_column(JSON)
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
    # Maestros con gestión: versión de los datos operativos (sube en cada cambio; viaja en maestro.unidad), cuándo
    # cambiaron, baja (no se borra: tiene historial) y el catastro que manda gestión (solo lectura en el PMS)
    maestro_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    maestro_cambiado: Mapped[datetime | None] = mapped_column(DateTime)
    baja: Mapped[datetime | None] = mapped_column(DateTime)
    catastro: Mapped[dict | None] = mapped_column(JSON)
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
    # Lista negra: Recepción 1, Recepción 2 o Dirección anotan el motivo; sale al volver a reservar
    lista_negra: Mapped[bool] = mapped_column(Boolean, default=False)
    lista_negra_motivo: Mapped[str | None] = mapped_column(Text)
    lista_negra_fecha: Mapped[datetime | None] = mapped_column(DateTime)
    lista_negra_user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class ContactDistinct(Base):
    """Dos fichas con el mismo nombre que recepción ha revisado: no son la misma persona. Ya no salen como repetidas."""
    __tablename__ = "terceros_distintos"
    __table_args__ = (UniqueConstraint("a_id", "b_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    a_id: Mapped[int] = mapped_column(ForeignKey("terceros.id", ondelete="CASCADE"), index=True)  # a_id < b_id
    b_id: Mapped[int] = mapped_column(ForeignKey("terceros.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    fecha: Mapped[datetime] = mapped_column(DateTime, default=_now)


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
    # Coordinación de actividades empresariales (CAE, RD 171/2004) y PRL: hasta cuándo es válida su documentación.
    # Vencida (o sin fecha, si se exige) no se le pueden asignar órdenes de trabajo.
    cae_vence: Mapped[date | None] = mapped_column(Date)
    cae_nota: Mapped[str | None] = mapped_column(String(300))
    notas: Mapped[str | None] = mapped_column(Text)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    # datos de pago (los manda gestión en la fusión: proveedor.alta / proveedor.actualizado)
    iban: Mapped[str | None] = mapped_column(String(34))
    forma_pago: Mapped[str | None] = mapped_column(String(30))


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
    estado: Mapped[str] = mapped_column(String(20), default="vigente")  # borrador | vigente | finalizado | rescindido | anulado
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
    # Plazas de garaje unidas al alquiler de la vivienda (id de unidades de garaje del mismo activo): quedan
    # ocupadas con el contrato, sin contrato aparte ni bloqueo. Ver app/plazas.py
    plazas: Mapped[list | None] = mapped_column(JSON)
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
    guest_id: Mapped[int] = mapped_column(ForeignKey("terceros.id"), index=True)
    localizador: Mapped[str | None] = mapped_column(String(60), index=True)
    canal: Mapped[str] = mapped_column(String(30), default="directo")
    fecha_entrada: Mapped[date] = mapped_column(Date, index=True)
    fecha_salida: Mapped[date] = mapped_column(Date, index=True)
    adultos: Mapped[int] = mapped_column(Integer, default=1)
    ninos: Mapped[int] = mapped_column(Integer, default=0)
    importe_total: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    importe_pagado: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    estado: Mapped[str] = mapped_column(String(20), default="confirmada", index=True)  # confirmada | checkin | checkout | cancelada | no_show
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
    # Dotación entregada: {habitual: bool, cambios: {codigo: cantidad («—» = se quita)}, extra: [{codigo, zona,
    # articulo, cantidad}]}. Ver app/dotacion.py
    dotacion: Mapped[dict | None] = mapped_column(JSON)
    # Revisión de salida hecha por limpieza desde el móvil: {fecha, nombre, nota, items: [{codigo, articulo, zona,
    # estado: falta|roto, cantidad, precio}]} (solo lo que no está bien)
    revision: Mapped[dict | None] = mapped_column(JSON)
    # Cobro de la fianza al llegar: {importe, forma, fecha, user_id, ref}. Ver app/fianzas.py
    fianza_cobro: Mapped[dict | None] = mapped_column(JSON)
    aviso_llegada: Mapped[datetime | None] = mapped_column(DateTime)  # mensaje de la víspera (documentos para SES)
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
    # «gestion:<orden>» si lo puso INVERGESTION por una orden de trabajo: solo se levanta al cerrarla allí
    origen: Mapped[str | None] = mapped_column(String(80), index=True)


class GestionEvento(Base):
    """Cola de avisos del PMS a INVERGESTION (reservas, check-outs, incidencias y liquidaciones). Se escribe en la
    misma transacción que el cambio y un hilo la envía con reintentos (ver app/gestion.py)."""
    __tablename__ = "gestion_cola"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_evento: Mapped[str] = mapped_column(String(80), unique=True)
    tipo: Mapped[str] = mapped_column(String(40), index=True)
    datos: Mapped[dict] = mapped_column(JSON)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", index=True)  # pendiente | enviado | aviso
    intentos: Mapped[int] = mapped_column(Integer, default=0)
    proximo: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    enviado: Mapped[datetime | None] = mapped_column(DateTime)
    ultimo_error: Mapped[str | None] = mapped_column(String(400))


class FusionEnlace(Base):
    """Fusión con gestión: registro del PMS (gasto, factura, pago, cobro, proveedor o producto) y su gemelo en
    INVERGESTION. «sincronizada»: ya está en gestión, que manda en sus datos contables (solo lectura en el PMS)."""
    __tablename__ = "fusion_enlaces"
    __table_args__ = (UniqueConstraint("tipo", "pms_ref"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20))  # recibida | emitida | externa | pago | cobro | proveedor | producto
    pms_ref: Mapped[int] = mapped_column(Integer)
    gestion_id: Mapped[str | None] = mapped_column(String(120), index=True)
    asset_id: Mapped[int | None] = mapped_column(Integer)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")  # pendiente | sincronizada | anulada
    origen: Mapped[str] = mapped_column(String(10), default="PMS")  # dónde nació: PMS | GESTION
    # «Pedir corrección» / «Pedir anulación» desde el PMS: queda pendiente hasta que gestión contesta
    solicitud: Mapped[str | None] = mapped_column(String(20))  # correccion | anulacion
    solicitud_datos: Mapped[dict | None] = mapped_column(JSON)
    solicitud_fecha: Mapped[datetime | None] = mapped_column(DateTime)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


class FusionEntrada(Base):
    """Avisos «fusion1» recibidos de gestión (POST /api/gestion/eventos). Uno por id_evento: el repetido no se aplica
    otra vez. «sin_tratar»: tipo desconocido o sincronización apagada; se guarda y se contesta 200."""
    __tablename__ = "fusion_entradas"
    id: Mapped[int] = mapped_column(primary_key=True)
    id_evento: Mapped[str] = mapped_column(String(160), unique=True)
    tipo: Mapped[str] = mapped_column(String(60), index=True)
    origen: Mapped[str | None] = mapped_column(String(20))
    id_evento_causa: Mapped[str | None] = mapped_column(String(160))
    estado: Mapped[str] = mapped_column(String(20), default="aplicado")  # aplicado | sin_tratar | eco | sso
    cuerpo: Mapped[dict | None] = mapped_column(JSON)
    resultado: Mapped[dict | None] = mapped_column(JSON)
    recibido: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class FusionDocumento(Base):
    """Documentos de la fusión: adjuntos de más del PMS («Adjuntar documento»), copias de las facturas emitidas que
    se mandan a gestión y documentos descargados de gestión («a_revisar» si su sha256 no cuadra: no se adjuntan)."""
    __tablename__ = "fusion_documentos"
    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20))  # recibida | emitida | externa | pago | cobro
    pms_ref: Mapped[int] = mapped_column(Integer, index=True)
    origen: Mapped[str] = mapped_column(String(10))  # PMS | GESTION
    categoria: Mapped[str] = mapped_column(String(20), default="OTRO")  # FACTURA | JUSTIFICANTE | ALBARAN | OTRO
    documento_id: Mapped[int | None] = mapped_column(ForeignKey("documentos_recibidos.id", ondelete="SET NULL"))
    fichero: Mapped[str | None] = mapped_column(String(64))  # copia cifrada (PDF de una factura emitida)
    doc_id_gestion: Mapped[str | None] = mapped_column(String(120), index=True)
    nombre: Mapped[str | None] = mapped_column(String(200))
    mime: Mapped[str | None] = mapped_column(String(100))
    tamano: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    estado: Mapped[str] = mapped_column(String(20), default="ok")  # ok | a_revisar
    motivo: Mapped[str | None] = mapped_column(String(300))
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Notificacion(Base):
    """Aviso dentro del PMS (campana de la barra superior, con sonido): lo que el usuario tiene que atender. Se crea
    junto con cada aviso que el PMS envía por correo al usuario (los que tiene elegidos en «Mi perfil»)."""
    __tablename__ = "notificaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    tipo: Mapped[str] = mapped_column(String(40))
    titulo: Mapped[str] = mapped_column(String(200))
    texto: Mapped[str | None] = mapped_column(String(600))
    vista: Mapped[str | None] = mapped_column(String(40))  # pantalla del PMS a la que lleva
    urgente: Mapped[bool] = mapped_column(Boolean, default=False)
    creada: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    leida: Mapped[datetime | None] = mapped_column(DateTime)


class ChatConversacion(Base):
    """Chat interno. «todos»: todo el equipo (los usuarios internos activos, sin lista de miembros). «directo»: dos
    personas. «grupo»: las que elige quien la crea, que es quien puede añadir o quitar personas."""
    __tablename__ = "chat_conversaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    tipo: Mapped[str] = mapped_column(String(10), default="grupo")  # todos | directo | grupo
    titulo: Mapped[str | None] = mapped_column(String(120))
    creador_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    creada: Mapped[datetime] = mapped_column(DateTime, default=_now)
    ultimo: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)  # último mensaje


class ChatMiembro(Base):
    __tablename__ = "chat_miembros"
    __table_args__ = (UniqueConstraint("conversacion_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    conversacion_id: Mapped[int] = mapped_column(ForeignKey("chat_conversaciones.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), index=True)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)  # False: salió o le quitaron
    leido_hasta: Mapped[int] = mapped_column(Integer, default=0)  # último mensaje leído
    anadido_por: Mapped[int | None] = mapped_column(Integer)
    anadido: Mapped[datetime] = mapped_column(DateTime, default=_now)


class ChatMensaje(Base):
    __tablename__ = "chat_mensajes"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversacion_id: Mapped[int] = mapped_column(ForeignKey("chat_conversaciones.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    texto: Mapped[str] = mapped_column(Text)
    sistema: Mapped[bool] = mapped_column(Boolean, default=False)  # «Ana ha añadido a Luis»
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    borrado: Mapped[bool] = mapped_column(Boolean, default=False)
    menciones: Mapped[list | None] = mapped_column(JSON)  # usuarios citados con @nombre (reciben aviso)


class ChatAdjunto(Base):
    """Foto o PDF de un mensaje del chat. El fichero va cifrado fuera de la base de datos (como los de las OT)."""
    __tablename__ = "chat_adjuntos"
    id: Mapped[int] = mapped_column(primary_key=True)
    mensaje_id: Mapped[int] = mapped_column(ForeignKey("chat_mensajes.id", ondelete="CASCADE"), index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    mime: Mapped[str] = mapped_column(String(80))
    tamano: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    fichero: Mapped[str] = mapped_column(String(80))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    subido: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Ajuste(Base):
    """Interruptores de la configuración del PMS que cambia la superadministración desde la pantalla (no del .env)."""
    __tablename__ = "ajustes"
    clave: Mapped[str] = mapped_column(String(60), primary_key=True)
    valor: Mapped[dict | None] = mapped_column(JSON)
    cambiado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))


class CalendarioEntrada(Base):
    """Calendario común PMS ↔ gestión (contrato «fusion1», tipos calendario.*). Una fila por uid: las que llegan de
    gestión (INVG-…) y el espejo de las que manda el PMS (PMS-AG-<agenda>, PMS-LIM-<limpieza>) con su versión."""
    __tablename__ = "calendario_comun"
    id: Mapped[int] = mapped_column(primary_key=True)
    uid: Mapped[str] = mapped_column(String(120), unique=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    version_remota: Mapped[int] = mapped_column(Integer, default=0)  # última versión aceptada de gestión
    tipo: Mapped[str] = mapped_column(String(20), index=True)
    subtipo: Mapped[str | None] = mapped_column(String(40))
    titulo: Mapped[str] = mapped_column(String(300))
    descripcion: Mapped[str | None] = mapped_column(Text)
    lugar: Mapped[str | None] = mapped_column(String(300))
    inicio: Mapped[datetime] = mapped_column(DateTime, index=True)  # hora de Madrid
    fin: Mapped[datetime | None] = mapped_column(DateTime)  # día completo: último día incluido
    todo_el_dia: Mapped[bool] = mapped_column(Boolean, default=False)
    activo: Mapped[str | None] = mapped_column(String(40))  # código de gestión (SFLORIDA…)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("activos.id", ondelete="SET NULL"), index=True)
    unidad: Mapped[str | None] = mapped_column(String(60))
    sociedad: Mapped[str | None] = mapped_column(String(10))
    responsables: Mapped[list | None] = mapped_column(JSON)
    invitados: Mapped[list | None] = mapped_column(JSON)
    estado: Mapped[str] = mapped_column(String(12), default="PENDIENTE")  # PENDIENTE | HECHA | CANCELADA
    recordatorio: Mapped[int | None] = mapped_column(Integer)
    repeticion: Mapped[str | None] = mapped_column(String(12))
    repetir_hasta: Mapped[date | None] = mapped_column(Date)
    importe: Mapped[float | None] = mapped_column(Numeric(14, 2))
    prioridad: Mapped[str | None] = mapped_column(String(20))
    origen: Mapped[str] = mapped_column(String(10), default="GESTION")  # GESTION | PMS
    editable_en: Mapped[str] = mapped_column(String(10), default="GESTION")  # GESTION | PMS | AMBOS
    solo_lectura: Mapped[bool] = mapped_column(Boolean, default=True)
    roles: Mapped[list | None] = mapped_column(JSON)
    url_gestion: Mapped[str | None] = mapped_column(String(500))
    datos: Mapped[dict | None] = mapped_column(JSON)  # el último «datos» completo (lo que no tiene columna)
    agenda_id: Mapped[int | None] = mapped_column(ForeignKey("agenda.id", ondelete="SET NULL"), index=True)
    limpieza_id: Mapped[int | None] = mapped_column(ForeignKey("limpiezas.id", ondelete="SET NULL"), index=True)
    ultimo_cambio: Mapped[str] = mapped_column(String(10), default="GESTION")  # quién hizo el último cambio
    cambio_local: Mapped[bool] = mapped_column(Boolean, default=False)  # cambio del PMS aún sin entregar a gestión
    historial: Mapped[list | None] = mapped_column(JSON)  # versiones anteriores descartadas («manda gestión»)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


class CalendarioEnlace(Base):
    """Enlace privado de cada usuario para suscribirse en Outlook (/cal/<clave>.ics). Solo se guarda la sha256."""
    __tablename__ = "calendario_enlaces"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id", ondelete="CASCADE"), unique=True)
    clave_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    mostrar_importes: Mapped[bool] = mapped_column(Boolean, default=False)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime)
    ventana: Mapped[datetime | None] = mapped_column(DateTime)  # hora en curso para el límite de peticiones
    peticiones: Mapped[int] = mapped_column(Integer, default=0)
    avisado: Mapped[bool] = mapped_column(Boolean, default=False)


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
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"), index=True)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("planes_preventivos.id"), index=True)
    # zona común del plano (p.ej. P4-A-PISCINA) cuando la incidencia no es de un apartamento
    zona: Mapped[str | None] = mapped_column(String(40), index=True)
    tipo: Mapped[str] = mapped_column(String(20), default="correctivo")  # correctivo | preventivo | mejora | normativo
    categoria: Mapped[str] = mapped_column(String(40), default="general")
    prioridad: Mapped[str] = mapped_column(String(20), default="media")  # baja | media | alta | urgente
    estado: Mapped[str] = mapped_column(String(30), default="abierta", index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str | None] = mapped_column(Text)
    asignado_a: Mapped[str | None] = mapped_column(String(120))
    proveedor: Mapped[str | None] = mapped_column(String(160))
    # a quién se encarga: personal propio (ficha de Personal) o subcontrata (ficha de Proveedores)
    asignacion: Mapped[str | None] = mapped_column(String(20))  # propio | subcontrata
    personal_id: Mapped[int | None] = mapped_column(ForeignKey("personal_servicio.id"))
    proveedor_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))
    coste_estimado: Mapped[float | None] = mapped_column(Numeric(10, 2))
    coste_real: Mapped[float | None] = mapped_column(Numeric(10, 2))
    bloquea_unidad: Mapped[bool] = mapped_column(Boolean, default=False)
    # correctivas y de mejora abiertas desde la 1.70: no se finalizan sin la foto del «antes» (adjunto «averia»)
    exige_foto_antes: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_false())
    motivo_subcontrata: Mapped[str | None] = mapped_column(String(30))  # abierta por mantenimiento (MOTIVOS_SUBCONTRATA)
    fecha_apertura: Mapped[date] = mapped_column(Date, default=date.today)
    fecha_prevista: Mapped[date | None] = mapped_column(Date)
    fecha_cierre: Mapped[date | None] = mapped_column(Date)
    solucion: Mapped[str | None] = mapped_column(Text)
    # Flujo (1.70): abre recepción -> personal propio: la cierra él (firma, foto y tiempo); subcontrata: la da por
    # finalizada y la cierran el Director Técnico o recepción. conf_limpieza_* ya no se usan (históricas).
    abierta_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    conf_mto_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    conf_mto_fecha: Mapped[datetime | None] = mapped_column(DateTime)
    conf_limpieza_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    conf_limpieza_fecha: Mapped[datetime | None] = mapped_column(DateTime)
    cerrada_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    # envíos de la orden al personal de mantenimiento: [{fecha, canal, destino, nombre, usuario}]
    envios: Mapped[list | None] = mapped_column(JSON)
    # resultado que envía el técnico desde su enlace (resuelta, pendiente_material, otra_visita, escalar, otro):
    # mientras no lo atiende recepción o dirección sale en el panel y, si queda en pausa, se recuerda cada día
    alerta_tecnico: Mapped[str | None] = mapped_column(String(20))
    alerta_fecha: Mapped[datetime | None] = mapped_column(DateTime)
    conformidad_en: Mapped[datetime | None] = mapped_column(DateTime)  # conformidad de la propiedad (cierre)
    # enlace del técnico: al reasignar la orden o al revocarlo sube y los enlaces anteriores dejan de valer
    enlace_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    plazo_avisado: Mapped[datetime | None] = mapped_column(DateTime)  # aviso de plazo de respuesta superado
    creada: Mapped[datetime | None] = mapped_column(DateTime, default=_now)  # fecha y hora de apertura (plazos)
    # acceso al apartamento con huésped: «llave» (el cliente autoriza usar la llave de recepción) | «contactar»
    acceso: Mapped[str | None] = mapped_column(String(12))
    # quién autorizó entrar con la llave de recepción, cómo y quién lo anotó; vale para esa estancia (reserva)
    acceso_autoriza: Mapped[str | None] = mapped_column(String(120))
    acceso_medio: Mapped[str | None] = mapped_column(String(20))  # en_persona | telefono | whatsapp | correo
    acceso_user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    acceso_fecha: Mapped[datetime | None] = mapped_column(DateTime)
    acceso_reserva_id: Mapped[int | None] = mapped_column(ForeignKey("reservas.id"))


AREAS_PERSONAL = {"mantenimiento": "Mantenimiento", "limpieza": "Limpieza", "conserjeria": "Conserjería",
                  "recepcion": "Recepción", "administracion": "Administración y oficinas",
                  "otros": "Otros (por administración)"}
TIPOS_CONTRATO = {"indefinido": "Indefinido", "fijo_discontinuo": "Fijo discontinuo", "temporal": "Temporal",
                  "practicas": "Prácticas / formación", "autonomo": "Autónomo / subcontrata", "otro": "Otro"}


class StaffMember(Base):
    """Personal de mantenimiento o limpieza (propio o de una subcontrata) al que se envían las órdenes de trabajo
    y el parte de limpieza por correo o WhatsApp. No necesita usuario en el PMS. Sin activo = todos."""
    __tablename__ = "personal_servicio"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("activos.id"), index=True)
    area: Mapped[str] = mapped_column(String(20))  # mantenimiento | limpieza | conserjeria | otros
    nombre: Mapped[str] = mapped_column(String(160))
    empresa: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(160))
    telefono: Mapped[str | None] = mapped_column(String(40))
    # mantenimiento: recibe por correo, al momento, las OT urgentes de su activo
    avisar_urgentes: Mapped[bool] = mapped_column(Boolean, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    notas: Mapped[str | None] = mapped_column(Text)
    # empresa (ficha de Proveedores) a la que pertenece: la ve su colaborador en el portal
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"), index=True)
    # ficha del empleado (personal propio): datos laborales, vacaciones y registro de jornada
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)  # su usuario del PMS
    dni: Mapped[str | None] = mapped_column(String(20))
    puesto: Mapped[str | None] = mapped_column(String(120))
    tipo_contrato: Mapped[str | None] = mapped_column(String(20))  # TIPOS_CONTRATO
    fecha_alta: Mapped[date | None] = mapped_column(Date)
    fecha_baja: Mapped[date | None] = mapped_column(Date)
    jornada_semanal: Mapped[float | None] = mapped_column(Numeric(5, 2))  # horas de contrato por semana
    vacaciones_dias: Mapped[int | None] = mapped_column(Integer)  # días de vacaciones al año (convenio)
    vacaciones_tipo: Mapped[str | None] = mapped_column(String(12))  # laborables | naturales
    fichaje_clave: Mapped[str | None] = mapped_column(String(40))  # enlace personal para fichar (revocable)
    # coste por hora para la empresa (salario + Seguridad Social): coste de la mano de obra propia en el informe de
    # mantenimiento (horas de OT y del parte diario × coste/hora)
    coste_hora: Mapped[float | None] = mapped_column(Numeric(8, 2))


# --------------------------------------------------------------------------- documentos recibidos y gastos
TIPOS_DOCUMENTO = {
    "factura": "Factura", "ticket": "Ticket / recibo", "albaran": "Albarán", "presupuesto": "Presupuesto",
    "carta": "Carta", "notificacion": "Notificación / requerimiento", "contrato": "Contrato",
    "seguro": "Póliza / seguro", "informe": "Informe mensual (presidencia)", "limpieza": "Parte de limpieza",
    "parte_trabajo": "Parte de trabajo (mantenimiento / limpieza)",
    "justificante": "Justificante de pago",
    "personal": "Documentación de personal (contratos, TC2, formación PRL, reconocimientos…)",
    "legal": "Documentación legal / CAE (seguros, certificados AEAT y TGSS, REA…)",
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
    # subido por un colaborador desde su portal: queda pendiente hasta que recepción o dirección lo revisa
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"), index=True)
    revision: Mapped[str | None] = mapped_column(String(20))  # pendiente | aceptado | rechazado
    revision_nota: Mapped[str | None] = mapped_column(String(300))
    revisado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    revisado_en: Mapped[datetime | None] = mapped_column(DateTime)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("personal_servicio.id"))  # trabajador al que se refiere
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("ordenes_trabajo.id"))  # OT a la que corresponde


# solo dirección y Recepción 1 del activo ven la documentación del personal (datos personales de trabajadores)
TIPOS_DOC_RESERVADOS = ("personal",)


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
    # justificante del pago (transferencia, cargo en cuenta…): obligatorio para marcarla como pagada
    justificante_id: Mapped[int | None] = mapped_column(ForeignKey("documentos_recibidos.id"))


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
    # mantenimiento (empresa mantenedora o personal propio) | oca (inspección reglamentaria por organismo de control)
    tipo: Mapped[str] = mapped_column(String(16), default="mantenimiento", server_default="mantenimiento")
    proveedor_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))
    # puntos a comprobar en cada revisión (si no se fijan, los de su instalación: app/preventivo.py)
    checklist: Mapped[list | None] = mapped_column(JSON)


class PreventiveRevision(Base):
    """Revisión hecha de un plan preventivo o inspección OCA: fecha, resultado, próxima fecha que indica el documento,
    puntos comprobados y deficiencias (cada una con su OT). Los documentos de la empresa van en adjuntos_revision."""
    __tablename__ = "revisiones_preventivo"
    id: Mapped[int] = mapped_column(primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("planes_preventivos.id"), index=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    fecha: Mapped[date] = mapped_column(Date)
    fecha_prevista: Mapped[date | None] = mapped_column(Date)  # la que tocaba según el plan (para ver retrasos)
    proxima: Mapped[date | None] = mapped_column(Date)  # la que indica el documento (o la del plan si no la indica)
    resultado: Mapped[str] = mapped_column(String(24))  # correcto | deficiencias | favorable | ... (preventivo.RESULTADOS)
    empresa: Mapped[str | None] = mapped_column(String(160))
    proveedor_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))
    tecnico: Mapped[str | None] = mapped_column(String(120))  # técnico o inspector
    numero: Mapped[str | None] = mapped_column(String(60))  # nº de acta / certificado / informe
    plazo_subsanacion: Mapped[date | None] = mapped_column(Date)
    checklist: Mapped[list | None] = mapped_column(JSON)  # [{punto, estado: ok|deficiencia|na, nota}]
    deficiencias: Mapped[list | None] = mapped_column(JSON)  # [{descripcion, gravedad: leve|grave|muy_grave, ot_id}]
    observaciones: Mapped[str | None] = mapped_column(Text)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("ordenes_trabajo.id"))  # OT preventiva que cierra
    creada: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class RevisionAttachment(Base):
    """Documento de una revisión (informe de la mantenedora, acta o certificado de la OCA, fotos), cifrado."""
    __tablename__ = "adjuntos_revision"
    id: Mapped[int] = mapped_column(primary_key=True)
    revision_id: Mapped[int] = mapped_column(ForeignKey("revisiones_preventivo.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(160))
    fichero: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(60))
    tamano: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    subido: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


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
    # accesos rápidos de la barra superior [{nombre, url}] (None = los de serie: Gmail, Outlook, Excel, Word y Teams)
    accesos: Mapped[list | None] = mapped_column(JSON)
    # presidencia: los demás no pueden asignarle tareas, recordatorios ni convocarle (él sí a ellos)
    no_asignable: Mapped[bool] = mapped_column(Boolean, default=False)
    # colaborador externo (subcontrata): solo entra en su portal y ve lo de este proveedor
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"), index=True)
    # sube al cambiar la contraseña o desactivar el usuario: las sesiones abiertas dejan de valer
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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


# --------------------------------------------------------------------------- pedidos de material
FAMILIAS_PRODUCTO = [
    "ELECTRICIDAD E ILUMINACIÓN", "FONTANERÍA", "CLIMATIZACIÓN", "PROTECCIÓN CONTRA INCENDIOS",
    "FERRETERÍA Y CERRAJERÍA", "PINTURA", "ALBAÑILERÍA Y MATERIALES", "CARPINTERÍA", "PISCINA", "JARDINERÍA",
    "ELECTRODOMÉSTICOS", "MOBILIARIO", "MENAJE", "LENCERÍA Y AMENITIES", "LIMPIEZA Y CONSUMIBLES", "MANO DE OBRA",
    "RESIDUOS Y CONTENEDORES", "OTROS"]
ESTADOS_PEDIDO = {"pendiente": "Pendiente de autorizar", "autorizado": "Autorizado", "enviado": "Enviado al proveedor",
                  "recibido": "Recibido", "rechazado": "Rechazado", "anulado": "Anulado"}


class Product(Base):
    """Catálogo de material del grupo (compartido por los activos), intercambiado con INVERGESTION.
    `referencia` es la clave con INVERGESTION: la suya (del proveedor o «INV-…») o la del PMS («PMS-000001»)."""
    __tablename__ = "productos"
    id: Mapped[int] = mapped_column(primary_key=True)
    referencia: Mapped[str] = mapped_column(String(60), unique=True)
    articulo: Mapped[str] = mapped_column(String(250))
    familia: Mapped[str] = mapped_column(String(60), default="OTROS")
    unidad: Mapped[str] = mapped_column(String(20), default="ud")
    precio: Mapped[float | None] = mapped_column(Numeric(12, 4))  # unitario sin IVA (último conocido)
    tipo_iva: Mapped[float] = mapped_column(Numeric(5, 2), default=21)
    marca: Mapped[str | None] = mapped_column(String(100))
    ref_proveedor: Mapped[str | None] = mapped_column(String(60))
    proveedor: Mapped[str | None] = mapped_column(String(200))
    proveedor_nif: Mapped[str | None] = mapped_column(String(20))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))
    origen: Mapped[str] = mapped_column(String(20), default="PMS")  # PMS | INVERGESTION
    fecha_factura: Mapped[date | None] = mapped_column(Date)  # de INVERGESTION: última factura recibida
    num_factura: Mapped[str | None] = mapped_column(String(60))
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("activos.id"))  # activo que lo dio de alta (PMS)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    alta_exportada: Mapped[datetime | None] = mapped_column(DateTime)  # alta enviada a INVERGESTION
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    actualizado: Mapped[datetime | None] = mapped_column(DateTime)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class PurchaseOrder(Base):
    """Pedido de material de un activo a un proveedor. Lo autoriza Recepción 1 del activo (o dirección), salvo
    que lo haga ella misma."""
    __tablename__ = "pedidos"
    id: Mapped[int] = mapped_column(primary_key=True)
    numero: Mapped[str] = mapped_column(String(30), unique=True)  # PED-SF-2026-0001
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("proveedores.id"))
    proveedor: Mapped[str | None] = mapped_column(String(200))  # nombre si no está en Proveedores
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    fecha: Mapped[date] = mapped_column(Date, index=True)
    fecha_entrega: Mapped[date | None] = mapped_column(Date)  # deseada
    notas: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    autorizado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    autorizado_en: Mapped[datetime | None] = mapped_column(DateTime)
    motivo_rechazo: Mapped[str | None] = mapped_column(String(300))
    enviado_en: Mapped[datetime | None] = mapped_column(DateTime)
    recibido_en: Mapped[datetime | None] = mapped_column(DateTime)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    lineas: Mapped[list["PurchaseOrderLine"]] = relationship(order_by="PurchaseOrderLine.orden",
                                                             cascade="all, delete-orphan")
    asset: Mapped[Asset] = relationship()


class PurchaseOrderLine(Base):
    __tablename__ = "pedido_lineas"
    id: Mapped[int] = mapped_column(primary_key=True)
    pedido_id: Mapped[int] = mapped_column(ForeignKey("pedidos.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("productos.id"))
    orden: Mapped[int] = mapped_column(Integer, default=0)
    cantidad: Mapped[float] = mapped_column(Numeric(12, 3))
    precio: Mapped[float | None] = mapped_column(Numeric(12, 4))  # unitario sin IVA en el pedido (estimado)
    tipo_iva: Mapped[float] = mapped_column(Numeric(5, 2), default=21)
    nota: Mapped[str | None] = mapped_column(String(200))
    exportado: Mapped[datetime | None] = mapped_column(DateTime)  # enviado a INVERGESTION
    producto: Mapped[Product] = relationship()


# --------------------------------------------------------------------------- parte de trabajo diario
AREAS_PARTE = {"mantenimiento": "Mantenimiento", "limpieza": "Limpieza"}


class WorkEntry(Base):
    """Actuación que no estaba en ningún parte (p.ej. limpieza de una zona común según el programa, o una tarea de
    mantenimiento sin OT). Se anota en el parte de trabajo del día de su área."""
    __tablename__ = "parte_actuaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    area: Mapped[str] = mapped_column(String(20))  # mantenimiento | limpieza
    fecha: Mapped[date] = mapped_column(Date, index=True)
    descripcion: Mapped[str] = mapped_column(Text)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"))
    ubicacion: Mapped[str | None] = mapped_column(String(160))  # zona común u otro lugar
    persona: Mapped[str | None] = mapped_column(String(160))
    horas: Mapped[float | None] = mapped_column(Numeric(5, 2))
    hora: Mapped[time | None] = mapped_column(Time)  # hora a la que se hizo el trabajo (vacía: la de anotarlo)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creada: Mapped[datetime] = mapped_column(DateTime, default=_now)


class WorkReport(Base):
    """Parte de trabajo diario de un área de un activo. Lo forman las OT terminadas y las limpiezas hechas ese
    día, más las actuaciones anotadas a mano. Recepción lo valida: se congela (`lineas`) y se archivan su PDF y
    su Excel en los documentos del activo. Hasta entonces no se imprime."""
    __tablename__ = "partes_trabajo"
    __table_args__ = (UniqueConstraint("asset_id", "area", "fecha"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    area: Mapped[str] = mapped_column(String(20))
    fecha: Mapped[date] = mapped_column(Date, index=True)
    estado: Mapped[str] = mapped_column(String(20), default="abierto")  # abierto | validado
    observaciones: Mapped[str | None] = mapped_column(Text)
    lineas: Mapped[list | None] = mapped_column(JSON)  # copia congelada al validar
    # correcciones de las líneas que vienen de una OT o de una limpieza (hora, persona, horas, detalle), sin tocar la
    # OT ni la limpieza: {"ot:12": {"hora": "09:30", "persona": "…", "horas": 1.5, "detalle": "…"}}
    correcciones: Mapped[dict | None] = mapped_column(JSON)
    validado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    validado_en: Mapped[datetime | None] = mapped_column(DateTime)
    pdf_id: Mapped[int | None] = mapped_column(ForeignKey("documentos_recibidos.id"))
    xlsx_id: Mapped[int | None] = mapped_column(ForeignKey("documentos_recibidos.id"))


# --------------------------------------------------------------------------- ausencias del personal
TIPOS_AUSENCIA = {
    "vacaciones": "Vacaciones", "dia_libre": "Día libre / asuntos propios", "baja_medica": "Baja médica",
    "permiso": "Permiso (boda, fallecimiento, mudanza, médico…)", "falta": "Falta (ausencia no prevista)",
    "otro": "Otro",
}
COLECTIVOS_AUSENCIA = {
    "mantenimiento": "Mantenimiento", "limpieza": "Limpieza", "conserjeria": "Conserjería",
    "otros": "Otros (por administración)", "recepcion1": "Recepción 1", "recepcion2": "Recepción 2",
    "direccion": "Dirección y oficinas",
}
ESTADOS_AUSENCIA = {
    "pendiente": "Pendiente", "visto_bueno": "Visto bueno de Recepción 1 (falta dirección)",
    "aprobada": "Autorizada", "denegada": "Desestimada", "anulada": "Anulada",
}


class Absence(Base):
    """Vacaciones, días libres, bajas, permisos y faltas del personal: usuarios del PMS o personal de subcontratas
    (ficha de Personal). Quién la aprueba depende del colectivo (ver app/ausencias.py)."""
    __tablename__ = "ausencias"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"), index=True)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("personal_servicio.id"), index=True)
    persona: Mapped[str] = mapped_column(String(160))
    colectivo: Mapped[str] = mapped_column(String(20))
    tipo: Mapped[str] = mapped_column(String(20))
    desde: Mapped[date] = mapped_column(Date, index=True)
    hasta: Mapped[date] = mapped_column(Date, index=True)
    motivo: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")
    visto_bueno_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    visto_bueno_en: Mapped[datetime | None] = mapped_column(DateTime)
    resuelto_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime)
    nota: Mapped[str | None] = mapped_column(Text)  # motivo de la denegación o de la anulación
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado_en: Mapped[datetime] = mapped_column(DateTime, default=_now)


# --------------------------------------------------------------------------- envíos al personal
class StaffDispatch(Base):
    """Copia de lo enviado a cada persona del personal (OT, parte de limpieza…) por correo o WhatsApp. Su
    colaborador lo ve en el portal."""
    __tablename__ = "envios_personal"
    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("personal_servicio.id"), index=True)
    fecha: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    tipo: Mapped[str] = mapped_column(String(30))  # ot_enviada | parte_limpieza | limpieza_urgente…
    clave: Mapped[str | None] = mapped_column(String(80))
    canal: Mapped[str] = mapped_column(String(12))
    asunto: Mapped[str] = mapped_column(String(200))
    texto: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


# --------------------------------------------------------------------------- documentación legal de los activos
class LegalItem(Base):
    """Punto del checklist de documentación legal de un activo (ver app/documentacion_legal.py): fechas,
    «no aplica» y notas. Los ficheros escaneados van en LegalFile. Los puntos propios del activo tienen clave
    «extra-N» y su título."""
    __tablename__ = "documentacion_legal"
    __table_args__ = (UniqueConstraint("asset_id", "clave"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    clave: Mapped[str] = mapped_column(String(40))
    titulo: Mapped[str | None] = mapped_column(String(200))  # solo los puntos propios
    no_aplica: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo: Mapped[str | None] = mapped_column(String(300))  # por qué no aplica
    fecha_documento: Mapped[date | None] = mapped_column(Date)
    vencimiento: Mapped[date | None] = mapped_column(Date)
    notas: Mapped[str | None] = mapped_column(Text)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    ficheros: Mapped[list["LegalFile"]] = relationship(cascade="all, delete-orphan", order_by="LegalFile.id",
                                                      lazy="selectin")


class LegalFile(Base):
    """Documento escaneado (PDF, cifrado) de un punto de la documentación legal."""
    __tablename__ = "documentacion_legal_ficheros"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("documentacion_legal.id", ondelete="CASCADE"), index=True)
    nombre: Mapped[str] = mapped_column(String(200))
    fichero: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(100))
    tamano: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    subido: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class StatusReport(Base):
    """Parte de estado: mantenimiento o limpieza revisan una vivienda o zona común y señalan una deficiencia con
    listas encadenadas (ver app/partes_estado.py). Recepción genera la orden de trabajo o lo descarta."""
    __tablename__ = "partes_estado"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"), index=True)
    zona: Mapped[str | None] = mapped_column(String(40))  # zona común del plano, si la hay
    tipologia: Mapped[str] = mapped_column(String(2))  # T0 | T1 | T2 | ZC
    estancia: Mapped[str] = mapped_column(String(40))
    familia: Mapped[str] = mapped_column(String(4))  # C1..C5
    elemento: Mapped[str] = mapped_column(String(40), index=True)
    clase: Mapped[str] = mapped_column(String(4))  # D1 técnica | D2 operativa
    deficiencia: Mapped[str] = mapped_column(String(30))
    gravedad: Mapped[str] = mapped_column(String(10))  # leve | media | critica
    departamento: Mapped[str] = mapped_column(String(20))  # mantenimiento | limpieza (motor de reglas)
    prioridad: Mapped[str] = mapped_column(String(10))  # prioridad propuesta para la orden de trabajo
    alertas: Mapped[list | None] = mapped_column(JSON)
    observaciones: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6))
    lon: Mapped[float | None] = mapped_column(Numeric(9, 6))
    precision_m: Mapped[float | None] = mapped_column(Numeric(8, 1))
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    estado: Mapped[str] = mapped_column(String(20), default="pendiente", index=True)
    bloquea_unidad: Mapped[bool] = mapped_column(Boolean, default=False)  # crítico: la dejó fuera de servicio
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("ordenes_trabajo.id"), index=True)
    gestionado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    gestionado_en: Mapped[datetime | None] = mapped_column(DateTime)
    motivo_descarte: Mapped[str | None] = mapped_column(String(300))
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime)
    fotos: Mapped[list["StatusReportPhoto"]] = relationship(cascade="all, delete-orphan", lazy="selectin",
                                                            order_by="StatusReportPhoto.id")


class StatusReportPhoto(Base):
    """Foto del parte de estado (obligatoria). Cifrada fuera de la base de datos, como las de las OT."""
    __tablename__ = "partes_estado_fotos"
    id: Mapped[int] = mapped_column(primary_key=True)
    parte_id: Mapped[int] = mapped_column(ForeignKey("partes_estado.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(160))
    fichero: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(60))
    tamano: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    subido: Mapped[datetime] = mapped_column(DateTime, default=_now)


RESULTADOS_TECNICO = {"resuelta": "Resuelta", "pendiente_material": "Pendiente de material",
                      "otra_visita": "Requiere otra visita", "escalar": "Derivar a subcontrata", "otro": "Otro"}
# Pausa de la actuación (1.74): el técnico para el reloj sin terminar y puede empezar otra mientras tanto
MOTIVOS_PAUSA = {"secando": "Secando", "vaciando_termo": "Vaciando termo", "repuesto": "A la espera de repuesto",
                 "otro": "Otro"}
# OT que mantenimiento abre directamente para una subcontrata desde el parte diario: solo instalaciones y averías
# graves que no resuelve el personal propio. motivo → (texto del checklist, categoría de la OT, grupo)
MOTIVOS_SUBCONTRATA = {
    "lavadora": ("Lavadora", "electrodomesticos", "Electrodomésticos"),
    "secadora": ("Secadora", "electrodomesticos", "Electrodomésticos"),
    "frigorifico": ("Frigorífico / congelador", "electrodomesticos", "Electrodomésticos"),
    "lavavajillas": ("Lavavajillas", "electrodomesticos", "Electrodomésticos"),
    "horno": ("Horno", "electrodomesticos", "Electrodomésticos"),
    "placa": ("Placa / vitrocerámica / inducción", "electrodomesticos", "Electrodomésticos"),
    "microondas": ("Microondas", "electrodomesticos", "Electrodomésticos"),
    "campana": ("Campana extractora", "electrodomesticos", "Electrodomésticos"),
    "termo": ("Termo eléctrico: avería o cambio", "acs", "Agua caliente"),
    "caldera": ("Caldera / calentador de gas", "acs", "Agua caliente"),
    "aire": ("Aire acondicionado / bomba de calor", "climatizacion", "Climatización"),
    "calefaccion": ("Calefacción / radiadores", "climatizacion", "Climatización"),
    "electricidad": ("Cuadro eléctrico / sin suministro / cortocircuito", "electricidad", "Electricidad"),
    "fuga": ("Fuga o rotura de tubería, bajante o depósito", "fontaneria", "Fontanería"),
    "saneamiento": ("Atasco general de saneamiento / arqueta", "fontaneria", "Fontanería"),
    "grupo_presion": ("Grupo de presión / bombas", "fontaneria", "Fontanería"),
    "ascensor": ("Ascensor parado o averiado", "ascensores", "Instalaciones del edificio"),
    "pci": ("Protección contra incendios (alarma, extintores, BIE)", "pci", "Instalaciones del edificio"),
    "portero": ("Portero / videoportero / control de accesos", "telecom", "Instalaciones del edificio"),
    "antena": ("Antena / TV / telecomunicaciones", "telecom", "Instalaciones del edificio"),
    "puerta_garaje": ("Puerta de garaje / puerta automática", "cerrajeria", "Instalaciones del edificio"),
    "cerradura": ("Cerradura o puerta de acceso que no cierra", "cerrajeria", "Instalaciones del edificio"),
    "otra": ("Otra instalación o avería grave (indique cuál)", "general", "Otras"),
}
NOMBRE_RESULTADO = {**RESULTADOS_TECNICO, "pausa": "En pausa"}  # para mostrar intervenciones (incluida la pausa)


class WorkOrderVisit(Base):
    """Intervención del técnico (propio o subcontrata) registrada desde el enlace de la orden de trabajo:
    llegada y salida, trabajos, materiales, estado al finalizar y firma táctil (cifrada fuera de la base de datos)."""
    __tablename__ = "intervenciones_ot"
    id: Mapped[int] = mapped_column(primary_key=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("ordenes_trabajo.id"), index=True)
    empresa: Mapped[str | None] = mapped_column(String(160))
    tecnico: Mapped[str | None] = mapped_column(String(120))
    llegada: Mapped[datetime | None] = mapped_column(DateTime)
    salida: Mapped[datetime | None] = mapped_column(DateTime)
    trabajos: Mapped[str | None] = mapped_column(Text)
    materiales: Mapped[list | None] = mapped_column(JSON)  # [{material, cantidad}]
    observaciones: Mapped[str | None] = mapped_column(Text)
    resultado: Mapped[str | None] = mapped_column(String(20))  # RESULTADOS_TECNICO; None = en curso
    fecha_propuesta: Mapped[date | None] = mapped_column(Date)  # siguiente visita
    justificacion: Mapped[str | None] = mapped_column(Text)
    firma: Mapped[str | None] = mapped_column(String(64))  # fichero cifrado con la firma (PNG)
    enviado: Mapped[datetime | None] = mapped_column(DateTime)
    ip: Mapped[str | None] = mapped_column(String(45))
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)


TIPOS_DOC_EMPLEADO = {
    "contrato": "Contrato de trabajo", "nomina": "Nómina", "alta_ss": "Alta / baja en la Seguridad Social",
    "dni": "DNI / NIE", "prl": "Formación PRL", "epi": "Entrega de EPI", "reconocimiento": "Reconocimiento médico",
    "certificado": "Certificado / carné profesional", "otro": "Otro",
}


class StaffDocument(Base):
    """Documento de la ficha del empleado (contrato, nóminas, PRL, EPI, reconocimiento médico…), cifrado fuera de la
    base de datos. Con fecha de vencimiento se avisa antes de que caduque."""
    __tablename__ = "documentos_personal"
    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("personal_servicio.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))
    nombre: Mapped[str] = mapped_column(String(160))
    fecha: Mapped[date | None] = mapped_column(Date)
    vence: Mapped[date | None] = mapped_column(Date, index=True)
    notas: Mapped[str | None] = mapped_column(String(300))
    fichero: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(60))
    tamano: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    subido: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class TimeEntry(Base):
    """Registro de jornada (RD-ley 8/2019): entrada y salida de cada día. Las correcciones guardan el registro
    original, quién y por qué; se conservan 4 años."""
    __tablename__ = "fichajes"
    id: Mapped[int] = mapped_column(primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("personal_servicio.id"), index=True)
    entrada: Mapped[datetime] = mapped_column(DateTime, index=True)
    salida: Mapped[datetime | None] = mapped_column(DateTime)
    origen: Mapped[str] = mapped_column(String(12), default="pms")  # pms | enlace | manual
    lat: Mapped[float | None] = mapped_column(Numeric(9, 6))
    lon: Mapped[float | None] = mapped_column(Numeric(9, 6))
    lat_salida: Mapped[float | None] = mapped_column(Numeric(9, 6))
    lon_salida: Mapped[float | None] = mapped_column(Numeric(9, 6))
    original: Mapped[dict | None] = mapped_column(JSON)  # antes de corregirlo
    editado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    editado_en: Mapped[datetime | None] = mapped_column(DateTime)
    motivo: Mapped[str | None] = mapped_column(String(300))
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)


# --------------------------------------------------------------------------- CAPEX (inversiones y reformas)
ESTADOS_CAPEX = {
    "definicion": "En definición", "licitacion": "En licitación", "adjudicacion": "Comparativo y adjudicación",
    "pendiente_aprobacion": "Pendiente de aprobación (Dirección General)", "adjudicado": "Adjudicado",
    "en_ejecucion": "En ejecución", "cancelado": "Cancelado",
}
ETIQUETAS_DOC_CAPEX = {
    "plano": "Plano (PDF / CAD)", "foto_previa": "Fotografía del estado previo", "pliego": "Pliego de condiciones",
    "memoria": "Memoria / informe técnico", "licencia": "Licencia / declaración responsable", "otro": "Otro",
    # fase 2 (obra): no van a licitación
    "prl": "Documentación PRL del contratista", "contrato": "Contrato firmado", "acta": "Acta de obra",
}


class CapexProject(Base):
    """Proyecto de inversión (reforma, obra mayor) de un activo: mediciones y presupuesto base, documentación,
    licitación a contratistas, comparativo, adjudicación y aprobación de la Dirección General (por encima del umbral)."""
    __tablename__ = "capex_proyectos"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"))
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    titulo: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str | None] = mapped_column(Text)
    ubicacion: Mapped[str | None] = mapped_column(String(200))  # zona común, planta… si no es una unidad
    estado: Mapped[str] = mapped_column(String(24), default="definicion", index=True)
    presupuesto_objetivo: Mapped[float | None] = mapped_column(Numeric(12, 2))
    fecha_inicio: Mapped[date | None] = mapped_column(Date)
    fecha_fin: Mapped[date | None] = mapped_column(Date)
    # fase 2: acta de replanteo (inicio de obra). Exige contrato firmado y la documentación PRL de cada contrata
    replanteo_fecha: Mapped[date | None] = mapped_column(Date)
    replanteo_doc_id: Mapped[int | None] = mapped_column(Integer)  # capex_documentos.id (sin FK: referencia circular)
    replanteo_nota: Mapped[str | None] = mapped_column(String(500))
    gg_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=13)  # gastos generales
    bi_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=6)  # beneficio industrial
    iva_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=21)
    plantilla_id: Mapped[int | None] = mapped_column(ForeignKey("capex_plantillas.id"))
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CapexItem(Base):
    """Partida del presupuesto (mediciones): capítulo, código, descripción, unidad, cantidad y precio base."""
    __tablename__ = "capex_partidas"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("capex_proyectos.id"), index=True)
    capitulo: Mapped[str] = mapped_column(String(20))
    capitulo_nombre: Mapped[str] = mapped_column(String(200))
    codigo: Mapped[str | None] = mapped_column(String(40))
    descripcion: Mapped[str] = mapped_column(Text)
    unidad: Mapped[str | None] = mapped_column(String(20))
    cantidad: Mapped[float] = mapped_column(Numeric(14, 3), default=0)
    precio: Mapped[float] = mapped_column(Numeric(12, 2), default=0)  # precio unitario de ejecución material
    orden: Mapped[int] = mapped_column(Integer, default=0)
    origen: Mapped[str] = mapped_column(String(12), default="manual")  # manual | plantilla | base | bc3


class CapexTemplate(Base):
    """«CAPEX tipo» (reforma integral de baño, panelado de puertas…): capítulos y partidas estándar y documentos
    base (planos, pliegos) que se cargan con un clic en un proyecto nuevo."""
    __tablename__ = "capex_plantillas"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(160), unique=True)
    descripcion: Mapped[str | None] = mapped_column(Text)
    partidas: Mapped[list] = mapped_column(JSON, default=list)
    activa: Mapped[bool] = mapped_column(Boolean, default=True)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CapexDocument(Base):
    """Documento del proyecto o de la plantilla (planos, fotos del estado previo, pliegos, licencias), cifrado.
    Los marcados «licitacion» se adjuntan a la petición de ofertas."""
    __tablename__ = "capex_documentos"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("capex_proyectos.id"), index=True)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("capex_plantillas.id"), index=True)
    etiqueta: Mapped[str] = mapped_column(String(20))
    nombre: Mapped[str] = mapped_column(String(160))
    notas: Mapped[str | None] = mapped_column(String(300))
    licitacion: Mapped[bool] = mapped_column(Boolean, default=True)
    fichero: Mapped[str] = mapped_column(String(64))
    mime: Mapped[str] = mapped_column(String(100))
    tamano: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    subido: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class PriceBase(Base):
    """Base de precios de construcción importada de un fichero FIEBDC-3 (.bc3)."""
    __tablename__ = "capex_bases_precios"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(160))
    fichero: Mapped[str | None] = mapped_column(String(160))
    partidas: Mapped[int] = mapped_column(Integer, default=0)
    importado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class PriceItem(Base):
    __tablename__ = "capex_precios"
    id: Mapped[int] = mapped_column(primary_key=True)
    base_id: Mapped[int] = mapped_column(ForeignKey("capex_bases_precios.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(40), index=True)
    unidad: Mapped[str | None] = mapped_column(String(20))
    resumen: Mapped[str] = mapped_column(String(300))
    texto: Mapped[str | None] = mapped_column(Text)
    precio: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    capitulo: Mapped[str | None] = mapped_column(String(300))  # ruta de capítulos de la base


class TenderProcess(Base):
    """Petición de ofertas (licitación ciega: los contratistas no ven los precios base)."""
    __tablename__ = "capex_licitaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("capex_proyectos.id"), index=True)
    fecha_limite: Mapped[date] = mapped_column(Date)
    mensaje: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(12), default="abierta")  # abierta | cerrada
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class TenderInvite(Base):
    """Contratista invitado: enlace con clave propia que caduca con el plazo y registro de aperturas."""
    __tablename__ = "capex_invitaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("capex_licitaciones.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    email: Mapped[str | None] = mapped_column(String(160))
    clave: Mapped[str] = mapped_column(String(64))
    enviado: Mapped[datetime | None] = mapped_column(DateTime)
    envio_error: Mapped[str | None] = mapped_column(String(300))
    abierto_en: Mapped[datetime | None] = mapped_column(DateTime)
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime)
    aperturas: Mapped[int] = mapped_column(Integer, default=0)
    descargas: Mapped[int] = mapped_column(Integer, default=0)
    revocada: Mapped[bool] = mapped_column(Boolean, default=False)


class SupplierBid(Base):
    """Oferta de un contratista: precio unitario por partida ({id de partida: precio})."""
    __tablename__ = "capex_ofertas"
    id: Mapped[int] = mapped_column(primary_key=True)
    tender_id: Mapped[int] = mapped_column(ForeignKey("capex_licitaciones.id"), index=True)
    invite_id: Mapped[int] = mapped_column(ForeignKey("capex_invitaciones.id"), unique=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"), index=True)
    precios: Mapped[dict] = mapped_column(JSON, default=dict)
    notas: Mapped[str | None] = mapped_column(Text)
    plazo_dias: Mapped[int | None] = mapped_column(Integer)  # plazo de ejecución ofertado
    estado: Mapped[str] = mapped_column(String(12), default="borrador")  # borrador | enviada
    origen: Mapped[str] = mapped_column(String(12), default="portal")  # portal | excel | recibida
    enviada_en: Mapped[datetime | None] = mapped_column(DateTime)
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=_now)


class CapexAward(Base):
    """Adjudicación (obra completa o por capítulos a distintas contratas)."""
    __tablename__ = "capex_adjudicaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("capex_proyectos.id"), index=True)
    bid_id: Mapped[int] = mapped_column(ForeignKey("capex_ofertas.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("proveedores.id"))
    capitulos: Mapped[list] = mapped_column(JSON, default=list)
    pem: Mapped[float] = mapped_column(Numeric(12, 2))
    importe: Mapped[float] = mapped_column(Numeric(12, 2))  # PEM + GG + BI (sin IVA)
    estado: Mapped[str] = mapped_column(String(12), default="propuesta")  # propuesta | aprobada | rechazada | anulada
    nota: Mapped[str | None] = mapped_column(String(500))
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    creado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    # fase 2 (obra): condiciones del contrato y enlace del contratista para subir su documentación PRL
    retencion_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=5, server_default="5")
    garantia_meses: Mapped[int] = mapped_column(Integer, default=12, server_default="12")
    plazo_dias: Mapped[int | None] = mapped_column(Integer)  # días naturales desde el acta de replanteo
    contrato_firmado: Mapped[date | None] = mapped_column(Date)
    contrato_doc_id: Mapped[int | None] = mapped_column(ForeignKey("capex_documentos.id"))
    clave: Mapped[str | None] = mapped_column(String(64))  # enlace de obra (None = aún no enviado)
    enlace_enviado: Mapped[datetime | None] = mapped_column(DateTime)


TIPOS_PRL_CAPEX = {  # documentación PRL que cada contrata aporta antes del acta de replanteo: (nombre, caduca)
    "rc": ("Seguro de responsabilidad civil y justificante de pago", True),
    "hacienda": ("Certificado de estar al corriente con Hacienda", True),
    "seg_social": ("Certificado de estar al corriente con la Seguridad Social", True),
    "rnt": ("Alta de los trabajadores en la Seguridad Social (RNT / TC2)", True),
    "formacion": ("Formación PRL de los trabajadores (art. 19 Ley 31/1995)", False),
    "rea": ("Inscripción en el REA (Registro de Empresas Acreditadas, Ley 32/2006)", True),
    "plan_ss": ("Evaluación de riesgos / Plan de Seguridad y Salud (RD 1627/1997)", False),
    "recurso_preventivo": ("Designación del recurso preventivo", False),
}


class CapexPrl(Base):
    """Documento PRL de una contrata adjudicataria. estado: falta | por_revisar (subido por el contratista) | valido |
    rechazado | no_aplica. Válido y con fecha de caducidad pasada cuenta como vencido."""
    __tablename__ = "capex_prl"
    __table_args__ = (UniqueConstraint("award_id", "tipo", name="uq_capex_prl_tipo"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    award_id: Mapped[int] = mapped_column(ForeignKey("capex_adjudicaciones.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(24))
    estado: Mapped[str] = mapped_column(String(12), default="falta")
    document_id: Mapped[int | None] = mapped_column(ForeignKey("capex_documentos.id"))
    vence: Mapped[date | None] = mapped_column(Date)
    nota: Mapped[str | None] = mapped_column(String(300))
    subido_en: Mapped[datetime | None] = mapped_column(DateTime)
    subido_por: Mapped[str | None] = mapped_column(String(12))  # contratista | pms
    revisado_por: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    revisado_en: Mapped[datetime | None] = mapped_column(DateTime)


class CapexApproval(Base):
    """Aprobación de la Dirección General por correo (botones Aprobar / Rechazar, sin entrar en el PMS) o desde el
    PMS. Queda la marca de tiempo, la decisión, el comentario y desde dónde se decidió."""
    __tablename__ = "capex_aprobaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("capex_proyectos.id"), index=True)
    email: Mapped[str] = mapped_column(String(160))
    clave: Mapped[str] = mapped_column(String(64))
    importe: Mapped[float] = mapped_column(Numeric(12, 2))
    resumen: Mapped[dict] = mapped_column(JSON, default=dict)
    estado: Mapped[str] = mapped_column(String(12), default="pendiente")  # pendiente | aprobada | rechazada | anulada
    enviada_en: Mapped[datetime | None] = mapped_column(DateTime)
    envio_error: Mapped[str | None] = mapped_column(String(300))
    decidido_en: Mapped[datetime | None] = mapped_column(DateTime)
    comentario: Mapped[str | None] = mapped_column(String(1000))
    canal: Mapped[str | None] = mapped_column(String(12))  # correo | pms
    ip: Mapped[str | None] = mapped_column(String(60))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)


class VacationRevision(Base):
    """Revisión del calendario de vacaciones: cada cambio en una solicitud genera el informe y se envía a todos."""
    __tablename__ = "vacaciones_revisiones"
    id: Mapped[int] = mapped_column(primary_key=True)
    anio: Mapped[int] = mapped_column(Integer, index=True)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    cambios: Mapped[list] = mapped_column(JSON, default=list)
    enviados: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class VacationChange(Base):
    """Cambio en las vacaciones pendiente de comunicar: se agrupan y se envían juntos en la siguiente revisión del
    calendario (cada pocas horas, o al momento con «Enviar calendario ahora»)."""
    __tablename__ = "vacaciones_cambios"
    id: Mapped[int] = mapped_column(primary_key=True)
    anio: Mapped[int] = mapped_column(Integer, index=True)
    texto: Mapped[str] = mapped_column(String(300))
    staff_id: Mapped[int | None] = mapped_column(Integer)
    desde: Mapped[date | None] = mapped_column(Date)
    hasta: Mapped[date | None] = mapped_column(Date)
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    revision_id: Mapped[int | None] = mapped_column(ForeignKey("vacaciones_revisiones.id"), index=True)


# --------------------------------------------------------------------------- fianzas
FORMAS_DEVOLUCION = {"transferencia": "Transferencia bancaria", "efectivo": "Efectivo", "tarjeta": "Tarjeta bancaria",
                     "no_procede": "No procede (fianza retenida)"}


class DepositRefund(Base):
    """Devolución de la fianza de una reserva al hacer la salida. Recepción 1 o 2 indican la forma; si es por
    transferencia se avisa a la Dirección para hacerla. Entra en la exportación a INVERGESTION (gestoría)."""
    __tablename__ = "fianzas_devoluciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_id: Mapped[int] = mapped_column(ForeignKey("reservas.id"), unique=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("terceros.id"), index=True)
    titular: Mapped[str] = mapped_column(String(200))
    fianza: Mapped[float] = mapped_column(Numeric(10, 2))
    importe: Mapped[float] = mapped_column(Numeric(10, 2))  # lo que se devuelve
    retenido_motivo: Mapped[str | None] = mapped_column(Text)  # si se devuelve menos (roturas, daños…)
    forma: Mapped[str] = mapped_column(String(20))  # transferencia | efectivo | tarjeta | no_procede
    iban: Mapped[str | None] = mapped_column(String(40))
    fecha: Mapped[date] = mapped_column(Date)  # de la devolución (prevista si es transferencia)
    estado: Mapped[str] = mapped_column(String(20), default="pendiente")  # pendiente | devuelta
    devuelta_fecha: Mapped[date | None] = mapped_column(Date)
    nota: Mapped[str | None] = mapped_column(Text)
    creada: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))
    avisada: Mapped[datetime | None] = mapped_column(DateTime)  # correo a la Dirección
    exportada: Mapped[datetime | None] = mapped_column(DateTime)  # incluida en un envío a INVERGESTION
    # roturas y faltas descontadas con su precio de reposición: [{codigo, articulo, cantidad, precio, importe, ot_id}]
    cargos: Mapped[list | None] = mapped_column(JSON)
    factura_exceso: Mapped[str | None] = mapped_column(String(30))  # factura de lo que supera la fianza


# --------------------------------------------------------------------------- dotación
class DotacionHabitual(Base):
    """Dotación habitual de los apartamentos de una tipología en un activo (la rellena Recepción la primera vez).
    `items`: [{codigo, zona, articulo, cantidad}] tomados del catálogo 3 llaves (app/dotacion.py) o artículos propios."""
    __tablename__ = "dotacion_habitual"
    __table_args__ = (UniqueConstraint("asset_id", "tipologia"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    tipologia: Mapped[str] = mapped_column(String(60))
    perfil: Mapped[str] = mapped_column(String(10))  # estudio | 1d | 2d | vip
    items: Mapped[list] = mapped_column(JSON)
    actualizada: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class DotacionArticulo(Base):
    """Artículo nuevo creado con «Otra dotación»: queda en el catálogo del activo para no volver a escribirlo."""
    __tablename__ = "dotacion_articulos"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int | None] = mapped_column(ForeignKey("activos.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(12), unique=True)
    zona: Mapped[str] = mapped_column(String(20))
    articulo: Mapped[str] = mapped_column(String(160))
    creado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class DotacionUnidad(Base):
    """Dotación propia de un apartamento concreto (terraza, VIP…): manda sobre la habitual de su tipología."""
    __tablename__ = "dotacion_unidades"
    id: Mapped[int] = mapped_column(primary_key=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("unidades.id"), unique=True)
    items: Mapped[list] = mapped_column(JSON)
    actualizada: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


class DotacionPrecio(Base):
    """Precio de reposición de un artículo en un activo (IVA incluido): se descuenta de la fianza si se rompe o falta."""
    __tablename__ = "dotacion_precios"
    __table_args__ = (UniqueConstraint("asset_id", "codigo"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(12))
    precio: Mapped[float] = mapped_column(Numeric(10, 2))
    actualizado: Mapped[datetime] = mapped_column(DateTime, default=_now)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id"))


# --------------------------------------------------------------------------- caja
class CashClose(Base):
    """Cierre de caja de un turno de recepción: lo cobrado y devuelto por el recepcionista en el activo desde su
    cierre anterior, por forma de pago, y el efectivo contado. `movimientos`: [{hora, tipo, ref, forma, importe}]."""
    __tablename__ = "cierres_caja"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("usuarios.id"), index=True)
    desde: Mapped[datetime] = mapped_column(DateTime)
    hasta: Mapped[datetime] = mapped_column(DateTime, index=True)
    totales: Mapped[dict] = mapped_column(JSON)  # {forma: importe}
    movimientos: Mapped[list] = mapped_column(JSON)
    fondo: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    efectivo_esperado: Mapped[float] = mapped_column(Numeric(10, 2))
    efectivo_contado: Mapped[float] = mapped_column(Numeric(10, 2))
    diferencia: Mapped[float] = mapped_column(Numeric(10, 2))
    nota: Mapped[str | None] = mapped_column(Text)
