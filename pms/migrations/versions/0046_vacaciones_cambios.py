"""Cambios de vacaciones pendientes de comunicar: se agrupan en una sola revisión del calendario cada pocas horas
en lugar de enviar un correo a todos por cada cambio.

Revision ID: 0046
Revises: 0045
Create Date: 2026-10-14 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0046'
down_revision = '0045'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vacaciones_cambios",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("anio", sa.Integer(), nullable=False, index=True),
        sa.Column("texto", sa.String(300), nullable=False),
        sa.Column("staff_id", sa.Integer()),
        sa.Column("desde", sa.Date()),
        sa.Column("hasta", sa.Date()),
        sa.Column("creado", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("vacaciones_revisiones.id"), index=True),
    )


def downgrade() -> None:
    op.drop_table("vacaciones_cambios")
