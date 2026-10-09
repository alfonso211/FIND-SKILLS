"""Borrar usuarios: sin actividad se eliminan; con actividad se conserva solo su nombre para el historial (sin
acceso, sin roles, fuera de la lista y con el email libre)."""
from conftest import login


def _alta(client, admin, ids, email, nombre="Usuario Borrar Pruebas"):
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": nombre, "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"]["Consulta"], "asset_id": ids["assets"]["BAB35"]["id"]}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_borrar_usuario_sin_actividad(client, admin, ids):
    uid = _alta(client, admin, ids, "borrar.nuevo@inversiete.com")
    r = client.delete(f"/api/admin/usuarios/{uid}", headers=admin)
    assert r.status_code == 200 and r.json() == {"ok": True, "historial": False}
    assert all(u["id"] != uid for u in client.get("/api/admin/usuarios", headers=admin).json())
    assert client.delete(f"/api/admin/usuarios/{uid}", headers=admin).status_code == 404
    _alta(client, admin, ids, "borrar.nuevo@inversiete.com")  # el email queda libre


def test_borrar_usuario_con_actividad_conserva_historial(client, admin, ids):
    uid = _alta(client, admin, ids, "borrar.activo@inversiete.com", "Usuario Con Historial")
    h = login(client, "borrar.activo@inversiete.com", "Provisional1")
    client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    r = client.delete(f"/api/admin/usuarios/{uid}", headers=admin)
    assert r.status_code == 200 and r.json()["historial"] is True
    assert all(u["id"] != uid for u in client.get("/api/admin/usuarios", headers=admin).json())
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.post("/api/auth/login", json={"email": "borrar.activo@inversiete.com",
                                                "password": "ClaveDefinitiva2026"}).status_code == 401
    _alta(client, admin, ids, "borrar.activo@inversiete.com", "Usuario Con Historial 2")  # el email queda libre
    assert client.delete(f"/api/admin/usuarios/{uid}", headers=admin).status_code == 404


def test_borrar_usuario_limites(client, admin, ids):
    me = client.get("/api/auth/me", headers=admin).json()
    assert client.delete(f"/api/admin/usuarios/{me['id']}", headers=admin).status_code == 400  # a sí mismo
    uid = _alta(client, admin, ids, "borrar.sinpermiso@inversiete.com")
    h = login(client, "borrar.sinpermiso@inversiete.com", "Provisional1")
    client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    assert client.delete(f"/api/admin/usuarios/{me['id']}", headers=h).status_code == 403  # sin permiso
    assert client.delete(f"/api/admin/usuarios/{uid}", headers=admin).status_code == 200
