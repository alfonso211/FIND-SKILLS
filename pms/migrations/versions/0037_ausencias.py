"""Ausencias del personal (vacaciones, días libres, bajas, permisos, faltas); rol «Dirección Técnica»

Revision ID: 0037
Revises: 0036
Create Date: 2026-10-08 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0037'
down_revision = '0036'
branch_labels = None
depends_on = None

PERMISOS_NUEVOS = {"Dirección Grupo": ["personal.autorizar"], "Dirección Sociedad": ["personal.autorizar"]}
ROL_TECNICO = ("Dirección Técnica", "Director técnico: autoriza las ausencias de mantenimiento (se suma a su otro rol)",
               ["activos.ver", "mantenimiento.ver", "personal.autorizar_mto"])
DIRECTOR_TECNICO = "alfonso@inversiete.es"


def upgrade() -> None:
    op.create_table(
        "ausencias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id"), index=True),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("personal_servicio.id"), index=True),
        sa.Column("persona", sa.String(160), nullable=False),
        sa.Column("colectivo", sa.String(20), nullable=False),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("desde", sa.Date(), nullable=False, index=True),
        sa.Column("hasta", sa.Date(), nullable=False, index=True),
        sa.Column("motivo", sa.Text()),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("visto_bueno_por", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("visto_bueno_en", sa.DateTime()),
        sa.Column("resuelto_por", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("resuelto_en", sa.DateTime()),
        sa.Column("nota", sa.Text()),
        sa.Column("creado_por", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("creado_en", sa.DateTime(), nullable=False),
    )
    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String),
                     sa.column("descripcion", sa.String), sa.column("permisos", sa.JSON))
    for rid, nombre, permisos in conn.execute(sa.select(roles.c.id, roles.c.nombre, roles.c.permisos)).all():
        nuevos = [p for p in PERMISOS_NUEVOS.get(nombre, []) if p not in (permisos or [])]
        if nuevos:
            conn.execute(roles.update().where(roles.c.id == rid).values(permisos=list(permisos or []) + nuevos))
    if not conn.scalar(sa.select(sa.func.count()).select_from(roles)):
        return  # instalación nueva: los roles y usuarios los crea el seed
    rid = conn.scalar(sa.select(roles.c.id).where(roles.c.nombre == ROL_TECNICO[0]))
    if rid is None:
        rid = conn.execute(roles.insert().values(nombre=ROL_TECNICO[0], descripcion=ROL_TECNICO[1],
                                                 permisos=ROL_TECNICO[2]).returning(roles.c.id)).scalar()
    # el director técnico (si ya existe su usuario) recibe el rol en todo el grupo
    usuarios = sa.table("usuarios", sa.column("id", sa.Integer), sa.column("email", sa.String))
    asig = sa.table("asignaciones", sa.column("user_id", sa.Integer), sa.column("role_id", sa.Integer),
                    sa.column("company_id", sa.Integer), sa.column("asset_id", sa.Integer))
    uid = conn.scalar(sa.select(usuarios.c.id).where(usuarios.c.email == DIRECTOR_TECNICO))
    if uid is not None and conn.scalar(sa.select(sa.func.count()).select_from(asig).where(
            asig.c.user_id == uid, asig.c.role_id == rid)) == 0:
        conn.execute(asig.insert().values(user_id=uid, role_id=rid, company_id=None, asset_id=None))


def downgrade() -> None:
    op.drop_table("ausencias")
