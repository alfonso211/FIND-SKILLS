"""Accesos rápidos de la barra superior: de serie Gmail, Outlook, Excel, Word y Teams; cada usuario elige los suyos
(solo https, como máximo 10) y no ve ni toca los de otro."""
from conftest import login


def _usuario(client, admin, ids, email):
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": "Usuario Accesos", "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"]["Consulta"], "asset_id": ids["assets"]["BAB35"]["id"]}]})
    assert r.status_code == 201, r.text
    h = login(client, email, "Provisional1")
    r = client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "AccesosRapidos2026"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_accesos_de_serie_y_personales(client, admin, ids):
    h = _usuario(client, admin, ids, "accesos.uno@inversiete.com")
    otro = _usuario(client, admin, ids, "accesos.dos@inversiete.com")
    r = client.get("/api/auth/accesos", headers=h).json()
    assert r["de_serie"] and r["maximo"] == 10
    assert [a["nombre"] for a in r["accesos"]] == ["Gmail", "Outlook", "Excel", "Word", "Teams"]
    assert all(a["url"].startswith("https://") for a in r["accesos"])
    assert client.get("/api/auth/me", headers=h).json()["accesos"] == r["accesos"]

    nuevos = [{"nombre": "  Catastro   sede ", "url": " https://www.sedecatastro.gob.es/ "},
              {"nombre": "Outlook", "url": "https://outlook.office.com/mail/"}]
    r = client.put("/api/auth/accesos", headers=h, json={"accesos": nuevos})
    assert r.status_code == 200, r.text
    assert r.json()["accesos"] == [{"nombre": "Catastro sede", "url": "https://www.sedecatastro.gob.es/"},
                                   {"nombre": "Outlook", "url": "https://outlook.office.com/mail/"}]
    assert not r.json()["de_serie"]
    assert client.get("/api/auth/me", headers=h).json()["accesos"][0]["nombre"] == "Catastro sede"
    # el otro usuario sigue con los de serie
    assert client.get("/api/auth/accesos", headers=otro).json()["de_serie"]

    # lista vacía: barra sin accesos (no vuelve a los de serie)
    assert client.put("/api/auth/accesos", headers=h, json={"accesos": []}).json()["accesos"] == []
    # null: vuelve a los de serie
    r = client.put("/api/auth/accesos", headers=h, json={"accesos": None}).json()
    assert r["de_serie"] and len(r["accesos"]) == 5


def test_accesos_rechaza_direcciones_peligrosas(client, admin, ids):
    h = _usuario(client, admin, ids, "accesos.tres@inversiete.com")
    malas = ["javascript:alert(1)", "http://mail.google.com", "data:text/html,hola", "file:///etc/passwd",
             "https://", "https://usuario:clave@ejemplo.com", "https://ejemplo.com/a b", "ftp://ejemplo.com",
             "https://ejemplo.com/" + "x" * 500]
    for url in malas:
        r = client.put("/api/auth/accesos", headers=h, json={"accesos": [{"nombre": "Prueba", "url": url}]})
        assert r.status_code == 400, url
    assert client.put("/api/auth/accesos", headers=h, json={"accesos": [{"nombre": " ", "url": "https://a.es"}]}).status_code == 400
    assert client.put("/api/auth/accesos", headers=h, json={"accesos": [{"nombre": "x" * 31, "url": "https://a.es"}]}).status_code == 400
    once = [{"nombre": f"A{i}", "url": f"https://a{i}.es"} for i in range(11)]
    assert client.put("/api/auth/accesos", headers=h, json={"accesos": once}).status_code == 400
    assert client.put("/api/auth/accesos", headers=h, json={"accesos": once[:10]}).status_code == 200
    # sin sesión no hay accesos
    assert client.get("/api/auth/accesos").status_code == 401
