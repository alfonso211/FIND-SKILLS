"""Sesiones y enlaces revocables, cobro de la fianza, mensaje de la víspera, plazo de las OT, CAE de subcontratas y
cierres de caja.

Revision ID: 0051
Revises: 0050
Create Date: 2026-10-13 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0051'
down_revision = '0050'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("usuarios") as b:
        b.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    with op.batch_alter_table("ordenes_trabajo") as b:
        b.add_column(sa.Column("enlace_version", sa.Integer(), nullable=False, server_default="0"))
        b.add_column(sa.Column("plazo_avisado", sa.DateTime()))
        b.add_column(sa.Column("creada", sa.DateTime()))
    with op.batch_alter_table("proveedores") as b:
        b.add_column(sa.Column("cae_vence", sa.Date()))
        b.add_column(sa.Column("cae_nota", sa.String(300)))
    with op.batch_alter_table("reservas") as b:
        b.add_column(sa.Column("fianza_cobro", sa.JSON()))
        b.add_column(sa.Column("aviso_llegada", sa.DateTime()))
    op.create_table(
        "cierres_caja",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id", name="fk_cierres_caja_activo"), nullable=False,
                  index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id", name="fk_cierres_caja_usuario"), nullable=False,
                  index=True),
        sa.Column("desde", sa.DateTime(), nullable=False),
        sa.Column("hasta", sa.DateTime(), nullable=False, index=True),
        sa.Column("totales", sa.JSON(), nullable=False),
        sa.Column("movimientos", sa.JSON(), nullable=False),
        sa.Column("fondo", sa.Numeric(10, 2), nullable=False),
        sa.Column("efectivo_esperado", sa.Numeric(10, 2), nullable=False),
        sa.Column("efectivo_contado", sa.Numeric(10, 2), nullable=False),
        sa.Column("diferencia", sa.Numeric(10, 2), nullable=False),
        sa.Column("nota", sa.Text()),
    )


def downgrade() -> None:
    op.drop_table("cierres_caja")
    with op.batch_alter_table("reservas") as b:
        b.drop_column("aviso_llegada")
        b.drop_column("fianza_cobro")
    with op.batch_alter_table("proveedores") as b:
        b.drop_column("cae_nota")
        b.drop_column("cae_vence")
    with op.batch_alter_table("ordenes_trabajo") as b:
        b.drop_column("creada")
        b.drop_column("plazo_avisado")
        b.drop_column("enlace_version")
    with op.batch_alter_table("usuarios") as b:
        b.drop_column("token_version")
