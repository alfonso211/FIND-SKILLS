"""Gestión del personal: ficha del empleado con datos laborales (solo para quien la gestiona), saldo de vacaciones con
aviso al superarlo, vista de ausencias de todos los activos, documentos con vencimiento y registro de jornada
(desde el usuario del PMS o con el enlace personal), con correcciones trazables, informe mensual y Excel."""
from datetime import date, datetime, timedelta

from app import avisos
from app.database import SessionLocal
from test_pms import _new_user

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


def _lunes(semanas: int) -> date:
    hoy = date.today()
    return hoy + timedelta(days=7 * semanas - hoy.weekday())


def test_ficha_saldo_documentos_y_jornada(client, admin, ids):
    sfl, sae = ids["assets"]["SFL"]["id"], ids["assets"]["SAE"]["id"]
    rec = _new_user(client, admin, "rec.ficha@inversiete.com", [{"role_id": ids["roles"]["Recepción"], "asset_id": sfl}])
    tec = _new_user(client, admin, "tec.ficha@inversiete.com",
                    [{"role_id": ids["roles"]["Técnico Mantenimiento"], "asset_id": sfl}])
    yo = client.get("/api/auth/me", headers=rec).json()
    anio = date.today().year

    # ficha completa (la crea dirección), enlazada al usuario de recepción
    p = client.post("/api/personal", headers=admin, json={
        "asset_id": sfl, "area": "recepcion", "nombre": "Recepcionista Ficha", "telefono": "600123123",
        "user_id": yo["id"], "dni": "12345678Z", "puesto": "Recepcionista", "tipo_contrato": "indefinido",
        "fecha_alta": f"{anio}-01-01", "jornada_semanal": 40, "vacaciones_dias": 22, "vacaciones_tipo": "laborables"})
    assert p.status_code == 201, p.text
    p = p.json()
    assert p["saldo"]["corresponden"] == 22 and p["dni"] == "12345678Z"
    m = client.post("/api/personal", headers=admin, json={
        "asset_id": sfl, "area": "mantenimiento", "nombre": "Técnico Ficha", "telefono": "600999888"}).json()
    # quien no gestiona la ficha no ve los datos laborales
    vista = {x["id"]: x for x in client.get("/api/personal", headers=tec).json()}
    assert "dni" not in vista[p["id"]] and not vista[p["id"]]["gestiona"]

    # vacaciones: saldo, aviso al superarlo y vista de todos los activos
    l1 = _lunes(8)
    v = client.post("/api/ausencias", headers=admin, json={
        "asset_id": sfl, "staff_id": p["id"], "tipo": "vacaciones", "desde": l1.isoformat(),
        "hasta": (l1 + timedelta(days=4)).isoformat(), "aprobar": True})
    assert v.status_code == 201 and v.json()["aviso_saldo"] is None and v.json()["estado"] == "aprobada"
    s = client.get(f"/api/personal/{p['id']}/saldo", headers=admin).json()
    if l1.year == anio:
        assert (s["aprobadas"], s["restantes"]) == (5, 17)
    l2 = _lunes(12)
    w = client.post("/api/ausencias", headers=admin, json={
        "asset_id": sfl, "staff_id": p["id"], "tipo": "vacaciones", "desde": l2.isoformat(), "hasta": (l2 + timedelta(days=27)).isoformat()})
    if l2.year == anio and (l2 + timedelta(days=27)).year == anio:
        assert "Supera el saldo" in w.json()["aviso_saldo"]
    todas = client.get("/api/ausencias", headers=admin, params={"estado": "vigentes"}).json()
    assert any(x["id"] == w.json()["id"] and x["activo"] == "Suite Florida" for x in todas)
    assert any(x["id"] == w.json()["id"] and x.get("aviso_saldo") for x in todas) or l2.year != anio
    assert client.get("/api/ausencias/resumen", headers=admin).status_code == 200
    assert client.get("/api/ausencias/excel", headers=admin).status_code == 200

    # documentos de la ficha con vencimiento
    vencido = (date.today() - timedelta(days=1)).isoformat()
    r = client.post(f"/api/personal/{p['id']}/documentos", headers=admin, data={"tipo": "reconocimiento", "vence": vencido},
                    files=[("ficheros", ("reco.pdf", PDF, "application/pdf"))])
    assert r.status_code == 201, r.text
    docs = client.get(f"/api/personal/{p['id']}/documentos", headers=admin).json()
    assert docs[0]["vencido"] and client.get(f"/api/personal/documentos/{docs[0]['id']}", headers=admin).status_code == 200
    assert client.get(f"/api/personal/{p['id']}/documentos", headers=tec).status_code == 403
    assert client.get(f"/api/personal/{p['id']}/documentos", headers=rec).status_code == 403  # Recepción 2 no
    with SessionLocal() as db:
        assert any(f[0] == "Recepcionista Ficha" for _, f in avisos._datos_resumen(db, date.today())["personal"])

    # registro de jornada desde su usuario del PMS
    assert client.get("/api/jornada/mia", headers=rec).json()["dentro"] is False
    assert client.post("/api/jornada/mia/fichar", headers=rec, json={"lat": 40.4, "lon": -3.7}).json()["dentro"]
    panel = client.get("/api/panel", headers=admin).json()["personal_hoy"]
    assert "Recepcionista Ficha" in panel["dentro"] and panel["documentos"] >= 1
    assert client.post("/api/jornada/mia/fichar", headers=rec, json={}).json()["dentro"] is False
    assert client.get("/api/jornada/mia", headers=tec).status_code == 404  # sin ficha enlazada

    # con su enlace personal (sin usuario); el de una subcontrata, no
    e = client.post(f"/api/personal/{m['id']}/enlace-fichaje", headers=admin).json()
    ruta = e["url"].split("://", 1)[1].split("/", 1)[1]
    assert client.get("/" + ruta.split("?")[0]).status_code == 200
    k = ruta.split("k=")[1]
    assert client.post(f"/api/publico/fichaje/{m['id']}?k={k}", json={}).json()["dentro"]
    assert client.post(f"/api/publico/fichaje/{m['id']}?k=otra", json={}).status_code == 404
    nueva = client.post(f"/api/personal/{m['id']}/enlace-fichaje?nuevo=true", headers=admin).json()["url"]
    assert nueva != e["url"] and client.get(f"/api/publico/fichaje/{m['id']}?k={k}").status_code == 404
    sub = client.post("/api/personal", headers=admin, json={
        "asset_id": sae, "area": "limpieza", "nombre": "Limpia Sub", "telefono": "611222333", "empresa": "Sub SL"}).json()
    client.post("/api/proveedores", headers=admin, json={"nombre": "Sub SL"})
    client.put(f"/api/personal/{sub['id']}", headers=admin, json={**{k_: sub[k_] for k_ in (
        "asset_id", "area", "nombre", "telefono", "empresa")}, "tipo_contrato": "autonomo"})
    assert client.post(f"/api/personal/{sub['id']}/enlace-fichaje", headers=admin).status_code == 400

    # consulta del mes, corrección trazable, registro manual, informe y Excel
    mes = date.today().strftime("%Y-%m")
    filas = {x["id"]: x for x in client.get("/api/jornada", headers=admin, params={"mes": mes}).json()}
    assert filas[p["id"]]["dias"] == 1 and filas[m["id"]]["fichajes"][0]["salida"] is None
    fid = filas[m["id"]]["fichajes"][0]["id"]
    ent = (datetime.now() - timedelta(days=1)).replace(hour=8, minute=0, second=0, microsecond=0)
    r = client.post(f"/api/jornada/{fid}/corregir", headers=admin, json={
        "entrada": ent.isoformat(), "salida": (ent + timedelta(hours=8)).isoformat(), "motivo": "Olvidó fichar la salida"})
    assert r.status_code == 200, r.text
    assert r.json()["corregido"] and r.json()["horas"] == 8
    assert client.post(f"/api/jornada/{fid}/corregir", headers=tec, json={
        "entrada": ent.isoformat(), "motivo": "xxx"}).status_code == 403
    r = client.post("/api/jornada/manual", headers=admin, json={
        "staff_id": m["id"], "entrada": (ent - timedelta(days=1)).isoformat(),
        "salida": (ent - timedelta(days=1) + timedelta(hours=40)).isoformat(), "motivo": "Sin móvil"})
    assert r.status_code == 400  # más de 16 horas
    pdf = client.get("/api/jornada/informe.pdf", headers=admin, params={"staff_id": m["id"], "mes": mes})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get("/api/jornada/excel", headers=admin, params={"mes": mes}).status_code == 200
    # la ficha con fichajes no se borra (se conservan 4 años): se da de baja
    assert client.delete(f"/api/personal/{m['id']}", headers=admin).status_code == 400
