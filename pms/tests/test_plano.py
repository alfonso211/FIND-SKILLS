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
    assert [a["codigo"] for a in client.get("/api/plano/activos", headers=admin).json()] == ["SAE", "SFL"]
    assert client.get(f"/api/plano/{ids['assets']['BAB35']['id']}", headers=admin).status_code == 404  # sin plano

    # tipologías de la ficha de apartamentos
    assert _unidad(client, admin, sae, "A-127")["dormitorios"] == 2
    assert _unidad(client, admin, sae, "B-213")["tipologia"] == "Apartamento 1 dormitorio con terraza grande"
    assert _unidad(client, admin, sae, "A-451")["tipologia"] == "Apartamento 1 dormitorio grande"

    # alojado (check-in), reserva pendiente de llegada y bloqueo
    alojado = _unidad(client, admin, sae, "B-305")
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": alojado["id"], "localizador": "PLANO-1", "fecha_entrada": HOY.isoformat(),
        "fecha_salida": (HOY + timedelta(days=2)).isoformat(),
        "guest": {"nombre": "Rosa", "apellidos": "Plano Gil", "documento_tipo": "DNI", "documento_num": "22222222J",
                  "num_soporte": "BAA000000", "nacionalidad": "ESP", "fecha_nacimiento": "1980-01-01", "sexo": "F",
                  "telefono": "611222333", "direccion": "C/ Mayor 1", "cp": "28013", "municipio": "Madrid",
                  "pais": "España"}}).json()
    assert client.post(f"/api/turistico/reservas/{r['id']}/checkin", headers=admin).status_code == 200
    reservado = _unidad(client, admin, sae, "B-306")
    client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": reservado["id"], "localizador": "PLANO-2", "fecha_entrada": HOY.isoformat(),
        "fecha_salida": (HOY + timedelta(days=1)).isoformat(), "guest": {"nombre": "Llega Hoy"}})

    p = client.get(f"/api/plano/{sae}", headers=admin).json()
    # miniaturas: primero el garaje exterior, después el interior y luego las plantas
    assert [x["planta"] for x in p["plantas"]] == ["0", "-1", "1", "2", "3", "4", "5"]
    assert [x["etiqueta"] for x in p["plantas"][:2]] == ["Garaje exterior", "Garaje interior (sótano -1)"]
    assert [x["resumen"]["total"] for x in p["plantas"]] == [64, 178, 48, 60, 64, 64, 64]
    assert [(x["columnas"], x["filas"]) for x in p["plantas"][:2]] == [(39, 23), (40, 24)]
    assert not any(c["t"] == "falta" for x in p["plantas"] for c in x["celdas"])
    c305, c306 = _celda(p, "B-305"), _celda(p, "B-306")
    assert c305["estado"] == "alquilado" and c305["reserva"]["huesped"] == "Rosa Plano Gil"
    assert c306["estado"] == "reserva" and c306["reserva"]["localizador"] == "PLANO-2"
    assert _celda(p, "A-127")["tipo"] == "2d" and _celda(p, "B-111")["tipo"] == "Est"
    assert _celda(p, "B-213")["tipo"] == "1d TG" and _celda(p, "A-464")["tipo"] == "1d G"
    assert (_celda(p, "B-401")["f"], _celda(p, "B-401")["c"]) == (11, 13)  # misma posición que el croquis
    zonas = [c for c in p["plantas"][5]["celdas"] if c["t"] == "zc"]
    assert [z["zona"] for z in zonas] == ["P4-A-PISCINA", "P4-A-ENTRADA", "P4-B-PISCINA", "P4-B-ENTRADA"]
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
    assert f["puede"] == {"reservar": True, "alquilar": False, "bloquear": True, "incidencia": True}
    assert client.post(f"/api/plano/unidades/{reservado['id']}/desbloquear", headers=admin,
                       json={"nota": "Obra terminada"}).json()["estado"] == "disponible"
    f = client.get(f"/api/plano/unidades/{reservado['id']}/ficha", headers=admin).json()
    assert f["bloqueos"][0]["nota_levantado"] == "Obra terminada" and f["estado"] == "reserva"
    f = client.get(f"/api/plano/unidades/{alojado['id']}/ficha", headers=admin).json()
    assert f["actual"]["huesped"] == "Rosa Plano Gil" and f["reservas"][0]["telefono"] == "611222333"
    client.post(f"/api/turistico/reservas/{r['id']}/checkout", headers=admin)


def test_zonas_comunes_y_permisos(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "zona": "P4-B-ENTRADA", "titulo": "Fluorescente fundido en pasillo", "categoria": "electricidad"})
    assert w.status_code == 201, w.text
    assert w.json()["zona_nombre"] == "Planta 4ª · Bloque B (izquierda) · lado entrada"
    assert client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "zona": "P9-X", "titulo": "x"}).status_code == 400
    u = _unidad(client, admin, sae, "B-401")
    assert client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "zona": "P4-B-ENTRADA", "unit_id": u["id"], "titulo": "x"}).status_code == 400
    z = client.get(f"/api/plano/{sae}/zonas/P4-B-ENTRADA", headers=admin).json()
    assert z["nombre"] == "Planta 4ª · Bloque B (izquierda) · lado entrada" and z["incidencias"][0]["titulo"].startswith("Fluorescente")
    p = client.get(f"/api/plano/{sae}", headers=admin).json()
    zc = [c for c in p["plantas"][5]["celdas"] if c.get("zona") == "P4-B-ENTRADA"][0]
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
    assert [a["codigo"] for a in client.get("/api/plano/activos", headers=h).json()] == ["SFL"]  # solo el suyo


def test_plano_suite_florida_y_garajes(client, admin, ids):
    """Suite Florida: sótanos -2 y -1 (plazas de garaje) y plantas 1ª a 5ª, con los portales en las esquinas."""
    from conftest import domicilio_fiscal
    domicilio_fiscal(client, admin)
    sfl = ids["assets"]["SFL"]["id"]
    p = client.get(f"/api/plano/{sfl}", headers=admin).json()
    assert [x["planta"] for x in p["plantas"]] == ["-2", "-1", "1", "2", "3", "4", "5"]  # orden de las miniaturas
    assert [x["etiqueta"] for x in p["plantas"][:3]] == ["Sótano -2", "Sótano -1", "1ª planta"]
    assert [x["resumen"]["total"] for x in p["plantas"]] == [96, 251, 65, 65, 65, 65, 65]
    assert [(x["columnas"], x["filas"]) for x in p["plantas"][1:3]] == [(32, 26), (15, 12)]
    assert not any(c["t"] == "falta" for x in p["plantas"] for c in x["celdas"])
    c = {(x["planta"], d["f"], d["c"]): d for x in p["plantas"] for d in x["celdas"]}
    # 1ª planta: portal 3 arriba a la izquierda, 2 arriba a la derecha, 4 abajo a la izquierda, 1 abajo a la derecha
    assert [c[("1", f, col)]["texto"] for f, col in ((1, 2), (1, 14), (12, 2), (12, 14))] == ["3", "2", "4", "1"]
    assert (c[("1", 1, 3)]["codigo"], c[("1", 1, 3)]["num"], c[("1", 1, 3)]["tipo"]) == ("P3-1H", "H", "2d")
    assert c[("1", 10, 13)]["codigo"] == "P1-1R" and c[("1", 11, 14)]["codigo"] == "P1-1J"
    assert c[("1", 6, 14)]["t"] == "acc"  # la entrada, a la derecha
    # la zona común de cada portal, en la casilla exterior junto a su número
    assert (c[("1", 1, 1)]["zona"], c[("1", 1, 1)]["nombre"]) == ("P1-PORTAL3", "Planta 1ª · Portal 3")
    assert c[("1", 12, 15)]["zona"] == "P1-PORTAL1" and c[("-1", 26, 32)]["nombre"] == "Sótano -1 · Portal 1"
    # garajes, en la posición del croquis
    assert c[("-1", 1, 4)]["codigo"] == "S1-1" and c[("-1", 26, 4)]["codigo"] == "S1-217"
    assert c[("-1", 20, 5)]["codigo"] == "S1-251" and c[("-2", 20, 8)]["codigo"] == "S2-96"
    assert c[("-1", 1, 4)]["tipo"] == "" and c[("-1", 1, 3)]["t"] == "negro"

    # tipologías según el croquis
    u = client.get(f"/api/unidades?asset_id={sfl}&q=P2-3M", headers=admin).json()[0]
    assert (u["tipologia"], u["dormitorios"]) == ("Apartamento 2 dormitorios", 2)

    # una plaza de garaje se reserva y factura como un apartamento, pero al 21 % y sin parte ni contrato
    hoy = date.today()
    dis = client.get(f"/api/turistico/disponibilidad?asset_id={sfl}&desde={hoy + timedelta(days=200)}"
                     f"&hasta={hoy + timedelta(days=201)}", headers=admin).json()
    assert dis["libres"] == 325 and all(x["uso"] == "apartamento" for x in dis["unidades"])
    dis = client.get(f"/api/turistico/disponibilidad?asset_id={sfl}&desde={hoy + timedelta(days=200)}"
                     f"&hasta={hoy + timedelta(days=201)}&uso=garaje", headers=admin).json()
    assert dis["libres"] == 347
    plaza = [x for x in client.get(f"/api/unidades?asset_id={sfl}&q=S1-25", headers=admin).json() if x["codigo"] == "S1-25"][0]
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": plaza["id"], "fecha_entrada": hoy.isoformat(), "fecha_salida": (hoy + timedelta(days=30)).isoformat(),
        "importe_total": 121, "importe_pagado": 121, "guest": {"nombre": "Cliente Garaje"}}).json()
    f = client.get(f"/api/facturas/{r['factura']['id']}", headers=admin).json()
    assert [(x["tipo"], x["tipo_iva"], x["base"]) for x in f["lineas"]] == [("garaje", 21, 100)]
    assert f["lineas"][0]["concepto"].startswith("Alquiler de plaza de garaje · Suite Florida · Sótano -1 plaza 25")
    assert client.post(f"/api/turistico/reservas/{r['id']}/checkin", headers=admin).json()["estado"] == "checkin"
    assert client.get(f"/api/turistico/reservas/{r['id']}/contrato", headers=admin).status_code == 400
    p = client.get(f"/api/plano/{sfl}", headers=admin).json()
    s1 = [x for x in p["plantas"] if x["planta"] == "-1"][0]
    assert s1["resumen"]["alquilado"] >= 1
    panel = {a["codigo"]: a for a in client.get("/api/panel", headers=admin).json()["activos"]}
    assert panel["SFL"]["garajes"] == 347 and panel["SFL"]["garajes_ocupados"] >= 1
    # incidencia en la zona común de un portal del garaje
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sfl, "zona": "S1-PORTAL2", "titulo": "Puerta del ascensor del garaje no cierra"}).json()
    assert w["zona_nombre"] == "Sótano -1 · Portal 2"
    client.post(f"/api/turistico/reservas/{r['id']}/checkout", headers=admin)


def test_garajes_suite_aeropuerto(client, admin, ids):
    """Garaje exterior (64 plazas) e interior, sótano -1 (178 plazas), con sus entradas y salidas de vehículos."""
    sae = ids["assets"]["SAE"]["id"]
    p = client.get(f"/api/plano/{sae}", headers=admin).json()
    ext, s1 = p["plantas"][0], p["plantas"][1]
    num = lambda pl, f, c: next(x for x in pl["celdas"] if (x["f"], x["c"]) == (f, c))  # noqa: E731
    assert num(ext, 1, 1)["codigo"] == "EXT-63" and num(ext, 21, 4)["codigo"] == "EXT-6"
    assert num(ext, 3, 37)["codigo"] == "EXT-37" and num(ext, 23, 1)["codigo"] == "EXT-5"
    assert num(s1, 2, 3)["codigo"] == "S1-186" and num(s1, 24, 38)["codigo"] == "S1-1"
    assert num(s1, 6, 9)["codigo"] == "S1-603" and num(s1, 20, 9)["codigo"] == "S1-601"
    assert num(s1, 16, 30)["codigo"] == "S1-55" and num(s1, 17, 30)["codigo"] == "S1-54"
    assert num(ext, 1, 38)["t"] == "entrada" and num(ext, 2, 38)["t"] == "salida"
    assert num(s1, 2, 33)["t"] == "entrada" and num(s1, 2, 35)["t"] == "salida"
    # las plazas no se confunden con los apartamentos del mismo número (S1-101 / B-101)
    assert num(s1, 15, 15)["codigo"] == "S1-101" and _celda(p, "B-101")["tipo"] != ""
    zonas = [c["zona"] for c in s1["celdas"] if c["t"] == "zc"]
    assert "S1-RAMPA" in zonas and len(zonas) == 5
    # funciona igual que una plaza de Suite Florida: ficha, reserva al 21 % y fuera de la ocupación de apartamentos
    plaza = num(ext, 21, 4)
    ficha = client.get(f"/api/plano/unidades/{plaza['unit_id']}/ficha", headers=admin).json()
    assert ficha["unidad"]["uso"] == "garaje" and ficha["unidad"]["bloque"] == "Garaje exterior"
    dis = client.get(f"/api/turistico/disponibilidad?asset_id={sae}&desde={HOY + timedelta(days=300)}"
                     f"&hasta={HOY + timedelta(days=301)}&uso=garaje", headers=admin).json()
    assert dis["libres"] == 242
