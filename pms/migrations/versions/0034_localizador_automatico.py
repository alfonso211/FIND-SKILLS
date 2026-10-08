"""Localizador automático: las reservas sin localizador reciben el suyo (SF0000000001, SA0000000001…)

Revision ID: 0034
Revises: 0033
Create Date: 2026-10-08 10:00:00
"""
import re

from alembic import op
import sqlalchemy as sa


revision = '0034'
down_revision = '0033'
branch_labels = None
depends_on = None

DIGITOS = 10  # como app.routers.turistico.DIGITOS_LOCALIZADOR


def upgrade() -> None:
    con = op.get_bind()
    activos = con.execute(sa.text("SELECT id, codigo, serie_factura FROM activos")).all()
    for aid, codigo, serie in activos:
        pre = (serie or codigo or "R")[:4].upper()
        filas = con.execute(sa.text(
            "SELECT r.id, r.localizador FROM reservas r JOIN unidades u ON u.id = r.unit_id WHERE u.asset_id = :a "
            "ORDER BY r.fecha_entrada, r.id"), {"a": aid}).all()
        patron = re.compile(rf"{re.escape(pre)}(\d{{{DIGITOS}}})")
        n = max((int(m.group(1)) for _, loc in filas if loc and (m := patron.fullmatch(loc))), default=0)
        for rid, loc in filas:
            if not (loc or "").strip():
                n += 1
                con.execute(sa.text("UPDATE reservas SET localizador = :l WHERE id = :i"),
                            {"l": f"{pre}{n:0{DIGITOS}d}", "i": rid})


def downgrade() -> None:
    pass  # los localizadores asignados se quedan: no se puede saber cuáles estaban vacíos
