"""Avisos con sonido (campana) y chat interno del equipo (1.65)."""
from conftest import login


def _usuario(client, admin, ids, email, nombre):
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": nombre, "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"]["Consulta"], "asset_id": ids["assets"]["BAB35"]["id"]}]})
    assert r.status_code == 201, r.text
    h = login(client, email, "Provisional1")
    r = client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ChatEquipo2026!"})
    assert r.status_code == 200, r.text
    return r.json()["user"]["id"] if "user" in r.json() else None, {"Authorization": f"Bearer {r.json()['token']}"}


def _yo(client, h):
    return client.get("/api/auth/me", headers=h).json()["id"]


def test_aviso_por_correo_llega_a_la_campana(client, admin, ids):
    from app import avisos
    from app.database import SessionLocal
    from app.models import User
    _, h = _usuario(client, admin, ids, "campana.uno@inversiete.com", "Campana Uno")
    e0 = client.get("/api/notificaciones/estado", headers=h).json()
    assert e0["sin_leer"] == 0 and e0["nuevas"] == [] and e0["ultima"] == 0  # primera consulta: solo la referencia
    with SessionLocal() as db:
        u = db.query(User).filter_by(email="campana.uno@inversiete.com").one()
        avisos._enviar_registrado(db, u, u.email, "prueba:1", "ot_urgente", "OT URGENTE · Prueba", "Avería\n  de prueba", "<p>x</p>")
        # sin usuario: se busca por el correo (mayúsculas indiferentes); a un huésped no se le deja aviso
        avisos._enviar_registrado(db, None, "CAMPANA.UNO@inversiete.com", "prueba:2", "agenda", "Reunión", "Mañana", "<p>x</p>")
        avisos._enviar_registrado(db, None, "huesped@example.com", "prueba:3", "aviso_llegada", "Llegada", "x", "<p>x</p>")
        db.commit()
    e = client.get("/api/notificaciones/estado", headers=h, params={"desde": e0["ultima"]}).json()
    assert e["sin_leer"] == 2 and [n["titulo"] for n in e["nuevas"]] == ["OT URGENTE · Prueba", "Reunión"]
    assert e["nuevas"][0]["urgente"] and e["nuevas"][0]["vista"] == "ordenes" and e["nuevas"][0]["texto"] == "Avería de prueba"
    assert not e["nuevas"][1]["urgente"] and e["nuevas"][1]["vista"] == "agenda"
    assert client.get("/api/notificaciones/estado", headers=h, params={"desde": e["ultima"]}).json()["nuevas"] == []
    assert client.post("/api/notificaciones/leidas", headers=h).json()["leidas"] == 2
    assert client.get("/api/notificaciones/estado", headers=h).json()["sin_leer"] == 0
    assert all(n["leida"] for n in client.get("/api/notificaciones", headers=h).json())
    # cada uno ve solo sus avisos
    assert all(n["titulo"] != "Reunión" for n in client.get("/api/notificaciones", headers=admin).json())


def test_chat_directo_grupo_y_todo_el_equipo(client, admin, ids):
    _, ana = _usuario(client, admin, ids, "chat.ana@inversiete.com", "Ana Chat")
    _, luis = _usuario(client, admin, ids, "chat.luis@inversiete.com", "Luis Chat")
    _, eva = _usuario(client, admin, ids, "chat.eva@inversiete.com", "Eva Chat")
    id_ana, id_luis, id_eva = _yo(client, ana), _yo(client, luis), _yo(client, eva)

    # «Todo el equipo» existe para todos
    convs = client.get("/api/chat/conversaciones", headers=ana).json()
    todos = next(c for c in convs if c["tipo"] == "todos")
    assert client.post(f"/api/chat/conversaciones/{todos['id']}/mensajes", headers=ana, json={"texto": "Buenos días a todos"}).status_code == 201
    e = client.get("/api/notificaciones/estado", headers=luis).json()["chat"]
    assert e["no_leidos"] >= 1 and any(x["id"] == todos["id"] for x in e["nuevos"])
    m = client.get(f"/api/chat/conversaciones/{todos['id']}/mensajes", headers=luis).json()
    assert m["mensajes"][-1]["texto"] == "Buenos días a todos" and m["mensajes"][-1]["autor"] == "Ana Chat"
    assert all(x["id"] != todos["id"] for x in client.get("/api/notificaciones/estado", headers=luis).json()["chat"]["nuevos"])
    assert client.delete(f"/api/chat/conversaciones/{todos['id']}/miembros/{id_ana}", headers=ana).status_code == 400

    # directo: se reutiliza y solo lo ven los dos
    d = client.post("/api/chat/conversaciones", headers=ana, json={"miembros": [id_luis], "texto": "Hola Luis"}).json()
    assert d["tipo"] == "directo" and d["titulo"] == "Luis Chat"
    assert client.post("/api/chat/conversaciones", headers=luis, json={"miembros": [id_ana]}).json()["id"] == d["id"]
    assert client.get(f"/api/chat/conversaciones/{d['id']}/mensajes", headers=eva).status_code == 404
    assert client.get(f"/api/chat/conversaciones/{d['id']}/mensajes", headers=admin).status_code == 404  # tampoco la Dirección
    assert client.post(f"/api/chat/conversaciones/{d['id']}/miembros", headers=ana, json={"miembros": [id_eva]}).status_code == 400

    # grupo: lo administra quien lo crea
    g = client.post("/api/chat/conversaciones", headers=ana, json={"miembros": [id_luis], "titulo": "Obra  Babilonia"}).json()
    assert g["tipo"] == "grupo" and g["titulo"] == "Obra Babilonia" and g["es_creador"]
    assert client.post(f"/api/chat/conversaciones/{g['id']}/miembros", headers=luis, json={"miembros": [id_eva]}).status_code == 403
    assert client.get(f"/api/chat/conversaciones/{g['id']}/mensajes", headers=eva).status_code == 404
    r = client.post(f"/api/chat/conversaciones/{g['id']}/miembros", headers=ana, json={"miembros": [id_eva]})
    assert r.status_code == 200 and {x["id"] for x in r.json()["miembros"]} == {id_ana, id_luis, id_eva}
    msgs = client.get(f"/api/chat/conversaciones/{g['id']}/mensajes", headers=eva).json()["mensajes"]
    assert [x["sistema"] for x in msgs] == [True, True] and "ha añadido a Eva Chat" in msgs[-1]["texto"]
    w = client.post(f"/api/chat/conversaciones/{g['id']}/mensajes", headers=eva, json={"texto": "Recibido"}).json()
    n = client.get(f"/api/chat/conversaciones/{g['id']}/mensajes", headers=luis, params={"despues": msgs[-1]["id"]}).json()
    assert [x["texto"] for x in n["mensajes"]] == ["Recibido"]
    assert client.delete(f"/api/chat/mensajes/{w['id']}", headers=luis).status_code == 403
    assert client.delete(f"/api/chat/mensajes/{w['id']}", headers=eva).status_code == 200
    assert client.get(f"/api/chat/conversaciones/{g['id']}/mensajes", headers=luis).json()["mensajes"][-1]["texto"] == "Mensaje eliminado"
    assert client.put(f"/api/chat/conversaciones/{g['id']}", headers=luis, json={"titulo": "Otro"}).status_code == 403
    assert client.put(f"/api/chat/conversaciones/{g['id']}", headers=ana, json={"titulo": "Obra BAB35"}).json()["titulo"] == "Obra BAB35"
    # quitar (solo el creador) y salir (cualquiera)
    assert client.delete(f"/api/chat/conversaciones/{g['id']}/miembros/{id_eva}", headers=luis).status_code == 403
    assert client.delete(f"/api/chat/conversaciones/{g['id']}/miembros/{id_eva}", headers=ana).status_code == 200
    assert client.get(f"/api/chat/conversaciones/{g['id']}/mensajes", headers=eva).status_code == 404
    assert client.delete(f"/api/chat/conversaciones/{g['id']}/miembros/{id_luis}", headers=luis).status_code == 200
    assert all(c["id"] != g["id"] for c in client.get("/api/chat/conversaciones", headers=luis).json())
    assert client.post("/api/chat/conversaciones", headers=ana, json={"miembros": [999999]}).status_code == 400
    assert client.post(f"/api/chat/conversaciones/{todos['id']}/mensajes", headers=ana, json={"texto": "   "}).status_code == 400
    assert client.post(f"/api/chat/conversaciones/{todos['id']}/mensajes", headers=ana, json={"texto": "x" * 4001}).status_code == 422


def test_chat_cerrado_a_colaboradores_e_inactivos(client, admin, ids):
    from app.database import SessionLocal
    from app.models import User
    _, h = _usuario(client, admin, ids, "chat.baja@inversiete.com", "Baja Chat")
    uid = _yo(client, h)
    with SessionLocal() as db:
        db.get(User, uid).supplier_id = None
        db.get(User, uid).activo = False
        db.commit()
    _, ana = _usuario(client, admin, ids, "chat.otra@inversiete.com", "Otra Chat")
    assert client.post("/api/chat/conversaciones", headers=ana, json={"miembros": [uid]}).status_code == 400
    assert all(u["id"] != uid for u in client.get("/api/chat/usuarios", headers=ana).json())
