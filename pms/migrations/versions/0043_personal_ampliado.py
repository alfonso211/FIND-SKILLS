"""Gestión del personal: ficha del empleado (datos laborales, vacaciones, usuario del PMS), documentos con
vencimiento y registro de jornada (fichajes).

Revision ID: 0043
Revises: 0042
Create Date: 2026-10-13 15:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0043'
down_revision = '0042'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("personal_servicio") as t:
        t.add_column(sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id", name="fk_personal_usuario")))
        t.add_column(sa.Column("dni", sa.String(20)))
        t.add_column(sa.Column("puesto", sa.String(120)))
        t.add_column(sa.Column("tipo_contrato", sa.String(20)))
        t.add_column(sa.Column("fecha_alta", sa.Date()))
        t.add_column(sa.Column("fecha_baja", sa.Date()))
        t.add_column(sa.Column("jornada_semanal", sa.Numeric(5, 2)))
        t.add_column(sa.Column("vacaciones_dias", sa.Integer()))
        t.add_column(sa.Column("vacaciones_tipo", sa.String(12)))
        t.add_column(sa.Column("fichaje_clave", sa.String(40)))
        t.create_index("ix_personal_servicio_user_id", ["user_id"])
    op.create_table(
        "documentos_personal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("personal_servicio.id"), nullable=False, index=True),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("fecha", sa.Date()),
        sa.Column("vence", sa.Date(), index=True),
        sa.Column("notas", sa.String(300)),
        sa.Column("fichero", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(60), nullable=False),
        sa.Column("tamano", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("subido", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
    )
    op.create_table(
        "fichajes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("personal_servicio.id"), nullable=False, index=True),
        sa.Column("entrada", sa.DateTime(), nullable=False, index=True),
        sa.Column("salida", sa.DateTime()),
        sa.Column("origen", sa.String(12), nullable=False),
        sa.Column("lat", sa.Numeric(9, 6)),
        sa.Column("lon", sa.Numeric(9, 6)),
        sa.Column("lat_salida", sa.Numeric(9, 6)),
        sa.Column("lon_salida", sa.Numeric(9, 6)),
        sa.Column("original", sa.JSON()),
        sa.Column("editado_por", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("editado_en", sa.DateTime()),
        sa.Column("motivo", sa.String(300)),
        sa.Column("creado", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fichajes")
    op.drop_table("documentos_personal")
    with op.batch_alter_table("personal_servicio") as t:
        t.drop_index("ix_personal_servicio_user_id")
        for c in ("fichaje_clave", "vacaciones_tipo", "vacaciones_dias", "jornada_semanal", "fecha_baja",
                  "fecha_alta", "tipo_contrato", "puesto", "dni", "user_id"):
            t.drop_column(c)
