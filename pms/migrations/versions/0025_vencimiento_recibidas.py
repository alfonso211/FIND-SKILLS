"""Vencimiento de las facturas recibidas (documentos recibidos y cuenta de gastos)

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-06 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0025'
down_revision = '0024'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('documentos_recibidos') as b:
        b.add_column(sa.Column('vencimiento', sa.Date()))
    with op.batch_alter_table('gastos') as b:
        b.add_column(sa.Column('vencimiento', sa.Date()))


def downgrade() -> None:
    with op.batch_alter_table('gastos') as b:
        b.drop_column('vencimiento')
    with op.batch_alter_table('documentos_recibidos') as b:
        b.drop_column('vencimiento')
