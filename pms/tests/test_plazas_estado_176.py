"""1.76 · La plaza unida a una vivienda se ve ocupada (estado, plano y ficha) también con el contrato en borrador, y la
ficha del apartamento trae las reservas con los datos que necesitan todas sus acciones (cambiar de apartamento…).
Datos ZZ-PRUEBA-176."""
from test_pms import d

Z = "ZZ176"


def _libres(client, admin, asset_id, uso, n):
    us = [u for u in client.get(f"/api/unidades?asset_id={asset_id}", headers=admin).json()
          if u["uso"] == uso and u["estado"] == "disponible"]
    return us[-n:]


def test_plaza_unida_ocupada_en_plano_y_ficha(client, admin, ids):
    bab = ids["assets"]["BAB35"]["id"]
    (v,), (g,) = _libres(client, admin, bab, "vivienda", 1), _libres(client, admin, bab, "garaje", 1)
    r = client.post("/api/alquiler/contratos", headers=admin, json={
        "fecha_inicio": d(-5), "renta_mensual": 700, "estado": "borrador", "unit_id": v["id"], "plazas": [g["id"]],
        "tenant": {"nombre": "Inquilino", "apellidos": Z, "documento_tipo": "PAS", "documento_num": f"{Z}A"}})
    assert r.status_code == 201, r.text
    lid = r.json()["id"]
    us = client.get(f"/api/unidades?asset_id={bab}", headers=admin).json()
    assert next(u for u in us if u["id"] == g["id"])["estado"] == "ocupada"
    plano = client.get(f"/api/plano/{bab}", headers=admin).json()
    fila = next(u for p in plano["plantas"] for u in p["unidades"] if u["unit_id"] == g["id"])
    assert fila["estado"] == "alquilado" and fila["alquiler"]["unida_a"] == v["codigo"]
    ficha = client.get(f"/api/plano/unidades/{g['id']}/ficha", headers=admin).json()
    assert ficha["alquiler"]["unida_a"] == v["codigo"] and ficha["unida_a"]["vivienda"] == v["codigo"]
    # la ficha de la vivienda trae el contrato con sus plazas (acciones «Plazas de garaje» y «Cambiar de vivienda»)
    fv = client.get(f"/api/plano/unidades/{v['id']}/ficha", headers=admin).json()
    assert any(c["id"] == lid and c["plazas"] == [g["id"]] for c in fv["contratos"])
    assert client.post(f"/api/alquiler/contratos/{lid}/anular", headers=admin, json={"motivo": "prueba ZZ176"}).status_code == 200
    us = client.get(f"/api/unidades?asset_id={bab}", headers=admin).json()
    assert next(u for u in us if u["id"] == g["id"])["estado"] == "disponible"


def test_ficha_apartamento_reservas_con_acciones(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    a = [u for u in client.get(f"/api/unidades?asset_id={sae}", headers=admin).json() if u["uso"] != "garaje"][-5]
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": a["id"], "localizador": f"{Z}-R", "fecha_entrada": d(420), "fecha_salida": d(422), "importe_total": 200,
        "guest": {"nombre": "Cliente", "apellidos": Z, "documento_tipo": "PAS", "documento_num": f"{Z}C"}})
    assert r.status_code == 201, r.text
    ficha = client.get(f"/api/plano/unidades/{a['id']}/ficha", headers=admin).json()
    x = next(y for y in ficha["reservas"] if y["id"] == r.json()["id"])
    assert x["unidad"] == a["codigo"] and x["asset_id"] == sae and x["uso"] == a["uso"] and x["unit_id"] == a["id"]
    assert x["estado"] == "confirmada" and "extras_pendientes" in x and x["entrada"] == d(420)
