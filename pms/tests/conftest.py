import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = tempfile.mkdtemp()
os.environ["PMS_DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["PMS_SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789"
os.environ["PMS_ADMIN_PASSWORD"] = "AdminTest!2026"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ADMIN = ("admin@inversiete.com", "AdminTest!2026")


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


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
