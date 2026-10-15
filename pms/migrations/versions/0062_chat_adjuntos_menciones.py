"""Chat: fotos y PDF en los mensajes (cifrados fuera de la base de datos) y menciones con @nombre.

Revision ID: 0062
Revises: 0061
Create Date: 2026-10-15 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0062'
down_revision = '0061'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_mensajes", sa.Column("menciones", sa.JSON))
    op.create_table(
        "chat_adjuntos",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("mensaje_id", sa.Integer, sa.ForeignKey("chat_mensajes.id", ondelete="CASCADE", name="fk_chatadj_msg"),
                  nullable=False),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("mime", sa.String(80), nullable=False),
        sa.Column("tamano", sa.Integer, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("fichero", sa.String(80), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="SET NULL", name="fk_chatadj_user")),
        sa.Column("subido", sa.DateTime, nullable=False),
    )
    op.create_index("ix_chat_adjuntos_mensaje_id", "chat_adjuntos", ["mensaje_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_adjuntos_mensaje_id", "chat_adjuntos")
    op.drop_table("chat_adjuntos")
    with op.batch_alter_table("chat_mensajes") as b:
        b.drop_column("menciones")
