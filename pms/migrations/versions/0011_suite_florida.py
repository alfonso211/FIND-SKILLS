"""Suite Florida: tipologías de los apartamentos según el croquis y plazas de garaje de los sótanos -1 y -2

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-05 09:00:00
"""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = '0011'
down_revision = '0010'
branch_labels = None
depends_on = None

DOS_DORMITORIOS = {1: "IJ", 2: "GHMNO", 3: "ABCHI", 4: "IJOPQ"}  # letras de 2 dormitorios por portal
GARAJES = Path(__file__).resolve().parents[2] / "app" / "data" / "planos_sfl_garajes.json"


def upgrade() -> None:
    conn = op.get_bind()
    activos = sa.table("activos", sa.column("id", sa.Integer), sa.column("codigo", sa.String))
    unidades = sa.table("unidades", sa.column("id", sa.Integer), sa.column("asset_id", sa.Integer),
                        sa.column("codigo", sa.String), sa.column("bloque", sa.String), sa.column("planta", sa.String),
                        sa.column("uso", sa.String), sa.column("tipologia", sa.String),
                        sa.column("dormitorios", sa.Integer), sa.column("estado", sa.String))
    sfl = conn.execute(sa.select(activos.c.id).where(activos.c.codigo == "SFL")).scalar()
    if sfl is None:
        return  # base nueva: lo hace la carga inicial
    existentes = {}
    for uid, codigo, tipologia in conn.execute(sa.select(unidades.c.id, unidades.c.codigo, unidades.c.tipologia)
                                               .where(unidades.c.asset_id == sfl)).all():
        existentes[codigo] = uid
        if tipologia or not codigo.startswith("P") or "-" not in codigo:
            continue
        portal, resto = codigo[1:].split("-", 1)
        if not portal.isdigit() or not resto[-1:].isalpha():
            continue
        dos = resto[-1] in DOS_DORMITORIOS.get(int(portal), "")
        conn.execute(unidades.update().where(unidades.c.id == uid).values(
            tipologia="Apartamento 2 dormitorios" if dos else "Apartamento 1 dormitorio", dormitorios=2 if dos else 1))
    plazas = json.loads(GARAJES.read_text(encoding="utf-8"))
    nuevas = [{"asset_id": sfl, "codigo": f"S{n}-{p}", "bloque": f"Sótano -{n}", "planta": f"-{n}", "uso": "garaje",
               "estado": "disponible"}
              for n in (1, 2) for p in sorted(plazas[f"S{n}"].values()) if f"S{n}-{p}" not in existentes]
    if nuevas:
        op.bulk_insert(unidades, nuevas)


def downgrade() -> None:
    pass  # datos: no se deshacen
