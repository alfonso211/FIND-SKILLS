"""Índices para las listas con muchas reservas y órdenes de trabajo (estado, cliente, localizador, apartamento, plan).

Revision ID: 0056
Revises: 0055
Create Date: 2026-10-14 18:00:00
"""
from alembic import op


revision = '0056'
down_revision = '0055'
branch_labels = None
depends_on = None

INDICES = [
    ("ix_reservas_estado", "reservas", "estado"),
    ("ix_reservas_guest_id", "reservas", "guest_id"),
    ("ix_reservas_localizador", "reservas", "localizador"),
    ("ix_ordenes_trabajo_estado", "ordenes_trabajo", "estado"),
    ("ix_ordenes_trabajo_unit_id", "ordenes_trabajo", "unit_id"),
    ("ix_ordenes_trabajo_plan_id", "ordenes_trabajo", "plan_id"),
]


def upgrade() -> None:
    for nombre, tabla, columna in INDICES:
        op.create_index(nombre, tabla, [columna])


def downgrade() -> None:
    for nombre, tabla, _ in INDICES:
        op.drop_index(nombre, table_name=tabla)
