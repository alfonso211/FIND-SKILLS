"""Servicios extra y limpieza contratada en la reserva; parte de limpieza (limpiezas pendientes y validadas)

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-07 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0030'
down_revision = '0029'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('reservas') as b:
        b.add_column(sa.Column('extras', sa.JSON()))
        b.add_column(sa.Column('limpieza', sa.JSON()))
    op.create_table(
        'limpiezas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('activos.id'), nullable=False, index=True),
        sa.Column('unit_id', sa.Integer(), sa.ForeignKey('unidades.id'), nullable=False, index=True),
        sa.Column('fecha', sa.Date(), nullable=False, index=True),
        sa.Column('tipo', sa.String(20), nullable=False),
        sa.Column('reservation_id', sa.Integer(), sa.ForeignKey('reservas.id'), index=True),
        sa.Column('clave', sa.String(60), unique=True),
        sa.Column('nota', sa.String(300)),
        sa.Column('estado', sa.String(20), nullable=False),
        sa.Column('creada', sa.DateTime(), nullable=False),
        sa.Column('creada_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('hecha', sa.DateTime()),
        sa.Column('validada_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
    )


def downgrade() -> None:
    op.drop_table('limpiezas')
    with op.batch_alter_table('reservas') as b:
        b.drop_column('limpieza')
        b.drop_column('extras')
