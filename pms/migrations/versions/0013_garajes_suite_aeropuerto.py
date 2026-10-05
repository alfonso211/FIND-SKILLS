"""Suite Aeropuerto: plazas de garaje exterior y del sótano -1 según los croquis

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-05 16:00:00
"""
import json
from pathlib import Path

from alembic import op
import sqlalchemy as sa


revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None

GARAJES = Path(__file__).resolve().parents[2] / "app" / "data" / "planos_sae_garajes.json"
NIVELES = {"EXT": ("Garaje exterior", "0"), "S1": ("Sótano -1", "-1")}


def upgrade() -> None:
    conn = op.get_bind()
    activos = sa.table("activos", sa.column("id", sa.Integer), sa.column("codigo", sa.String))
    unidades = sa.table("unidades", sa.column("id", sa.Integer), sa.column("asset_id", sa.Integer),
                        sa.column("codigo", sa.String), sa.column("bloque", sa.String), sa.column("planta", sa.String),
                        sa.column("uso", sa.String), sa.column("estado", sa.String))
    sae = conn.execute(sa.select(activos.c.id).where(activos.c.codigo == "SAE")).scalar()
    if sae is None:
        return  # base nueva: lo hace la carga inicial
    existentes = set(conn.execute(sa.select(unidades.c.codigo).where(unidades.c.asset_id == sae)).scalars())
    plazas = json.loads(GARAJES.read_text(encoding="utf-8"))
    nuevas = [{"asset_id": sae, "codigo": f"{clave}-{n}", "bloque": bloque, "planta": planta, "uso": "garaje",
               "estado": "disponible"}
              for clave, (bloque, planta) in NIVELES.items() for n in sorted(plazas[clave].values())
              if f"{clave}-{n}" not in existentes]
    if nuevas:
        op.bulk_insert(unidades, nuevas)


def downgrade() -> None:
    pass  # datos: no se deshacen
