"""Justificante de pago de las facturas recibidas (obligatorio para marcarlas como pagadas)

Revision ID: 0040
Revises: 0039
Create Date: 2026-10-09 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0040'
down_revision = '0039'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("gastos") as t:
        t.add_column(sa.Column("justificante_id", sa.Integer(),
                               sa.ForeignKey("documentos_recibidos.id", name="fk_gastos_justificante")))


def downgrade() -> None:
    with op.batch_alter_table("gastos") as t:
        t.drop_column("justificante_id")
