"""Alquiler mensual de plazas de garaje a clientes externos: matrícula, vehículo y mandos del contrato

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-05 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("contratos") as b:
        b.add_column(sa.Column("matricula", sa.String(20)))
        b.add_column(sa.Column("vehiculo", sa.String(80)))
        b.add_column(sa.Column("mandos", sa.String(80)))


def downgrade() -> None:
    with op.batch_alter_table("contratos") as b:
        for c in ("mandos", "vehiculo", "matricula"):
            b.drop_column(c)
