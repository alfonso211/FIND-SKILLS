"""Lector de documentos que «teclea» la zona MRZ: lectura exacta sin imagen ni OCR, incluso con la distribución
del teclado cambiada o con las líneas seguidas, y la ficha del cliente se completa como con el escáner."""
from app import ocr_documentos
from docs_sinteticos import mrz_dni

PAS = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10"]


def test_texto_tecleado():
    # DNI con saltos de línea de Windows
    d = ocr_documentos.leer_texto("\r\n".join(mrz_dni()) + "\r\n", "DNI")
    assert d["leido"] and d["mrz_valido"] and (d["documento_tipo"], d["documento_num"]) == ("DNI", "99999999R")
    # lector configurado en inglés con teclado español: «<» llega como «;»; y en minúsculas
    p = ocr_documentos.leer_texto("\n".join(PAS).replace("<", ";").lower())
    assert p["mrz_valido"] and (p["documento_tipo"], p["apellidos"]) == ("PAS", "Eriksson")
    assert any("CADUCADO" in a for a in p["avisos"])
    # todo seguido, sin saltos de línea
    assert ocr_documentos.leer_texto("".join(mrz_dni()))["mrz_valido"]
    assert ocr_documentos.leer_texto("".join(PAS))["mrz_valido"]
    assert not ocr_documentos.leer_texto("HOLA QUE TAL ESTO NO ES UN DOCUMENTO")["leido"]


def test_api_lector_mrz(client, admin, ids):
    texto = "\n".join(mrz_dni())
    r = client.post("/api/documentos/mrz", headers=admin, json={"texto": texto, "tipo": "DNI"})
    assert r.status_code == 200 and r.json()["lectura"]["documento_num"] == "99999999R"
    assert r.json()["tercero"] is None
    c = client.post("/api/terceros", headers=admin, json={
        "company_id": ids["companies"]["INVERSIETE S.A."], "tipo": "huesped", "nombre": "Lucía"}).json()
    r = client.post("/api/documentos/mrz", headers=admin, json={"texto": texto, "tercero_id": c["id"]}).json()
    assert "documento_num" in r["aplicado"] and r["tercero"]["num_soporte"] == "BAA000589"
    assert client.post("/api/documentos/mrz", headers=admin, json={"texto": "x" * 30}).json()["lectura"]["leido"] is False
