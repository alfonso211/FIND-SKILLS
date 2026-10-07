"""Provincia y país en clientes, sociedades y activos; OPEX/CAPEX en la cuenta de gastos

Revision ID: 0027
Revises: 0026
Create Date: 2026-10-07 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0027'
down_revision = '0026'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('sociedades') as b:
        b.add_column(sa.Column('pais', sa.String(60)))
    with op.batch_alter_table('activos') as b:
        b.add_column(sa.Column('pais', sa.String(60)))
    with op.batch_alter_table('terceros') as b:
        b.add_column(sa.Column('provincia', sa.String(100)))
    with op.batch_alter_table('gastos') as b:
        b.add_column(sa.Column('naturaleza', sa.String(10)))
    # lo que ya existe es de España
    op.execute("UPDATE sociedades SET pais = 'España' WHERE pais IS NULL")
    op.execute("UPDATE activos SET pais = 'España' WHERE pais IS NULL")


def downgrade() -> None:
    with op.batch_alter_table('gastos') as b:
        b.drop_column('naturaleza')
    with op.batch_alter_table('terceros') as b:
        b.drop_column('provincia')
    with op.batch_alter_table('activos') as b:
        b.drop_column('pais')
    with op.batch_alter_table('sociedades') as b:
        b.drop_column('pais')
