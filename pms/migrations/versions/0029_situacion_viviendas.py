"""Situación de las viviendas (alquilada, vacía, en reforma…) y aviso del contrato pendiente

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-07 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0029'
down_revision = '0028'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('unidades') as b:
        b.add_column(sa.Column('situacion', sa.String(30)))
        b.add_column(sa.Column('situacion_texto', sa.String(200)))
        b.add_column(sa.Column('situacion_fecha', sa.DateTime()))
        b.add_column(sa.Column('situacion_user_id', sa.Integer(),
                               sa.ForeignKey('usuarios.id', name='fk_unidades_situacion_user')))
        b.add_column(sa.Column('contrato_pospuesto', sa.Date()))


def downgrade() -> None:
    with op.batch_alter_table('unidades') as b:
        b.drop_column('contrato_pospuesto')
        b.drop_column('situacion_user_id')
        b.drop_column('situacion_fecha')
        b.drop_column('situacion_texto')
        b.drop_column('situacion')
