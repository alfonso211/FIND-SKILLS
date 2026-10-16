"""1.75: plazas de garaje unidas al contrato de una vivienda (Babilonia): `contratos.plazas` con los id de las
unidades de garaje que van con el alquiler (quedan ocupadas con él, sin contrato aparte ni bloqueo).

Revision ID: 0066
Revises: 0065
Create Date: 2026-10-16 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0066'
down_revision = '0065'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contratos", sa.Column("plazas", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("contratos", "plazas")
