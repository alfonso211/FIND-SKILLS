"""Proveedores del grupo (sin sociedad): nombre, CIF/DNI, domicilio, correo, teléfono y notas. Los proveedores
que había como terceros de una sociedad se pasan al nuevo fichero.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-05 15:00:00
"""
from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = '0017'
down_revision = '0016'
branch_labels = None
depends_on = None

REFERENCIAS = (("contratos", "tenant_id"), ("reservas", "guest_id"), ("reserva_ocupantes", "contact_id"),
               ("documentos_terceros", "contact_id"), ("facturas", "contact_id"))


def upgrade() -> None:
    prov = op.create_table(
        "proveedores",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("nombre", sa.String(200), nullable=False),
        sa.Column("tipo_persona", sa.String(20), nullable=False),
        sa.Column("nif", sa.String(20), unique=True),
        sa.Column("direccion", sa.String(300)),
        sa.Column("cp", sa.String(10)),
        sa.Column("municipio", sa.String(100)),
        sa.Column("provincia", sa.String(60)),
        sa.Column("pais", sa.String(60)),
        sa.Column("email", sa.String(160)),
        sa.Column("telefono", sa.String(40)),
        sa.Column("persona_contacto", sa.String(160)),
        sa.Column("actividad", sa.String(160)),
        sa.Column("activo", sa.Boolean(), nullable=False),
        sa.Column("notas", sa.Text()),
        sa.Column("creado", sa.DateTime(), nullable=False),
    )
    conn = op.get_bind()
    filas = conn.execute(sa.text(
        "select id, nombre, apellidos, documento_tipo, documento_num, direccion, cp, municipio, pais, email, "
        "telefono, notas from terceros where tipo = 'proveedor' order by id")).mappings().all()
    vistos, nuevos = set(), []
    for f in filas:
        nif = (f["documento_num"] or "").replace(" ", "").replace("-", "").upper() or None
        clave = nif or " ".join(filter(None, (f["nombre"], f["apellidos"]))).upper()
        if clave in vistos:
            continue
        vistos.add(clave)
        nuevos.append({"nombre": " ".join(filter(None, (f["nombre"], f["apellidos"])))[:200],
                       "tipo_persona": "particular" if f["documento_tipo"] in ("DNI", "NIE") else "empresa",
                       "nif": nif, "direccion": f["direccion"], "cp": f["cp"], "municipio": f["municipio"],
                       "pais": f["pais"], "email": f["email"], "telefono": f["telefono"], "notas": f["notas"],
                       "activo": True, "creado": datetime.now()})
    if nuevos:
        op.bulk_insert(prov, nuevos)
    usados = " ".join(f"and id not in (select {c} from {t} where {c} is not null)" for t, c in REFERENCIAS)
    conn.execute(sa.text(f"delete from terceros where tipo = 'proveedor' {usados}"))


def downgrade() -> None:
    op.drop_table("proveedores")
