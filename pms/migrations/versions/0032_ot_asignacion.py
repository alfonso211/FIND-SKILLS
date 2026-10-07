"""Órdenes de trabajo: asignadas a personal propio o a una subcontrata (proveedor)

Revision ID: 0032
Revises: 0031
Create Date: 2026-10-07 23:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0032'
down_revision = '0031'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('ordenes_trabajo') as b:
        b.add_column(sa.Column('asignacion', sa.String(20)))
        b.add_column(sa.Column('personal_id', sa.Integer(),
                               sa.ForeignKey('personal_servicio.id', name='fk_ot_personal')))
        b.add_column(sa.Column('proveedor_id', sa.Integer(), sa.ForeignKey('proveedores.id', name='fk_ot_proveedor')))


def downgrade() -> None:
    with op.batch_alter_table('ordenes_trabajo') as b:
        b.drop_column('proveedor_id')
        b.drop_column('personal_id')
        b.drop_column('asignacion')
