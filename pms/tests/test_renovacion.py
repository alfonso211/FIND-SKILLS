"""Renovación de estancias al mismo cliente y reutilización de la ficha del cliente que vuelve."""
from datetime import date, timedelta

HOY = date.today()
COMPLETO = {"nombre": "Renata", "apellidos": "Vuelve Pronto", "documento_tipo": "DNI", "documento_num": "71234567Z",
            "num_soporte": "BAA555555", "nacionalidad": "España", "fecha_nacimiento": "1980-05-05", "sexo": "F",
            "telefono": "611555444", "email": "renata@example.com", "direccion": "C/ Sol 3", "cp": "28013",
            "municipio": "Madrid", "pais": "España"}


def _plaza(client, h, asset_id, codigo):
    return next(u for u in client.get(f"/api/unidades?asset_id={asset_id}&q={codigo}", headers=h).json()
                if u["codigo"] == codigo)


def test_renovar_estancia(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    apto, plaza = _plaza(client, admin, sae, "A-552"), _plaza(client, admin, sae, "S1-150")
    ent, sal = HOY - timedelta(days=35), HOY - timedelta(days=5)  # estancia vencida hace 5 días
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": apto["id"], "localizador": "RN-1", "fecha_entrada": ent.isoformat(), "fecha_salida": sal.isoformat(),
        "importe_total": 900, "guest": {"nombre": "Renata", "telefono": "611555444"}}).json()
    client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": plaza["id"], "localizador": "RN-1-G", "fecha_entrada": ent.isoformat(),
        "fecha_salida": sal.isoformat(), "guest_id": r["guest_id"]})
    for rid in (r["id"],):  # alojada (check-in hecho), como las cargadas del PMS anterior
        client.put(f"/api/turistico/reservas/{rid}", headers=admin, json={"estado": "checkin"})
    g = client.get(f"/api/turistico/reservas?asset_id={sae}&q=RN-1-G", headers=admin).json()[0]
    client.put(f"/api/turistico/reservas/{g['id']}", headers=admin, json={"estado": "checkin"})

    info = client.get(f"/api/turistico/reservas/{r['id']}/renovacion", headers=admin).json()
    assert info["desde"] == sal.isoformat() and info["hasta"] == (sal + timedelta(days=30)).isoformat()
    assert info["pendiente"] and info["garajes"] == ["S1-150"]
    nueva_salida = (sal + timedelta(days=30)).isoformat()
    falta = client.post(f"/api/turistico/reservas/{r['id']}/renovar", headers=admin,
                        json={"fecha_salida": nueva_salida, "importe_total": 900})
    assert falta.status_code == 400 and "complete los datos" in falta.json()["detail"]

    # se completan los datos del cliente (escaneo o ficha) y ya se puede renovar
    guest = client.get("/api/terceros?tipo=huesped&q=Renata", headers=admin).json()[0]
    client.put(f"/api/terceros/{guest['id']}", headers=admin, json={**COMPLETO, "company_id": guest["company_id"],
                                                                     "tipo": "huesped"})
    client.post(f"/api/turistico/reservas/{r['id']}/contrato", headers=admin, json={
        "fecha_firma": HOY.isoformat(), "fianza": 300, "motivo": ["laboral"], "acreditacion": ["dni"],
        "solo_guardar": True})
    ren = client.post(f"/api/turistico/reservas/{r['id']}/renovar", headers=admin,
                      json={"fecha_salida": nueva_salida, "importe_total": 900})
    assert ren.status_code == 201, ren.text
    n = ren.json()
    assert n["localizador"] == "RN-1/R1" and n["estado"] == "checkin" and n["guest_id"] == r["guest_id"]
    assert (n["fecha_entrada"], n["fecha_salida"]) == (sal.isoformat(), nueva_salida) and n["importe_pagado"] == 0
    # la estancia anterior queda cerrada sin pasar por limpieza; ya no figura como vencida
    ant = client.get(f"/api/turistico/reservas?asset_id={sae}&q=RN-1", headers=admin).json()
    est = {x["localizador"]: x["estado"] for x in ant}
    assert est["RN-1"] == "checkout" and est["RN-1-G"] == "checkout" and est["RN-1/R1-G"] == "checkin"
    p = client.get(f"/api/plano/{sae}", headers=admin).json()
    celda = next(c for pl in p["plantas"] for c in pl["celdas"] if c.get("codigo") == "A-552")
    assert celda["estado"] == "alquilado" and not celda["vencida"] and celda["reserva"]["localizador"] == "RN-1/R1"
    v = client.get(f"/api/turistico/vencidas?asset_id={sae}", headers=admin).json()
    assert not any(x["localizador"].startswith("RN-1") for x in v["vencidas"])
    # contrato nuevo con los datos del cliente y la fianza de la estancia anterior
    datos = client.get(f"/api/turistico/reservas/{n['id']}/contrato", headers=admin).json()["datos"]
    assert datos["cliente_documento"] == "71234567Z" and datos["fianza"] == 300 and datos["motivo"] == ["laboral"]
    assert datos["localizador"] == "RN-1/R1" and datos["precio_total"] == 900
    # se puede renovar la renovación, pero no dos veces la misma estancia
    r2 = client.post(f"/api/turistico/reservas/{n['id']}/renovar", headers=admin,
                     json={"fecha_salida": (sal + timedelta(days=60)).isoformat()})
    assert r2.status_code == 201 and r2.json()["estado"] == "confirmada"  # empieza más adelante: pasa sola a alojado
    alojados = client.get(f"/api/turistico/hoy?asset_id={sae}", headers=admin).json()["alojados"]
    assert [x["localizador"] for x in alojados if x["unidad"] == "A-552"] == ["RN-1/R1"]
    assert client.post(f"/api/turistico/reservas/{n['id']}/renovar", headers=admin,
                       json={"fecha_salida": (sal + timedelta(days=90)).isoformat()}).status_code == 400


def test_cliente_que_vuelve(client, admin, ids):
    """Con el mismo documento se reutiliza la ficha (sin duplicar) y su último contrato rellena el nuevo."""
    sfl = ids["assets"]["SFL"]["id"]
    u = _plaza(client, admin, sfl, "P3-4A")
    primera = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": u["id"], "fecha_entrada": (HOY + timedelta(days=100)).isoformat(),
        "fecha_salida": (HOY + timedelta(days=103)).isoformat(), "guest": {**COMPLETO, "documento_num": "52345678W",
                                                                          "nombre": "Vuelve"}}).json()
    client.post(f"/api/turistico/reservas/{primera['id']}/contrato", headers=admin, json={
        "fecha_firma": HOY.isoformat(), "motivo": ["turismo"], "acreditacion": ["dni"], "fianza": 150,
        "solo_guardar": True})
    otra = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": u["id"], "fecha_entrada": (HOY + timedelta(days=200)).isoformat(),
        "fecha_salida": (HOY + timedelta(days=202)).isoformat(),
        "guest": {"nombre": "Vuelve", "documento_num": "52345678w", "telefono": "699000111"}}).json()
    assert otra["guest_id"] == primera["guest_id"]
    datos = client.get(f"/api/turistico/reservas/{otra['id']}/contrato", headers=admin).json()["datos"]
    assert datos["motivo"] == ["turismo"] and datos["cliente_movil"] == "699000111" and not datos.get("fianza")
