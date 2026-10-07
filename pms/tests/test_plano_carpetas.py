"""Babilonia 35: carpetas por planta, situación de cada vivienda y aviso del contrato pendiente."""
from app.routers import plano as rp


def _vivienda(client, admin, bab, codigo):
    d = client.get(f"/api/plano/{bab}", headers=admin).json()
    return next(u for p in d["plantas"] for u in p["unidades"] if u["codigo"] == codigo)


def test_carpetas(client, admin, ids):
    bab = ids["assets"]["BAB35"]["id"]
    d = client.get(f"/api/plano/{bab}", headers=admin).json()
    assert d["tipo"] == "carpetas" and d["logo"] == "/static/marca/comercial_del_campo-claro.png"
    assert [p["etiqueta"] for p in d["plantas"]][:8] == [
        "Planta baja", "Planta 1ª", "Planta 2ª", "Planta 3ª", "Planta 4ª", "Sótano -1", "Sótano -2", "Sótano -3"]
    baja = d["plantas"][0]
    assert [u["codigo"] for u in baja["unidades"]] == ["BJ-F", "BJ-H", "BJ-I", "BJ-L", "BJ-Q"]
    assert baja["resumen"]["sin_situacion"] == 5 and baja["resumen"]["pendientes"] == 5 and not baja["garaje"]
    st3 = next(p for p in d["plantas"] if p["planta"] == "ST-3")
    assert st3["garaje"] and st3["resumen"]["total"] == 26 and st3["resumen"]["pendientes"] == 0
    assert all(not u["pendiente_situacion"] for u in st3["unidades"])  # las plazas no piden situación


def test_situacion_y_contrato(client, admin, ids, monkeypatch):
    bab = ids["assets"]["BAB35"]["id"]
    uid = _vivienda(client, admin, bab, "BJ-F")["unit_id"]
    f = client.get(f"/api/plano/unidades/{uid}/ficha", headers=admin).json()
    assert f["pendientes"] == {"situacion": True, "contrato": None}
    assert f["puede"]["situacion"] and not f["puede"]["reservar"]  # alquiler residencial: sin reservas
    assert "alquilada" in f["situaciones"] and "otra" in f["situaciones"]
    url = f"/api/plano/unidades/{uid}/situacion"
    assert client.put(url, headers=admin, json={"situacion": "inventada"}).status_code == 400
    assert client.put(url, headers=admin, json={"situacion": "otra"}).status_code == 400  # sin decir cuál
    r = client.put(url, headers=admin, json={"situacion": "otra", "texto": "Pendiente de tasación"}).json()
    assert r["situacion"]["texto"] == "Pendiente de tasación" and r["situacion"]["por"] == "Administrador"
    r = client.put(url, headers=admin, json={"situacion": "reforma_menor"}).json()
    assert r["pendientes"] == {"situacion": False, "contrato": None} and r["situacion"]["texto"] is None
    # alquilada sin contrato: se pide crearlo; «más tarde» lo aplaza hasta mañana
    r = client.put(url, headers=admin, json={"situacion": "alquilada"}).json()
    c = r["pendientes"]["contrato"]
    assert c["lease_id"] is None and c["mostrar"] and c["faltan"][0].startswith("Contrato de alquiler sin crear")
    assert _vivienda(client, admin, bab, "BJ-F")["pendiente_contrato"]
    p = client.post(f"/api/plano/unidades/{uid}/contrato-mas-tarde", headers=admin).json()["pendientes"]
    assert p["contrato"]["mostrar"] is False
    # con contrato creado pero sin completar: sigue pendiente con lo que falta
    lease = client.post("/api/alquiler/contratos", headers=admin, json={
        "unit_id": uid, "tenant": {"nombre": "Inquilino", "apellidos": "Carpeta Prueba", "documento_num": "00000003A"},
        "fecha_inicio": "2026-01-01", "renta_mensual": 900, "estado": "borrador"})  # borrador: no altera la ocupación
    assert lease.status_code == 201, lease.text
    f = client.get(f"/api/plano/unidades/{uid}/ficha", headers=admin).json()
    assert f["pendientes"]["contrato"]["lease_id"] == lease.json()["id"] and f["pendientes"]["contrato"]["faltan"]
    assert [x["id"] for x in f["contratos"]] == [lease.json()["id"]]
    # contrato completo: deja de pedirse
    monkeypatch.setattr(rp.cv, "faltan", lambda db, lease: [])
    f = client.get(f"/api/plano/unidades/{uid}/ficha", headers=admin).json()
    assert f["pendientes"] == {"situacion": False, "contrato": None}


def test_garaje_sin_situacion(client, admin, ids):
    bab = ids["assets"]["BAB35"]["id"]
    uid = _vivienda(client, admin, bab, "ST3-03")["unit_id"]
    f = client.get(f"/api/plano/unidades/{uid}/ficha", headers=admin).json()
    assert "situaciones" not in f and "pendientes" not in f
    assert client.put(f"/api/plano/unidades/{uid}/situacion", headers=admin,
                      json={"situacion": "alquilada"}).status_code == 400
