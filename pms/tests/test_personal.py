"""Personal de mantenimiento y limpieza: fichas, envío de órdenes de trabajo y del parte de limpieza."""
from datetime import date, timedelta
from urllib.parse import unquote

from app import avisos
from test_adjuntos_ot import _usuario

HOY = date.today()


def _unidad(client, h, asset_id, codigo):
    return next(u for u in client.get(f"/api/unidades?asset_id={asset_id}&q={codigo}", headers=h).json()
                if u["codigo"] == codigo)


def test_fichas_del_personal(client, admin, ids):
    sae, sfl = ids["assets"]["SAE"]["id"], ids["assets"]["SFL"]["id"]
    sin_contacto = client.post("/api/personal", headers=admin, json={"area": "limpieza", "nombre": "Sin datos"})
    assert sin_contacto.status_code == 400 and "correo" in sin_contacto.json()["detail"]
    assert client.post("/api/personal", headers=admin, json={
        "area": "cocina", "nombre": "Equis", "telefono": "600000000"}).status_code == 400
    assert client.post("/api/personal", headers=admin, json={
        "area": "limpieza", "nombre": "Equis", "email": "no-es-correo"}).status_code == 422
    p = client.post("/api/personal", headers=admin, json={
        "asset_id": sae, "area": "mantenimiento", "nombre": "Técnico Fichas", "empresa": "Instalaciones Prueba SL",
        "email": "tecnico.fichas@example.com", "telefono": "611 22 33 44"})
    assert p.status_code == 201, p.text
    p = p.json()
    assert p["activo_nombre"] == "Suite Aeropuerto" and p["area_nombre"] == "Mantenimiento" and p["whatsapp"]
    # el de otro activo no aparece al filtrar por SAE; el de «todos los activos» sí
    client.post("/api/personal", headers=admin, json={"asset_id": sfl, "area": "limpieza", "nombre": "Limpieza Florida",
                                                       "telefono": "622000111"})
    client.post("/api/personal", headers=admin, json={"area": "limpieza", "nombre": "Limpieza Todos",
                                                       "telefono": "622000222"})
    nombres = {x["nombre"] for x in client.get(f"/api/personal?asset_id={sae}", headers=admin).json()}
    assert {"Técnico Fichas", "Limpieza Todos"} <= nombres and "Limpieza Florida" not in nombres
    r = client.put(f"/api/personal/{p['id']}", headers=admin, json={**p, "telefono": "611223355", "activo": False})
    assert r.status_code == 200 and not r.json()["activo"]
    assert p["id"] not in [x["id"] for x in client.get("/api/personal?solo_activos=true", headers=admin).json()]
    assert client.delete(f"/api/personal/{p['id']}", headers=admin).json()["ok"]

    # recepción ve el personal (para enviar trabajo) pero no da de alta técnicos de mantenimiento; la gobernanta
    # da de alta al personal de limpieza de su activo, pero no para todos los activos
    rec = _usuario(client, admin, ids, "recepcion.personal@inversiete.com", "Recepción", "SAE")
    assert client.get(f"/api/personal?asset_id={sae}", headers=rec).status_code == 200
    assert client.post("/api/personal", headers=rec, json={"asset_id": sae, "area": "mantenimiento", "nombre": "No",
                                                           "telefono": "600111222"}).status_code == 403
    gob = _usuario(client, admin, ids, "gobernanta.personal@inversiete.com", "Gobernanta / Limpieza", "SAE")
    assert client.post("/api/personal", headers=gob, json={"asset_id": sae, "area": "limpieza", "nombre": "Camarera",
                                                           "telefono": "600111333"}).status_code == 201
    assert client.post("/api/personal", headers=gob, json={"area": "limpieza", "nombre": "Camarera grupo",
                                                           "telefono": "600111444"}).status_code == 403


def test_enviar_orden_de_trabajo(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    tec = client.post("/api/personal", headers=admin, json={
        "asset_id": sae, "area": "mantenimiento", "nombre": "Fontanero Envío", "email": "fontanero@example.com",
        "telefono": "633445566"}).json()
    solo_tel = client.post("/api/personal", headers=admin, json={
        "asset_id": sae, "area": "mantenimiento", "nombre": "Electricista Móvil", "telefono": "+44 7700 900123"}).json()
    otro = client.post("/api/personal", headers=admin, json={
        "asset_id": ids["assets"]["SFL"]["id"], "area": "mantenimiento", "nombre": "Técnico Florida",
        "email": "florida@example.com"}).json()
    apto = _unidad(client, admin, sae, "A-140")
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "unit_id": apto["id"], "titulo": "Grifo del baño gotea", "categoria": "fontaneria"}).json()

    url = f"/api/mantenimiento/ordenes/{w['id']}/enviar"
    assert client.post(url, headers=admin, json={"personal_ids": [otro["id"]], "canal": "email"}).status_code == 400
    sin_correo = client.post(url, headers=admin, json={"personal_ids": [solo_tel["id"]], "canal": "email"})
    assert sin_correo.status_code == 400 and "no tiene correo" in sin_correo.json()["detail"]

    avisos.BANDEJA.clear()
    r = client.post(url, headers=admin, json={"personal_ids": [tec["id"]], "canal": "email", "nota": "Llave en recepción"})
    assert r.status_code == 200, r.text
    m = avisos.BANDEJA[-1]
    assert m["para"] == "fontanero@example.com" and m["asunto"].startswith(f"OT-{w['id']:05d} · Suite Aeropuerto")
    assert "Grifo del baño gotea" in m["texto"] and "Llave en recepción" in m["texto"]
    assert m["adjuntos"][0][0] == f"Parte_OT-{w['id']:05d}.pdf" and m["adjuntos"][0][2] == "application/pdf"
    o = r.json()["orden"]
    assert o["estado"] == "asignada" and o["asignado_a"] == "Fontanero Envío"
    assert o["envios"][0]["nombre"] == "Fontanero Envío" and o["envios"][0]["canal"] == "email"

    wa = client.post(url, headers=admin, json={"personal_ids": [solo_tel["id"]], "canal": "whatsapp"}).json()
    enlace = wa["enviados"][0]["whatsapp"]
    assert enlace.startswith("https://wa.me/447700900123?text=") and "Grifo del baño gotea" in unquote(enlace)
    assert len(wa["orden"]["envios"]) == 2 and wa["orden"]["asignado_a"] == "Fontanero Envío"


def test_ot_urgente_al_personal(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    client.post("/api/personal", headers=admin, json={
        "asset_id": sae, "area": "mantenimiento", "nombre": "Técnico Guardia", "email": "guardia@example.com",
        "avisar_urgentes": True})
    client.post("/api/personal", headers=admin, json={
        "asset_id": sae, "area": "mantenimiento", "nombre": "Técnico Sin Guardia", "email": "singuardia@example.com"})
    avisos.BANDEJA.clear()
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sae, "titulo": "Sin agua caliente en el bloque B", "categoria": "acs", "prioridad": "urgente"}).json()
    m = [x for x in avisos.BANDEJA if x["para"] == "guardia@example.com"]
    assert len(m) == 1 and m[0]["asunto"].startswith(f"URGENTE · OT-{w['id']:05d}") and m[0]["adjuntos"]
    assert not [x for x in avisos.BANDEJA if x["para"] == "singuardia@example.com"]
    o = next(x for x in client.get(f"/api/mantenimiento/ordenes?asset_id={sae}", headers=admin).json()
             if x["id"] == w["id"])
    assert o["estado"] == "asignada" and o["envios"][0]["usuario"] == "Aviso automático (urgente)"


def test_parte_de_limpieza(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    sucio, sale = _unidad(client, admin, sae, "A-141"), _unidad(client, admin, sae, "A-142")
    client.put(f"/api/unidades/{sucio['id']}", headers=admin, json={"estado": "pendiente_limpieza"})
    r = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": sale["id"], "localizador": "LIMP-1", "fecha_entrada": (HOY - timedelta(days=3)).isoformat(),
        "fecha_salida": HOY.isoformat(), "guest": {"nombre": "Sale Hoy"}}).json()
    client.put(f"/api/turistico/reservas/{r['id']}", headers=admin, json={"estado": "checkin"})
    client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": sucio["id"], "localizador": "LIMP-2", "fecha_entrada": HOY.isoformat(),
        "fecha_salida": (HOY + timedelta(days=2)).isoformat(), "adultos": 2, "guest": {"nombre": "Llega Hoy"}})

    p = client.get(f"/api/personal/limpieza?asset_id={sae}", headers=admin).json()
    u = {x["codigo"]: x for x in p["unidades"]}
    assert u["A-141"]["llegada"] and u["A-141"]["pax_llegada"] == 2 and u["A-141"]["motivo"] == "Pendiente de limpieza"
    assert u["A-142"]["motivo"] == "Salida hoy" and not u["A-142"]["llegada"]
    assert p["unidades"][0]["llegada"]  # primero las que tienen llegada

    cam = client.post("/api/personal", headers=admin, json={
        "asset_id": sae, "area": "limpieza", "nombre": "Camarera Parte", "email": "camarera@example.com",
        "telefono": "644556677"}).json()
    avisos.BANDEJA.clear()
    env = client.post("/api/personal/limpieza/enviar", headers=admin, json={
        "asset_id": sae, "unit_ids": [sucio["id"], sale["id"]], "personal_ids": [cam["id"]], "canal": "email",
        "nota": "Cambiar toallas"})
    assert env.status_code == 200, env.text
    m = avisos.BANDEJA[-1]
    assert m["para"] == "camarera@example.com" and "2 unidad(es)" in m["asunto"]
    assert m["texto"].index("A-141") < m["texto"].index("A-142") and "LLEGADA HOY (2 pax)" in m["texto"]
    assert "Cambiar toallas" in m["texto"]
    wa = client.post("/api/personal/limpieza/enviar", headers=admin, json={
        "asset_id": sae, "unit_ids": [sale["id"]], "personal_ids": [cam["id"]], "canal": "whatsapp"}).json()
    assert wa["enviados"][0]["whatsapp"].startswith("https://wa.me/34644556677?text=")
    otra = _unidad(client, admin, ids["assets"]["SFL"]["id"], client.get(
        f"/api/unidades?asset_id={ids['assets']['SFL']['id']}", headers=admin).json()[0]["codigo"])
    assert client.post("/api/personal/limpieza/enviar", headers=admin, json={
        "asset_id": sae, "unit_ids": [otra["id"]], "personal_ids": [cam["id"]], "canal": "email"}).status_code == 400
