"""Esquemas de entrada (validación). Las respuestas se serializan con Base.to_dict()."""
from datetime import date

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Login(BaseModel):
    email: str
    password: str


# --------------------------------------------------------------------------- estructura
class CompanyIn(BaseModel):
    nombre: str
    cif: str | None = None
    direccion: str | None = None  # domicilio fiscal (sale en las facturas)
    cp: str | None = None
    municipio: str | None = None
    provincia: str | None = None
    parent_id: int | None = None
    activa: bool = True


class AssetIn(BaseModel):
    company_id: int  # sociedad gestora
    propietaria_id: int | None = None  # si se omite, la propia gestora
    codigo: str = Field(min_length=1, max_length=20)
    nombre: str
    modalidad: str
    direccion: str | None = None
    municipio: str | None = None
    provincia: str | None = None
    cp: str | None = None
    ref_catastral: str | None = None
    num_registro_turistico: str | None = None
    serie_factura: str | None = Field(default=None, pattern=r"^[A-Z0-9]{1,8}$")
    activo: bool = True
    contrato_representante: str | None = None
    contrato_representante_dni: str | None = None
    contrato_email: str | None = None
    notas: str | None = None


class AssetUpdate(BaseModel):
    company_id: int | None = None
    propietaria_id: int | None = None
    nombre: str | None = None
    direccion: str | None = None
    municipio: str | None = None
    provincia: str | None = None
    cp: str | None = None
    ref_catastral: str | None = None
    num_registro_turistico: str | None = None
    serie_factura: str | None = Field(default=None, pattern=r"^[A-Z0-9]{1,8}$")
    activo: bool | None = None
    contrato_representante: str | None = None
    contrato_representante_dni: str | None = None
    contrato_email: str | None = None
    notas: str | None = None


class UnitIn(BaseModel):
    asset_id: int
    codigo: str
    bloque: str | None = None
    uso: str = "vivienda"
    coef_participacion: float | None = None
    cuota_comunidad: float | None = None
    anejos: str | None = None
    tipologia: str | None = None
    planta: str | None = None
    superficie_m2: float | None = None
    dormitorios: int | None = None
    capacidad: int | None = None
    ref_catastral: str | None = None
    estado: str = "disponible"
    renta_base: float | None = None
    tarifa_base_noche: float | None = None
    notas: str | None = None


class UnitUpdate(BaseModel):
    codigo: str | None = None
    bloque: str | None = None
    uso: str | None = None
    coef_participacion: float | None = None
    cuota_comunidad: float | None = None
    anejos: str | None = None
    tipologia: str | None = None
    planta: str | None = None
    superficie_m2: float | None = None
    dormitorios: int | None = None
    capacidad: int | None = None
    ref_catastral: str | None = None
    estado: str | None = None
    renta_base: float | None = None
    tarifa_base_noche: float | None = None
    notas: str | None = None


class UnitBulk(BaseModel):
    asset_id: int
    prefijo: str = ""
    desde: int = Field(ge=0)
    hasta: int = Field(ge=0)
    digitos: int = Field(default=3, ge=1, le=6)
    bloque: str | None = None
    uso: str = "vivienda"
    tipologia: str | None = None
    capacidad: int | None = None
    tarifa_base_noche: float | None = None
    renta_base: float | None = None


# --------------------------------------------------------------------------- terceros
class ContactIn(BaseModel):
    company_id: int
    tipo: str  # inquilino | huesped | proveedor
    nombre: str
    apellidos: str | None = None
    documento_tipo: str | None = None
    documento_num: str | None = None
    nacionalidad: str | None = None
    fecha_nacimiento: date | None = None
    sexo: Literal["M", "F"] | None = None
    num_soporte: str | None = None
    fecha_caducidad_doc: date | None = None
    email: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    cp: str | None = None
    municipio: str | None = None
    pais: str | None = None
    iban: str | None = None
    notas: str | None = None
    documentos: list[int] = []  # copias escaneadas antes de dar de alta al cliente


class ContactInline(BaseModel):
    """Para crear el tercero al vuelo desde un contrato o reserva."""
    nombre: str
    apellidos: str | None = None
    documento_tipo: str | None = None
    documento_num: str | None = None
    nacionalidad: str | None = None
    fecha_nacimiento: date | None = None
    sexo: Literal["M", "F"] | None = None
    num_soporte: str | None = None
    fecha_caducidad_doc: date | None = None
    email: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    cp: str | None = None
    municipio: str | None = None
    pais: str | None = None


# --------------------------------------------------------------------------- alquiler
class LeaseIn(BaseModel):
    unit_id: int
    tenant_id: int | None = None
    tenant: ContactInline | None = None
    referencia: str | None = None
    fecha_inicio: date
    fecha_fin: date | None = None
    renta_mensual: float = Field(gt=0)
    fianza: float | None = None
    garantia_adicional: float | None = None
    dia_pago: int = Field(default=5, ge=1, le=28)
    indice_actualizacion: str = "IRAV"
    tipo_iva: float | None = Field(default=None, ge=0, le=21)  # vacío: vivienda exenta, resto 21 %
    estado: str = "vigente"
    notas: str | None = None
    documentos: list[int] = []  # copias del documento del cliente escaneadas en el alta


class LeaseUpdate(BaseModel):
    referencia: str | None = None
    fecha_fin: date | None = None
    fianza: float | None = None
    garantia_adicional: float | None = None
    dia_pago: int | None = Field(default=None, ge=1, le=28)
    indice_actualizacion: str | None = None
    tipo_iva: float | None = Field(default=None, ge=0, le=21)
    estado: str | None = None
    notas: str | None = None


class RentUpdate(BaseModel):
    porcentaje: float = Field(ge=-50, le=50)
    motivo: str | None = None


class ChargeGenerate(BaseModel):
    periodo: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    asset_id: int | None = None


class FacturarA(BaseModel):
    """Empresa u otra persona a la que se factura en lugar del cliente."""
    nombre: str = Field(min_length=2)
    nif: str = Field(min_length=5, max_length=20)
    domicilio: str = Field(min_length=5)


class ServiceLine(BaseModel):
    """Servicio a facturar: del catálogo (servicio_id) o escrito a mano. Precio unitario con IVA incluido."""
    servicio_id: int | None = None
    concepto: str | None = Field(default=None, max_length=200)
    cantidad: float = Field(default=1, gt=0)
    precio: float | None = Field(default=None, ge=0)
    tipo_iva: float | None = Field(default=None, ge=0, le=21)


class ServiceIn(BaseModel):
    asset_id: int | None = None  # vacío = para todos los activos
    nombre: str = Field(min_length=2, max_length=120)
    precio: float | None = Field(default=None, ge=0)
    tipo_iva: float = Field(default=21, ge=0, le=21)
    unidad: str = Field(default="ud", max_length=20)
    activo: bool = True


class ServiceInvoiceIn(BaseModel):
    """Factura solo de servicios (p.ej. plaza de aparcamiento a un cliente externo)."""
    asset_id: int
    reservation_id: int | None = None  # se factura al huésped de la reserva
    contact_id: int | None = None
    cliente: FacturarA | None = None
    lineas: list[ServiceLine] = Field(min_length=1)
    forma_pago: Literal["efectivo", "tarjeta", "transferencia", "domiciliacion", "bizum", "plataforma"] | None = None
    fecha_operacion: date | None = None


class Payment(BaseModel):
    """Cobro: al registrarlo se emite la factura. Puede incluir servicios (limpieza, aparcamiento...)."""
    importe: float = Field(default=0, ge=0)
    servicios: list[ServiceLine] = []
    fecha_pago: date | None = None
    forma_pago: Literal["efectivo", "tarjeta", "transferencia", "domiciliacion", "bizum", "plataforma"] | None = None
    facturar_a: FacturarA | None = None

    @field_validator("fecha_pago")
    @classmethod
    def _no_futura(cls, v):
        if v and v > date.today():
            raise ValueError("La fecha de cobro no puede ser futura")
        return v

    @model_validator(mode="after")
    def _algo(self):
        if not self.importe and not self.servicios:
            raise ValueError("Indique el importe cobrado o añada algún servicio")
        return self


class InvoiceRectify(BaseModel):
    motivo: str = Field(min_length=5)


# --------------------------------------------------------------------------- turístico
class ReservationIn(BaseModel):
    unit_id: int
    guest_id: int | None = None
    guest: ContactInline | None = None
    localizador: str | None = None
    canal: str = "directo"
    fecha_entrada: date
    fecha_salida: date
    adultos: int = Field(default=1, ge=1)
    ninos: int = Field(default=0, ge=0)
    importe_total: float = Field(default=0, ge=0)
    importe_pagado: float = Field(default=0, ge=0)  # si se indica, se registra el cobro y se factura
    forma_pago: Literal["efectivo", "tarjeta", "transferencia", "domiciliacion", "bizum", "plataforma"] | None = None
    notas: str | None = None
    documentos: list[int] = []  # copias del documento del cliente escaneadas en el alta

    @field_validator("fecha_salida")
    @classmethod
    def _salida_posterior(cls, v, info):
        ent = info.data.get("fecha_entrada")
        if ent and v <= ent:
            raise ValueError("La fecha de salida debe ser posterior a la de entrada")
        return v


class ReservationUpdate(BaseModel):
    unit_id: int | None = None
    localizador: str | None = None
    canal: str | None = None
    fecha_entrada: date | None = None
    fecha_salida: date | None = None
    adultos: int | None = None
    ninos: int | None = None
    importe_total: float | None = Field(default=None, ge=0)  # lo cobrado solo cambia con "Cobro" (factura)
    estado: str | None = None
    notas: str | None = None


class AccommodationContractIn(BaseModel):
    """Datos del contrato de alojamiento. Lo que se deje vacío se imprime con puntos para rellenar a mano."""
    fecha_firma: date
    localizador: str | None = None
    representante: str | None = None
    representante_dni: str | None = None
    email_empresa: str | None = None
    cliente_nombre: str | None = None
    cliente_nacionalidad: str | None = None
    cliente_documento: str | None = None
    cliente_domicilio: str | None = None
    cliente_cp: str | None = None
    cliente_municipio: str | None = None
    cliente_pais: str | None = None
    cliente_email: str | None = None
    cliente_movil: str | None = None
    capacidad: int | None = None
    dormitorios: int | None = None
    garaje_sotano: str | None = None
    garaje_plaza: str | None = None
    precio_total: float | None = Field(default=None, ge=0)
    fianza: float | None = Field(default=None, ge=0)
    tarjeta_titular: str | None = None
    # Nunca el número completo de la tarjeta: solo los 4 últimos dígitos
    tarjeta_terminacion: str | None = Field(default=None, pattern=r"^\d{4}$")
    tarjeta_caducidad: str | None = Field(default=None, pattern=r"^(0[1-9]|1[0-2])/\d{2}$")
    ocupantes: str | None = None
    sin_garaje: bool = False
    # Casillas ☐/☒ (se pueden marcar varias)
    motivo: list[Literal["turismo", "laboral", "medico", "estudios", "obras", "transito", "otro"]] = []
    motivo_otro: str | None = None
    acreditacion: list[Literal["empadronamiento", "dni", "alquiler", "suministro", "residencia_fiscal", "otro"]] = []
    acreditacion_otro: str | None = None
    actualizar_huesped: bool = True
    # Por defecto no se imprime si falta algo: el cliente solo debe firmar
    permitir_huecos: bool = False
    # Guardar los datos sin imprimir (p.ej. al hacer la reserva, para imprimir a la llegada)
    solo_guardar: bool = False

    @field_validator("motivo", "acreditacion", mode="before")
    @classmethod
    def _lista(cls, v):  # contratos guardados con una sola casilla
        if v in (None, ""):
            return []
        return [v] if isinstance(v, str) else v


# --------------------------------------------------------------------------- mantenimiento
class WorkOrderIn(BaseModel):
    asset_id: int
    unit_id: int | None = None
    zona: str | None = Field(default=None, max_length=40)  # zona común del plano (sin unidad)
    tipo: str = "correctivo"
    categoria: str = "general"
    prioridad: str = "media"
    titulo: str
    descripcion: str | None = None
    asignado_a: str | None = None
    proveedor: str | None = None
    coste_estimado: float | None = None
    bloquea_unidad: bool = False
    fecha_prevista: date | None = None


class WorkOrderUpdate(BaseModel):
    tipo: str | None = None
    categoria: str | None = None
    prioridad: str | None = None
    estado: str | None = None
    titulo: str | None = None
    descripcion: str | None = None
    asignado_a: str | None = None
    proveedor: str | None = None
    coste_estimado: float | None = None
    coste_real: float | None = None
    fecha_prevista: date | None = None
    solucion: str | None = None


class PlanIn(BaseModel):
    asset_id: int
    titulo: str
    categoria: str
    normativa: str | None = None
    periodicidad_dias: int = Field(ge=1)
    proxima_fecha: date
    proveedor: str | None = None
    activo: bool = True


class PlanUpdate(BaseModel):
    titulo: str | None = None
    categoria: str | None = None
    normativa: str | None = None
    periodicidad_dias: int | None = Field(default=None, ge=1)
    proxima_fecha: date | None = None
    proveedor: str | None = None
    activo: bool | None = None


# --------------------------------------------------------------------------- usuarios
class AssignmentIn(BaseModel):
    role_id: int
    company_id: int | None = None
    asset_id: int | None = None


class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    nombre: str
    password: str = Field(min_length=8)  # provisional: el usuario debe cambiarla al entrar
    is_superadmin: bool = False
    activo: bool = True
    asignaciones: list[AssignmentIn] = []


class UserUpdate(BaseModel):
    email: str | None = Field(default=None, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    nombre: str | None = None
    password: str | None = Field(default=None, min_length=8)  # restablece contraseña provisional
    is_superadmin: bool | None = None
    activo: bool | None = None
    asignaciones: list[AssignmentIn] | None = None


class RoleIn(BaseModel):
    nombre: str
    descripcion: str | None = None
    permisos: list[str] = []


class PasswordChange(BaseModel):
    actual: str
    nueva: str
