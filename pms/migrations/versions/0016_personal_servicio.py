"""Personal de mantenimiento y limpieza (correo y teléfono) y registro de envíos de las órdenes de trabajo

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-05 13:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_servicio",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=True),
        sa.Column("area", sa.String(20), nullable=False),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("empresa", sa.String(160)),
        sa.Column("email", sa.String(160)),
        sa.Column("telefono", sa.String(40)),
        sa.Column("avisar_urgentes", sa.Boolean(), nullable=False),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("notas", sa.Text()),
    )
    op.create_index("ix_personal_servicio_asset_id", "personal_servicio", ["asset_id"])
    with op.batch_alter_table("ordenes_trabajo") as b:
        b.add_column(sa.Column("envios", sa.JSON()))


def downgrade() -> None:
    with op.batch_alter_table("ordenes_trabajo") as b:
        b.drop_column("envios")
    op.drop_index("ix_personal_servicio_asset_id", "personal_servicio")
    op.drop_table("personal_servicio")
