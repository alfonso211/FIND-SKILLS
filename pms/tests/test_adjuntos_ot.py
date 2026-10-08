"""Fotos y documentos de las OT, parte de incidencia en PDF, avisos de OT urgente y versión de la interfaz."""
from io import BytesIO

import pypdfium2 as pdfium
from PIL import Image

from app import avisos
from conftest import login


def _jpeg(ancho=3000, alto=1500, color=(200, 40, 40)) -> bytes:
    out = BytesIO()
    Image.new("RGB", (ancho, alto), color).save(out, "JPEG")
    return out.getvalue()


def _pdf_texto(datos: bytes) -> str:
    doc = pdfium.PdfDocument(datos)
    return "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc)))


def _usuario(client, admin, ids, email, rol, codigo):
    a = ids["assets"][codigo]["id"]
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": email.split("@")[0], "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"][rol], "asset_id": a}]})
    assert r.status_code == 201, r.text
    h = login(client, email, "Provisional1")
    client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    return h


def test_version_interfaz(client):
    html = client.get("/").text
    assert "/static/app.js?v=" in html and "window.PMS_VERSION" in html
    assert client.get("/").headers["cache-control"] == "no-cache"
    v = html.split('window.PMS_VERSION = "')[1].split('"')[0]
    assert client.get("/api/auth/me").headers["x-pms-version"] == v  # también en respuestas de error


def test_adjuntos_y_parte(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    unit = client.get(f"/api/unidades?asset_id={sae}&q=A-133", headers=admin).json()[0]
    rec = _usuario(client, admin, ids, "recepcion.adjuntos@inversiete.com", "Recepción", "SAE")
    w = client.post("/api/mantenimiento/ordenes", headers=rec, json={
        "asset_id": sae, "unit_id": unit["id"], "titulo": "Gotera en baño", "categoria": "fontaneria",
        "descripcion": "Gotea el techo del baño sobre el lavabo"}).json()
    base = f"/api/mantenimiento/ordenes/{w['id']}/adjuntos"

    # recepción sube fotos de la avería: se reducen a 2000 px y se guardan en JPEG
    r = client.post(base, headers=rec, data={"tipo": "averia"},
                    files=[("ficheros", ("IMG_0001.png", _png(), "image/png")),
                           ("ficheros", ("IMG_0002.jpg", _jpeg(), "image/jpeg"))])
    assert r.status_code == 201, r.text
    fotos = r.json()
    assert [f["nombre"] for f in fotos] == ["IMG_0001.jpg", "IMG_0002.jpg"]
    assert all(f["mime"] == "image/jpeg" and f["tipo_nombre"] == "Foto de la avería" for f in fotos)
    img = Image.open(BytesIO(client.get(f"/api/mantenimiento/adjuntos/{fotos[1]['id']}", headers=rec).content))
    assert max(img.size) == 2000
    # pero no facturas ni certificados (son de mantenimiento)
    pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
    assert client.post(base, headers=rec, data={"tipo": "factura"},
                       files=[("ficheros", ("f.pdf", pdf, "application/pdf"))]).status_code == 403
    r = client.post(base, headers=admin, data={"tipo": "oca", "descripcion": "Certificado OCA BT"},
                    files=[("ficheros", ("certificado.pdf", pdf, "application/pdf"))])
    assert r.status_code == 201 and r.json()[0]["mime"] == "application/pdf"
    oca = r.json()[0]
    # formatos no admitidos
    r = client.post(base, headers=admin, data={"tipo": "otro"}, files=[("ficheros", ("x.txt", b"hola", "text/plain"))])
    assert r.status_code == 400 and "Formato no admitido" in r.json()["detail"]
    heic = b"\x00\x00\x00\x18ftypheic" + b"\x00" * 50
    r = client.post(base, headers=admin, data={"tipo": "averia"}, files=[("ficheros", ("a.heic", heic, "image/heic"))])
    assert r.status_code == 400 and "HEIC" in r.json()["detail"]

    lista = client.get(base, headers=rec).json()
    assert len(lista) == 3 and lista[0]["usuario"] == "recepcion.adjuntos"
    ot = [o for o in client.get(f"/api/mantenimiento/ordenes?asset_id={sae}", headers=admin).json() if o["id"] == w["id"]][0]
    assert ot["n_adjuntos"] == 3
    # borrar: recepción solo lo suyo; mantenimiento todo
    assert client.delete(f"/api/mantenimiento/adjuntos/{oca['id']}", headers=rec).status_code == 403
    assert client.delete(f"/api/mantenimiento/adjuntos/{fotos[0]['id']}", headers=rec).json() == {"ok": True}

    # parte de incidencia para la subcontrata, con la foto de la avería
    client.put(f"/api/mantenimiento/ordenes/{w['id']}", headers=admin,
               json={"proveedor": "Fontanería Ejemplo SL", "prioridad": "alta"})
    r = client.get(f"/api/mantenimiento/ordenes/{w['id']}/parte", headers=rec)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert f'Parte_OT-{w["id"]:05d}.pdf' in r.headers["content-disposition"]
    texto = _pdf_texto(r.content)
    for esperado in ("PARTE DE INCIDENCIA", f"OT-{w['id']:05d}", "Gotera en baño", "Fontanería Ejemplo SL",
                     "INVERSIETE S.A.", "A rellenar por la subcontrata", "FOTOS DE LA AVERÍA"):
        assert esperado in texto, esperado
    imagenes = [o for o in pdfium.PdfDocument(r.content)[0].get_objects() if o.type == pdfium.raw.FPDF_PAGEOBJ_IMAGE]
    assert len(imagenes) == 3  # logotipos de INVERSIETE y del activo + la foto que queda (la otra se borró)
    # sin permiso sobre el activo
    rec_sfl = _usuario(client, admin, ids, "recepcion.adjuntos.sfl@inversiete.com", "Recepción", "SFL")
    assert client.get(base, headers=rec_sfl).status_code == 403
    assert client.get(f"/api/mantenimiento/ordenes/{w['id']}/parte", headers=rec_sfl).status_code == 403


def _png() -> bytes:
    out = BytesIO()
    Image.new("RGBA", (800, 600), (0, 120, 200, 128)).save(out, "PNG")
    return out.getvalue()


def test_aviso_ot_urgente(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    rec = _usuario(client, admin, ids, "recepcion.avisos@inversiete.com", "Recepción", "SAE")
    callado = _usuario(client, admin, ids, "recepcion.sinavisos@inversiete.com", "Recepción", "SAE")
    prefs = client.get("/api/auth/avisos", headers=rec).json()
    assert prefs["correo_configurado"] and [t["tipo"] for t in prefs["tipos"]] == ["ot_urgente", "estancias_vencidas", "garajes_impagados", "garajes_vencen", "facturas_pendientes", "informe_presidencia", "documentacion_legal", "agenda"]  # recepción
    assert all(t["activo"] for t in prefs["tipos"])
    assert client.put("/api/auth/avisos", headers=callado, json={"avisos": []}).json()["tipos"][0]["activo"] is False
    assert client.put("/api/auth/avisos", headers=callado, json={"avisos": ["inventado"]}).status_code == 400

    avisos.BANDEJA.clear()
    w = client.post("/api/mantenimiento/ordenes", headers=rec, json={
        "asset_id": sae, "titulo": "Ascensor bloque A parado con persona dentro", "categoria": "ascensores",
        "prioridad": "urgente"}).json()
    para = {m["para"] for m in avisos.BANDEJA}
    assert "alfonso@inversiete.es" in para and "jaime@apartamentossuitesaeropuerto.es" in para
    assert "recepcion.avisos@inversiete.com" not in para  # quien la abre no se avisa a sí mismo
    assert "recepcion.sinavisos@inversiete.com" not in para  # lo ha desactivado
    assert "juancarlos@apartamentossuitesflorida.es" not in para  # otro activo
    m = [m for m in avisos.BANDEJA if m["para"] == "alfonso@inversiete.es"][0]
    assert m["asunto"].startswith("OT URGENTE · Suite Aeropuerto · Zonas comunes: Ascensor bloque A")
    assert f"OT-{w['id']:05d}" in m["texto"] and "recepcion.avisos" in m["texto"]
    # cambiar otra cosa de la OT no repite el aviso; pasar otra OT a urgente sí avisa
    n = len(avisos.BANDEJA)
    client.put(f"/api/mantenimiento/ordenes/{w['id']}", headers=admin, json={"asignado_a": "Técnico guardia"})
    assert len(avisos.BANDEJA) == n
    w2 = client.post("/api/mantenimiento/ordenes", headers=admin, json={"asset_id": sae, "titulo": "Fuga leve"}).json()
    assert len(avisos.BANDEJA) == n
    client.put(f"/api/mantenimiento/ordenes/{w2['id']}", headers=admin, json={"prioridad": "urgente"})
    assert any("Fuga leve" in m["asunto"] for m in avisos.BANDEJA[n:])
