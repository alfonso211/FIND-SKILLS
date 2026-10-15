"""Flujo de OT simplificado (1.70): los partes de estado los genera limpieza; recepción abre las OT; el personal
propio cierra las suyas (firma, foto y tiempo); las de subcontratas las cierran el Director Técnico o recepción;
limpieza ya no confirma la unidad tras la reparación. Sin tablas nuevas: permisos de los roles y estado de las OT
que esperaban a limpieza.

Revision ID: 0063
Revises: 0062
Create Date: 2026-10-15 22:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0063'
down_revision = '0062'
branch_labels = None
depends_on = None

QUITAR = {"Recepción": ("partes_estado.crear",), "Técnico Mantenimiento": ("partes_estado.crear",),
          "Dirección Sociedad": ("partes_estado.crear",)}
PONER = {"Dirección Técnica": ("mantenimiento.cerrar",)}
DESCRIPCION = {
    "Recepción": "Reservas, llegadas y salidas. Abre las órdenes de trabajo y cierra las de subcontratas",
    "Gobernanta / Limpieza": "Limpieza de unidades. Genera los partes de estado",
    "Técnico Mantenimiento": "Ejecuta las órdenes de trabajo (las de personal propio las cierra él), parte diario con "
                             "el tiempo y preventivo",
    "Dirección Técnica": "Director técnico: cierra las OT de subcontratas y autoriza las ausencias de mantenimiento "
                         "(se suma a su otro rol)",
}


def upgrade() -> None:
    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("nombre", sa.String),
                     sa.column("descripcion", sa.String), sa.column("permisos", sa.JSON))
    for rid, nombre, permisos in conn.execute(sa.select(roles.c.id, roles.c.nombre, roles.c.permisos)).all():
        antes = list(permisos or [])
        nuevos = [p for p in antes if p != "limpieza.confirmar_ot" and p not in QUITAR.get(nombre, ())]
        nuevos += [p for p in PONER.get(nombre, ()) if p not in nuevos]
        valores = {"permisos": nuevos} if nuevos != antes else {}
        if nombre in DESCRIPCION:
            valores["descripcion"] = DESCRIPCION[nombre]
        if valores:
            conn.execute(roles.update().where(roles.c.id == rid).values(**valores))
    # OT que esperaban la confirmación de limpieza: pasan a pendientes de cierre
    ot = sa.table("ordenes_trabajo", sa.column("estado", sa.String))
    conn.execute(ot.update().where(ot.c.estado == "trabajo_realizado").values(estado="pendiente_cierre"))


def downgrade() -> None:
    pass  # los permisos se pueden volver a poner a mano en Administración → Roles
