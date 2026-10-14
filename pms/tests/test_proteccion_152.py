"""Versión 1.52: límite de intentos por conexión, aviso a la Dirección y política de contenido del navegador."""
import time

from app import avisos, proteccion
from app.config import settings


def _esperar_aviso(texto: str, antes: int) -> list:
    for _ in range(50):  # el correo sale en otro hilo
        nuevos = [m for m in avisos.BANDEJA[antes:] if texto in m["asunto"]]
        if nuevos:
            return nuevos
        time.sleep(0.05)
    return []


def test_login_bloqueado_por_conexion(client, admin):
    antes = len(avisos.BANDEJA)
    for i in range(proteccion.LIMITES["login"]):  # usuarios distintos: el bloqueo por usuario no salta
        r = client.post("/api/auth/login", json={"email": f"prueba{i}@ejemplo.com", "password": "mala-clave"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"email": "admin@inversiete.com", "password": "AdminTest!2026"})
    assert r.status_code == 429 and "conexión" in r.json()["detail"]  # ni con la contraseña buena
    assert _esperar_aviso("conexión bloqueada", antes)
    b = client.get("/api/admin/seguridad", headers=admin).json()
    x = next(x for x in b if x["tipo"] == "login")
    assert x["clave"] == "testclient" and x["intentos"] == proteccion.LIMITES["login"]
    # se desbloquea desde Usuarios y ya se puede entrar
    assert client.post("/api/admin/seguridad/desbloquear", headers=admin,
                       json={"tipo": "login", "clave": "testclient"}).status_code == 200
    assert client.post("/api/auth/login", json={"email": "admin@inversiete.com",
                                                "password": "AdminTest!2026"}).status_code == 200
    aud = client.get("/api/admin/auditoria", headers=admin).json()
    assert any(e["accion"] == "desbloquear_acceso" for e in aud)


def test_usuario_bloqueado_avisa_y_se_desbloquea(client, admin):
    antes = len(avisos.BANDEJA)
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "admin@inversiete.com", "password": "mala-clave"})
    r = client.post("/api/auth/login", json={"email": "admin@inversiete.com", "password": "AdminTest!2026"})
    assert r.status_code == 429
    m = _esperar_aviso("usuario bloqueado", antes)
    assert m and m[0]["para"] in settings.seguridad_avisos
    assert any(x["tipo"] == "cuenta" and x["clave"] == "admin@inversiete.com"
               for x in client.get("/api/admin/seguridad", headers=admin).json())
    client.post("/api/admin/seguridad/desbloquear", headers=admin, json={"tipo": "cuenta", "clave": "admin@inversiete.com"})
    assert client.post("/api/auth/login", json={"email": "admin@inversiete.com",
                                                "password": "AdminTest!2026"}).status_code == 200
    # un correo inventado se bloquea igual, pero no avisa
    antes = len(avisos.BANDEJA)
    for _ in range(6):
        client.post("/api/auth/login", json={"email": "no-existe@ejemplo.com", "password": "x"})
    time.sleep(0.3)
    assert not [m for m in avisos.BANDEJA[antes:] if "no-existe" in m["asunto"]]


def test_enlaces_publicos_bloqueados(client, admin):
    for i in range(proteccion.LIMITES["enlace"]):
        r = client.get(f"/api/publico/ot/{900000 + i}/datos?c=9999999999&f=firma-falsa")
        assert r.status_code in (401, 403, 404, 410)
    r = client.get("/api/publico/ot/1/datos?c=9999999999&f=firma-falsa")
    assert r.status_code == 429
    # el resto del PMS sigue funcionando desde esa conexión
    assert client.get("/api/auth/me", headers=admin).status_code == 200
    assert any(x["tipo"] == "enlace" for x in client.get("/api/admin/seguridad", headers=admin).json())


def test_solo_administradores_ven_los_bloqueos(client, admin, ids):
    from test_adjuntos_ot import _usuario
    rec = _usuario(client, admin, ids, "recepcion.seguridad152@inversiete.com", "Recepción", "SFL")
    assert client.get("/api/admin/seguridad", headers=rec).status_code == 403
    assert client.post("/api/admin/seguridad/desbloquear", headers=rec,
                       json={"tipo": "login", "clave": "1.2.3.4"}).status_code == 403


def test_politica_de_contenido(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    assert "script-src 'self' 'sha256-" in csp and "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "geolocation=(self)" in r.headers["permissions-policy"]
    # el código en línea de cada página tiene su huella en la política
    import re
    for pagina in ("/", "/tecnico/1", "/fichar/1"):
        html = client.get(pagina).text
        for js in re.findall(r"<script>(.*?)</script>", html, re.S):
            assert proteccion._hash(js) in csp, pagina
    assert "content-security-policy" not in client.get("/docs").headers  # documentación de la API, sin política


def test_politica_en_modo_informe(client, monkeypatch):
    monkeypatch.setattr(settings, "csp", "informe")
    h = client.get("/").headers
    assert "content-security-policy-report-only" in h and "content-security-policy" not in h
    monkeypatch.setattr(settings, "csp", "0")
    assert "content-security-policy-report-only" not in client.get("/").headers
