"""1.74: las OT que abren recepción y dirección no exigen la foto del «antes»; solo la exigen las que vienen de un
parte de estado (sus fotos se copian solas). Se libera a las OT ya abiertas sin parte de estado.

Revision ID: 0065
Revises: 0064
Create Date: 2026-10-16 10:00:00
"""
from alembic import op


revision = '0065'
down_revision = '0064'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE ordenes_trabajo SET exige_foto_antes = false WHERE exige_foto_antes = true AND id NOT IN "
               "(SELECT work_order_id FROM partes_estado WHERE work_order_id IS NOT NULL)")


def downgrade() -> None:
    pass  # no se puede saber qué OT la exigían: se quedan sin exigirla
