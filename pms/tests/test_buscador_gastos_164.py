"""Buscador de la Cuenta de gastos (1.64): proveedor, nº de factura, concepto, notas o importe; también en el Excel."""
from datetime import date, timedelta

AYER = (date.today() - timedelta(days=1)).isoformat()


def _gasto(client, admin, aid, proveedor, numero, concepto, total, notas=None):
    r = client.post("/api/gastos", headers=admin, json={
        "asset_id": aid, "fecha": AYER, "categoria": "mantenimiento", "naturaleza": "OPEX", "concepto": concepto,
        "proveedor": proveedor, "numero_factura": numero, "total": total, "tipo_iva": 21,
        "forma_pago": "transferencia", "notas": notas, "confirmar_duplicado": True})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _ids(client, admin, aid, q):
    return {g["id"] for g in client.get("/api/gastos", headers=admin, params={"asset_id": aid, "q": q}).json()["gastos"]}


def test_buscador_de_gastos(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    a = _gasto(client, admin, sae, "Cristalería Buscador SL", "CB-2026-77", "Cambio de luna del portal", 1210.5)
    b = _gasto(client, admin, sae, "Electricidad Lupa SA", "EL-9", "Revisión cuadro general", 96.8, notas="urgente portal B")
    assert a in _ids(client, admin, sae, "buscador") and b not in _ids(client, admin, sae, "buscador")  # proveedor
    assert _ids(client, admin, sae, "cb-2026") >= {a}                                                  # nº factura
    assert b in _ids(client, admin, sae, "cuadro general")                                             # concepto
    assert b in _ids(client, admin, sae, "portal B")                                                   # notas
    assert a in _ids(client, admin, sae, "1.210,50") and a in _ids(client, admin, sae, "1210,5")       # importe
    assert b in _ids(client, admin, sae, "96,80") and a not in _ids(client, admin, sae, "96,80")
    assert _ids(client, admin, sae, "no-existe-nada-asi") == set()
    r = client.get("/api/gastos", headers=admin, params={"asset_id": sae, "q": "Lupa"}).json()
    assert r["totales"]["total"] == 96.8  # los totales son los de lo encontrado
    xls = client.get("/api/gastos/excel", headers=admin, params={"asset_id": sae, "q": "Lupa"})
    assert xls.status_code == 200 and xls.content[:2] == b"PK"
