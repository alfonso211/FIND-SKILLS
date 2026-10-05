"""Documentos recibidos (carpeta por activo) y cuenta de gastos; permisos nuevos en los roles existentes

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-05 19:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None

AMBOS = ["documentos.ver", "documentos.editar"]
PERMISOS_NUEVOS = {  # todos salvo limpieza y mantenimiento
    "Dirección Grupo": AMBOS, "Dirección Sociedad": AMBOS, "Gestor Alquiler Residencial": AMBOS,
    "Recepción": AMBOS, "Administración / Finanzas": AMBOS, "Consulta": ["documentos.ver"],
}


def upgrade() -> None:
    op.create_table(
        "documentos_recibidos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("unidades.id")),
        sa.Column("tipo", sa.String(20), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("emisor", sa.String(200)),
        sa.Column("referencia", sa.String(60)),
        sa.Column("descripcion", sa.Text()),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("fichero", sa.String(64), nullable=False),
        sa.Column("mime", sa.String(60), nullable=False),
        sa.Column("tamano", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("subido", sa.DateTime(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
    )
    op.create_index("ix_documentos_recibidos_asset_id", "documentos_recibidos", ["asset_id"])
    op.create_index("ix_documentos_recibidos_fecha", "documentos_recibidos", ["fecha"])
    op.create_table(
        "gastos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False),
        sa.Column("documento_id", sa.Integer(), sa.ForeignKey("documentos_recibidos.id")),
        sa.Column("ambito", sa.String(20), nullable=False),
        sa.Column("unit_id", sa.Integer(), sa.ForeignKey("unidades.id")),
        sa.Column("ambito_detalle", sa.String(200)),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("categoria", sa.String(30), nullable=False),
        sa.Column("concepto", sa.String(300), nullable=False),
        sa.Column("proveedor", sa.String(200)),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("proveedores.id")),
        sa.Column("numero_factura", sa.String(60)),
        sa.Column("base", sa.Numeric(12, 2), nullable=False),
        sa.Column("tipo_iva", sa.Numeric(5, 2), nullable=False),
        sa.Column("cuota", sa.Numeric(12, 2), nullable=False),
        sa.Column("total", sa.Numeric(12, 2), nullable=False),
        sa.Column("forma_pago", sa.String(30)),
        sa.Column("pagado", sa.Boolean(), nullable=False),
        sa.Column("fecha_pago", sa.Date()),
        sa.Column("notas", sa.Text()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("creado", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_gastos_asset_id", "gastos", ["asset_id"])
    op.create_index("ix_gastos_documento_id", "gastos", ["documento_id"])
    op.create_index("ix_gastos_fecha", "gastos", ["fecha"])
    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String),
                     sa.column("permisos", sa.JSON))
    for rid, nombre, permisos in conn.execute(sa.select(roles.c.id, roles.c.nombre, roles.c.permisos)).all():
        nuevos = [p for p in PERMISOS_NUEVOS.get(nombre, []) if p not in (permisos or [])]
        if nuevos:
            conn.execute(roles.update().where(roles.c.id == rid).values(permisos=list(permisos or []) + nuevos))


def downgrade() -> None:
    op.drop_table("gastos")
    op.drop_table("documentos_recibidos")
