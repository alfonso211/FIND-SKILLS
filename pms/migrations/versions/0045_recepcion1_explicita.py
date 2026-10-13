"""Recepción 1 de cada activo asignada expresamente en la ficha del activo (antes se deducía del nombre del usuario,
y un cambio de nombre la convertía en Recepción 2). Se rellena con las cuentas de Recepción 1 del grupo.
Revisiones del calendario de vacaciones (informe que se envía a todos en cada cambio).

Revision ID: 0045
Revises: 0044
Create Date: 2026-10-14 09:00:00
"""
import re

from alembic import op
import sqlalchemy as sa


revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None

RECEPCION_1 = {"SFL": "juancarlos@apartamentossuitesflorida.es", "SAE": "jaime@apartamentossuitesaeropuerto.es"}


def upgrade() -> None:
    op.create_table(
        "vacaciones_revisiones",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("anio", sa.Integer(), nullable=False, index=True),
        sa.Column("creado", sa.DateTime(), nullable=False),
        sa.Column("cambios", sa.JSON(), nullable=False),
        sa.Column("enviados", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
    )
    with op.batch_alter_table("activos") as b:
        b.add_column(sa.Column("recepcion1_id", sa.Integer(), nullable=True))
        b.create_foreign_key("fk_activos_recepcion1", "usuarios", ["recepcion1_id"], ["id"])
    conn = op.get_bind()
    activos = sa.table("activos", sa.column("id", sa.Integer), sa.column("codigo", sa.String),
                       sa.column("recepcion1_id", sa.Integer))
    usuarios = sa.table("usuarios", sa.column("id", sa.Integer), sa.column("email", sa.String),
                        sa.column("nombre", sa.String), sa.column("activo", sa.Boolean))
    asign = sa.table("asignaciones", sa.column("user_id", sa.Integer), sa.column("asset_id", sa.Integer),
                     sa.column("role_id", sa.Integer))
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String))
    for aid, codigo in conn.execute(sa.select(activos.c.id, activos.c.codigo)).all():
        recep = conn.execute(sa.select(usuarios.c.id, usuarios.c.email, usuarios.c.nombre)
                             .join(asign, asign.c.user_id == usuarios.c.id).join(roles, roles.c.id == asign.c.role_id)
                             .where(asign.c.asset_id == aid, roles.c.nombre == "Recepción", usuarios.c.activo)).all()
        elegido = next((u for u in recep if (u.email or "").lower() == RECEPCION_1.get(codigo)), None) or \
            next((u for u in recep if re.match(r"recepci[oó]n\s*1\b", u.nombre or "", re.I)), None)
        if elegido:
            conn.execute(activos.update().where(activos.c.id == aid).values(recepcion1_id=elegido.id))


def downgrade() -> None:
    op.drop_table("vacaciones_revisiones")
    with op.batch_alter_table("activos") as b:
        b.drop_constraint("fk_activos_recepcion1", type_="foreignkey")
        b.drop_column("recepcion1_id")
