"""Revisión de salida desde el móvil de limpieza y factura de las roturas que superan la fianza.

Revision ID: 0049
Revises: 0048
Create Date: 2026-10-13 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0049'
down_revision = '0048'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("reservas") as b:
        b.add_column(sa.Column("revision", sa.JSON()))
    with op.batch_alter_table("fianzas_devoluciones") as b:
        b.add_column(sa.Column("factura_exceso", sa.String(30)))


def downgrade() -> None:
    with op.batch_alter_table("fianzas_devoluciones") as b:
        b.drop_column("factura_exceso")
    with op.batch_alter_table("reservas") as b:
        b.drop_column("revision")
