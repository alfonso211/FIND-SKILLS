"""Pedidos de material: catálogo de productos (intercambio con INVERGESTION), pedidos y sus líneas; permisos

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-08 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0035'
down_revision = '0034'
branch_labels = None
depends_on = None

PERMISOS_NUEVOS = {
    "Dirección Grupo": ["pedidos.crear", "pedidos.autorizar"],
    "Dirección Sociedad": ["pedidos.crear", "pedidos.autorizar"],
    "Recepción": ["pedidos.crear"],
    "Gobernanta / Limpieza": ["pedidos.crear"],
    "Técnico Mantenimiento": ["pedidos.crear"],
}


def upgrade() -> None:
    op.create_table(
        "productos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("referencia", sa.String(60), nullable=False, unique=True),
        sa.Column("articulo", sa.String(250), nullable=False),
        sa.Column("familia", sa.String(60), nullable=False),
        sa.Column("unidad", sa.String(20), nullable=False),
        sa.Column("precio", sa.Numeric(12, 4)),
        sa.Column("tipo_iva", sa.Numeric(5, 2), nullable=False),
        sa.Column("marca", sa.String(100)),
        sa.Column("ref_proveedor", sa.String(60)),
        sa.Column("proveedor", sa.String(200)),
        sa.Column("proveedor_nif", sa.String(20)),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("proveedores.id")),
        sa.Column("origen", sa.String(20), nullable=False),
        sa.Column("fecha_factura", sa.Date()),
        sa.Column("num_factura", sa.String(60)),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id")),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("alta_exportada", sa.DateTime()),
        sa.Column("creado", sa.DateTime(), nullable=False),
        sa.Column("actualizado", sa.DateTime()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
    )
    op.create_table(
        "pedidos",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("numero", sa.String(30), nullable=False, unique=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("activos.id"), nullable=False, index=True),
        sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("proveedores.id")),
        sa.Column("proveedor", sa.String(200)),
        sa.Column("estado", sa.String(20), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False, index=True),
        sa.Column("fecha_entrega", sa.Date()),
        sa.Column("notas", sa.Text()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("autorizado_por", sa.Integer(), sa.ForeignKey("usuarios.id")),
        sa.Column("autorizado_en", sa.DateTime()),
        sa.Column("motivo_rechazo", sa.String(300)),
        sa.Column("enviado_en", sa.DateTime()),
        sa.Column("recibido_en", sa.DateTime()),
        sa.Column("creado", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "pedido_lineas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("pedido_id", sa.Integer(), sa.ForeignKey("pedidos.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("productos.id"), nullable=False),
        sa.Column("orden", sa.Integer(), nullable=False),
        sa.Column("cantidad", sa.Numeric(12, 3), nullable=False),
        sa.Column("precio", sa.Numeric(12, 4)),
        sa.Column("tipo_iva", sa.Numeric(5, 2), nullable=False),
        sa.Column("nota", sa.String(200)),
        sa.Column("exportado", sa.DateTime()),
    )
    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String),
                     sa.column("permisos", sa.JSON))
    for rid, nombre, permisos in conn.execute(sa.select(roles.c.id, roles.c.nombre, roles.c.permisos)).all():
        nuevos = [p for p in PERMISOS_NUEVOS.get(nombre, []) if p not in (permisos or [])]
        if nuevos:
            conn.execute(roles.update().where(roles.c.id == rid).values(permisos=list(permisos or []) + nuevos))


def downgrade() -> None:
    op.drop_table("pedido_lineas")
    op.drop_table("pedidos")
    op.drop_table("productos")
