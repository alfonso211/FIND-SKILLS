"""Partes de trabajo editables: hora del trabajo en las actuaciones y correcciones de las líneas de OT y limpieza.

Revision ID: 0052
Revises: 0051
Create Date: 2026-10-14 08:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0052'
down_revision = '0051'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("parte_actuaciones") as b:
        b.add_column(sa.Column("hora", sa.Time()))
    with op.batch_alter_table("partes_trabajo") as b:
        b.add_column(sa.Column("correcciones", sa.JSON()))


def downgrade() -> None:
    with op.batch_alter_table("partes_trabajo") as b:
        b.drop_column("correcciones")
    with op.batch_alter_table("parte_actuaciones") as b:
        b.drop_column("hora")
