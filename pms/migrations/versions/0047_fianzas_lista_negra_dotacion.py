"""Devolución de fianzas al hacer la salida, lista negra de clientes y dotación de los apartamentos.

Revision ID: 0047
Revises: 0046
Create Date: 2026-10-13 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0047'
down_revision = '0046'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("terceros") as b:
        b.add_column(sa.Column("lista_negra", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("lista_negra_motivo", sa.Text()))
        b.add_column(sa.Column("lista_negra_fecha", sa.DateTime()))
        b.add_column(sa.Column("lista_negra_user_id", sa.Integer(),
                                sa.ForeignKey("usuarios.id", name="fk_terceros_lista_negra_user")))
    with op.batch_alter_table("reservas") as b:
        b.add_column(sa.Column("dotacion", sa.JSON()))
    op.create_table(
        "fianzas_devoluciones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reservation_id", sa.Integer(), sa.ForeignKey("reservas.id"), nullable=False, unique=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False, index=True),
        sa.Column("contact_id", sa.Integer(), sa.ForeignKey("terceros.id"), nullable=False, index=True),
        sa.Column("titular", sa.String(200), nullable=False),
        sa.Column("fianza", sa.Numeric(10, 2), nullable=False),
        sa.Column("importe", sa.Numeric(10, 2), nullable=False),
        sa.Column("retenido_motivo", sa.Text()),
        sa.Column("forma", sa.String(20), nullable=False),
        sa.Column("iban", sa.String(40)),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("devuelta_fecha", sa.Date()),
        sa.Column("nota", sa.Text()),
        sa.Column("creada", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("avisada", sa.DateTime()),
        sa.Column("exportada", sa.DateTime()),
    )
    op.create_table(
        "dotacion_habitual",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False, index=True),
        sa.Column("tipologia", sa.String(60), nullable=False),
        sa.Column("perfil", sa.String(10), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("actualizada", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.UniqueConstraint("asset_id", "tipologia"),
    )
    op.create_table(
        "dotacion_articulos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), index=True),
        sa.Column("codigo", sa.String(12), nullable=False, unique=True),
        sa.Column("zona", sa.String(20), nullable=False),
        sa.Column("articulo", sa.String(160), nullable=False),
        sa.Column("creado", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
    )


def downgrade() -> None:
    op.drop_table("dotacion_articulos")
    op.drop_table("dotacion_habitual")
    op.drop_table("fianzas_devoluciones")
    with op.batch_alter_table("reservas") as b:
        b.drop_column("dotacion")
    with op.batch_alter_table("terceros") as b:
        b.drop_constraint("fk_terceros_lista_negra_user", type_="foreignkey")
        for c in ("lista_negra_user_id", "lista_negra_fecha", "lista_negra_motivo", "lista_negra"):
            b.drop_column(c)
