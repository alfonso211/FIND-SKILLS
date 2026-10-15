"""Chat (1.68): fotos y PDF en los mensajes (cifrados, solo para los miembros) y menciones con @nombre que avisan
por la campana."""
from io import BytesIO

from PIL import Image
from sqlalchemy import select

from conftest import login


def _usuario(client, admin, ids, email, nombre):
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": nombre, "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"]["Consulta"], "asset_id": ids["assets"]["BAB35"]["id"]}]})
    assert r.status_code == 201, r.text
    h = login(client, email, "Provisional1")
    r = client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ChatAdjuntos2026!"})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    return client.get("/api/auth/me", headers=h).json()["id"], h


def _png():
    b = BytesIO()
    Image.new("RGB", (40, 30), (200, 160, 90)).save(b, "PNG")
    return b.getvalue()


def test_fotos_y_pdf_en_el_chat(client, admin, ids):
    from app.database import SessionLocal
    from app.models import ChatAdjunto
    from app.config import settings
    ia, ana = _usuario(client, admin, ids, "adj.ana@inversiete.com", "Ana Adjuntos")
    ib, luis = _usuario(client, admin, ids, "adj.luis@inversiete.com", "Luis Adjuntos")
    _, eva = _usuario(client, admin, ids, "adj.eva@inversiete.com", "Eva Adjuntos")
    g = client.post("/api/chat/conversaciones", headers=ana, json={"miembros": [ib], "titulo": "Obra con fotos"}).json()
    pdf = b"%PDF-1.4\n% presupuesto\n%%EOF\n"
    r = client.post(f"/api/chat/conversaciones/{g['id']}/adjuntos", headers=ana, data={"texto": "Fotos de la caldera"},
                    files=[("ficheros", ("caldera.png", _png(), "image/png")), ("ficheros", ("presu.pdf", pdf, "application/pdf"))])
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["texto"] == "Fotos de la caldera" and [a["mime"] for a in m["adjuntos"]] == ["image/jpeg", "application/pdf"]
    foto, doc = m["adjuntos"]
    assert foto["nombre"] == "caldera.jpg"  # las fotos se pasan a JPEG (sin datos de ubicación)
    leido = client.get(f"/api/chat/conversaciones/{g['id']}/mensajes", headers=luis).json()["mensajes"][-1]
    assert [a["id"] for a in leido["adjuntos"]] == [foto["id"], doc["id"]]
    r = client.get(f"/api/chat/adjuntos/{doc['id']}", headers=luis)
    assert r.status_code == 200 and r.content == pdf and r.headers["content-type"] == "application/pdf"
    assert client.get(f"/api/chat/adjuntos/{foto['id']}", headers=luis).content[:3] == b"\xff\xd8\xff"
    assert client.get(f"/api/chat/adjuntos/{doc['id']}", headers=eva).status_code == 404  # no es del grupo
    with SessionLocal() as db:  # en disco, cifrado
        fichero = db.get(ChatAdjunto, doc["id"]).fichero
    assert pdf not in (settings.docs_dir / fichero).read_bytes()
    # solo fotos o PDF, y como mucho 5
    r = client.post(f"/api/chat/conversaciones/{g['id']}/adjuntos", headers=ana,
                    files=[("ficheros", ("virus.exe", b"MZ\x90\x00", "application/octet-stream"))])
    assert r.status_code == 400
    r = client.post(f"/api/chat/conversaciones/{g['id']}/adjuntos", headers=ana,
                    files=[("ficheros", (f"p{i}.pdf", pdf, "application/pdf")) for i in range(6)])
    assert r.status_code == 400
    assert client.post(f"/api/chat/conversaciones/{g['id']}/adjuntos", headers=eva,
                       files=[("ficheros", ("p.pdf", pdf, "application/pdf"))]).status_code == 404
    # borrar el mensaje borra los ficheros
    assert client.delete(f"/api/chat/mensajes/{m['id']}", headers=ana).status_code == 200
    assert client.get(f"/api/chat/adjuntos/{doc['id']}", headers=luis).status_code == 404
    assert not (settings.docs_dir / fichero).exists()
    assert client.get(f"/api/chat/conversaciones/{g['id']}/mensajes", headers=luis).json()["mensajes"][-1]["adjuntos"] == []


def test_menciones_avisan_por_la_campana(client, admin, ids):
    ia, ana = _usuario(client, admin, ids, "men.ana@inversiete.com", "Ana María Mención")
    ib, jose = _usuario(client, admin, ids, "men.jose@inversiete.com", "José Mención")
    ic, eva = _usuario(client, admin, ids, "men.eva@inversiete.com", "Eva Mención")
    g = client.post("/api/chat/conversaciones", headers=ana, json={"miembros": [ib], "titulo": "Turno de noche"}).json()
    antes = {k: client.get("/api/notificaciones/estado", headers=h).json()["ultima"] for k, h in (("j", jose), ("e", eva), ("a", ana))}
    r = client.post(f"/api/chat/conversaciones/{g['id']}/mensajes", headers=ana,
                    json={"texto": "@jose mencion, ¿puedes revisar el 2B? @Eva Mención @Ana María Mención"})
    assert r.json()["menciones"] == [ib]  # sin tildes ni mayúsculas; Eva no está en el grupo; a sí misma no
    n = client.get("/api/notificaciones/estado", headers=jose, params={"desde": antes["j"]}).json()["nuevas"]
    assert len(n) == 1 and n[0]["tipo"] == "chat_mencion" and n[0]["vista"] == f"chat:{g['id']}"
    assert "Ana María Mención" in n[0]["titulo"] and "revisar el 2B" in n[0]["texto"]
    assert client.get("/api/notificaciones/estado", headers=eva, params={"desde": antes["e"]}).json()["nuevas"] == []
    assert client.get("/api/notificaciones/estado", headers=ana, params={"desde": antes["a"]}).json()["nuevas"] == []
    # «Todo el equipo»: cualquiera del personal; sin @ no hay aviso
    todos = next(c for c in client.get("/api/chat/conversaciones", headers=ana).json() if c["tipo"] == "todos")
    r = client.post(f"/api/chat/conversaciones/{todos['id']}/mensajes", headers=jose, json={"texto": "Gracias @Eva Mención"})
    assert r.json()["menciones"] == [ic]
    r = client.post(f"/api/chat/conversaciones/{todos['id']}/mensajes", headers=jose, json={"texto": "Buenas noches, Eva"})
    assert r.json()["menciones"] == []
