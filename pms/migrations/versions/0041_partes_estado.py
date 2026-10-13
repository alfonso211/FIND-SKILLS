"""Partes de estado (revisión de viviendas y zonas comunes por mantenimiento y limpieza). Mantenimiento y limpieza
dejan de abrir órdenes de trabajo: las genera recepción a partir del parte.

Revision ID: 0041
Revises: 0040
Create Date: 2026-10-13 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0041'
down_revision = '0040'
branch_labels = None
depends_on = None

CREAR = "partes_estado.crear"
CON_PARTE = ("Dirección Grupo", "Dirección Sociedad", "Recepción", "Gobernanta / Limpieza", "Técnico Mantenimiento")
SIN_ABRIR_OT = ("Gobernanta / Limpieza", "Técnico Mantenimiento")


def upgrade() -> None:
    op.create_table(
        "partes_estado",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False, index=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("unidades.id"), index=True),
        sa.Column("zona", sa.String(40)),
        sa.Column("tipologia", sa.String(2), nullable=False),
        sa.Column("estancia", sa.String(40), nullable=False),
        sa.Column("familia", sa.String(4), nullable=False),
        sa.Column("elemento", sa.String(40), nullable=False, index=True),
        sa.Column("clase", sa.String(4), nullable=False),
        sa.Column("deficiencia", sa.String(30), nullable=False),
        sa.Column("gravedad", sa.String(10), nullable=False),
        sa.Column("departamento", sa.String(20), nullable=False),
        sa.Column("prioridad", sa.String(10), nullable=False),
        sa.Column("alertas", sa.JSON()),
        sa.Column("observaciones", sa.Text()),
        sa.Column("lat", sa.Numeric(9, 6)),
        sa.Column("lon", sa.Numeric(9, 6)),
        sa.Column("precision_m", sa.Numeric(8, 1)),
        sa.Column("creado", sa.DateTime(), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("estado", sa.String(20), nullable=False, index=True),
        sa.Column("bloquea_unidad", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("ordenes_trabajo.id"), index=True),
        sa.Column("gestionado_por", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("gestionado_en", sa.DateTime()),
        sa.Column("motivo_descarte", sa.String(300)),
        sa.Column("resuelto_en", sa.DateTime()),
    )
    op.create_table(
        "partes_estado_fotos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("parte_id", sa.Integer(), sa.ForeignKey("partes_estado.id"), nullable=False, index=True),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("fichero", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(60), nullable=False),
        sa.Column("tamano", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("subido", sa.DateTime(), nullable=False),
    )
    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String), sa.column("permisos", sa.JSON))
    for rid, nombre, permisos in conn.execute(sa.select(roles.c.id, roles.c.nombre, roles.c.permisos)).all():
        nuevos = list(permisos or [])
        if nombre in CON_PARTE and CREAR not in nuevos:
            nuevos.append(CREAR)
        if nombre in SIN_ABRIR_OT:
            nuevos = [p for p in nuevos if p != "mantenimiento.abrir"]
        if nuevos != list(permisos or []):
            conn.execute(roles.update().where(roles.c.id == rid).values(permisos=nuevos))


def downgrade() -> None:
    op.drop_table("partes_estado_fotos")
    op.drop_table("partes_estado")
