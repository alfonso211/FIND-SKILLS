"""Facturas emitidas pendientes de cobro (renovaciones y reservas que pagan por transferencia)

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-06 14:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0024'
down_revision = '0023'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('facturas') as b:
        b.add_column(sa.Column('cobro', sa.String(12), nullable=False, server_default='cobrada'))
        b.add_column(sa.Column('cobro_fecha', sa.Date()))
        b.add_column(sa.Column('cobro_forma', sa.String(30)))
        b.add_column(sa.Column('cobro_ref', sa.String(80)))
        b.add_column(sa.Column('cobro_user_id', sa.Integer(), sa.ForeignKey('usuarios.id',
                                                                             name='fk_facturas_cobro_user')))
        b.add_column(sa.Column('cobro_marcado', sa.DateTime()))
    op.create_index('ix_facturas_cobro', 'facturas', ['cobro'])


def downgrade() -> None:
    op.drop_index('ix_facturas_cobro', 'facturas')
    with op.batch_alter_table('facturas') as b:
        for c in ('cobro_marcado', 'cobro_user_id', 'cobro_ref', 'cobro_forma', 'cobro_fecha', 'cobro'):
            b.drop_column(c)
