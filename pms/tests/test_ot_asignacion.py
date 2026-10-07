"""Órdenes de trabajo asignadas a personal propio o a una subcontrata, enviadas por WhatsApp y/o correo, con copia
al personal de mantenimiento propio."""
from urllib.parse import unquote, urlparse

from app import avisos
from app.config import settings


def test_ot_propio_y_subcontrata(client, admin, ids, monkeypatch):
    monkeypatch.setattr(settings, "url", "https://pms.example.com")
    bab = ids["assets"]["BAB35"]["id"]
    tecnico = client.post("/api/personal", headers=admin, json={
        "asset_id": bab, "area": "mantenimiento", "nombre": "Técnico Propio OT", "telefono": "611222333"}).json()
    client.post("/api/personal", headers=admin, json={
        "asset_id": bab, "area": "mantenimiento", "nombre": "Jefe Mantenimiento OT", "email": "jefe.mto@example.com"}).json()
    sub = client.post("/api/proveedores", headers=admin, json={
        "nombre": "Fontanería Subcontrata OT SL", "email": "avisos@fontaneria-ot.example.com",
        "telefono": "622333444", "actividad": "fontanería"}).json()

    # personal propio: se envía por WhatsApp, con copia al resto del personal de mantenimiento
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": bab, "titulo": "Grifo que gotea", "categoria": "fontaneria", "asignacion": "propio",
        "personal_id": tecnico["id"]}).json()
    assert w["asignado_a"] == "Técnico Propio OT" and w["contacto"]["whatsapp"]
    avisos.BANDEJA.clear()
    r = client.post(f"/api/mantenimiento/ordenes/{w['id']}/enviar-asignado", headers=admin,
                    json={"canales": ["whatsapp"]}).json()
    principal = [x for x in r["enviados"] if not x.get("copia")]
    copias = [x for x in r["enviados"] if x.get("copia")]
    assert principal[0]["destino"] == "34611222333" and principal[0]["whatsapp"].startswith("https://wa.me/34611222333")
    assert "Parte en PDF: https://pms.example.com/api/publico/ot/" in unquote(principal[0]["whatsapp"])
    assert any(x["destino"] == "jefe.mto@example.com" for x in copias)  # copia por correo a quien tiene correo
    assert any(m["asunto"].startswith("Copia · ") for m in avisos.BANDEJA)
    assert r["orden"]["estado"] == "asignada"
    # el enlace del PDF funciona sin iniciar sesión; con la firma cambiada, no
    enlace = next(x for x in unquote(principal[0]["whatsapp"]).split() if "/api/publico/ot/" in x)
    ruta = urlparse(enlace)
    assert client.get(f"{ruta.path}?{ruta.query}").content.startswith(b"%PDF")
    assert client.get(f"{ruta.path}?{ruta.query.replace('f=', 'f=0')}").status_code == 404
    # sin correo en la ficha no se puede enviar por correo
    assert client.post(f"/api/mantenimiento/ordenes/{w['id']}/enviar-asignado", headers=admin,
                       json={"canales": ["email"]}).status_code == 400

    # subcontrata buscada en Proveedores por su nombre: correo con el PDF y WhatsApp, ambos
    w2 = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": bab, "titulo": "Bajante atascada", "categoria": "fontaneria", "asignacion": "subcontrata",
        "proveedor": "fontanería subcontrata ot sl"}).json()
    assert w2["proveedor_id"] == sub["id"] and w2["proveedor"] == "Fontanería Subcontrata OT SL"
    assert w2["asignado_a"] == "Subcontrata: Fontanería Subcontrata OT SL"
    avisos.BANDEJA.clear()
    r = client.post(f"/api/mantenimiento/ordenes/{w2['id']}/enviar-asignado", headers=admin,
                    json={"canales": ["email", "whatsapp"], "copia_mantenimiento": True}).json()
    principal = [x for x in r["enviados"] if not x.get("copia")]
    assert [x["canal"] for x in principal] == ["email", "whatsapp"]
    m = next(m for m in avisos.BANDEJA if m["para"] == "avisos@fontaneria-ot.example.com")
    assert m["adjuntos"][0][0] == f"Parte_OT-{w2['id']:05d}.pdf"
    copias = [x for x in r["enviados"] if x.get("copia")]
    assert {x["nombre"] for x in copias} >= {"Técnico Propio OT", "Jefe Mantenimiento OT"}
    # sin copia
    r = client.post(f"/api/mantenimiento/ordenes/{w2['id']}/enviar-asignado", headers=admin,
                    json={"canales": ["whatsapp"], "copia_mantenimiento": False}).json()
    assert len(r["enviados"]) == 1

    # subcontrata que no está en Proveedores: se avisa de que hay que darla de alta
    w3 = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": bab, "titulo": "Persiana", "asignacion": "subcontrata", "proveedor": "Persianas Desconocidas SL"}).json()
    assert w3["proveedor_id"] is None
    assert "Proveedores" in client.post(f"/api/mantenimiento/ordenes/{w3['id']}/enviar-asignado", headers=admin,
                                        json={"canales": ["email"]}).json()["detail"]
    # personal de otro área: no vale como personal propio de mantenimiento
    lim = client.post("/api/personal", headers=admin, json={
        "asset_id": bab, "area": "limpieza", "nombre": "Limpieza OT", "telefono": "633444555"}).json()
    assert client.put(f"/api/mantenimiento/ordenes/{w3['id']}", headers=admin, json={
        "asignacion": "propio", "personal_id": lim["id"]}).status_code == 400
