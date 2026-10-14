"""CAPEX fase 2 (obra): documentación PRL de cada contrata, contrato firmado, enlace de obra y acta de replanteo.

Revision ID: 0058
Revises: 0057
Create Date: 2026-10-14 19:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0058'
down_revision = '0057'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("capex_proyectos") as b:
        b.add_column(sa.Column("replanteo_fecha", sa.Date))
        b.add_column(sa.Column("replanteo_doc_id", sa.Integer))
        b.add_column(sa.Column("replanteo_nota", sa.String(500)))
    with op.batch_alter_table("capex_adjudicaciones") as b:
        b.add_column(sa.Column("retencion_pct", sa.Numeric(5, 2), nullable=False, server_default="5"))
        b.add_column(sa.Column("garantia_meses", sa.Integer, nullable=False, server_default="12"))
        b.add_column(sa.Column("plazo_dias", sa.Integer))
        b.add_column(sa.Column("contrato_firmado", sa.Date))
        b.add_column(sa.Column("contrato_doc_id", sa.Integer,
                               sa.ForeignKey("capex_documentos.id", name="fk_capex_adj_contrato_doc")))
        b.add_column(sa.Column("clave", sa.String(64)))
        b.add_column(sa.Column("enlace_enviado", sa.DateTime))
    op.create_table(
        "capex_prl",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("award_id", sa.Integer, sa.ForeignKey("capex_adjudicaciones.id"), nullable=False),
        sa.Column("tipo", sa.String(24), nullable=False),
        sa.Column("estado", sa.String(12), nullable=False),
        sa.Column("document_id", sa.Integer, sa.ForeignKey("capex_documentos.id")),
        sa.Column("vence", sa.Date),
        sa.Column("nota", sa.String(300)),
        sa.Column("subido_en", sa.DateTime),
        sa.Column("subido_por", sa.String(12)),
        sa.Column("revisado_por", sa.Integer, sa.ForeignKey("usuarios.id")),
        sa.Column("revisado_en", sa.DateTime),
        sa.UniqueConstraint("award_id", "tipo", name="uq_capex_prl_tipo"),
    )
    op.create_index("ix_capex_prl_award_id", "capex_prl", ["award_id"])


def downgrade() -> None:
    op.drop_index("ix_capex_prl_award_id", "capex_prl")
    op.drop_table("capex_prl")
    with op.batch_alter_table("capex_adjudicaciones") as b:
        for c in ("enlace_enviado", "clave", "contrato_doc_id", "contrato_firmado", "plazo_dias", "garantia_meses",
                  "retencion_pct"):
            b.drop_column(c)
    with op.batch_alter_table("capex_proyectos") as b:
        for c in ("replanteo_nota", "replanteo_doc_id", "replanteo_fecha"):
            b.drop_column(c)
