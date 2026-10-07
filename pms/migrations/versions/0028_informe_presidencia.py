"""Informe mensual a la presidencia: responsable y destinatarios por activo y registro de envíos

Revision ID: 0028
Revises: 0027
Create Date: 2026-10-07 12:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0028'
down_revision = '0027'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # el tipo MIME de un Excel (.xlsx) pasa de 60 caracteres
    with op.batch_alter_table('documentos_recibidos') as b:
        b.alter_column('mime', type_=sa.String(100), existing_type=sa.String(60))
    with op.batch_alter_table('activos') as b:
        b.add_column(sa.Column('informe_responsable_id', sa.Integer(),
                               sa.ForeignKey('usuarios.id', name='fk_activos_informe_responsable')))
        b.add_column(sa.Column('informe_emails', sa.String(500)))
        b.add_column(sa.Column('informe_whatsapp', sa.String(30)))
    op.create_table(
        'informes_presidencia',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('activos.id'), nullable=False, index=True),
        sa.Column('anio', sa.Integer(), nullable=False),
        sa.Column('mes', sa.Integer(), nullable=False),
        sa.Column('revisado_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('revisado_en', sa.DateTime()),
        sa.Column('enviado_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('enviado_en', sa.DateTime()),
        sa.Column('canal', sa.String(12)),
        sa.Column('destino', sa.String(500)),
        sa.Column('documento_id', sa.Integer(), sa.ForeignKey('documentos_recibidos.id')),
        sa.Column('resumen', sa.JSON()),
        sa.UniqueConstraint('asset_id', 'anio', 'mes'),
    )


def downgrade() -> None:
    op.drop_table('informes_presidencia')
    with op.batch_alter_table('documentos_recibidos') as b:
        b.alter_column('mime', type_=sa.String(60), existing_type=sa.String(100))
    with op.batch_alter_table('activos') as b:
        for c in ('informe_whatsapp', 'informe_emails', 'informe_responsable_id'):
            b.drop_column(c)
