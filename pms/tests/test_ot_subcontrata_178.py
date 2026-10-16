"""1.78 · Mantenimiento abre desde el parte diario una OT para una subcontrata (instalaciones y averías graves, con
el motivo del checklist), sin foto; la subcontrata la deja finalizada y la cierra recepción. Datos ZZ-PRUEBA-178."""
from datetime import date, timedelta

from conftest import trabajo_realizado
from test_pms import _new_user

Z = "ZZ-PRUEBA-178"


def test_mantenimiento_abre_ot_a_subcontrata(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    rol = ids["roles"]
    mto = _new_user(client, admin, "mto.178@inversiete.es", [{"role_id": rol["Técnico Mantenimiento"], "asset_id": sae}])
    rec = _new_user(client, admin, "rec.178@inversiete.es", [{"role_id": rol["Recepción"], "asset_id": sae}])
    lim = _new_user(client, admin, "lim.178@inversiete.es", [{"role_id": rol["Gobernanta / Limpieza"], "asset_id": sae}])
    prov = client.post("/api/proveedores", headers=admin, json={"nombre": f"{Z} Electrodomésticos SL",
                                                                "email": "sat.178@example.com"}).json()
    vencida = client.post("/api/proveedores", headers=admin, json={
        "nombre": f"{Z} Sin CAE SL", "cae_vence": (date.today() - timedelta(days=3)).isoformat()}).json()
    u = [x for x in client.get(f"/api/unidades?asset_id={sae}", headers=admin).json() if x["uso"] != "garaje"][-7]

    motivos = client.get("/api/mantenimiento/motivos-subcontrata", headers=mto).json()
    claves = {m["clave"]: m for m in motivos}
    assert {"lavadora", "frigorifico", "termo", "aire", "otra"} <= set(claves)
    assert claves["termo"]["categoria"] == "acs" and claves["lavadora"]["grupo"] == "Electrodomésticos"
    assert client.get("/api/mantenimiento/motivos-subcontrata", headers=lim).status_code == 403

    url = "/api/mantenimiento/ordenes-subcontrata"
    base = {"asset_id": sae, "unit_id": u["id"], "motivo": "lavadora", "detalle": "No centrifuga", "proveedor_id": prov["id"]}
    # mantenimiento no abre OT normales, pero sí estas; limpieza no
    assert client.post("/api/mantenimiento/ordenes", headers=mto, json={"asset_id": sae, "titulo": "x"}).status_code == 403
    assert client.post(url, headers=lim, json=base).status_code == 403
    # motivo de la lista; «otra» con detalle; lugar; subcontrata válida y con CAE al día
    assert client.post(url, headers=mto, json={**base, "motivo": "pintar"}).status_code == 400
    assert client.post(url, headers=mto, json={**base, "motivo": "otra", "detalle": ""}).status_code == 400
    assert client.post(url, headers=mto, json={**base, "unit_id": None}).status_code == 400
    r = client.post(url, headers=mto, json={**base, "proveedor_id": vencida["id"]})
    assert r.status_code == 400 and "CAE" in r.json()["detail"]

    r = client.post(url, headers=mto, json={**base, "bloquea_unidad": True})
    assert r.status_code == 201, r.text
    w = r.json()
    assert w["asignacion"] == "subcontrata" and w["proveedor_id"] == prov["id"] and w["estado"] == "asignada"
    assert w["categoria"] == "electrodomesticos" and w["titulo"] == "Lavadora" and w["motivo_subcontrata"] == "lavadora"
    assert w["exige_foto_antes"] is False and w["prioridad"] == "alta" and "No centrifuga" in w["descripcion"]
    est = next(x for x in client.get(f"/api/unidades?asset_id={sae}", headers=admin).json() if x["id"] == u["id"])
    assert est["estado"] == "mantenimiento"
    # recepción tiene el aviso en la campana, con enlace a la OT
    lista = client.get("/api/notificaciones", headers=rec).json()
    assert any("OT a subcontrata" in a["titulo"] and a["vista"] == f"ordenes?id={w['id']}" for a in lista)
    # parte PDF para la subcontrata
    assert client.get(f"/api/mantenimiento/ordenes/{w['id']}/parte", headers=mto).status_code == 200

    # la subcontrata termina (sin foto obligatoria) y la cierra recepción; mantenimiento no la cierra
    fin = trabajo_realizado(client, mto, w["id"], "Cambio de bomba de desagüe", foto=False)
    assert fin.status_code == 200, fin.text
    assert fin.json()["estado"] == "pendiente_cierre"
    sb = f"/api/mantenimiento/ordenes/{w['id']}"
    assert client.post(f"{sb}/cerrar", headers=mto, json={}).status_code == 403
    c = client.post(f"{sb}/cerrar", headers=rec, json={})
    assert c.status_code == 200 and c.json()["estado"] == "cerrada", c.text

    # «otra» con detalle y urgente: prioridad urgente, en zona común
    r = client.post(url, headers=mto, json={"asset_id": sae, "ubicacion": "Sala de calderas", "motivo": "otra",
                                            "detalle": "Bomba de recirculación ruidosa", "urgente": True,
                                            "proveedor_id": prov["id"]})
    assert r.status_code == 201 and r.json()["prioridad"] == "urgente" and r.json()["unit_id"] is None
