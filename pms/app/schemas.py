"""Esquemas de entrada (validación). Las respuestas se serializan con Base.to_dict()."""
from datetime import date

from pydantic import BaseModel, Field, field_validator


class Login(BaseModel):
    email: str
    password: str


# --------------------------------------------------------------------------- estructura
class CompanyIn(BaseModel):
    nombre: str
    cif: str | None = None
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
    activo: bool = True
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
    activo: bool | None = None
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
    email: str | None = None
    telefono: str | None = None
    direccion: str | None = None
    iban: str | None = None
    notas: str | None = None


class ContactInline(BaseModel):
    """Para crear el tercero al vuelo desde un contrato o reserva."""
    nombre: str
    apellidos: str | None = None
    documento_tipo: str | None = None
    documento_num: str | None = None
    nacionalidad: str | None = None
    fecha_nacimiento: date | None = None
    email: str | None = None
    telefono: str | None = None
    direccion: str | None = None


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
    estado: str = "vigente"
    notas: str | None = None


class LeaseUpdate(BaseModel):
    referencia: str | None = None
    fecha_fin: date | None = None
    fianza: float | None = None
    garantia_adicional: float | None = None
    dia_pago: int | None = Field(default=None, ge=1, le=28)
    indice_actualizacion: str | None = None
    estado: str | None = None
    notas: str | None = None


class RentUpdate(BaseModel):
    porcentaje: float = Field(ge=-50, le=50)
    motivo: str | None = None


class ChargeGenerate(BaseModel):
    periodo: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    asset_id: int | None = None


class Payment(BaseModel):
    importe: float = Field(gt=0)
    fecha_pago: date | None = None


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
    importe_pagado: float = Field(default=0, ge=0)
    notas: str | None = None

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
    importe_total: float | None = None
    importe_pagado: float | None = None
    estado: str | None = None
    notas: str | None = None


# --------------------------------------------------------------------------- mantenimiento
class WorkOrderIn(BaseModel):
    asset_id: int
    unit_id: int | None = None
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
    password: str = Field(min_length=10)
    is_superadmin: bool = False
    activo: bool = True
    asignaciones: list[AssignmentIn] = []


class UserUpdate(BaseModel):
    nombre: str | None = None
    password: str | None = Field(default=None, min_length=10)
    is_superadmin: bool | None = None
    activo: bool | None = None
    asignaciones: list[AssignmentIn] | None = None


class RoleIn(BaseModel):
    nombre: str
    descripcion: str | None = None
    permisos: list[str] = []


class PasswordChange(BaseModel):
    actual: str
    nueva: str = Field(min_length=10)
