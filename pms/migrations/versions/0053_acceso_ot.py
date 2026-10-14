"""Acceso al apartamento con huésped en las órdenes de trabajo (llave de recepción autorizada o contactar).

Revision ID: 0053
Revises: 0052
Create Date: 2026-10-14 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0053'
down_revision = '0052'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ordenes_trabajo") as b:
        b.add_column(sa.Column("acceso", sa.String(12)))


def downgrade() -> None:
    with op.batch_alter_table("ordenes_trabajo") as b:
        b.drop_column("acceso")
