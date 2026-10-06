"""Expediente de los contratos de vivienda (LAU): datos de sociedad, ficha e inventario de la vivienda,
expediente del contrato y carpeta documental

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-06 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('sociedades') as b:
        b.add_column(sa.Column('contratos', sa.JSON()))
    with op.batch_alter_table('unidades') as b:
        b.add_column(sa.Column('ficha', sa.JSON()))
        b.add_column(sa.Column('inventario', sa.JSON()))
    with op.batch_alter_table('contratos') as b:
        b.add_column(sa.Column('expediente', sa.JSON()))
    op.create_table(
        'contrato_documentos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('lease_id', sa.Integer(), sa.ForeignKey('contratos.id', ondelete='CASCADE'), nullable=False),
        sa.Column('clave', sa.String(30), nullable=False),
        sa.Column('nombre', sa.String(200), nullable=False),
        sa.Column('fichero', sa.String(80), nullable=False),
        sa.Column('mime', sa.String(80), nullable=False),
        sa.Column('tamano', sa.Integer(), nullable=False),
        sa.Column('sha256', sa.String(64), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('subido', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_contrato_documentos_lease_id', 'contrato_documentos', ['lease_id'])


def downgrade() -> None:
    op.drop_table('contrato_documentos')
    with op.batch_alter_table('contratos') as b:
        b.drop_column('expediente')
    with op.batch_alter_table('unidades') as b:
        b.drop_column('inventario')
        b.drop_column('ficha')
    with op.batch_alter_table('sociedades') as b:
        b.drop_column('contratos')
