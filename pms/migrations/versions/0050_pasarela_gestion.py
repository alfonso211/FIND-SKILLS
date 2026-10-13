"""Pasarela con INVERGESTION (fase 4): cola de avisos a gestión, origen de los bloqueos y comisión por canal.

Revision ID: 0050
Revises: 0049
Create Date: 2026-10-13 13:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0050'
down_revision = '0049'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gestion_cola",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("id_evento", sa.String(80), nullable=False, unique=True),
        sa.Column("tipo", sa.String(40), nullable=False, index=True),
        sa.Column("datos", sa.JSON(), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False, index=True),
        sa.Column("intentos", sa.Integer(), nullable=False),
        sa.Column("proximo", sa.DateTime(), nullable=False, index=True),
        sa.Column("creado", sa.DateTime(), nullable=False),
        sa.Column("enviado", sa.DateTime()),
        sa.Column("ultimo_error", sa.String(400)),
    )
    with op.batch_alter_table("bloqueos_unidad") as b:
        b.add_column(sa.Column("origen", sa.String(80)))
        b.create_index("ix_bloqueos_unidad_origen", ["origen"])
    with op.batch_alter_table("activos") as b:
        b.add_column(sa.Column("comisiones_canal", sa.JSON()))


def downgrade() -> None:
    with op.batch_alter_table("activos") as b:
        b.drop_column("comisiones_canal")
    with op.batch_alter_table("bloqueos_unidad") as b:
        b.drop_index("ix_bloqueos_unidad_origen")
        b.drop_column("origen")
    op.drop_table("gestion_cola")
