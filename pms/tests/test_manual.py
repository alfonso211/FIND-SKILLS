"""Manual de uso: secciones por puesto, la recomendada según el rol, la versión (últimas novedades) y el PDF."""
from app.routers import manual
from test_adjuntos_ot import _usuario


def test_manual_por_puesto(client, admin, ids):
    idx = client.get("/api/manual", headers=admin).json()
    assert [s["id"] for s in idx["secciones"]] == list(manual.SECCIONES)
    assert idx["recomendada"] == "direccion" and idx["version"].startswith("20")
    for s in manual.SECCIONES:
        t = client.get(f"/api/manual/{s}", headers=admin).json()["texto"]
        assert t.startswith("# ")
    assert client.get("/api/manual/otra", headers=admin).status_code == 404
    assert client.get("/api/manual").status_code == 401

    rec = _usuario(client, admin, ids, "recepcion.manual@inversiete.com", "Recepción", "SFL")
    assert client.get("/api/manual", headers=rec).json()["recomendada"] == "recepcion"
    lim = _usuario(client, admin, ids, "limpieza.manual@inversiete.com", "Gobernanta / Limpieza", "SFL")
    assert client.get("/api/manual", headers=lim).json()["recomendada"] == "limpieza"

    for s in manual.SECCIONES:
        r = client.get(f"/api/manual/{s}/pdf", headers=rec)
        assert r.status_code == 200 and r.content.startswith(b"%PDF") and len(r.content) > 3000
        assert r.headers["content-disposition"].startswith('attachment; filename="Manual_')


def test_markdown_en_linea():
    assert manual._en_linea("**Cobrada** y *nota* <x> & `cód`") == \
        "<b>Cobrada</b> y <i>nota</i> &lt;x&gt; &amp; <font face='Courier'>cód</font>"
    assert manual._en_linea("3 * 4 = 12") == "3 * 4 = 12"
