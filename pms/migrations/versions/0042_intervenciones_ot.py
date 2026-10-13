"""Órdenes de trabajo, fase 2: intervención del técnico desde su enlace (tiempos, trabajos, materiales, estado al
finalizar y firma), aviso a recepción y conformidad de la propiedad al cerrar.

Revision ID: 0042
Revises: 0041
Create Date: 2026-10-13 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0042'
down_revision = '0041'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "intervenciones_ot",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("ordenes_trabajo.id"), nullable=False, index=True),
        sa.Column("empresa", sa.String(160)),
        sa.Column("tecnico", sa.String(120)),
        sa.Column("llegada", sa.DateTime()),
        sa.Column("salida", sa.DateTime()),
        sa.Column("trabajos", sa.Text()),
        sa.Column("materiales", sa.JSON()),
        sa.Column("observaciones", sa.Text()),
        sa.Column("resultado", sa.String(20)),
        sa.Column("fecha_propuesta", sa.Date()),
        sa.Column("justificacion", sa.Text()),
        sa.Column("firma", sa.String(64)),
        sa.Column("enviado", sa.DateTime()),
        sa.Column("ip", sa.String(45)),
        sa.Column("creado", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("ordenes_trabajo") as t:
        t.add_column(sa.Column("alerta_tecnico", sa.String(20)))
        t.add_column(sa.Column("alerta_fecha", sa.DateTime()))
        t.add_column(sa.Column("conformidad_en", sa.DateTime()))


def downgrade() -> None:
    with op.batch_alter_table("ordenes_trabajo") as t:
        t.drop_column("conformidad_en")
        t.drop_column("alerta_fecha")
        t.drop_column("alerta_tecnico")
    op.drop_table("intervenciones_ot")
