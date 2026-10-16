"""1.75 · Babilonia: plazas de garaje unidas al alquiler de una vivienda; cambio de vivienda del inquilino y de
apartamento de una reserva turística sin anular (con motivo). Datos ZZ-PRUEBA-175."""
from datetime import date, timedelta

from test_pms import d

Z = "ZZ175"


def _libres(client, admin, asset_id, uso, n):
    """Unidades del seed libres (no se crean unidades nuevas: test_seed cuenta las de Babilonia)."""
    us = [u for u in client.get(f"/api/unidades?asset_id={asset_id}", headers=admin).json()
          if u["uso"] == uso and u["estado"] == "disponible"]
    return us[-n:]


def _estado(client, admin, asset_id, codigo):
    us = client.get(f"/api/unidades?asset_id={asset_id}", headers=admin).json()
    return next(u["estado"] for u in us if u["codigo"] == codigo)


def test_plazas_unidas_y_cambio_de_vivienda(client, admin, ids):
    bab = ids["assets"]["BAB35"]["id"]
    v1, v2 = _libres(client, admin, bab, "vivienda", 2)
    g1, g2 = _libres(client, admin, bab, "garaje", 2)
    V1, V2, G1, G2 = (u["codigo"] for u in (v1, v2, g1, g2))
    base = {"fecha_inicio": d(-10), "renta_mensual": 800, "estado": "vigente",
            "tenant": {"nombre": "Inquilino", "apellidos": Z, "documento_tipo": "PAS", "documento_num": f"{Z}A"}}
    # no se une la propia vivienda ni una unidad que no sea garaje
    assert client.post("/api/alquiler/contratos", headers=admin,
                       json={**base, "unit_id": v1["id"], "plazas": [v2["id"]]}).status_code == 400
    r = client.post("/api/alquiler/contratos", headers=admin, json={**base, "unit_id": v1["id"], "plazas": [g1["id"]]})
    assert r.status_code == 201, r.text
    l = r.json()
    assert l["plazas"] == [g1["id"]] and l["plazas_codigos"] == [G1]
    assert _estado(client, admin, bab, G1) == "ocupada"  # sin bloquearla ni contrato aparte

    # la plaza unida no se alquila aparte ni se une a otro contrato
    otro = {**base, "tenant": {**base["tenant"], "documento_num": f"{Z}B"}}
    assert client.post("/api/alquiler/contratos", headers=admin, json={**otro, "unit_id": g1["id"]}).status_code == 400
    r2 = client.post("/api/alquiler/contratos", headers=admin, json={**otro, "unit_id": v2["id"], "plazas": [g1["id"]]})
    assert r2.status_code == 400 and V1 in r2.json()["detail"]

    # ficha de la plaza: a qué vivienda va unida
    ficha = client.get(f"/api/plano/unidades/{g1['id']}/ficha", headers=admin).json()
    assert ficha["unida_a"]["vivienda"] == V1

    # cambiar las plazas: la que sale se libera
    r = client.put(f"/api/alquiler/contratos/{l['id']}", headers=admin, json={"plazas": [g2["id"]]})
    assert r.status_code == 200 and r.json()["plazas_codigos"] == [G2]
    assert _estado(client, admin, bab, G1) == "disponible"
    assert _estado(client, admin, bab, G2) == "ocupada"

    # cambio de vivienda sin anular: motivo obligatorio, mismo edificio y uso, se conservan contrato y plazas
    url = f"/api/alquiler/contratos/{l['id']}/cambiar-unidad"
    assert client.post(url, headers=admin, json={"unit_id": v2["id"], "motivo": ""}).status_code == 422
    assert client.post(url, headers=admin, json={"unit_id": g1["id"], "motivo": "error"}).status_code == 400
    r = client.post(url, headers=admin, json={"unit_id": v2["id"], "motivo": "Humedad en el dormitorio"})
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["id"] == l["id"] and c["unidad"] == V2 and c["plazas_codigos"] == [G2]
    assert "Humedad en el dormitorio" in c["notas"] and f"{V1} → {V2}" in c["notas"]
    assert _estado(client, admin, bab, V1) == "disponible"
    assert _estado(client, admin, bab, V2) == "ocupada"

    # al anular el contrato, las plazas unidas quedan libres
    assert client.post(f"/api/alquiler/contratos/{l['id']}/anular", headers=admin,
                       json={"motivo": "prueba ZZ175"}).status_code == 200
    assert _estado(client, admin, bab, G2) == "disponible"


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
