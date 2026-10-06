"""Plazas de los apartamentos turísticos según tipología: estudio 2, 1 dormitorio 2, 2 dormitorios 3

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-06 08:00:00
"""
from alembic import op


revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None

PLAZAS = {0: 2, 1: 2, 2: 3}  # dormitorios → plazas (0 = estudio)


def upgrade() -> None:
    for dormitorios, plazas in PLAZAS.items():
        op.execute(f"UPDATE unidades SET capacidad = {plazas} WHERE uso = 'apartamento' AND dormitorios = {dormitorios}")


def downgrade() -> None:
    pass  # no se sabe qué capacidad tenía cada unidad antes
