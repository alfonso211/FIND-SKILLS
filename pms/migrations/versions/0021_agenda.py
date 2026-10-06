"""Agenda: reuniones, tareas, recordatorios y eventos (privados, compartidos o públicos); presidencia sin asignaciones

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-06 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0021'
down_revision = '0020'
branch_labels = None
depends_on = None

PRESIDENCIA = "jr@inversiete.es"


def upgrade() -> None:
    with op.batch_alter_table('usuarios') as b:
        b.add_column(sa.Column('no_asignable', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.execute(f"UPDATE usuarios SET no_asignable = TRUE WHERE lower(email) = '{PRESIDENCIA}'")
    op.create_table(
        'agenda',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('tipo', sa.String(20), nullable=False),
        sa.Column('titulo', sa.String(200), nullable=False),
        sa.Column('descripcion', sa.Text()),
        sa.Column('lugar', sa.String(200)),
        sa.Column('inicio', sa.DateTime(), nullable=False),
        sa.Column('fin', sa.DateTime()),
        sa.Column('todo_el_dia', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('visibilidad', sa.String(20), nullable=False),
        sa.Column('prioridad', sa.String(10), nullable=False, server_default='normal'),
        sa.Column('asset_id', sa.Integer(), sa.ForeignKey('activos.id')),
        sa.Column('repeticion', sa.String(10)),
        sa.Column('repetir_hasta', sa.Date()),
        sa.Column('aviso_min', sa.Integer()),
        sa.Column('hecha', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('hecha_por', sa.Integer(), sa.ForeignKey('usuarios.id')),
        sa.Column('hecha_en', sa.DateTime()),
        sa.Column('creador_id', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=False),
        sa.Column('creado', sa.DateTime(), nullable=False),
    )
    op.create_index('ix_agenda_inicio', 'agenda', ['inicio'])
    op.create_index('ix_agenda_creador_id', 'agenda', ['creador_id'])
    op.create_table(
        'agenda_participantes',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('agenda.id', ondelete='CASCADE'), nullable=False),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('usuarios.id'), nullable=False),
        sa.Column('respuesta', sa.String(12), nullable=False, server_default='pendiente'),
        sa.Column('visto', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint('event_id', 'user_id'),
    )
    op.create_index('ix_agenda_participantes_event_id', 'agenda_participantes', ['event_id'])
    op.create_index('ix_agenda_participantes_user_id', 'agenda_participantes', ['user_id'])


def downgrade() -> None:
    op.drop_table('agenda_participantes')
    op.drop_table('agenda')
    with op.batch_alter_table('usuarios') as b:
        b.drop_column('no_asignable')
