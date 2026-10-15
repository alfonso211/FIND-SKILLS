"""Avisos dentro del PMS (campana con sonido) y chat interno (todo el equipo, directos y grupos).

Revision ID: 0060
Revises: 0059
Create Date: 2026-10-15 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0060'
down_revision = '0059'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notificaciones",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="CASCADE", name="fk_notif_user"),
                  nullable=False),
        sa.Column("tipo", sa.String(40), nullable=False),
        sa.Column("titulo", sa.String(200), nullable=False),
        sa.Column("texto", sa.String(600)),
        sa.Column("vista", sa.String(40)),
        sa.Column("urgente", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("creada", sa.DateTime, nullable=False),
        sa.Column("leida", sa.DateTime),
    )
    op.create_index("ix_notificaciones_user_id", "notificaciones", ["user_id"])
    op.create_index("ix_notificaciones_creada", "notificaciones", ["creada"])
    op.create_table(
        "chat_conversaciones",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("tipo", sa.String(10), nullable=False),
        sa.Column("titulo", sa.String(120)),
        sa.Column("creador_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="SET NULL", name="fk_chatconv_creador")),
        sa.Column("creada", sa.DateTime, nullable=False),
        sa.Column("ultimo", sa.DateTime, nullable=False),
    )
    op.create_index("ix_chat_conversaciones_ultimo", "chat_conversaciones", ["ultimo"])
    op.create_table(
        "chat_miembros",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("conversacion_id", sa.Integer, sa.ForeignKey("chat_conversaciones.id", ondelete="CASCADE",
                                                               name="fk_chatmiem_conv"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="CASCADE", name="fk_chatmiem_user"),
                  nullable=False),
        sa.Column("activo", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("leido_hasta", sa.Integer, nullable=False, server_default="0"),
        sa.Column("anadido_por", sa.Integer),
        sa.Column("anadido", sa.DateTime, nullable=False),
        sa.UniqueConstraint("conversacion_id", "user_id", name="uq_chat_miembro"),
    )
    op.create_index("ix_chat_miembros_conversacion_id", "chat_miembros", ["conversacion_id"])
    op.create_index("ix_chat_miembros_user_id", "chat_miembros", ["user_id"])
    op.create_table(
        "chat_mensajes",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("conversacion_id", sa.Integer, sa.ForeignKey("chat_conversaciones.id", ondelete="CASCADE",
                                                               name="fk_chatmsg_conv"), nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="SET NULL", name="fk_chatmsg_user")),
        sa.Column("texto", sa.Text, nullable=False),
        sa.Column("sistema", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("creado", sa.DateTime, nullable=False),
        sa.Column("borrado", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_chat_mensajes_conversacion_id", "chat_mensajes", ["conversacion_id"])


def downgrade() -> None:
    op.drop_table("chat_mensajes")
    op.drop_table("chat_miembros")
    op.drop_table("chat_conversaciones")
    op.drop_table("notificaciones")
