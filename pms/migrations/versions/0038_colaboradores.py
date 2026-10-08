"""Portal del colaborador (subcontratas): usuario y personal ligados a un proveedor, documentos subidos por el
colaborador con revisión, copia de los envíos al personal; rol «Colaborador»

Revision ID: 0038
Revises: 0037
Create Date: 2026-10-08 20:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0038'
down_revision = '0037'
branch_labels = None
depends_on = None

ROL = ("Colaborador", "Subcontrata: solo su portal (sus OT, partes y envíos; sube facturas y documentación)",
       ["colaborador.portal"])


def _norm(s: str | None) -> str:
    return "".join(ch for ch in (s or "").casefold() if ch.isalnum())  # «S.L.», «SL» y «s. l.» son iguales


def upgrade() -> None:
    with op.batch_alter_table("usuarios") as t:
        t.add_column(sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("proveedores.id", name="fk_usuarios_proveedor")))
        t.create_index("ix_usuarios_supplier_id", ["supplier_id"])
    with op.batch_alter_table("personal_servicio") as t:
        t.add_column(sa.Column("supplier_id", sa.Integer(),
                               sa.ForeignKey("proveedores.id", name="fk_personal_proveedor")))
        t.create_index("ix_personal_servicio_supplier_id", ["supplier_id"])
    with op.batch_alter_table("documentos_recibidos") as t:
        t.add_column(sa.Column("supplier_id", sa.Integer(), sa.ForeignKey("proveedores.id", name="fk_docrec_proveedor")))
        t.add_column(sa.Column("revision", sa.String(20)))
        t.add_column(sa.Column("revision_nota", sa.String(300)))
        t.add_column(sa.Column("revisado_por", sa.Integer(), sa.ForeignKey("usuarios.id", name="fk_docrec_revisor")))
        t.add_column(sa.Column("revisado_en", sa.DateTime()))
        t.add_column(sa.Column("staff_id", sa.Integer(), sa.ForeignKey("personal_servicio.id", name="fk_docrec_personal")))
        t.add_column(sa.Column("work_order_id", sa.Integer(), sa.ForeignKey("ordenes_trabajo.id", name="fk_docrec_ot")))
        t.create_index("ix_documentos_recibidos_supplier_id", ["supplier_id"])
    op.create_table(
        "envios_personal",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("staff_id", sa.Integer(), sa.ForeignKey("personal_servicio.id"), nullable=False, index=True),
        sa.Column("fecha", sa.DateTime(), nullable=False, index=True),
        sa.Column("tipo", sa.String(30), nullable=False),
        sa.Column("clave", sa.String(80)),
        sa.Column("canal", sa.String(12), nullable=False),
        sa.Column("asunto", sa.String(200), nullable=False),
        sa.Column("texto", sa.Text()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("usuarios.id")),
    )
    conn = op.get_bind()
    # el personal existente se enlaza con su empresa por el nombre (si está en Proveedores)
    prov = sa.table("proveedores", sa.column("id", sa.Integer), sa.column("nombre", sa.String))
    pers = sa.table("personal_servicio", sa.column("id", sa.Integer), sa.column("empresa", sa.String),
                    sa.column("supplier_id", sa.Integer))
    por_nombre: dict[str, int | None] = {}
    for pid, nombre in conn.execute(sa.select(prov.c.id, prov.c.nombre)).all():
        k = _norm(nombre)
        por_nombre[k] = None if k in por_nombre else pid  # nombre repetido: no se enlaza
    for sid, empresa in conn.execute(sa.select(pers.c.id, pers.c.empresa).where(pers.c.empresa.is_not(None))).all():
        pid = por_nombre.get(_norm(empresa))
        if pid:
            conn.execute(pers.update().where(pers.c.id == sid).values(supplier_id=pid))
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String),
                     sa.column("descripcion", sa.String), sa.column("permisos", sa.JSON))
    if conn.scalar(sa.select(sa.func.count()).select_from(roles)) and not conn.scalar(
            sa.select(roles.c.id).where(roles.c.nombre == ROL[0])):
        conn.execute(roles.insert().values(nombre=ROL[0], descripcion=ROL[1], permisos=ROL[2]))


def downgrade() -> None:
    op.drop_table("envios_personal")
    with op.batch_alter_table("documentos_recibidos") as t:
        for c in ("work_order_id", "staff_id", "revisado_en", "revisado_por", "revision_nota", "revision", "supplier_id"):
            t.drop_column(c)
    with op.batch_alter_table("personal_servicio") as t:
        t.drop_column("supplier_id")
    with op.batch_alter_table("usuarios") as t:
        t.drop_column("supplier_id")
