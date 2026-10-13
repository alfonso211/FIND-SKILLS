"""Dotación propia por apartamento, precios de reposición y cargos por roturas en la devolución de la fianza.

Revision ID: 0048
Revises: 0047
Create Date: 2026-10-13 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0048'
down_revision = '0047'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("fianzas_devoluciones") as b:
        b.add_column(sa.Column("cargos", sa.JSON()))
    op.create_table(
        "dotacion_unidades",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("unidades.id"), nullable=False, unique=True),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("actualizada", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
    )
    op.create_table(
        "dotacion_precios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False, index=True),
        sa.Column("codigo", sa.String(12), nullable=False),
        sa.Column("precio", sa.Numeric(10, 2), nullable=False),
        sa.Column("actualizado", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.UniqueConstraint("asset_id", "codigo"),
    )


def downgrade() -> None:
    op.drop_table("dotacion_precios")
    op.drop_table("dotacion_unidades")
    with op.batch_alter_table("fianzas_devoluciones") as b:
        b.drop_column("cargos")
