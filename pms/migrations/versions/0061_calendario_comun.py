"""Calendario común PMS ↔ gestión (citas, tareas, mantenimiento, limpiezas y, solo para administración y dirección,
vencimientos y fiscal), enlace de Outlook por usuario e interruptores de la configuración.

Revision ID: 0061
Revises: 0060
Create Date: 2026-10-15 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0061'
down_revision = '0060'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ajustes",
        sa.Column("clave", sa.String(60), primary_key=True),
        sa.Column("valor", sa.JSON),
        sa.Column("cambiado", sa.DateTime, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="SET NULL", name="fk_ajustes_user")),
    )
    op.create_table(
        "calendario_comun",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("uid", sa.String(120), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("version_remota", sa.Integer, nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("subtipo", sa.String(40)),
        sa.Column("titulo", sa.String(300), nullable=False),
        sa.Column("descripcion", sa.Text),
        sa.Column("lugar", sa.String(300)),
        sa.Column("inicio", sa.DateTime, nullable=False),
        sa.Column("fin", sa.DateTime),
        sa.Column("todo_el_dia", sa.Boolean, nullable=False),
        sa.Column("activo", sa.String(40)),
        sa.Column("asset_id", sa.Integer, sa.ForeignKey("activos.id", ondelete="SET NULL", name="fk_calcom_asset")),
        sa.Column("unidad", sa.String(60)),
        sa.Column("sociedad", sa.String(10)),
        sa.Column("responsables", sa.JSON),
        sa.Column("invitados", sa.JSON),
        sa.Column("estado", sa.String(12), nullable=False),
        sa.Column("recordatorio", sa.Integer),
        sa.Column("repeticion", sa.String(12)),
        sa.Column("repetir_hasta", sa.Date),
        sa.Column("importe", sa.Numeric(14, 2)),
        sa.Column("prioridad", sa.String(20)),
        sa.Column("origen", sa.String(10), nullable=False),
        sa.Column("editable_en", sa.String(10), nullable=False),
        sa.Column("solo_lectura", sa.Boolean, nullable=False),
        sa.Column("roles", sa.JSON),
        sa.Column("url_gestion", sa.String(500)),
        sa.Column("datos", sa.JSON),
        sa.Column("agenda_id", sa.Integer, sa.ForeignKey("agenda.id", ondelete="SET NULL", name="fk_calcom_agenda")),
        sa.Column("limpieza_id", sa.Integer, sa.ForeignKey("limpiezas.id", ondelete="SET NULL", name="fk_calcom_limpieza")),
        sa.Column("ultimo_cambio", sa.String(10), nullable=False),
        sa.Column("cambio_local", sa.Boolean, nullable=False),
        sa.Column("historial", sa.JSON),
        sa.Column("actualizado", sa.DateTime, nullable=False),
        sa.UniqueConstraint("uid", name="uq_calcom_uid"),
    )
    for col in ("tipo", "inicio", "asset_id", "agenda_id", "limpieza_id", "actualizado"):
        op.create_index(f"ix_calendario_comun_{col}", "calendario_comun", [col])
    op.create_table(
        "calendario_enlaces",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("usuarios.id", ondelete="CASCADE", name="fk_calenl_user"),
                  nullable=False),
        sa.Column("clave_sha256", sa.String(64), nullable=False),
        sa.Column("mostrar_importes", sa.Boolean, nullable=False),
        sa.Column("creado", sa.DateTime, nullable=False),
        sa.Column("ultimo_acceso", sa.DateTime),
        sa.Column("ventana", sa.DateTime),
        sa.Column("peticiones", sa.Integer, nullable=False),
        sa.Column("avisado", sa.Boolean, nullable=False),
        sa.UniqueConstraint("user_id", name="uq_calenl_user"),
        sa.UniqueConstraint("clave_sha256", name="uq_calenl_clave"),
    )


def downgrade() -> None:
    op.drop_table("calendario_enlaces")
    for col in ("tipo", "inicio", "asset_id", "agenda_id", "limpieza_id", "actualizado"):
        op.drop_index(f"ix_calendario_comun_{col}", "calendario_comun")
    op.drop_table("calendario_comun")
    op.drop_table("ajustes")
