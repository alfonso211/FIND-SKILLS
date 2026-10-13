"""CAPEX: proyectos de inversión y reforma (mediciones y presupuesto base), plantillas «CAPEX tipo», base de precios
FIEBDC-3, documentos, licitación ciega a contratistas, ofertas, adjudicación y aprobación de la Dirección General.

Revision ID: 0044
Revises: 0043
Create Date: 2026-10-13 18:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0044'
down_revision = '0043'
branch_labels = None
depends_on = None

PERMISOS = {"Dirección Grupo": ("capex.ver", "capex.gestionar"), "Dirección Sociedad": ("capex.ver",)}


def upgrade() -> None:
    op.create_table('capex_bases_precios',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nombre', sa.String(length=160), nullable=False),
    sa.Column('fichero', sa.String(length=160), nullable=True),
    sa.Column('partidas', sa.Integer(), nullable=False),
    sa.Column('importado', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('capex_plantillas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nombre', sa.String(length=160), nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=True),
    sa.Column('partidas', sa.JSON(), nullable=False),
    sa.Column('activa', sa.Boolean(), nullable=False),
    sa.Column('creado_por', sa.Integer(), nullable=True),
    sa.Column('creado', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['creado_por'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('nombre')
    )
    op.create_table('capex_precios',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('base_id', sa.Integer(), nullable=False),
    sa.Column('codigo', sa.String(length=40), nullable=False),
    sa.Column('unidad', sa.String(length=20), nullable=True),
    sa.Column('resumen', sa.String(length=300), nullable=False),
    sa.Column('texto', sa.Text(), nullable=True),
    sa.Column('precio', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('capitulo', sa.String(length=300), nullable=True),
    sa.ForeignKeyConstraint(['base_id'], ['capex_bases_precios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('capex_precios', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_capex_precios_base_id'), ['base_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_capex_precios_codigo'), ['codigo'], unique=False)

    op.create_table('capex_proyectos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('asset_id', sa.Integer(), nullable=False),
    sa.Column('unit_id', sa.Integer(), nullable=True),
    sa.Column('codigo', sa.String(length=20), nullable=False),
    sa.Column('titulo', sa.String(length=200), nullable=False),
    sa.Column('descripcion', sa.Text(), nullable=True),
    sa.Column('ubicacion', sa.String(length=200), nullable=True),
    sa.Column('estado', sa.String(length=24), nullable=False),
    sa.Column('presupuesto_objetivo', sa.Numeric(precision=12, scale=2), nullable=True),
    sa.Column('fecha_inicio', sa.Date(), nullable=True),
    sa.Column('fecha_fin', sa.Date(), nullable=True),
    sa.Column('gg_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('bi_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('iva_pct', sa.Numeric(precision=5, scale=2), nullable=False),
    sa.Column('plantilla_id', sa.Integer(), nullable=True),
    sa.Column('creado_por', sa.Integer(), nullable=True),
    sa.Column('creado', sa.DateTime(), nullable=False),
    sa.Column('actualizado', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['asset_id'], ['activos.id'], ),
    sa.ForeignKeyConstraint(['creado_por'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['plantilla_id'], ['capex_plantillas.id'], ),
    sa.ForeignKeyConstraint(['unit_id'], ['unidades.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('codigo')
    )
    with op.batch_alter_table('capex_proyectos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_capex_proyectos_asset_id'), ['asset_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_capex_proyectos_estado'), ['estado'], unique=False)

    op.create_table('capex_aprobaciones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=160), nullable=False),
    sa.Column('clave', sa.String(length=64), nullable=False),
    sa.Column('importe', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('resumen', sa.JSON(), nullable=False),
    sa.Column('estado', sa.String(length=12), nullable=False),
    sa.Column('enviada_en', sa.DateTime(), nullable=True),
    sa.Column('envio_error', sa.String(length=300), nullable=True),
    sa.Column('decidido_en', sa.DateTime(), nullable=True),
    sa.Column('comentario', sa.String(length=1000), nullable=True),
    sa.Column('canal', sa.String(length=12), nullable=True),
    sa.Column('ip', sa.String(length=60), nullable=True),
    sa.Column('user_agent', sa.String(length=300), nullable=True),
    sa.Column('creado', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['capex_proyectos.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('capex_aprobaciones', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_capex_aprobaciones_project_id'), ['project_id'], unique=False)

    op.create_table('capex_documentos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=True),
    sa.Column('template_id', sa.Integer(), nullable=True),
    sa.Column('etiqueta', sa.String(length=20), nullable=False),
    sa.Column('nombre', sa.String(length=160), nullable=False),
    sa.Column('notas', sa.String(length=300), nullable=True),
    sa.Column('licitacion', sa.Boolean(), nullable=False),
    sa.Column('fichero', sa.String(length=64), nullable=False),
    sa.Column('mime', sa.String(length=100), nullable=False),
    sa.Column('tamano', sa.Integer(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('subido', sa.DateTime(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['capex_proyectos.id'], ),
    sa.ForeignKeyConstraint(['template_id'], ['capex_plantillas.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['usuarios.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('capex_documentos', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_capex_documentos_project_id'), ['project_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_capex_documentos_template_id'), ['template_id'], unique=False)

    op.create_table('capex_licitaciones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('fecha_limite', sa.Date(), nullable=False),
    sa.Column('mensaje', sa.Text(), nullable=True),
    sa.Column('estado', sa.String(length=12), nullable=False),
    sa.Column('creado', sa.DateTime(), nullable=False),
    sa.Column('creado_por', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['creado_por'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['capex_proyectos.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('capex_licitaciones', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_capex_licitaciones_project_id'), ['project_id'], unique=False)

    op.create_table('capex_partidas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('capitulo', sa.String(length=20), nullable=False),
    sa.Column('capitulo_nombre', sa.String(length=200), nullable=False),
    sa.Column('codigo', sa.String(length=40), nullable=True),
    sa.Column('descripcion', sa.Text(), nullable=False),
    sa.Column('unidad', sa.String(length=20), nullable=True),
    sa.Column('cantidad', sa.Numeric(precision=14, scale=3), nullable=False),
    sa.Column('precio', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('orden', sa.Integer(), nullable=False),
    sa.Column('origen', sa.String(length=12), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['capex_proyectos.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('capex_partidas', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_capex_partidas_project_id'), ['project_id'], unique=False)

    op.create_table('capex_invitaciones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tender_id', sa.Integer(), nullable=False),
    sa.Column('supplier_id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=160), nullable=True),
    sa.Column('clave', sa.String(length=64), nullable=False),
    sa.Column('enviado', sa.DateTime(), nullable=True),
    sa.Column('envio_error', sa.String(length=300), nullable=True),
    sa.Column('abierto_en', sa.DateTime(), nullable=True),
    sa.Column('ultimo_acceso', sa.DateTime(), nullable=True),
    sa.Column('aperturas', sa.Integer(), nullable=False),
    sa.Column('descargas', sa.Integer(), nullable=False),
    sa.Column('revocada', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['supplier_id'], ['proveedores.id'], ),
    sa.ForeignKeyConstraint(['tender_id'], ['capex_licitaciones.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('capex_invitaciones', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_capex_invitaciones_supplier_id'), ['supplier_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_capex_invitaciones_tender_id'), ['tender_id'], unique=False)

    op.create_table('capex_ofertas',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tender_id', sa.Integer(), nullable=False),
    sa.Column('invite_id', sa.Integer(), nullable=False),
    sa.Column('supplier_id', sa.Integer(), nullable=False),
    sa.Column('precios', sa.JSON(), nullable=False),
    sa.Column('notas', sa.Text(), nullable=True),
    sa.Column('plazo_dias', sa.Integer(), nullable=True),
    sa.Column('estado', sa.String(length=12), nullable=False),
    sa.Column('origen', sa.String(length=12), nullable=False),
    sa.Column('enviada_en', sa.DateTime(), nullable=True),
    sa.Column('actualizado', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['invite_id'], ['capex_invitaciones.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['proveedores.id'], ),
    sa.ForeignKeyConstraint(['tender_id'], ['capex_licitaciones.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('invite_id')
    )
    with op.batch_alter_table('capex_ofertas', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_capex_ofertas_supplier_id'), ['supplier_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_capex_ofertas_tender_id'), ['tender_id'], unique=False)

    op.create_table('capex_adjudicaciones',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('bid_id', sa.Integer(), nullable=False),
    sa.Column('supplier_id', sa.Integer(), nullable=False),
    sa.Column('capitulos', sa.JSON(), nullable=False),
    sa.Column('pem', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('importe', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('estado', sa.String(length=12), nullable=False),
    sa.Column('nota', sa.String(length=500), nullable=True),
    sa.Column('creado', sa.DateTime(), nullable=False),
    sa.Column('creado_por', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['bid_id'], ['capex_ofertas.id'], ),
    sa.ForeignKeyConstraint(['creado_por'], ['usuarios.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['capex_proyectos.id'], ),
    sa.ForeignKeyConstraint(['supplier_id'], ['proveedores.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('capex_adjudicaciones', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_capex_adjudicaciones_project_id'), ['project_id'], unique=False)

    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String), sa.column("permisos", sa.JSON))
    for rid, nombre, permisos in conn.execute(sa.select(roles.c.id, roles.c.nombre, roles.c.permisos)).all():
        nuevos = list(permisos or [])
        for p in PERMISOS.get(nombre, ()):
            if p not in nuevos:
                nuevos.append(p)
        if nuevos != list(permisos or []):
            conn.execute(roles.update().where(roles.c.id == rid).values(permisos=nuevos))


def downgrade() -> None:
    with op.batch_alter_table('capex_adjudicaciones', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_capex_adjudicaciones_project_id'))

    op.drop_table('capex_adjudicaciones')
    with op.batch_alter_table('capex_ofertas', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_capex_ofertas_tender_id'))
        batch_op.drop_index(batch_op.f('ix_capex_ofertas_supplier_id'))

    op.drop_table('capex_ofertas')
    with op.batch_alter_table('capex_invitaciones', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_capex_invitaciones_tender_id'))
        batch_op.drop_index(batch_op.f('ix_capex_invitaciones_supplier_id'))

    op.drop_table('capex_invitaciones')
    with op.batch_alter_table('capex_partidas', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_capex_partidas_project_id'))

    op.drop_table('capex_partidas')
    with op.batch_alter_table('capex_licitaciones', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_capex_licitaciones_project_id'))

    op.drop_table('capex_licitaciones')
    with op.batch_alter_table('capex_documentos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_capex_documentos_template_id'))
        batch_op.drop_index(batch_op.f('ix_capex_documentos_project_id'))

    op.drop_table('capex_documentos')
    with op.batch_alter_table('capex_aprobaciones', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_capex_aprobaciones_project_id'))

    op.drop_table('capex_aprobaciones')
    with op.batch_alter_table('capex_proyectos', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_capex_proyectos_estado'))
        batch_op.drop_index(batch_op.f('ix_capex_proyectos_asset_id'))

    op.drop_table('capex_proyectos')
    with op.batch_alter_table('capex_precios', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_capex_precios_codigo'))
        batch_op.drop_index(batch_op.f('ix_capex_precios_base_id'))

    op.drop_table('capex_precios')
    op.drop_table('capex_plantillas')
    op.drop_table('capex_bases_precios')
