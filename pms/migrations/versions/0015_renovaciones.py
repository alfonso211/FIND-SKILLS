"""Renovación de estancias: cada renovación es una reserva nueva enlazada con la que renueva

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-05 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0015'
down_revision = '0014'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("reservas") as b:
        b.add_column(sa.Column("renueva_id", sa.Integer()))
        b.create_foreign_key("fk_reservas_renueva_id", "reservas", ["renueva_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("reservas") as b:
        b.drop_constraint("fk_reservas_renueva_id", type_="foreignkey")
        b.drop_column("renueva_id")
