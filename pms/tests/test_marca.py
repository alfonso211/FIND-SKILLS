"""Imagen corporativa INVERPMS: logotipos de sociedades y activos, favicon y pantalla de acceso."""
from app import marca


def test_logos_en_api(client, admin):
    socs = {c["cif"]: c for c in client.get("/api/sociedades", headers=admin).json()}
    assert socs["A78072915"]["logo"] == "/static/marca/inversiete-oscuro.png"
    assert socs["A28362309"]["logo"] == "/static/marca/comercial_del_campo-oscuro.png"
    assert socs["A28309433"]["logo"] == "/static/marca/edificios_cameranos-oscuro.png"
    assert socs["A28116853"]["logo"] == "/static/marca/ethosa-oscuro.png"
    activos = {a["codigo"]: a for a in client.get("/api/activos", headers=admin).json()}
    assert activos["SFL"]["logo"] == "/static/marca/suite_florida-oscuro.png"
    assert activos["SAE"]["logo"] == "/static/marca/suite_aeropuerto-oscuro.png"
    assert activos["SAE"]["logo_sociedad"] == "/static/marca/inversiete-oscuro.png"
    assert activos["BAB35"]["logo"] is None


def test_ficheros_de_marca(client):
    for clave in [*marca.LOGO_SOCIEDAD.values(), *marca.LOGO_ACTIVO.values(), "inversiete-marca"]:
        for v in ("claro", "oscuro"):
            r = client.get(f"/static/marca/{clave}-{v}.png")
            assert r.status_code == 200 and r.content.startswith(b"\x89PNG"), (clave, v)
    assert client.get("/static/marca/favicon.png").status_code == 200


def test_pantalla_inverpms(client):
    html = client.get("/").text
    assert "<title>INVERPMS" in html and "INVER<b>PMS</b>" in html
    assert "/static/marca/favicon.png" in html and 'id="userAvatar"' in html
