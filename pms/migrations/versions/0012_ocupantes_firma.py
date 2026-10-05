"""Ocupantes de las reservas (parte de viajeros SES.HOSPEDAJE), código INE del municipio, código de
establecimiento SES y firma digital de los contratos de alojamiento

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-05 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("activos", sa.Column("ses_codigo_establecimiento", sa.String(20)))
    op.add_column("terceros", sa.Column("municipio_ine", sa.String(5)))
    op.add_column("reservas", sa.Column("ses_comunicado", sa.DateTime()))
    with op.batch_alter_table("contratos_alojamiento") as b:
        b.add_column(sa.Column("firmado", sa.DateTime()))
        b.add_column(sa.Column("fichero", sa.String(80)))
        b.add_column(sa.Column("sha256", sa.String(64)))
        b.add_column(sa.Column("evidencias", sa.JSON()))
        b.add_column(sa.Column("token_hash", sa.String(64)))
        b.add_column(sa.Column("token_expira", sa.DateTime()))
        b.add_column(sa.Column("envios", sa.JSON()))
    op.create_index("ix_contratos_alojamiento_token_hash", "contratos_alojamiento", ["token_hash"])
    op.create_table(
        "reserva_ocupantes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reservation_id", sa.Integer(), sa.ForeignKey("reservas.id"), nullable=False),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("terceros.id"), nullable=False),
        sa.Column("titular", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("parentesco", sa.String(2)),
        sa.Column("orden", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("reservation_id", "contact_id"),
    )
    op.create_index("ix_reserva_ocupantes_reservation_id", "reserva_ocupantes", ["reservation_id"])
    # el huésped de cada reserva existente pasa a ser su ocupante titular
    op.execute("INSERT INTO reserva_ocupantes (reservation_id, contact_id, titular, orden) "
               "SELECT id, guest_id, true, 0 FROM reservas")


def downgrade() -> None:
    op.drop_table("reserva_ocupantes")
    op.drop_index("ix_contratos_alojamiento_token_hash", "contratos_alojamiento")
    with op.batch_alter_table("contratos_alojamiento") as b:
        for c in ("envios", "token_expira", "token_hash", "evidencias", "sha256", "fichero", "firmado"):
            b.drop_column(c)
    op.drop_column("reservas", "ses_comunicado")
    op.drop_column("terceros", "municipio_ine")
    op.drop_column("activos", "ses_codigo_establecimiento")
