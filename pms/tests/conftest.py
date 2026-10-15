import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp()
# Por defecto SQLite temporal; para probar contra PostgreSQL:
#   PMS_TEST_DATABASE_URL=postgresql+psycopg://usuario:clave@localhost/pmstest python -m pytest
os.environ["PMS_DATABASE_URL"] = os.environ.get("PMS_TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db")
os.environ["PMS_SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["PMS_ADMIN_PASSWORD"] = "AdminTest!2026"
os.environ["PMS_DOCS_DIR"] = f"{_tmp}/documentos"
os.environ["PMS_SMTP_HOST"] = "memoria"  # los avisos se guardan en avisos.BANDEJA, no se envían
os.environ["PMS_SMTP_FROM"] = "avisos@inversiete.es"
os.environ["PMS_AVISOS_AUTO"] = "0"
os.environ["PMS_VIGILANTE"] = "0"  # el reinicio automático solo en el servidor
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN = ("admin@inversiete.com", "AdminTest!2026")


@pytest.fixture(scope="session")
def client():
    from app.database import Base, engine
    Base.metadata.drop_all(engine)  # base limpia (relevante con PostgreSQL)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _contadores_de_acceso():
    # todas las pruebas llegan desde la misma «conexión»: cada prueba empieza con los contadores a cero
    from app import proteccion
    proteccion._fallos.clear()
    proteccion._avisado.clear()
    yield


def login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def admin(client):
    return login(client, *ADMIN)


@pytest.fixture(scope="session")
def ids(client, admin):
    assets = {a["codigo"]: a for a in client.get("/api/activos", headers=admin).json()}
    roles = {r["nombre"]: r["id"] for r in client.get("/api/admin/roles", headers=admin).json()}
    comps = {c["nombre"]: c["id"] for c in client.get("/api/sociedades", headers=admin).json()}
    return {"assets": assets, "roles": roles, "companies": comps}


def domicilio_fiscal(client, admin):
    """Las facturas exigen el domicilio fiscal del emisor (en pruebas, uno ficticio)."""
    for c in client.get("/api/sociedades", headers=admin).json():
        if c["nombre"] in ("INVERSIETE S.A.", "COMERCIAL DEL CAMPO S.A.") and not c.get("direccion"):
            r = client.put(f"/api/sociedades/{c['id']}", headers=admin, json={
                **{k: c[k] for k in ("nombre", "cif", "parent_id", "activa")},
                "direccion": "Calle de Prueba 1", "cp": "28001", "municipio": "Madrid", "provincia": "Madrid"})
            assert r.status_code == 200, r.text


def png_bytes() -> bytes:
    import io as _io
    from PIL import Image as _Image
    out = _io.BytesIO()
    _Image.new("RGB", (300, 120), "white").save(out, "PNG")
    return out.getvalue()


def firma_png() -> str:
    import base64 as _b64
    return "data:image/png;base64," + _b64.b64encode(png_bytes()).decode()


def foto_trabajo(client, h, wid):
    """Foto de la reparación (obligatoria para finalizar o cerrar una OT, 1.70)."""
    r = client.post(f"/api/mantenimiento/ordenes/{wid}/adjuntos", headers=h, data={"tipo": "trabajo"},
                    files={"ficheros": ("reparacion.png", png_bytes(), "image/png")})
    assert r.status_code == 201, r.text


def trabajo_realizado(client, h, wid, solucion="Trabajo realizado", coste_real=None, minutos=45, foto=True):
    """«Trabajo realizado» desde el PMS con foto, tiempo (llegada y salida) y firma. Personal propio: queda cerrada;
    subcontrata: pendiente de cierre."""
    from datetime import datetime as _dt, timedelta as _td
    if foto:
        foto_trabajo(client, h, wid)
    salida = _dt.now().replace(microsecond=0) - _td(minutes=1)
    body = {"solucion": solucion, "llegada": (salida - _td(minutes=minutos)).isoformat(), "salida": salida.isoformat(),
            "firma": firma_png()}
    if coste_real is not None:
        body["coste_real"] = coste_real
    return client.post(f"/api/mantenimiento/ordenes/{wid}/confirmar-mantenimiento", headers=h, json=body)
