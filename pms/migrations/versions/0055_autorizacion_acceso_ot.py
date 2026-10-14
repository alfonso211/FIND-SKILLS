"""Autorización del acceso con la llave de recepción en las OT: quién la da, cómo, quién la anota y para qué estancia.

Revision ID: 0055
Revises: 0054
Create Date: 2026-10-14 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0055'
down_revision = '0054'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ordenes_trabajo") as b:
        b.add_column(sa.Column("acceso_autoriza", sa.String(120)))
        b.add_column(sa.Column("acceso_medio", sa.String(20)))
        b.add_column(sa.Column("acceso_user_id", sa.Integer, sa.ForeignKey("usuarios.id", name="fk_ot_acceso_usuario")))
        b.add_column(sa.Column("acceso_fecha", sa.DateTime))
        b.add_column(sa.Column("acceso_reserva_id", sa.Integer, sa.ForeignKey("reservas.id", name="fk_ot_acceso_reserva")))


def downgrade() -> None:
    with op.batch_alter_table("ordenes_trabajo") as b:
        for c in ("acceso_reserva_id", "acceso_fecha", "acceso_user_id", "acceso_medio", "acceso_autoriza"):
            b.drop_column(c)
