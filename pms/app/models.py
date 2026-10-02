"""Modelo de datos del PMS Grupo INVERSIETE.

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


def _now() -> datetime:
    return datetime.now()


# --------------------------------------------------------------------------- estructura
class Company(Base):
    __tablename__ = "sociedades"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(200), unique=True)
    cif: Mapped[str | None] = mapped_column(String(20))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("sociedades.id"))
    activa: Mapped[bool] = mapped_column(Boolean, default=True)


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
    ref_catastral: Mapped[str | None] = mapped_column(String(30))
    num_registro_turistico: Mapped[str | None] = mapped_column(String(60))
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
    asset: Mapped[Asset] = relationship()


# --------------------------------------------------------------------------- terceros
class Contact(Base):
    """Inquilino, huésped o proveedor. Datos compatibles con parte de viajeros (RD 933/2021)."""
    __tablename__ = "terceros"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("sociedades.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(20))  # inquilino | huesped | proveedor
    nombre: Mapped[str] = mapped_column(String(120))
    apellidos: Mapped[str | None] = mapped_column(String(160))
    documento_tipo: Mapped[str | None] = mapped_column(String(10))  # DNI | NIE | PAS | CIF
    documento_num: Mapped[str | None] = mapped_column(String(30))
    nacionalidad: Mapped[str | None] = mapped_column(String(60))
    fecha_nacimiento: Mapped[date | None] = mapped_column(Date)
    email: Mapped[str | None] = mapped_column(String(160))
    telefono: Mapped[str | None] = mapped_column(String(40))
    direccion: Mapped[str | None] = mapped_column(String(300))
    iban: Mapped[str | None] = mapped_column(String(40))
    notas: Mapped[str | None] = mapped_column(Text)


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
    notas: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[Unit] = relationship()
    tenant: Mapped[Contact] = relationship()


class Charge(Base):
    __tablename__ = "recibos"
    __table_args__ = (UniqueConstraint("lease_id", "periodo", "concepto"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lease_id: Mapped[int] = mapped_column(ForeignKey("contratos.id"), index=True)
    periodo: Mapped[str] = mapped_column(String(7))  # AAAA-MM
    concepto: Mapped[str] = mapped_column(String(60), default="Renta")
    importe: Mapped[float] = mapped_column(Numeric(10, 2))
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
    creada: Mapped[datetime] = mapped_column(DateTime, default=_now)
    unit: Mapped[Unit] = relationship()
    guest: Mapped[Contact] = relationship()


# --------------------------------------------------------------------------- mantenimiento
class WorkOrder(Base):
    __tablename__ = "ordenes_trabajo"
    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("activos.id"), index=True)
    unit_id: Mapped[int | None] = mapped_column(ForeignKey("unidades.id"))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey("planes_preventivos.id"))
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
