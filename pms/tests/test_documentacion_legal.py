"""Documentación legal de los activos: checklist según la modalidad, escaneos en PDF, vencimientos, «no aplica»,
puntos propios, impresión, envío por correo y recordatorio semanal (lunes) a Recepción 1 y a la dirección."""
from datetime import date, timedelta

from app import avisos
from app import documentacion_legal as dl
from conftest import login

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _user(client, admin, ids, email, nombre, rol, codigo=None):
    asg = {"role_id": ids["roles"][rol]}
    if codigo:
        asg["asset_id"] = ids["assets"][codigo]["id"]
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": nombre, "password": "Provisional1", "asignaciones": [asg]})
    assert r.status_code == 201, r.text
    h = login(client, email, "Provisional1")
    client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    return h


def test_catalogo_por_modalidad():
    at = {c[0] for c in dl.aplicables(dl.AT)}
    lau = {c[0] for c in dl.aplicables(dl.LAU)}
    assert {"dr_turismo", "ret", "hojas_reclamaciones", "ses", "cee", "seguro_rc"} <= at
    assert {"fianzas", "cee", "contratos_alquiler"} <= lau and "dr_turismo" not in lau and "fianzas" not in at
    assert dl.vencimiento_por_defecto("seguro_rc", date(2026, 1, 31)) == date(2027, 1, 31)
    assert dl.vencimiento_por_defecto("cee", date(2024, 2, 29)) == date(2034, 2, 28)
    assert dl.vencimiento_por_defecto("escrituras", date(2026, 1, 1)) is None


def test_documentacion_legal(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    rec = _user(client, admin, ids, "rec.legal@inversiete.com", "Recepción 2 · Legal", "Recepción", "SAE")
    cons = _user(client, admin, ids, "tec.legal@inversiete.com", "Técnico Legal", "Técnico Mantenimiento", "SAE")
    assert client.get("/api/documentacion-legal", headers=cons, params={"asset_id": sae}).status_code == 403
    c = client.get("/api/documentacion-legal", headers=rec, params={"asset_id": sae}).json()
    items = {x["clave"]: x for x in c["items"]}
    assert items["dr_turismo"]["estado"] == "falta" and items["nra"]["estado"] == "opcional"
    assert c["resumen"]["porcentaje"] == 0
    # escaneo con fecha: el vencimiento sale solo (seguro: 1 año)
    hoy = date.today()
    r = client.post(f"/api/documentacion-legal/{sae}/seguro_rc/ficheros", headers=rec,
                    files=[("ficheros", ("poliza.pdf", PDF, "application/pdf"))], data={"fecha_documento": hoy.isoformat()})
    assert r.status_code == 201, r.text
    s = {x["clave"]: x for x in r.json()["items"]}["seguro_rc"]
    assert s["estado"] == "aportado" and s["vencimiento"] == dl.vencimiento_por_defecto("seguro_rc", hoy).isoformat()
    assert s["ficheros"][0]["nombre"].startswith("SAE_") and s["ficheros"][0]["nombre"].endswith(".pdf")
    assert client.post(f"/api/documentacion-legal/{sae}/seguro_rc/ficheros", headers=rec,
                       files=[("ficheros", ("p.pdf", PDF, "application/pdf"))]).status_code == 409
    fid = s["ficheros"][0]["id"]
    assert client.get(f"/api/documentacion-legal/ficheros/{fid}", headers=rec).content == PDF
    # caducado y por vencer
    vieja = (hoy - timedelta(days=400)).isoformat()
    client.post(f"/api/documentacion-legal/{sae}/ddd/ficheros", headers=rec,
                files=[("ficheros", ("ddd.pdf", PDF + b"1", "application/pdf"))], data={"fecha_documento": vieja})
    client.post(f"/api/documentacion-legal/{sae}/pci/ficheros", headers=rec,
                files=[("ficheros", ("pci.pdf", PDF + b"2", "application/pdf"))],
                data={"vencimiento": (hoy + timedelta(days=20)).isoformat()})
    items = {x["clave"]: x for x in client.get("/api/documentacion-legal", headers=rec, params={"asset_id": sae}).json()["items"]}
    assert items["ddd"]["estado"] == "caducado" and items["pci"]["estado"] == "por_vencer"
    # no aplica (con motivo) y puntos propios
    assert client.put(f"/api/documentacion-legal/{sae}/gas", headers=rec, json={"no_aplica": True}).status_code == 400
    r = client.put(f"/api/documentacion-legal/{sae}/gas", headers=rec, json={"no_aplica": True, "motivo": "Sin gas"}).json()
    assert {x["clave"]: x for x in r["items"]}["gas"]["estado"] == "no_aplica"
    assert client.put(f"/api/documentacion-legal/{sae}/fianzas", headers=rec, json={}).status_code == 400  # solo LAU
    r = client.post(f"/api/documentacion-legal/{sae}/extra", headers=rec, json={"titulo": "Licencia de rótulo"}).json()
    extra = next(x for x in r["items"] if x["grupo"] == "propios")
    assert extra["titulo"] == "Licencia de rótulo" and extra["estado"] == "falta"
    assert client.delete(f"/api/documentacion-legal/{sae}/extra/{extra['clave']}", headers=rec).status_code == 200
    # imprimir y enviar
    pdf = client.get(f"/api/documentacion-legal/{sae}/checklist.pdf", headers=rec)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    avisos.BANDEJA.clear()
    assert client.post(f"/api/documentacion-legal/{sae}/seguro_rc/enviar", headers=rec,
                       json={"email": "gestoria@ejemplo.es", "nota": "Póliza en vigor"}).json()["ok"]
    assert avisos.BANDEJA[-1]["para"] == "gestoria@ejemplo.es"
    resumen = {x["asset_id"]: x for x in client.get("/api/documentacion-legal/resumen", headers=rec).json()}
    assert resumen[sae]["caducado"] == 1 and "Control de plagas" in " ".join(resumen[sae]["pendientes_lista"])
    assert client.delete(f"/api/documentacion-legal/ficheros/{fid}", headers=cons).status_code == 403


def test_recordatorio_semanal(client, admin, ids):
    from app.database import SessionLocal
    _user(client, admin, ids, "r1.legal@inversiete.com", "Recepción 1 · Zzzz legal", "Recepción", "BAB35")
    _user(client, admin, ids, "dir.legal@inversiete.com", "Dirección Legal Pruebas", "Dirección Grupo")
    lunes = date.today() - timedelta(days=date.today().weekday())
    avisos.BANDEJA.clear()
    with SessionLocal() as db:
        assert dl.recordatorio_semanal(db, lunes + timedelta(days=1)) == 0  # solo los lunes
        assert dl.recordatorio_semanal(db, lunes) >= 2
        assert dl.recordatorio_semanal(db, lunes) == 0  # una vez por semana
    with SessionLocal() as db:
        from app.ausencias import recepcion_1
        from app.models import Asset
        r1 = recepcion_1(db, db.get(Asset, ids["assets"]["BAB35"]["id"])).email
    por = {m["para"]: m for m in avisos.BANDEJA}
    assert "C/ BABILONIA 35" in por[r1]["texto"] and "Depósito de las fianzas" in por[r1]["texto"]
    assert "Suite Florida".upper() in por["dir.legal@inversiete.com"]["texto"]  # la dirección recibe todos los activos
    assert "SUITE FLORIDA" not in por[r1]["texto"]  # Recepción 1 solo el suyo
