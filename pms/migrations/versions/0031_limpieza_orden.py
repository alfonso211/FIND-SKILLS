"""Parte de limpieza: orden y urgencia que fija recepción antes de imprimir o enviar

Revision ID: 0031
Revises: 0030
Create Date: 2026-10-07 22:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0031'
down_revision = '0030'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('limpiezas') as b:
        b.add_column(sa.Column('orden', sa.Integer()))
        b.add_column(sa.Column('urgente', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table('limpiezas') as b:
        b.drop_column('urgente')
        b.drop_column('orden')
