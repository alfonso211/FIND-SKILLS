"""Fichas de clientes por activo: cada recepción ve solo los clientes de su activo

Se asigna a cada ficha el activo de sus reservas, ocupaciones, contratos o facturas. Si un cliente estuvo en
varios activos, se le abre una ficha en cada uno (copia de sus datos) y cada activo se queda con lo suyo; los
documentos escaneados siguen en la ficha original.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-05 17:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0018'
down_revision = '0017'
branch_labels = None
depends_on = None

# (tabla, columna del tercero, cómo se llega al activo, columna de la tabla para filtrar al mover)
VINCULOS = (
    ("reservas", "guest_id", "select r.id, u.asset_id from reservas r join unidades u on u.id = r.unit_id "
                             "where r.guest_id = :c"),
    ("reserva_ocupantes", "contact_id", "select o.id, u.asset_id from reserva_ocupantes o join reservas r "
                                        "on r.id = o.reservation_id join unidades u on u.id = r.unit_id "
                                        "where o.contact_id = :c"),
    ("contratos", "tenant_id", "select l.id, u.asset_id from contratos l join unidades u on u.id = l.unit_id "
                               "where l.tenant_id = :c"),
    ("facturas", "contact_id", "select f.id, f.asset_id from facturas f where f.contact_id = :c"),
)


def upgrade() -> None:
    with op.batch_alter_table("terceros") as b:
        b.add_column(sa.Column("asset_id", sa.Integer()))
        b.create_foreign_key("fk_terceros_asset_id", "activos", ["asset_id"], ["id"])
        b.create_index("ix_terceros_asset_id", ["asset_id"])
    conn = op.get_bind()
    columnas = [c["name"] for c in sa.inspect(conn).get_columns("terceros") if c["name"] not in ("id", "asset_id")]
    for (cid,) in conn.execute(sa.text("select id from terceros order by id")).all():
        filas = {t: conn.execute(sa.text(q), {"c": cid}).all() for t, _, q in VINCULOS}
        activos = []
        for t, _, _ in VINCULOS:
            for _, aid in filas[t]:
                if aid not in activos:
                    activos.append(aid)
        if not activos:
            continue
        conn.execute(sa.text("update terceros set asset_id = :a where id = :c"), {"a": activos[0], "c": cid})
        for aid in activos[1:]:  # otro activo: ficha propia con los mismos datos
            cols = ", ".join(columnas)
            nid = conn.execute(sa.text(f"insert into terceros ({cols}, asset_id) select {cols}, :a from terceros "
                                       f"where id = :c returning id"), {"a": aid, "c": cid}).scalar()
            for t, col, _ in VINCULOS:
                ids = [i for i, a in filas[t] if a == aid]
                if ids:
                    conn.execute(sa.text(f"update {t} set {col} = :n where id in ({', '.join(map(str, ids))})"),
                                 {"n": nid})


def downgrade() -> None:
    with op.batch_alter_table("terceros") as b:
        b.drop_index("ix_terceros_asset_id")
        b.drop_constraint("fk_terceros_asset_id", type_="foreignkey")
        b.drop_column("asset_id")
