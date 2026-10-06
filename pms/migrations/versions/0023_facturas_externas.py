"""Facturación del programa anterior (SYADE) para la producción

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-06 13:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'facturas_externas',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('activos.id'), nullable=False),
        sa.Column('origen', sa.String(20), nullable=False),
        sa.Column('tipo', sa.String(20), nullable=False),
        sa.Column('serie', sa.String(12), nullable=False),
        sa.Column('numero', sa.String(30), nullable=False),
        sa.Column('fecha', sa.Date(), nullable=False),
        sa.Column('localizador', sa.String(60)),
        sa.Column('nif', sa.String(30)),
        sa.Column('cliente', sa.String(200)),
        sa.Column('base', sa.Numeric(12, 2), nullable=False),
        sa.Column('tipo_iva', sa.Numeric(5, 2)),
        sa.Column('cuota', sa.Numeric(12, 2), nullable=False),
        sa.Column('total', sa.Numeric(12, 2), nullable=False),
        sa.Column('fianza', sa.Numeric(12, 2), nullable=False),
        sa.Column('detalle', sa.JSON()),
        sa.Column('reservation_id', sa.Integer(), sa.ForeignKey('reservas.id', ondelete='SET NULL')),
        sa.Column('importado', sa.DateTime(), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.UniqueConstraint('asset_id', 'tipo', 'serie', 'numero'),
    )
    op.create_index('ix_facturas_externas_asset_id', 'facturas_externas', ['asset_id'])
    op.create_index('ix_facturas_externas_fecha', 'facturas_externas', ['fecha'])
    op.create_index('ix_facturas_externas_localizador', 'facturas_externas', ['localizador'])


def downgrade() -> None:
    op.drop_table('facturas_externas')
