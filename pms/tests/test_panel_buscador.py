"""Buscador del panel: un dato cualquiera y todas las coincidencias que el usuario puede ver."""
# (se ejecuta después de test_facturacion: crea una factura y las series deben empezar allí en 00001)
from test_adjuntos_ot import _usuario
from test_pms import d

LETRAS = "TRWAGMYFPDXBNJZSQVHLCKE"
DNI = f"45678912{LETRAS[45678912 % 23]}"


def _buscar(client, h, q):
    r = client.get("/api/buscar", headers=h, params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()


def test_buscador_del_panel(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    u = client.get(f"/api/unidades?asset_id={sae}&q=A-141", headers=admin).json()[0]
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": u["id"], "localizador": "BKG-778899", "fecha_entrada": d(400), "fecha_salida": d(403),
        "importe_total": 300, "guest": {"nombre": "Bartolomé", "apellidos": "Quiñones Zubizarreta",
                                        "documento_tipo": "DNI", "documento_num": DNI, "telefono": "699 112 233"}})
    assert r.status_code == 201, r.text
    res = r.json()

    # por documento (con o sin guion), por nombre sin tildes, por teléfono y por localizador
    for q in (DNI, DNI[:8] + "-" + DNI[8], "bartolome quinones", "Zubizarreta", "699112233", "BKG-778899"):
        j = _buscar(client, admin, q)
        assert any(c["documento"] == DNI for c in j["clientes"]) or any(x["id"] == res["id"] for x in j["reservas"]), q
    j = _buscar(client, admin, "bartolome quinones")
    assert j["clientes"][0]["nombre"] == "Bartolomé Quiñones Zubizarreta"
    assert any(x["id"] == res["id"] and x["huesped"].startswith("Bartolomé") for x in j["reservas"])

    # por apartamento: «a141», «A 141» o «A-141»; se ven sus reservas vigentes
    for q in ("a141", "A 141", "A-141"):
        j = _buscar(client, admin, q)
        assert j["unidades"][0]["codigo"] == "A-141", q
        assert any(x["id"] == res["id"] for x in j["reservas"])

    # facturas por número y órdenes de trabajo por número
    cobro = client.post(f"/api/turistico/reservas/{res['id']}/cobro", headers=admin,
                        json={"importe": 100, "forma_pago": "tarjeta"})
    assert cobro.status_code in (200, 201), cobro.text
    factura = client.get(f"/api/facturas?reservation_id={res['id']}", headers=admin).json()[0]
    assert _buscar(client, admin, factura["codigo"])["facturas"][0]["id"] == factura["id"]
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "unit_id": u["id"], "titulo": "Grifo del baño gotea", "prioridad": "media"}).json()
    assert any(o["id"] == w["id"] for o in _buscar(client, admin, f"OT-{w['id']:05d}")["ordenes"])
    assert any(o["id"] == w["id"] for o in _buscar(client, admin, "grifo del baño")["ordenes"])

    # muy corto: no busca
    assert _buscar(client, admin, "a")["clientes"] == []

    # recepción de Suite Florida no ve nada de Suite Aeropuerto
    rec = _usuario(client, admin, ids, "rec.buscador@inversiete.com", "Recepción", "SFL")
    j = _buscar(client, rec, DNI)
    assert j["clientes"] == [] and j["reservas"] == []
    assert _buscar(client, rec, "A-141")["unidades"] == [] and _buscar(client, rec, "BKG-778899")["reservas"] == []
    assert _buscar(client, rec, "grifo del baño")["ordenes"] == []
