"""Activos y unidades sincronizados con gestión (maestros, contrato «fusion1»): versión de los datos operativos de
cada unidad, fecha del último cambio, baja (sin borrar) y el JSON `catastro` que manda gestión (unidades y activos).
La casilla «Sincronizar activos y unidades con gestión» es el ajuste «maestros_sync» (sin fila = apagada).

Revision ID: 0064
Revises: 0063
Create Date: 2026-10-15 23:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0064'
down_revision = '0063'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("unidades", sa.Column("maestro_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("unidades", sa.Column("maestro_cambiado", sa.DateTime(), nullable=True))
    op.add_column("unidades", sa.Column("baja", sa.DateTime(), nullable=True))
    op.add_column("unidades", sa.Column("catastro", sa.JSON(), nullable=True))
    op.add_column("activos", sa.Column("catastro", sa.JSON(), nullable=True))
    # versión inicial 1 para todas: así la carga inicial lleva una versión válida y el primer cambio sube a 2
    op.execute("UPDATE unidades SET maestro_version = 1")


def downgrade() -> None:
    op.drop_column("activos", "catastro")
    op.drop_column("unidades", "catastro")
    op.drop_column("unidades", "baja")
    op.drop_column("unidades", "maestro_cambiado")
    op.drop_column("unidades", "maestro_version")
