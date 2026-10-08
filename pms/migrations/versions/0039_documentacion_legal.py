"""Documentación legal de los activos (checklist, documentos escaneados y vencimientos); permisos legal.*

Revision ID: 0039
Revises: 0038
Create Date: 2026-10-08 22:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0039'
down_revision = '0038'
branch_labels = None
depends_on = None

PERMISOS_NUEVOS = {"Dirección Grupo": ["legal.ver", "legal.editar"], "Dirección Sociedad": ["legal.ver", "legal.editar"],
                   "Gestor Alquiler Residencial": ["legal.ver", "legal.editar"], "Recepción": ["legal.ver", "legal.editar"]}


def upgrade() -> None:
    op.create_table(
        "documentacion_legal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False, index=True),
        sa.Column("clave", sa.String(40), nullable=False),
        sa.Column("titulo", sa.String(200)),
        sa.Column("no_aplica", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("motivo", sa.String(300)),
        sa.Column("fecha_documento", sa.Date()),
        sa.Column("vencimiento", sa.Date()),
        sa.Column("notas", sa.Text()),
        sa.Column("actualizado", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.UniqueConstraint("asset_id", "clave"),
    )
    op.create_table(
        "documentacion_legal_ficheros",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("documentacion_legal.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("fichero", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(100), nullable=False),
        sa.Column("tamano", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("subido", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
    )
    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String),
                     sa.column("permisos", sa.JSON))
    for rid, nombre, permisos in conn.execute(sa.select(roles.c.id, roles.c.nombre, roles.c.permisos)).all():
        nuevos = [p for p in PERMISOS_NUEVOS.get(nombre, []) if p not in (permisos or [])]
        if nuevos:
            conn.execute(roles.update().where(roles.c.id == rid).values(permisos=list(permisos or []) + nuevos))


def downgrade() -> None:
    op.drop_table("documentacion_legal_ficheros")
    op.drop_table("documentacion_legal")
