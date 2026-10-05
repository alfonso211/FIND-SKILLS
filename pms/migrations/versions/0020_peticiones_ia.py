"""Peticiones IA: permiso «ia.usar» para dirección y recepción en los roles existentes

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-05 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None

ROLES = ("Dirección Grupo", "Dirección Sociedad", "Recepción")


def upgrade() -> None:
    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String),
                     sa.column("permisos", sa.JSON))
    for rid, nombre, permisos in conn.execute(sa.select(roles.c.id, roles.c.nombre, roles.c.permisos)).all():
        if nombre in ROLES and "ia.usar" not in (permisos or []):
            conn.execute(roles.update().where(roles.c.id == rid).values(permisos=list(permisos or []) + ["ia.usar"]))


def downgrade() -> None:
    pass
