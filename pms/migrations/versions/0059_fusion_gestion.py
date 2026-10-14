"""Fusión con gestión (contrato «fusion1»): enlaces PMS ↔ gestión, avisos recibidos, documentos de la fusión, casilla
«Sincronizar facturas» por activo e IBAN y forma de pago del proveedor.

Revision ID: 0059
Revises: 0058
Create Date: 2026-10-14 21:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0059'
down_revision = '0058'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("activos") as b:
        b.add_column(sa.Column("sync_facturas", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("proveedores") as b:
        b.add_column(sa.Column("iban", sa.String(34)))
        b.add_column(sa.Column("forma_pago", sa.String(30)))
    op.create_table(
        "fusion_enlaces",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("pms_ref", sa.Integer, nullable=False),
        sa.Column("gestion_id", sa.String(120)),
        sa.Column("asset_id", sa.Integer),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("origen", sa.String(10), nullable=False),
        sa.Column("solicitud", sa.String(20)),
        sa.Column("solicitud_datos", sa.JSON),
        sa.Column("solicitud_fecha", sa.DateTime),
        sa.Column("actualizado", sa.DateTime, nullable=False),
        sa.UniqueConstraint("tipo", "pms_ref", name="uq_fusion_enlace"),
    )
    op.create_index("ix_fusion_enlaces_gestion_id", "fusion_enlaces", ["gestion_id"])
    op.create_table(
        "fusion_entradas",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("id_evento", sa.String(160), nullable=False, unique=True),
        sa.Column("tipo", sa.String(60), nullable=False),
        sa.Column("origen", sa.String(20)),
        sa.Column("id_evento_causa", sa.String(160)),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("cuerpo", sa.JSON),
        sa.Column("resultado", sa.JSON),
        sa.Column("recibido", sa.DateTime, nullable=False),
    )
    op.create_index("ix_fusion_entradas_tipo", "fusion_entradas", ["tipo"])
    op.create_index("ix_fusion_entradas_recibido", "fusion_entradas", ["recibido"])
    op.create_table(
        "fusion_documentos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("pms_ref", sa.Integer, nullable=False),
        sa.Column("origen", sa.String(10), nullable=False),
        sa.Column("categoria", sa.String(20), nullable=False),
        sa.Column("documento_id", sa.Integer, sa.ForeignKey("documentos_recibidos.id", ondelete="SET NULL",
                                                            name="fk_fusion_doc_documento")),
        sa.Column("fichero", sa.String(64)),
        sa.Column("doc_id_gestion", sa.String(120)),
        sa.Column("nombre", sa.String(200)),
        sa.Column("mime", sa.String(100)),
        sa.Column("tamano", sa.Integer),
        sa.Column("sha256", sa.String(64)),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("motivo", sa.String(300)),
        sa.Column("creado", sa.DateTime, nullable=False),
    )
    op.create_index("ix_fusion_documentos_pms_ref", "fusion_documentos", ["pms_ref"])
    op.create_index("ix_fusion_documentos_doc_id_gestion", "fusion_documentos", ["doc_id_gestion"])


def downgrade() -> None:
    op.drop_table("fusion_documentos")
    op.drop_table("fusion_entradas")
    op.drop_table("fusion_enlaces")
    with op.batch_alter_table("proveedores") as b:
        b.drop_column("forma_pago")
        b.drop_column("iban")
    with op.batch_alter_table("activos") as b:
        b.drop_column("sync_facturas")
