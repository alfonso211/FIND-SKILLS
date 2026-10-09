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


def test_solo_alfonso_y_admin_borran(client, admin, ids, monkeypatch):
    """Solo las cuentas autorizadas (por defecto alfonso@inversiete.es y el administrador) borran usuarios; a ellas
    no se las puede borrar. Otra cuenta de dirección, aunque gestione usuarios, no borra."""
    from app.config import settings
    assert {"alfonso@inversiete.es", "admin@inversiete.es"} <= set(settings.borrar_usuarios)
    monkeypatch.setattr(settings, "borrar_usuarios", ("dt.borrar@inversiete.com",))  # hace de alfonso@
    me = client.get("/api/auth/me", headers=admin).json()
    assert me["borrar_usuarios"] is True  # administrador inicial
    assert client.delete(f"/api/admin/usuarios/{me['id']}", headers=admin).status_code == 400  # a sí mismo

    def alta_con_clave(email, rol):
        r = client.post("/api/admin/usuarios", headers=admin, json={
            "email": email, "nombre": email, "password": "Provisional1",
            "asignaciones": [{"role_id": ids["roles"][rol]}]})
        assert r.status_code == 201, r.text
        h = login(client, email, "Provisional1")
        client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
        return r.json()["id"], h
    _, direccion = alta_con_clave("dir.borrar@inversiete.com", "Dirección Grupo")
    dt_id, dt = alta_con_clave("dt.borrar@inversiete.com", "Dirección Grupo")
    uid = _alta(client, admin, ids, "borrar.limites@inversiete.com")
    assert client.get("/api/auth/me", headers=direccion).json()["borrar_usuarios"] is False
    assert client.delete(f"/api/admin/usuarios/{uid}", headers=direccion).status_code == 403
    assert client.get("/api/auth/me", headers=dt).json()["borrar_usuarios"] is True
    assert client.delete(f"/api/admin/usuarios/{me['id']}", headers=dt).status_code == 400  # el administrador
    assert client.delete(f"/api/admin/usuarios/{dt_id}", headers=admin).status_code == 400  # la otra cuenta
    assert client.delete(f"/api/admin/usuarios/{uid}", headers=dt).status_code == 200
