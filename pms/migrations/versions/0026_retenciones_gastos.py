"""Facturas recibidas: retención de IRPF (u otra) y pago retenido con fecha de revisión

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-06 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0026'
down_revision = '0025'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('gastos') as b:
        b.add_column(sa.Column('retencion_tipo', sa.String(30)))
        b.add_column(sa.Column('retencion_pct', sa.Numeric(5, 2), nullable=False, server_default='0'))
        b.add_column(sa.Column('retencion', sa.Numeric(12, 2), nullable=False, server_default='0'))
        b.add_column(sa.Column('pago_retenido', sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column('pago_retenido_motivo', sa.String(300)))
        b.add_column(sa.Column('pago_retenido_revision', sa.Date()))
        b.add_column(sa.Column('pago_retenido_user_id', sa.Integer(),
                               sa.ForeignKey('usuarios.id', name='fk_gastos_pago_retenido_user')))
        b.add_column(sa.Column('pago_retenido_fecha', sa.DateTime()))


def downgrade() -> None:
    with op.batch_alter_table('gastos') as b:
        for c in ('pago_retenido_fecha', 'pago_retenido_user_id', 'pago_retenido_revision', 'pago_retenido_motivo',
                  'pago_retenido', 'retencion', 'retencion_pct', 'retencion_tipo'):
            b.drop_column(c)
