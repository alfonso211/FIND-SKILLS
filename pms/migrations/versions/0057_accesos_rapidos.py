"""Accesos rápidos de la barra superior, elegidos por cada usuario.

Revision ID: 0057
Revises: 0056
Create Date: 2026-10-14 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0057'
down_revision = '0056'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("usuarios") as b:
        b.add_column(sa.Column("accesos", sa.JSON))


def downgrade() -> None:
    with op.batch_alter_table("usuarios") as b:
        b.drop_column("accesos")
