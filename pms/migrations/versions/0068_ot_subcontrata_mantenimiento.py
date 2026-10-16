"""1.78: mantenimiento abre desde el parte diario OT para subcontratas (instalaciones y averías graves): se guarda
el motivo del checklist en `ordenes_trabajo.motivo_subcontrata`.

Revision ID: 0068
Revises: 0067
Create Date: 2026-10-16 16:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0068'
down_revision = '0067'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ordenes_trabajo", sa.Column("motivo_subcontrata", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("ordenes_trabajo", "motivo_subcontrata")
