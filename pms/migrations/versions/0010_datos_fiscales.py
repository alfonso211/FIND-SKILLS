"""Datos fiscales oficiales de las sociedades del grupo (razón social, CIF y domicilio fiscal)

Fuente: «Datos fiscales sociedades Grupo INVERSIETE S.A.». Solo actualiza datos; las facturas ya emitidas
conservan los datos del emisor con los que se expidieron.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-05 08:00:00
"""
import re

from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

DOMICILIO = {"direccion": "C/ Campezo 8", "cp": "28022", "municipio": "Madrid", "provincia": "Madrid"}
SOCIEDADES = [  # (inicio del nombre actual, razón social oficial, CIF)
    ("INVERSIETE", "INVERSIETE S.A.", "A78072915"),
    ("COMERCIAL DEL CAMPO", "COMERCIAL DEL CAMPO S.A.", "A28362309"),
    ("EDIFICIOS CAMERANOS", "EDIFICIOS CAMERANOS S.A.", "A28309433"),
    ("EMPRESA TURISTICA HOTELERA", "EMPRESA TURISTICA HOTELERA S.A.", "A28116853"),
]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9 ]", " ", (s or "").upper())).strip()


def upgrade() -> None:
    conn = op.get_bind()
    soc = sa.table("sociedades", sa.column("id", sa.Integer), sa.column("nombre", sa.String),
                   sa.column("cif", sa.String), sa.column("direccion", sa.String), sa.column("cp", sa.String),
                   sa.column("municipio", sa.String), sa.column("provincia", sa.String))
    for sid, nombre in conn.execute(sa.select(soc.c.id, soc.c.nombre)).all():
        for inicio, oficial, cif in SOCIEDADES:
            if _norm(nombre).startswith(inicio):
                conn.execute(soc.update().where(soc.c.id == sid).values(nombre=oficial, cif=cif, **DOMICILIO))
                break


def downgrade() -> None:
    pass  # datos: no se deshacen
