"""Plano interactivo de Suite Aeropuerto: estados por colores, ficha del apartamento, bloqueos y zonas comunes."""
from datetime import date, timedelta

from conftest import login

HOY = date.today()


def _unidad(client, h, sae, codigo):
    return [u for u in client.get(f"/api/unidades?asset_id={sae}&q={codigo}", headers=h).json() if u["codigo"] == codigo][0]


def _celda(plano, codigo):
    return [c for p in plano["plantas"] for c in p["celdas"] if c.get("codigo") == codigo][0]


def test_plano_y_estados(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    assert [a["codigo"] for a in client.get("/api/plano/activos", headers=admin).json()] == ["SAE"]
    assert client.get(f"/api/plano/{ids['assets']['SFL']['id']}", headers=admin).status_code == 404  # aún sin plano

    # tipologías de la ficha de apartamentos
    assert _unidad(client, admin, sae, "A-127")["dormitorios"] == 2
    assert _unidad(client, admin, sae, "B-213")["tipologia"] == "Apartamento 1 dormitorio con terraza grande"
    assert _unidad(client, admin, sae, "A-451")["tipologia"] == "Apartamento 1 dormitorio grande"

    # alojado (check-in), reserva pendiente de llegada y bloqueo
    alojado = _unidad(client, admin, sae, "B-305")
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": alojado["id"], "localizador": "PLANO-1", "fecha_entrada": HOY.isoformat(),
        "fecha_salida": (HOY + timedelta(days=2)).isoformat(),
        "guest": {"nombre": "Rosa", "apellidos": "Plano", "documento_num": "22222222J", "nacionalidad": "ESP",
                  "fecha_nacimiento": "1980-01-01", "telefono": "611222333"}}).json()
    assert client.post(f"/api/turistico/reservas/{r['id']}/checkin", headers=admin).status_code == 200
    reservado = _unidad(client, admin, sae, "B-306")
    client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": reservado["id"], "localizador": "PLANO-2", "fecha_entrada": HOY.isoformat(),
        "fecha_salida": (HOY + timedelta(days=1)).isoformat(), "guest": {"nombre": "Llega Hoy"}})

    p = client.get(f"/api/plano/{sae}", headers=admin).json()
    assert [x["planta"] for x in p["plantas"]] == ["1", "2", "3", "4", "5"]
    assert [x["resumen"]["total"] for x in p["plantas"]] == [48, 60, 64, 64, 64]
    assert not any(c["t"] == "falta" for x in p["plantas"] for c in x["celdas"])
    c305, c306 = _celda(p, "B-305"), _celda(p, "B-306")
    assert c305["estado"] == "alquilado" and c305["reserva"]["huesped"] == "Rosa Plano"
    assert c306["estado"] == "reserva" and c306["reserva"]["localizador"] == "PLANO-2"
    assert _celda(p, "A-127")["tipo"] == "2d" and _celda(p, "B-111")["tipo"] == "Est"
    assert _celda(p, "B-213")["tipo"] == "1d TG" and _celda(p, "A-464")["tipo"] == "1d G"
    assert (_celda(p, "B-401")["f"], _celda(p, "B-401")["c"]) == (11, 13)  # misma posición que el croquis
    zonas = [c for c in p["plantas"][3]["celdas"] if c["t"] == "zc"]
    assert [z["zona"] for z in zonas] == ["P4-A-PISCINA", "P4-A-JARDIN", "P4-B-PISCINA", "P4-B-JARDIN"]
    # el día siguiente la reserva de PLANO-2 ya ha salido
    manana = client.get(f"/api/plano/{sae}?fecha={(HOY + timedelta(days=1)).isoformat()}", headers=admin).json()
    assert _celda(manana, "B-306")["estado"] == "disponible"

    # bloqueo con motivo: no con huésped alojado; avisa de reservas afectadas
    assert client.post(f"/api/plano/unidades/{alojado['id']}/bloquear", headers=admin,
                       json={"motivo": "Pintura"}).status_code == 400
    b = client.post(f"/api/plano/unidades/{reservado['id']}/bloquear", headers=admin,
                    json={"motivo": "Cambio de suelo del baño", "hasta": (HOY + timedelta(days=5)).isoformat()}).json()
    assert b["estado"] == "bloqueada" and [x["localizador"] for x in b["reservas_afectadas"]] == ["PLANO-2"]
    assert client.post(f"/api/plano/unidades/{reservado['id']}/bloquear", headers=admin,
                       json={"motivo": "Otra vez"}).status_code == 400
    p = client.get(f"/api/plano/{sae}", headers=admin).json()
    assert _celda(p, "B-306")["estado"] == "bloqueado"

    # ficha: todo lo del apartamento
    f = client.get(f"/api/plano/unidades/{reservado['id']}/ficha", headers=admin).json()
    assert f["estado"] == "bloqueado" and f["bloqueos"][0]["motivo"] == "Cambio de suelo del baño"
    assert f["bloqueos"][0]["levantado"] is None and f["reservas"][0]["localizador"] == "PLANO-2"
    assert f["puede"] == {"reservar": True, "bloquear": True, "incidencia": True}
    assert client.post(f"/api/plano/unidades/{reservado['id']}/desbloquear", headers=admin,
                       json={"nota": "Obra terminada"}).json()["estado"] == "disponible"
    f = client.get(f"/api/plano/unidades/{reservado['id']}/ficha", headers=admin).json()
    assert f["bloqueos"][0]["nota_levantado"] == "Obra terminada" and f["estado"] == "reserva"
    f = client.get(f"/api/plano/unidades/{alojado['id']}/ficha", headers=admin).json()
    assert f["actual"]["huesped"] == "Rosa Plano" and f["reservas"][0]["telefono"] == "611222333"
    client.post(f"/api/turistico/reservas/{r['id']}/checkout", headers=admin)


def test_zonas_comunes_y_permisos(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "zona": "P4-B-JARDIN", "titulo": "Fluorescente fundido en pasillo", "categoria": "electricidad"})
    assert w.status_code == 201, w.text
    assert w.json()["zona_nombre"] == "Planta 4ª · Bloque B · lado jardín"
    assert client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "zona": "P9-X", "titulo": "x"}).status_code == 400
    u = _unidad(client, admin, sae, "B-401")
    assert client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "zona": "P4-B-JARDIN", "unit_id": u["id"], "titulo": "x"}).status_code == 400
    z = client.get(f"/api/plano/{sae}/zonas/P4-B-JARDIN", headers=admin).json()
    assert z["nombre"] == "Planta 4ª · Bloque B · lado jardín" and z["incidencias"][0]["titulo"].startswith("Fluorescente")
    p = client.get(f"/api/plano/{sae}", headers=admin).json()
    zc = [c for c in p["plantas"][3]["celdas"] if c.get("zona") == "P4-B-JARDIN"][0]
    assert zc["ot"] == 1
    parte = client.get(f"/api/mantenimiento/ordenes/{w.json()['id']}/parte", headers=admin)
    assert parte.status_code == 200

    # limpieza: ve el plano y abre incidencias, pero no reserva ni bloquea
    email = "limpieza.plano@inversiete.com"
    client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": "Limpieza", "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"]["Gobernanta / Limpieza"], "asset_id": sae}]})
    h = login(client, email, "Provisional1")
    client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    p = client.get(f"/api/plano/{sae}", headers=h).json()
    assert p["puede"] == {"reservar": False, "bloquear": False, "incidencia": True, "ver_reservas": False,
                          "ver_mantenimiento": True}
    assert "reserva" not in _celda(p, "B-305")  # no ve datos de huéspedes
    f = client.get(f"/api/plano/unidades/{u['id']}/ficha", headers=h).json()
    assert "reservas" not in f and "facturas" not in f and "incidencias" in f
    assert client.post(f"/api/plano/unidades/{u['id']}/bloquear", headers=h, json={"motivo": "Prueba"}).status_code == 403
    assert client.post("/api/mantenimiento/ordenes", headers=h, json={
        "asset_id": sae, "unit_id": u["id"], "titulo": "Grifo gotea"}).status_code == 201
    # sin acceso al activo
    email = "recepcion.plano.sfl@inversiete.com"
    client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": "x", "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"]["Recepción"], "asset_id": ids["assets"]["SFL"]["id"]}]})
    h = login(client, email, "Provisional1")
    client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    assert client.get(f"/api/plano/{sae}", headers=h).status_code == 403
    assert client.get("/api/plano/activos", headers=h).json() == []
