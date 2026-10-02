from datetime import date, timedelta

from conftest import login

HOY = date.today()


def d(n=0):
    return (HOY + timedelta(days=n)).isoformat()


def test_auth_required(client):
    assert client.get("/api/activos").status_code == 401
    assert client.post("/api/auth/login", json={"email": "admin@inversiete.com", "password": "x"}).status_code == 401


def test_seed(client, admin, ids):
    a = ids["assets"]
    assert set(a) == {"BAB35", "SFL", "SAE"}
    assert a["SFL"]["num_unidades"] == 325
    assert a["SAE"]["num_unidades"] == 300
    assert a["BAB35"]["modalidad"] == "alquiler_residencial"
    # gestora / propietaria
    assert (a["BAB35"]["sociedad"], a["BAB35"]["propietaria"]) == ("COMERCIAL DEL CAMPO S.A.", "COMERCIAL DEL CAMPO S.A.")
    for c in ("SFL", "SAE"):
        assert (a[c]["sociedad"], a[c]["propietaria"]) == ("INVERSIETE SA", "COMERCIAL DEL CAMPO S.A.")
    assert len(ids["companies"]) == 4
    me = client.get("/api/auth/me", headers=admin).json()
    assert me["is_superadmin"] and all(me["permisos"].values())


def _new_user(client, admin, email, assignments):
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": email.split("@")[0], "password": "ClaveSegura123", "asignaciones": assignments})
    assert r.status_code == 201, r.text
    return login(client, email, "ClaveSegura123")


def test_recepcion_scoped_to_one_asset(client, admin, ids):
    sfl, sae = ids["assets"]["SFL"]["id"], ids["assets"]["SAE"]["id"]
    rec = _new_user(client, admin, "recepcion.florida@inversiete.com",
                    [{"role_id": ids["roles"]["Recepción"], "asset_id": sfl}])
    visibles = [a["codigo"] for a in client.get("/api/activos", headers=rec).json()]
    assert visibles == ["SFL"]
    units = client.get("/api/unidades", headers=rec).json()
    assert len(units) == 325 and all(u["asset_id"] == sfl for u in units)
    # no puede tocar otro activo, ni administrar, ni ver alquiler residencial
    sae_unit = client.get(f"/api/unidades?asset_id={sae}", headers=admin).json()[0]
    r = client.post("/api/turistico/reservas", headers=rec, json={
        "unit_id": sae_unit["id"], "guest": {"nombre": "X"}, "fecha_entrada": d(1), "fecha_salida": d(2)})
    assert r.status_code == 403
    assert client.get("/api/admin/usuarios", headers=rec).status_code == 403
    assert client.get("/api/alquiler/contratos", headers=rec).json() == []
    assert client.post("/api/activos", headers=rec, json={
        "company_id": 1, "codigo": "X", "nombre": "X", "modalidad": "apartamentos_turisticos"}).status_code == 403
    me = client.get("/api/auth/me", headers=rec).json()
    assert me["permisos"]["reservas.editar"] and not me["permisos"]["alquiler.ver"]


def test_reservation_flow(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    unit = client.get(f"/api/unidades?asset_id={sfl}&q=SF-010", headers=admin).json()[0]
    body = {"unit_id": unit["id"], "guest": {"nombre": "Ana", "apellidos": "López"}, "canal": "booking",
            "fecha_entrada": d(0), "fecha_salida": d(3), "adultos": 2, "importe_total": 360}
    r = client.post("/api/turistico/reservas", headers=admin, json=body)
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["noches"] == 3
    # solape rechazado; contiguo permitido
    clash = client.post("/api/turistico/reservas", headers=admin, json={**body, "fecha_entrada": d(2), "fecha_salida": d(5)})
    assert clash.status_code == 400
    ok = client.post("/api/turistico/reservas", headers=admin, json={**body, "fecha_entrada": d(3), "fecha_salida": d(5)})
    assert ok.status_code == 201
    # salida anterior a entrada
    assert client.post("/api/turistico/reservas", headers=admin,
                       json={**body, "fecha_entrada": d(10), "fecha_salida": d(9)}).status_code == 422
    # check-in exige datos del parte de viajeros
    assert client.post(f"/api/turistico/reservas/{res['id']}/checkin", headers=admin).status_code == 400
    guest = client.get("/api/terceros?tipo=huesped&q=Ana", headers=admin).json()[0]
    upd = {**{k: guest[k] for k in ("company_id", "tipo", "nombre", "apellidos")},
           "documento_tipo": "DNI", "documento_num": "12345678Z", "nacionalidad": "ESP", "fecha_nacimiento": "1990-01-01"}
    assert client.put(f"/api/terceros/{guest['id']}", headers=admin, json=upd).status_code == 200
    assert client.post(f"/api/turistico/reservas/{res['id']}/checkin", headers=admin).json()["estado"] == "checkin"
    panel = {a["codigo"]: a for a in client.get("/api/panel", headers=admin).json()["activos"]}
    assert panel["SFL"]["ocupacion_hoy"] > 0 and panel["SFL"]["llegadas_hoy"] >= 1
    assert client.post(f"/api/turistico/reservas/{res['id']}/checkout", headers=admin).json()["estado"] == "checkout"
    u = client.get(f"/api/unidades?asset_id={sfl}&q=SF-010", headers=admin).json()[0]
    assert u["estado"] == "pendiente_limpieza"
    assert client.post(f"/api/unidades/{u['id']}/limpia", headers=admin).json()["estado"] == "disponible"
    disp = client.get(f"/api/turistico/disponibilidad?asset_id={sfl}&desde={d(3)}&hasta={d(4)}", headers=admin).json()
    assert disp["libres"] == 324
    plan = client.get(f"/api/turistico/planning?asset_id={sfl}&dias=7", headers=admin).json()
    assert len(plan["unidades"]) == 325


def test_residential_lease_and_charges(client, admin, ids):
    bab = ids["assets"]["BAB35"]["id"]
    r = client.post("/api/unidades/masivo", headers=admin, json={
        "asset_id": bab, "prefijo": "1", "desde": 1, "hasta": 4, "digitos": 2, "tipologia": "Vivienda 2D"})
    assert r.json() == {"creadas": 4, "omitidas": 0}
    unit = client.get(f"/api/unidades?asset_id={bab}", headers=admin).json()[0]
    # contrato que empieza el día 16 de un mes de 30 días -> recibo prorrateado 15/30
    lease = client.post("/api/alquiler/contratos", headers=admin, json={
        "unit_id": unit["id"], "tenant": {"nombre": "Luis", "apellidos": "Pérez", "documento_num": "00000000T"},
        "fecha_inicio": "2026-09-16", "renta_mensual": 1200, "fianza": 1200, "dia_pago": 5})
    assert lease.status_code == 201, lease.text
    lid = lease.json()["id"]
    assert client.post("/api/alquiler/contratos", headers=admin, json={
        "unit_id": unit["id"], "tenant_id": lease.json()["tenant_id"], "fecha_inicio": "2026-12-01",
        "renta_mensual": 1000}).status_code == 400  # solape
    # contratos solo en activos residenciales
    sfl_unit = client.get(f"/api/unidades?asset_id={ids['assets']['SFL']['id']}", headers=admin).json()[0]
    assert client.post("/api/alquiler/contratos", headers=admin, json={
        "unit_id": sfl_unit["id"], "tenant": {"nombre": "x"}, "fecha_inicio": "2026-09-01",
        "renta_mensual": 10}).status_code == 400

    assert client.post("/api/alquiler/recibos/generar", headers=admin, json={"periodo": "2026-09"}).json()["creados"] == 1
    assert client.post("/api/alquiler/recibos/generar", headers=admin, json={"periodo": "2026-09"}).json()["creados"] == 0
    rec = client.get("/api/alquiler/recibos?periodo=2026-09", headers=admin).json()[0]
    assert rec["importe"] == 600.0
    p = client.post(f"/api/alquiler/recibos/{rec['id']}/cobro", headers=admin, json={"importe": 200}).json()
    assert p["estado"] == "parcial" and p["pendiente"] == 400.0
    assert client.post(f"/api/alquiler/recibos/{rec['id']}/cobro", headers=admin, json={"importe": 500}).status_code == 400
    assert client.post(f"/api/alquiler/recibos/{rec['id']}/cobro", headers=admin, json={"importe": 400}).json()["estado"] == "pagado"
    # actualización de renta
    up = client.post(f"/api/alquiler/contratos/{lid}/actualizar-renta", headers=admin, json={"porcentaje": 2.2}).json()
    assert up["renta_mensual"] == 1226.4
    # fin de contrato libera la unidad
    client.put(f"/api/alquiler/contratos/{lid}", headers=admin, json={"estado": "finalizado"})
    assert client.get(f"/api/unidades?asset_id={bab}&q={unit['codigo']}", headers=admin).json()[0]["estado"] == "disponible"


def test_maintenance(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    unit = client.get(f"/api/unidades?asset_id={sae}", headers=admin).json()[5]
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "unit_id": unit["id"], "titulo": "Fuga termo eléctrico", "categoria": "acs",
        "prioridad": "urgente", "bloquea_unidad": True}).json()
    assert client.get(f"/api/unidades?asset_id={sae}&q={unit['codigo']}", headers=admin).json()[0]["estado"] == "mantenimiento"
    # unidad bloqueada no admite reservas
    assert client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": unit["id"], "guest": {"nombre": "X"}, "fecha_entrada": d(1), "fecha_salida": d(2)}).status_code == 400
    c = client.post(f"/api/mantenimiento/ordenes/{w['id']}/cerrar", headers=admin,
                    json={"solucion": "Sustitución válvula", "coste_real": 85.5}).json()
    assert c["estado"] == "cerrada"
    assert client.get(f"/api/unidades?asset_id={sae}&q={unit['codigo']}", headers=admin).json()[0]["estado"] == "pendiente_limpieza"
    n = client.post("/api/mantenimiento/planes/plantilla", headers=admin,
                    json={"asset_id": sae, "primera_fecha": d(0)}).json()["creados"]
    assert n > 5
    assert client.post("/api/mantenimiento/planes/plantilla", headers=admin, json={"asset_id": sae}).json()["creados"] == 0
    g = client.post("/api/mantenimiento/planes/generar", headers=admin, json={"asset_id": sae}).json()
    assert g["creadas"] == n
    assert client.post("/api/mantenimiento/planes/generar", headers=admin, json={"asset_id": sae}).json()["creadas"] == 0


def test_company_scope_includes_future_assets(client, admin, ids):
    ethosa = ids["companies"]["EMPRESA TURISTICA HOTELERA (ETHOSA)"]
    dir_ = _new_user(client, admin, "director.ethosa@inversiete.com",
                     [{"role_id": ids["roles"]["Dirección Sociedad"], "company_id": ethosa}])
    assert client.get("/api/activos", headers=dir_).json() == []
    r = client.post("/api/activos", headers=dir_, json={
        "company_id": ethosa, "codigo": "NUEVO1", "nombre": "Nuevo activo", "modalidad": "apartamentos_turisticos"})
    assert r.status_code == 201, r.text
    assert [a["codigo"] for a in client.get("/api/activos", headers=dir_).json()] == ["NUEVO1"]
    # no puede crear en otra sociedad ni gestionar usuarios
    assert client.post("/api/activos", headers=dir_, json={
        "company_id": ids["companies"]["INVERSIETE SA"], "codigo": "NUEVO2", "nombre": "x",
        "modalidad": "alquiler_residencial"}).status_code == 403
    assert client.get("/api/admin/usuarios", headers=dir_).status_code == 403


def test_audit_trail(client, admin):
    log = client.get("/api/admin/auditoria", headers=admin).json()
    acciones = {e["accion"] for e in log}
    assert {"login", "crear", "checkin", "cobro", "actualizar_renta"} <= acciones


def test_scope_follows_managing_company(client, admin, ids):
    """El ámbito de sociedad se aplica sobre la sociedad gestora, no sobre la propietaria."""
    ccampo = ids["companies"]["COMERCIAL DEL CAMPO S.A."]
    h = _new_user(client, admin, "director.ccampo@inversiete.com",
                  [{"role_id": ids["roles"]["Dirección Sociedad"], "company_id": ccampo}])
    assert [a["codigo"] for a in client.get("/api/activos", headers=h).json()] == ["BAB35"]
    # nuevo activo sin propietaria explícita -> propietaria = gestora
    r = client.post("/api/activos", headers=h, json={
        "company_id": ccampo, "codigo": "CC2", "nombre": "Prueba", "modalidad": "alquiler_residencial"})
    assert r.json()["propietaria"] == "COMERCIAL DEL CAMPO S.A."
