"""Fichas con el mismo nombre revisadas como personas distintas (ya no salen como repetidas)

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-08 08:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0033'
down_revision = '0032'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'terceros_distintos',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('a_id', sa.Integer(), sa.ForeignKey('terceros.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('b_id', sa.Integer(), sa.ForeignKey('terceros.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('fecha', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('a_id', 'b_id'),
    )


def downgrade() -> None:
    op.drop_table('terceros_distintos')
