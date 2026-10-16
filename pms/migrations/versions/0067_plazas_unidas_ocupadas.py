"""1.76: las plazas de garaje ya unidas al contrato de una vivienda (en borrador o vigente, ya empezado) pasan a
«ocupada», igual que hace el PMS desde ahora al unirlas.

Revision ID: 0067
Revises: 0066
Create Date: 2026-10-16 14:00:00
"""
import json
from datetime import date

from alembic import op
import sqlalchemy as sa


revision = '0067'
down_revision = '0066'
branch_labels = None
depends_on = None


def upgrade() -> None:
    con = op.get_bind()
    hoy = date.today()
    ids = set()
    for _, plazas, inicio, fin in con.execute(sa.text(
            "SELECT id, plazas, fecha_inicio, fecha_fin FROM contratos "
            "WHERE plazas IS NOT NULL AND estado IN ('borrador', 'vigente')")):
        if isinstance(plazas, str):
            plazas = json.loads(plazas)
        inicio = date.fromisoformat(str(inicio)[:10])
        fin = date.fromisoformat(str(fin)[:10]) if fin else None
        if inicio <= hoy and (fin is None or fin >= hoy):
            ids.update(int(p) for p in plazas or [])
    for pid in ids:
        con.execute(sa.text("UPDATE unidades SET estado = 'ocupada' WHERE id = :id AND uso = 'garaje' "
                            "AND estado IN ('disponible', 'bloqueada')"), {"id": pid})


def downgrade() -> None:
    pass  # no se sabe qué plazas estaban libres antes: se quedan ocupadas
