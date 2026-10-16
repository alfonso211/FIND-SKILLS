"""1.75 · Babilonia: plazas de garaje unidas al alquiler de una vivienda; cambio de vivienda del inquilino y de
apartamento de una reserva turística sin anular (con motivo). Datos ZZ-PRUEBA-175."""
from datetime import date, timedelta

from test_pms import d

Z = "ZZ175"


def _unidad(client, admin, asset_id, codigo, uso):
    r = client.post("/api/unidades", headers=admin, json={"asset_id": asset_id, "codigo": codigo, "uso": uso})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _estado(client, admin, asset_id, codigo):
    return client.get(f"/api/unidades?asset_id={asset_id}&q={codigo}", headers=admin).json()[0]["estado"]


def test_plazas_unidas_y_cambio_de_vivienda(client, admin, ids):
    bab = ids["assets"]["BAB35"]["id"]
    v1 = _unidad(client, admin, bab, f"{Z}-V1", "vivienda")
    v2 = _unidad(client, admin, bab, f"{Z}-V2", "vivienda")
    g1 = _unidad(client, admin, bab, f"{Z}-G1", "garaje")
    g2 = _unidad(client, admin, bab, f"{Z}-G2", "garaje")
    base = {"fecha_inicio": d(-10), "renta_mensual": 800, "estado": "vigente",
            "tenant": {"nombre": "Inquilino", "apellidos": Z, "documento_tipo": "PAS", "documento_num": f"{Z}A"}}
    # no se une la propia vivienda ni una unidad que no sea garaje
    assert client.post("/api/alquiler/contratos", headers=admin,
                       json={**base, "unit_id": v1["id"], "plazas": [v2["id"]]}).status_code == 400
    r = client.post("/api/alquiler/contratos", headers=admin, json={**base, "unit_id": v1["id"], "plazas": [g1["id"]]})
    assert r.status_code == 201, r.text
    l = r.json()
    assert l["plazas"] == [g1["id"]] and l["plazas_codigos"] == [f"{Z}-G1"]
    assert _estado(client, admin, bab, f"{Z}-G1") == "ocupada"  # sin bloquearla ni contrato aparte

    # la plaza unida no se alquila aparte ni se une a otro contrato
    otro = {**base, "tenant": {**base["tenant"], "documento_num": f"{Z}B"}}
    assert client.post("/api/alquiler/contratos", headers=admin, json={**otro, "unit_id": g1["id"]}).status_code == 400
    r2 = client.post("/api/alquiler/contratos", headers=admin, json={**otro, "unit_id": v2["id"], "plazas": [g1["id"]]})
    assert r2.status_code == 400 and f"{Z}-V1" in r2.json()["detail"]

    # ficha de la plaza: a qué vivienda va unida
    ficha = client.get(f"/api/plano/unidades/{g1['id']}/ficha", headers=admin).json()
    assert ficha["unida_a"]["vivienda"] == f"{Z}-V1"

    # cambiar las plazas: la que sale se libera
    r = client.put(f"/api/alquiler/contratos/{l['id']}", headers=admin, json={"plazas": [g2["id"]]})
    assert r.status_code == 200 and r.json()["plazas_codigos"] == [f"{Z}-G2"]
    assert _estado(client, admin, bab, f"{Z}-G1") == "disponible"
    assert _estado(client, admin, bab, f"{Z}-G2") == "ocupada"

    # cambio de vivienda sin anular: motivo obligatorio, mismo edificio y uso, se conservan contrato y plazas
    url = f"/api/alquiler/contratos/{l['id']}/cambiar-unidad"
    assert client.post(url, headers=admin, json={"unit_id": v2["id"], "motivo": ""}).status_code == 422
    assert client.post(url, headers=admin, json={"unit_id": g1["id"], "motivo": "error"}).status_code == 400
    r = client.post(url, headers=admin, json={"unit_id": v2["id"], "motivo": "Humedad en el dormitorio"})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["id"] == l["id"] and c["unidad"] == f"{Z}-V2" and c["plazas_codigos"] == [f"{Z}-G2"]
    assert "Humedad en el dormitorio" in c["notas"] and f"{Z}-V1 → {Z}-V2" in c["notas"]
    assert _estado(client, admin, bab, f"{Z}-V1") == "disponible"
    assert _estado(client, admin, bab, f"{Z}-V2") == "ocupada"

    # al anular el contrato, las plazas unidas quedan libres
    assert client.post(f"/api/alquiler/contratos/{l['id']}/anular", headers=admin,
                       json={"motivo": "prueba ZZ175"}).status_code == 200
    assert _estado(client, admin, bab, f"{Z}-G2") == "disponible"


def test_cambio_de_apartamento_de_una_reserva(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    us = [u for u in client.get(f"/api/unidades?asset_id={sae}", headers=admin).json() if u["uso"] != "garaje"]
    a, b = us[-3], us[-4]
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": a["id"], "localizador": f"{Z}-R", "fecha_entrada": d(400), "fecha_salida": d(403), "importe_total": 300,
        "guest": {"nombre": "Cliente", "apellidos": Z, "documento_tipo": "PAS", "documento_num": f"{Z}C"}})
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    url = f"/api/turistico/reservas/{rid}/cambiar-apartamento"
    assert client.post(url, headers=admin, json={"unit_id": b["id"], "motivo": ""}).status_code == 422
    assert client.post(url, headers=admin, json={"unit_id": a["id"], "motivo": "mismo"}).status_code == 400
    x = client.post(url, headers=admin, json={"unit_id": b["id"], "motivo": "Avería del aire acondicionado"})
    assert x.status_code == 200, x.text
    x = x.json()
    assert x["id"] == rid and x["unit_id"] == b["id"]
    assert "Avería del aire acondicionado" in x["notas"] and f"{a['codigo']} → {b['codigo']}" in x["notas"]
    # el contrato no se repite: el formulario sigue con los datos de la reserva
    assert client.get(f"/api/turistico/reservas/{rid}/contrato", headers=admin).status_code == 200
    assert date.fromisoformat(d(400)) - date.today() == timedelta(days=400)
