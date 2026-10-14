"""Revisiones de los planes preventivos e inspecciones OCA: resultado, próxima fecha, puntos comprobados,
deficiencias con su OT y documentos de la empresa.

Revision ID: 0054
Revises: 0053
Create Date: 2026-10-14 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0054'
down_revision = '0053'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("planes_preventivos") as b:
        b.add_column(sa.Column("tipo", sa.String(16), nullable=False, server_default="mantenimiento"))
        b.add_column(sa.Column("proveedor_id", sa.Integer, sa.ForeignKey("proveedores.id", name="fk_plan_proveedor")))
        b.add_column(sa.Column("checklist", sa.JSON))
    # las inspecciones por organismo de control que ya estaban como planes
    op.execute("UPDATE planes_preventivos SET tipo = 'oca' WHERE titulo LIKE '%OCA%' OR titulo LIKE 'Inspección periódica%'")
    op.create_table(
        "revisiones_preventivo",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("plan_id", sa.Integer, sa.ForeignKey("planes_preventivos.id"), nullable=False, index=True),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("activos.id"), nullable=False, index=True),
        sa.Column("fecha", sa.Date, nullable=False),
        sa.Column("fecha_prevista", sa.Date),
        sa.Column("proxima", sa.Date),
        sa.Column("resultado", sa.String(24), nullable=False),
        sa.Column("empresa", sa.String(160)),
        sa.Column("proveedor_id", sa.Integer, sa.ForeignKey("proveedores.id")),
        sa.Column("tecnico", sa.String(120)),
        sa.Column("numero", sa.String(60)),
        sa.Column("plazo_subsanacion", sa.Date),
        sa.Column("checklist", sa.JSON),
        sa.Column("deficiencias", sa.JSON),
        sa.Column("observaciones", sa.Text),
        sa.Column("work_order_id", sa.Integer, sa.ForeignKey("ordenes_trabajo.id")),
        sa.Column("creada", sa.DateTime, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("usuarios.id")),
    )
    op.create_table(
        "adjuntos_revision",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("revision_id", sa.Integer, sa.ForeignKey("revisiones_preventivo.id"), nullable=False, index=True),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("fichero", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(60), nullable=False),
        sa.Column("tamano", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("subido", sa.DateTime, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("usuarios.id")),
    )


def downgrade() -> None:
    op.drop_table("adjuntos_revision")
    op.drop_table("revisiones_preventivo")
    with op.batch_alter_table("planes_preventivos") as b:
        b.drop_column("checklist")
        b.drop_column("proveedor_id")
        b.drop_column("tipo")
