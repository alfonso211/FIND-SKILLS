from datetime import date, timedelta

from conftest import domicilio_fiscal, login

INICIAL = "00000000"

HOY = date.today()


def d(n=0):
    return (HOY + timedelta(days=n)).isoformat()


def test_auth_required(client):
    assert client.get("/api/activos").status_code == 401
    assert client.post("/api/auth/login", json={"email": "admin@inversiete.com", "password": "x"}).status_code == 401


def test_seed(client, admin, ids):
    a = ids["assets"]
    assert set(a) == {"BAB35", "SFL", "SAE"}
    assert a["SFL"]["num_unidades"] == 672  # 325 apartamentos + 347 plazas de garaje (sótanos -1 y -2)
    assert a["SAE"]["num_unidades"] == 300
    assert a["BAB35"]["num_unidades"] == 53
    assert (a["SFL"]["num_registro_turistico"], a["SFL"]["direccion"]) == ("AM 265", "Calle Campezo 2")
    assert (a["SAE"]["num_registro_turistico"], a["SAE"]["direccion"]) == ("AM 259", "Calle Campezo 8")
    bab = client.get(f"/api/unidades?asset_id={a['BAB35']['id']}", headers=admin).json()
    viv = [u for u in bab if u["uso"] == "vivienda"]
    gar = [u for u in bab if u["uso"] == "garaje"]
    assert len(viv) == 20 and len(gar) == 33
    assert round(sum(u["cuota_comunidad"] for u in viv), 2) == 1950.20  # cuadra con el listado de comunidad
    assert round(sum(u["cuota_comunidad"] for u in gar), 2) == 629.64
    assert client.get(f"/api/unidades/bloques?asset_id={a['SFL']['id']}", headers=admin).json() == \
        ["Portal 1", "Portal 2", "Portal 3", "Portal 4", "Sótano -1", "Sótano -2"]
    assert client.get(f"/api/unidades/bloques?asset_id={a['SAE']['id']}", headers=admin).json() == ["Bloque A", "Bloque B"]
    sae = client.get(f"/api/unidades?asset_id={a['SAE']['id']}&q=A-148", headers=admin).json()[0]
    assert sae["tipologia"] == "Apartamento 2 dormitorios" and sae["dormitorios"] == 2
    assert a["BAB35"]["modalidad"] == "alquiler_residencial"
    # gestora / propietaria
    assert (a["BAB35"]["sociedad"], a["BAB35"]["propietaria"]) == ("COMERCIAL DEL CAMPO S.A.", "COMERCIAL DEL CAMPO S.A.")
    for c in ("SFL", "SAE"):
        assert (a[c]["sociedad"], a[c]["propietaria"]) == ("INVERSIETE S.A.", "COMERCIAL DEL CAMPO S.A.")
    assert len(ids["companies"]) == 4
    cifs = {c["nombre"]: c["cif"] for c in client.get("/api/sociedades", headers=admin).json()}
    assert cifs["INVERSIETE S.A."] == "A78072915" and cifs["COMERCIAL DEL CAMPO S.A."] == "A28362309"
    me = client.get("/api/auth/me", headers=admin).json()
    assert me["is_superadmin"] and all(me["permisos"].values())


def _first_login(client, email, provisional, nueva="ClaveDefinitiva2026"):
    h = login(client, email, provisional)
    r = client.post("/api/auth/password", headers=h, json={"actual": provisional, "nueva": nueva})
    assert r.status_code == 200, r.text
    return h


def _new_user(client, admin, email, assignments):
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": email.split("@")[0], "password": "Provisional1", "asignaciones": assignments})
    assert r.status_code == 201, r.text
    return _first_login(client, email, "Provisional1")


def test_recepcion_scoped_to_one_asset(client, admin, ids):
    sfl, sae = ids["assets"]["SFL"]["id"], ids["assets"]["SAE"]["id"]
    rec = _new_user(client, admin, "recepcion.florida@inversiete.com",
                    [{"role_id": ids["roles"]["Recepción"], "asset_id": sfl}])
    visibles = [a["codigo"] for a in client.get("/api/activos", headers=rec).json()]
    assert visibles == ["SFL"]
    units = client.get("/api/unidades", headers=rec).json()
    assert len(units) == 672 and all(u["asset_id"] == sfl for u in units)
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
    unit = client.get(f"/api/unidades?asset_id={sfl}&q=P1-1J", headers=admin).json()[0]
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
    upd = {**{k: guest[k] for k in ("company_id", "tipo", "nombre")}, "apellidos": "López Ruiz",
           "documento_tipo": "DNI", "documento_num": "12345678Z", "num_soporte": "BAA123456", "nacionalidad": "ESP",
           "fecha_nacimiento": "1990-01-01", "sexo": "F", "telefono": "600111222", "direccion": "C/ Alcalá 10, 3º B",
           "cp": "28009", "municipio": "Madrid", "pais": "España"}
    assert client.put(f"/api/terceros/{guest['id']}", headers=admin, json=upd).json()["municipio_ine"] == "28079"
    # reserva para 2: falta registrar al segundo ocupante
    falta = client.post(f"/api/turistico/reservas/{res['id']}/checkin", headers=admin)
    assert falta.status_code == 400 and "1 ocupante(s) por registrar" in falta.json()["detail"]
    hijo = {"contact": {"nombre": "Pablo", "apellidos": "López Ruiz", "fecha_nacimiento": d(-365 * 6),
                        "sexo": "M", "nacionalidad": "España", "direccion": "C/ Alcalá 10, 3º B", "cp": "28009",
                        "municipio": "Madrid", "pais": "España"}}
    sin_parentesco = client.post(f"/api/turistico/reservas/{res['id']}/ocupantes", headers=admin, json=hijo)
    assert sin_parentesco.status_code == 400  # menor sin parentesco
    o = client.post(f"/api/turistico/reservas/{res['id']}/ocupantes", headers=admin, json={**hijo, "parentesco": "HJ"})
    assert o.status_code == 201, o.text
    assert o.json()["menor"] and o.json()["faltan"] == []  # menor sin documento: registro manual válido
    lista = client.get(f"/api/turistico/reservas/{res['id']}/ocupantes", headers=admin).json()
    assert [x["titular"] for x in lista["ocupantes"]] == [True, False] and lista["pendiente"] == []
    contrato = client.get(f"/api/turistico/reservas/{res['id']}/contrato", headers=admin).json()["datos"]
    assert contrato["ocupantes"].splitlines() == [
        "Ana López Ruiz (DNI 12345678Z)", "Pablo López Ruiz (menor, 5 años, sin documento, hijo/a de un adulto de la reserva)"]
    assert client.post(f"/api/turistico/reservas/{res['id']}/checkin", headers=admin).json()["estado"] == "checkin"
    panel = {a["codigo"]: a for a in client.get("/api/panel", headers=admin).json()["activos"]}
    assert panel["SFL"]["ocupacion_hoy"] > 0 and panel["SFL"]["llegadas_hoy"] >= 1
    assert client.post(f"/api/turistico/reservas/{res['id']}/checkout", headers=admin).json()["estado"] == "checkout"
    u = client.get(f"/api/unidades?asset_id={sfl}&q=P1-1J", headers=admin).json()[0]
    assert u["estado"] == "pendiente_limpieza"
    assert client.post(f"/api/unidades/{u['id']}/limpia", headers=admin).json()["estado"] == "disponible"
    disp = client.get(f"/api/turistico/disponibilidad?asset_id={sfl}&desde={d(3)}&hasta={d(4)}", headers=admin).json()
    assert disp["libres"] == 324
    plan = client.get(f"/api/turistico/planning?asset_id={sfl}&dias=7", headers=admin).json()
    assert len(plan["unidades"]) == 325
    p1 = client.get(f"/api/turistico/planning?asset_id={sfl}&dias=7&bloque=Portal 1", headers=admin).json()
    assert len(p1["unidades"]) == 90 and any(u["reservas"] for u in p1["unidades"])


def test_residential_lease_and_charges(client, admin, ids):
    bab = ids["assets"]["BAB35"]["id"]
    r = client.post("/api/unidades/masivo", headers=admin, json={
        "asset_id": bab, "prefijo": "T-", "desde": 1, "hasta": 4, "digitos": 2, "uso": "trastero"})
    assert r.json() == {"creadas": 4, "omitidas": 0}
    unit = client.get(f"/api/unidades?asset_id={bab}&uso=vivienda", headers=admin).json()[0]
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

    panel = {a["codigo"]: a for a in client.get("/api/panel", headers=admin).json()["activos"]}
    assert panel["BAB35"]["ocupacion_hoy"] == 5.0  # 1 de 20 viviendas (los garajes no cuentan)
    assert panel["BAB35"]["alquiladas_por_uso"] == {"vivienda": 1}
    assert client.post("/api/alquiler/recibos/generar", headers=admin, json={"periodo": "2026-09"}).json()["creados"] == 1
    assert client.post("/api/alquiler/recibos/generar", headers=admin, json={"periodo": "2026-09"}).json()["creados"] == 0
    rec = client.get("/api/alquiler/recibos?periodo=2026-09", headers=admin).json()[0]
    assert rec["importe"] == 600.0
    domicilio_fiscal(client, admin)  # sin él no se puede facturar el cobro
    p = client.post(f"/api/alquiler/recibos/{rec['id']}/cobro", headers=admin, json={"importe": 200}).json()
    assert p["estado"] == "parcial" and p["pendiente"] == 400.0
    assert p["factura"]["codigo"].startswith("B35/") and p["factura"]["codigo"].endswith(f"/{HOY.year}")
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
    base = f"/api/mantenimiento/ordenes/{w['id']}"
    # sin confirmaciones no se puede cerrar
    assert client.post(f"{base}/cerrar", headers=admin, json={}).status_code == 400
    assert client.post(f"{base}/confirmar-mantenimiento", headers=admin,
                       json={"solucion": "Sustitución válvula", "coste_real": 85.5}).json()["estado"] == "trabajo_realizado"
    assert client.post(f"{base}/confirmar-limpieza", headers=admin).json()["estado"] == "pendiente_cierre"
    c = client.post(f"{base}/cerrar", headers=admin, json={}).json()
    assert c["estado"] == "cerrada" and c["coste_real"] == 85.5
    # limpieza ya confirmó la unidad -> queda disponible
    assert client.get(f"/api/unidades?asset_id={sae}&q={unit['codigo']}", headers=admin).json()[0]["estado"] == "disponible"
    n = client.post("/api/mantenimiento/planes/plantilla", headers=admin,
                    json={"asset_id": sae, "primera_fecha": d(0)}).json()["creados"]
    assert n > 5
    assert client.post("/api/mantenimiento/planes/plantilla", headers=admin, json={"asset_id": sae}).json()["creados"] == 0
    g = client.post("/api/mantenimiento/planes/generar", headers=admin, json={"asset_id": sae}).json()
    assert g["creadas"] == n
    assert client.post("/api/mantenimiento/planes/generar", headers=admin, json={"asset_id": sae}).json()["creadas"] == 0


def test_company_scope_includes_future_assets(client, admin, ids):
    ethosa = ids["companies"]["EMPRESA TURISTICA HOTELERA S.A."]
    dir_ = _new_user(client, admin, "director.ethosa@inversiete.com",
                     [{"role_id": ids["roles"]["Dirección Sociedad"], "company_id": ethosa}])
    assert client.get("/api/activos", headers=dir_).json() == []
    r = client.post("/api/activos", headers=dir_, json={
        "company_id": ethosa, "codigo": "NUEVO1", "nombre": "Nuevo activo", "modalidad": "apartamentos_turisticos"})
    assert r.status_code == 201, r.text
    assert [a["codigo"] for a in client.get("/api/activos", headers=dir_).json()] == ["NUEVO1"]
    # no puede crear en otra sociedad ni gestionar usuarios
    assert client.post("/api/activos", headers=dir_, json={
        "company_id": ids["companies"]["INVERSIETE S.A."], "codigo": "NUEVO2", "nombre": "x",
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


def test_initial_users_and_forced_password_change(client, admin):
    users = {u["email"]: u for u in client.get("/api/admin/usuarios", headers=admin).json()}
    iniciales = ["jr@inversiete.es", "barbara@inversiete.es", "alfonso@inversiete.es",
                 "juancarlos@apartamentossuitesflorida.es", "info@apartamentossuitesflorida.es",
                 "jaime@apartamentossuitesaeropuerto.es", "info@apartamentossuitesaeropuerto.es"]
    for e in iniciales:
        assert users[e]["debe_cambiar_password"]
    for e in iniciales[:3]:
        assert users[e]["asignaciones"][0]["rol"] == "Dirección Grupo" and users[e]["asignaciones"][0]["asset_id"] is None
    # con la contraseña provisional solo puede ver su perfil y cambiarla
    h = login(client, "jr@inversiete.es", INICIAL)
    assert client.get("/api/auth/me", headers=h).json()["debe_cambiar_password"] is True
    assert client.get("/api/activos", headers=h).status_code == 403
    bad = [("ZZZZZZZZ", "OtraClave2026"), (INICIAL, INICIAL), (INICIAL, "corta12"), (INICIAL, "aaaaaaaaaaaa")]
    for actual, nueva in bad:
        assert client.post("/api/auth/password", headers=h, json={"actual": actual, "nueva": nueva}).status_code == 400
    assert client.post("/api/auth/password", headers=h, json={"actual": INICIAL, "nueva": "Presidencia#2026"}).status_code == 200
    assert client.get("/api/auth/me", headers=h).json()["debe_cambiar_password"] is False
    # acceso total
    assert {a["codigo"] for a in client.get("/api/activos", headers=h).json()} >= {"BAB35", "SFL", "SAE"}
    assert client.get("/api/admin/usuarios", headers=h).status_code == 200
    # la provisional ya no sirve
    assert client.post("/api/auth/login", json={"email": "jr@inversiete.es", "password": INICIAL}).status_code == 401


def test_staff_per_asset(client, admin, ids):
    sfl, sae = ids["assets"]["SFL"]["id"], ids["assets"]["SAE"]["id"]
    rec_sf = _first_login(client, "juancarlos@apartamentossuitesflorida.es", INICIAL)
    rec_sa = _first_login(client, "info@apartamentossuitesaeropuerto.es", INICIAL)
    # puestos aún sin titular: se dan de alta desde administración
    lim_sf = _new_user(client, admin, "limpieza.prueba@inversiete.es",
                       [{"role_id": ids["roles"]["Gobernanta / Limpieza"], "asset_id": sfl}])
    mto_sa = _new_user(client, admin, "mto.prueba@inversiete.es",
                       [{"role_id": ids["roles"]["Técnico Mantenimiento"], "asset_id": sae}])
    assert [a["codigo"] for a in client.get("/api/activos", headers=rec_sf).json()] == ["SFL"]
    assert [a["codigo"] for a in client.get("/api/activos", headers=mto_sa).json()] == ["SAE"]

    # huésped de Suite Aeropuerto: lo ve la recepción de SA, no la de SF (misma sociedad gestora)
    sa_unit = client.get(f"/api/unidades?asset_id={sae}&q=B-305", headers=admin).json()[0]
    r = client.post("/api/turistico/reservas", headers=rec_sa, json={
        "unit_id": sa_unit["id"], "guest": {"nombre": "Huesped", "apellidos": "SoloAeropuerto"},
        "fecha_entrada": d(20), "fecha_salida": d(22)})
    assert r.status_code == 201, r.text
    assert client.get("/api/terceros?tipo=huesped&q=SoloAeropuerto", headers=rec_sa).json()
    assert client.get("/api/terceros?tipo=huesped&q=SoloAeropuerto", headers=rec_sf).json() == []
    gid = r.json()["guest_id"]
    assert client.put(f"/api/terceros/{gid}", headers=rec_sf, json={
        "company_id": ids["companies"]["INVERSIETE S.A."], "tipo": "huesped", "nombre": "x"}).status_code == 403
    assert client.get("/api/turistico/reservas", headers=rec_sf).json() == [] or \
        all(x["asset_id"] == sfl for x in client.get("/api/turistico/reservas", headers=rec_sf).json())

    # limpieza: marca limpia, pero no reserva ni ve reservas
    u = client.get(f"/api/unidades?asset_id={sfl}&q=P2-3C", headers=admin).json()[0]
    client.put(f"/api/unidades/{u['id']}", headers=admin, json={"estado": "pendiente_limpieza"})
    assert client.post(f"/api/unidades/{u['id']}/limpia", headers=lim_sf).json()["estado"] == "disponible"
    assert client.post("/api/turistico/reservas", headers=lim_sf, json={
        "unit_id": u["id"], "guest": {"nombre": "x"}, "fecha_entrada": d(1), "fecha_salida": d(2)}).status_code == 403
    assert client.get("/api/turistico/reservas", headers=lim_sf).json() == []

    # mantenimiento: OT en su activo sí, en el otro no
    assert client.post("/api/mantenimiento/ordenes", headers=mto_sa, json={
        "asset_id": sae, "titulo": "Revisión bomba ACS", "categoria": "acs"}).status_code == 201
    assert client.post("/api/mantenimiento/ordenes", headers=mto_sa, json={
        "asset_id": sfl, "titulo": "x"}).status_code == 403


def test_login_lockout(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "nadie@inversiete.com", "password": "x"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "nadie@inversiete.com", "password": "x"}).status_code == 429


def test_work_order_flow_by_role(client, admin, ids):
    """Abren recepción/limpieza/mantenimiento; confirma mantenimiento, luego limpieza; cierra solo recepción."""
    sfl = ids["assets"]["SFL"]["id"]
    rol = ids["roles"]
    rec = _new_user(client, admin, "rec.ot@inversiete.es", [{"role_id": rol["Recepción"], "asset_id": sfl}])
    lim = _new_user(client, admin, "lim.ot@inversiete.es", [{"role_id": rol["Gobernanta / Limpieza"], "asset_id": sfl}])
    mto = _new_user(client, admin, "mto.ot@inversiete.es", [{"role_id": rol["Técnico Mantenimiento"], "asset_id": sfl}])
    unit = client.get(f"/api/unidades?asset_id={sfl}&q=P4-2B", headers=admin).json()[0]

    # los tres pueden abrir; quien solo abre no fija datos de gestión
    for h in (rec, lim, mto):
        r = client.post("/api/mantenimiento/ordenes", headers=h, json={
            "asset_id": sfl, "unit_id": unit["id"], "titulo": "Grifo gotea", "categoria": "fontaneria",
            "proveedor": "X", "coste_estimado": 999})
        assert r.status_code == 201, r.text
    ot = client.post("/api/mantenimiento/ordenes", headers=lim, json={
        "asset_id": sfl, "unit_id": unit["id"], "titulo": "Persiana rota", "bloquea_unidad": True,
        "coste_estimado": 999}).json()
    assert ot["coste_estimado"] is None and ot["abierta_por_nombre"] == "lim.ot"
    assert client.get(f"/api/unidades?asset_id={sfl}&q=P4-2B", headers=admin).json()[0]["estado"] == "mantenimiento"
    base = f"/api/mantenimiento/ordenes/{ot['id']}"

    # limpieza no puede confirmar antes que mantenimiento; recepción y limpieza no confirman trabajo
    assert client.post(f"{base}/confirmar-limpieza", headers=lim).status_code == 400
    assert client.post(f"{base}/confirmar-mantenimiento", headers=rec, json={"solucion": "xxx"}).status_code == 403
    assert client.post(f"{base}/confirmar-mantenimiento", headers=lim, json={"solucion": "xxx"}).status_code == 403
    # mantenimiento no puede cerrar
    assert client.post(f"{base}/cerrar", headers=mto, json={}).status_code == 403

    assert client.post(f"{base}/confirmar-mantenimiento", headers=mto,
                       json={"solucion": "Cambio de cinta", "coste_real": 25}).status_code == 200
    # recepción no puede sustituir la confirmación de limpieza ni cerrar sin ella
    assert client.post(f"{base}/confirmar-limpieza", headers=rec).status_code == 403
    assert client.post(f"{base}/confirmar-limpieza", headers=mto).status_code == 403
    assert "limpieza" in client.post(f"{base}/cerrar", headers=rec, json={}).json()["detail"]
    # limpieza rechaza: vuelve a mantenimiento sin confirmaciones
    r = client.post(f"{base}/rechazar", headers=lim, json={"motivo": "Sigue sin bajar"}).json()
    assert r["estado"] == "en_curso" and r["conf_mto_por"] is None and "Sigue sin bajar" in r["descripcion"]
    client.post(f"{base}/confirmar-mantenimiento", headers=mto, json={"solucion": "Cambio de cinta y polea"})
    assert client.post(f"{base}/confirmar-limpieza", headers=lim).json()["estado"] == "pendiente_cierre"
    # limpieza y mantenimiento no cierran; recepción sí
    assert client.post(f"{base}/cerrar", headers=lim, json={}).status_code == 403
    c = client.post(f"{base}/cerrar", headers=rec, json={}).json()
    assert c["estado"] == "cerrada" and c["cerrada_por_nombre"] == "rec.ot"
    assert c["conf_mto_por_nombre"] == "mto.ot" and c["conf_limpieza_por_nombre"] == "lim.ot"
    # la unidad bloqueada se libera solo cuando no quedan OT bloqueantes abiertas
    assert client.get(f"/api/unidades?asset_id={sfl}&q=P4-2B", headers=admin).json()[0]["estado"] == "disponible"


def test_preventive_common_areas_skip_cleaning(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    rol = ids["roles"]
    rec = _new_user(client, admin, "rec.prev@inversiete.es", [{"role_id": rol["Recepción"], "asset_id": sae}])
    lim = _new_user(client, admin, "lim.prev@inversiete.es", [{"role_id": rol["Gobernanta / Limpieza"], "asset_id": sae}])
    mto = _new_user(client, admin, "mto.prev@inversiete.es", [{"role_id": rol["Técnico Mantenimiento"], "asset_id": sae}])
    # preventiva de zonas comunes: mantenimiento confirma -> recepción cierra, sin limpieza
    w = client.post("/api/mantenimiento/ordenes", headers=mto, json={
        "asset_id": sae, "tipo": "preventivo", "categoria": "pci", "titulo": "Revisión trimestral extintores"}).json()
    assert w["requiere_limpieza"] is False
    base = f"/api/mantenimiento/ordenes/{w['id']}"
    r = client.post(f"{base}/confirmar-mantenimiento", headers=mto, json={"solucion": "Revisados 24 extintores"}).json()
    assert r["estado"] == "pendiente_cierre"
    assert client.post(f"{base}/confirmar-limpieza", headers=lim).status_code == 400
    assert client.post(f"{base}/rechazar", headers=lim, json={"motivo": "xxx"}).status_code == 403
    assert client.post(f"{base}/cerrar", headers=mto, json={}).status_code == 403
    assert client.post(f"{base}/cerrar", headers=rec, json={}).json()["estado"] == "cerrada"
    # preventiva en una unidad y correctiva en zonas comunes sí requieren limpieza
    unit = client.get(f"/api/unidades?asset_id={sae}&q=A-250", headers=admin).json()[0]
    assert client.post("/api/mantenimiento/ordenes", headers=mto, json={
        "asset_id": sae, "unit_id": unit["id"], "tipo": "preventivo", "titulo": "Limpieza filtros split"}).json()["requiere_limpieza"]
    assert client.post("/api/mantenimiento/ordenes", headers=rec, json={
        "asset_id": sae, "titulo": "Fuga en pasillo planta 2"}).json()["requiere_limpieza"]
    # las OT generadas por los planes preventivos (zonas comunes) tampoco pasan por limpieza
    client.post("/api/mantenimiento/planes/plantilla", headers=admin, json={"asset_id": sae})
    client.post("/api/mantenimiento/planes/generar", headers=admin, json={"asset_id": sae, "dias_antelacion": 90})
    gen = client.get(f"/api/mantenimiento/ordenes?asset_id={sae}&tipo=preventivo&abiertas=true", headers=admin).json()
    assert any(not o["requiere_limpieza"] and o["plan_id"] for o in gen)
