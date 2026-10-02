import pytest

from app import ocr_documentos
from app.config import settings
from docs_sinteticos import reverso_dni, tarjeta
from test_contrato_alojamiento import _reserva
from test_pms import _new_user

pytestmark = pytest.mark.skipif(not ocr_documentos.disponible(), reason="tesseract-ocr no instalado")


def _subir(client, h, cid, anverso=None, reverso=None):
    files = {}
    if anverso:
        files["anverso"] = ("anverso.png", anverso, "image/png")
    if reverso:
        files["reverso"] = ("reverso.jpg", reverso, "image/jpeg")
    return client.post(f"/api/terceros/{cid}/documentos", headers=h, files=files)


def test_escaneo_dni_completa_ficha_y_guarda_copia_cifrada(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    r = _reserva(client, admin, sfl, "P2-4C", 50, 52)
    gid = r["guest_id"]
    reverso = reverso_dni(formato="JPEG")
    res = _subir(client, admin, gid, anverso=tarjeta(["DNI"], []), reverso=reverso)
    assert res.status_code == 201, res.text
    j = res.json()
    lec = j["lectura"]
    assert lec["leido"] and lec["mrz_valido"] and lec["documento_tipo"] == "DNI"
    assert lec["domicilio"]["municipio"] == "Sevilla"
    t = j["tercero"]
    assert (t["documento_num"], t["num_soporte"], t["sexo"], t["fecha_nacimiento"]) == \
        ("99999999R", "BAA000589", "F", "1980-01-01")
    assert t["nacionalidad"] == "España" and t["fecha_caducidad_doc"] == "2031-06-02"
    assert t["nombre"] == "Lucía"  # el nombre tecleado (con tilde) no se pisa
    assert len(j["documentos"]) == 2

    # copia cifrada en disco: no es legible sin la clave
    ficheros = list(settings.docs_dir.glob("*.bin"))
    assert ficheros and all(not f.read_bytes().startswith((b"\xff\xd8", b"\x89PNG")) for f in ficheros)
    lista = client.get(f"/api/terceros/{gid}/documentos", headers=admin).json()
    rev = next(d for d in lista if d["cara"] == "reverso")
    ver = client.get(f"/api/documentos/{rev['id']}", headers=admin)
    assert ver.status_code == 200 and ver.content == reverso and ver.headers["content-type"] == "image/jpeg"
    log = client.get("/api/admin/auditoria?entidad=tercero", headers=admin).json()
    assert {"escanear_documento", "ver_documento"} <= {e["accion"] for e in log}


def test_documento_no_valido_y_permisos(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    r = _reserva(client, admin, sae, "A-250", 60, 61)
    gid = r["guest_id"]
    assert _subir(client, admin, gid, anverso=b"esto no es una imagen").status_code == 400
    assert client.post(f"/api/terceros/{gid}/documentos", headers=admin).status_code == 400
    # sin zona MRZ: se guarda la copia pero no se toca la ficha y se avisa
    j = _subir(client, admin, gid, anverso=tarjeta(["FOTO"], [])).json()
    assert j["lectura"]["leido"] is False and j["aplicado"] == [] and "MRZ" not in j["lectura"]["avisos"][0]
    # la recepción de otro activo no ve ni sube documentos de este cliente
    rec_sf = _new_user(client, admin, "rec.sf.docs@inversiete.es",
                       [{"role_id": ids["roles"]["Recepción"], "asset_id": ids["assets"]["SFL"]["id"]}])
    assert client.get(f"/api/terceros/{gid}/documentos", headers=rec_sf).status_code == 403
    did = j["documentos"][0]["id"]
    assert client.get(f"/api/documentos/{did}", headers=rec_sf).status_code == 403
    assert _subir(client, rec_sf, gid, anverso=reverso_dni()).status_code == 403
    # borrar
    assert client.delete(f"/api/documentos/{did}", headers=admin).status_code == 200
    assert client.get(f"/api/documentos/{did}", headers=admin).status_code == 404
