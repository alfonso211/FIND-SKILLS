"""Parte de trabajo diario de mantenimiento y limpieza: actuaciones anotadas y partes validados; permiso

Revision ID: 0036
Revises: 0035
Create Date: 2026-10-08 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0036'
down_revision = '0035'
branch_labels = None
depends_on = None

PERMISOS_NUEVOS = {"Dirección Grupo": ["partes.validar"], "Dirección Sociedad": ["partes.validar"],
                   "Recepción": ["partes.validar"]}


def upgrade() -> None:
    op.create_table(
        "parte_actuaciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False, index=True),
        sa.Column("area", sa.String(20), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False, index=True),
        sa.Column("descripcion", sa.Text(), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("unidades.id")),
        sa.Column("ubicacion", sa.String(160)),
        sa.Column("persona", sa.String(160)),
        sa.Column("horas", sa.Numeric(5, 2)),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("creada", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "partes_trabajo",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False, index=True),
        sa.Column("area", sa.String(20), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False, index=True),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("observaciones", sa.Text()),
        sa.Column("lineas", sa.JSON()),
        sa.Column("validado_por", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("validado_en", sa.DateTime()),
        sa.Column("pdf_id", sa.Integer(), sa.ForeignKey("documentos_recibidos.id")),
        sa.Column("xlsx_id", sa.Integer(), sa.ForeignKey("documentos_recibidos.id")),
        sa.UniqueConstraint("asset_id", "area", "fecha"),
    )
    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String),
                     sa.column("permisos", sa.JSON))
    for rid, nombre, permisos in conn.execute(sa.select(roles.c.id, roles.c.nombre, roles.c.permisos)).all():
        nuevos = [p for p in PERMISOS_NUEVOS.get(nombre, []) if p not in (permisos or [])]
        if nuevos:
            conn.execute(roles.update().where(roles.c.id == rid).values(permisos=list(permisos or []) + nuevos))


def downgrade() -> None:
    op.drop_table("partes_trabajo")
    op.drop_table("parte_actuaciones")
