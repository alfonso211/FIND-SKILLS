"""Portal del colaborador: el usuario de una subcontrata solo entra en su portal y ve lo de su empresa (personal,
OT, partes validados y envíos); sube documentos que quedan pendientes de revisar; la documentación de personal
solo la ven Recepción 1 y dirección."""
from datetime import date

from conftest import login

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _user(client, admin, ids, email, nombre, rol, codigo="BAB35", **extra):
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": nombre, "password": "Provisional1", **extra,
        "asignaciones": [{"role_id": ids["roles"][rol], "asset_id": ids["assets"][codigo]["id"]}]})
    assert r.status_code == 201, r.text
    h = login(client, email, "Provisional1")
    client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    return h, r.json()


def test_portal_colaborador(client, admin, ids):
    bab, sfl = ids["assets"]["BAB35"]["id"], ids["assets"]["SFL"]["id"]
    prov = client.post("/api/proveedores", headers=admin, json={"nombre": "Limpiezas Colab S.L."}).json()
    otro = client.post("/api/proveedores", headers=admin, json={"nombre": "Otra Empresa Colab SL"}).json()
    mia = client.post("/api/personal", headers=admin, json={
        "asset_id": bab, "area": "limpieza", "nombre": "Ana Colab", "empresa": "LIMPIEZAS COLAB SL",
        "telefono": "600111222"}).json()
    ajena = client.post("/api/personal", headers=admin, json={
        "asset_id": bab, "area": "limpieza", "nombre": "Luis Ajeno", "empresa": "Otra Empresa Colab SL",
        "telefono": "600333444"}).json()
    w1 = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": bab, "titulo": "Limpieza a fondo del portal", "asignacion": "subcontrata",
        "proveedor_id": prov["id"]}).json()
    w2 = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": bab, "titulo": "OT de otra empresa", "asignacion": "subcontrata", "proveedor_id": otro["id"]}).json()
    env = client.post(f"/api/mantenimiento/ordenes/{w1['id']}/enviar", headers=admin, json={
        "personal_ids": [mia["id"]], "canal": "whatsapp"})
    assert env.status_code == 200, env.text
    client.post(f"/api/mantenimiento/ordenes/{w2['id']}/enviar", headers=admin, json={
        "personal_ids": [ajena["id"]], "canal": "whatsapp"})
    hoy = date.today().isoformat()
    client.post(f"/api/mantenimiento/ordenes/{w1['id']}/confirmar-mantenimiento", headers=admin,
                json={"solucion": "Hecho con máquina"})
    client.post(f"/api/mantenimiento/ordenes/{w2['id']}/confirmar-mantenimiento", headers=admin,
                json={"solucion": "Trabajo de otros"})
    v = client.post("/api/partes-trabajo/validar", headers=admin, json={"asset_id": bab, "area": "mantenimiento",
                                                                         "fecha": hoy})
    assert v.status_code == 200, v.text

    col, u = _user(client, admin, ids, "colab@limpiezascolab.es", "Ana (Limpiezas Colab)", "Colaborador",
                   supplier_id=prov["id"])
    assert u["supplier_id"] == prov["id"]
    # fuera de su portal no entra en nada
    for ruta in ("/api/activos", "/api/documentos-recibidos", "/api/mantenimiento/ordenes", "/api/personal",
                 f"/api/ausencias?asset_id={bab}", "/api/proveedores", "/api/agenda/pendientes"):
        assert client.get(ruta, headers=col).status_code == 403, ruta
    me = client.get("/api/auth/me", headers=col).json()
    assert me["colaborador"]["proveedor"] == "Limpiezas Colab S.L."

    res = client.get("/api/colaborador/resumen", headers=col).json()
    assert [a["id"] for a in res["activos"]] == [bab] and res["personal"] == 1
    assert [p["nombre"] for p in client.get("/api/colaborador/personal", headers=col).json()] == ["Ana Colab"]
    ots = client.get("/api/colaborador/ordenes", headers=col).json()
    assert [o["id"] for o in ots] == [w1["id"]]
    envios = client.get("/api/colaborador/envios", headers=col).json()
    assert len(envios) == 1 and envios[0]["persona"] == "Ana Colab" and "portal" in envios[0]["texto"].lower()
    partes = client.get("/api/colaborador/partes", headers=col).json()
    refs = [x["ref"] for p in partes for x in p["lineas"]]
    assert f"OT-{w1['id']:05d}" in refs and f"OT-{w2['id']:05d}" not in refs

    # sube documentos: pendientes de revisar; solo en sus activos
    sube = lambda **d: client.post("/api/colaborador/documentos", headers=col, files=[("ficheros", ("f.pdf", d.pop("pdf", PDF), "application/pdf"))], data=d)  # noqa: E731
    f = sube(asset_id=bab, tipo="factura", fecha=hoy, referencia="F-2026-77", work_order_id=w1["id"]).json()
    assert f["revision"] == "pendiente" and f["ot"] == f"OT-{w1['id']:05d}"
    assert sube(asset_id=sfl, tipo="factura", fecha=hoy).status_code == 403
    assert sube(asset_id=bab, tipo="factura", fecha=hoy).status_code == 409  # mismo fichero
    assert sube(asset_id=bab, tipo="otro", fecha=hoy, work_order_id=w2["id"], pdf=PDF + b"x").status_code == 400
    assert sube(asset_id=bab, tipo="personal", fecha=hoy, staff_id=ajena["id"], pdf=PDF + b"y").status_code == 400
    dp = sube(asset_id=bab, tipo="personal", fecha=hoy, staff_id=mia["id"], descripcion="TC2 septiembre",
              pdf=PDF + b"z").json()
    assert dp["persona"] == "Ana Colab"
    assert client.get(f"/api/colaborador/documentos/{f['id']}/fichero", headers=col).content == PDF

    # recepción: ve la factura, no la documentación de personal (sí Recepción 1 y dirección)
    r2, _ = _user(client, admin, ids, "r2.colab@inversiete.com", "Recepción 2 · Colab", "Recepción")
    r1, _ = _user(client, admin, ids, "r1.colab@inversiete.com", "Recepción 1 · Zzz colab", "Recepción")
    ver = lambda h: {d["id"] for d in client.get("/api/documentos-recibidos", headers=h, params={  # noqa: E731
        "asset_id": bab, "revision": "pendiente"}).json()}
    assert f["id"] in ver(r2) and dp["id"] not in ver(r2)
    assert client.get(f"/api/documentos-recibidos/{dp['id']}/fichero", headers=r2).status_code == 403
    assert client.post(f"/api/documentos-recibidos/{dp['id']}/revisar", headers=r2, json={"aceptar": True}).status_code == 403
    assert {f["id"], dp["id"]} <= ver(admin)
    assert client.post(f"/api/documentos-recibidos/{f['id']}/revisar", headers=r2, json={"aceptar": False}).status_code == 400
    assert client.post(f"/api/documentos-recibidos/{f['id']}/revisar", headers=r2,
                       json={"aceptar": False, "nota": "Falta el nº de pedido"}).json()["revision"] == "rechazado"
    mios = {d["id"]: d for d in client.get("/api/colaborador/documentos", headers=col).json()}
    assert mios[f["id"]]["revision_nota"] == "Falta el nº de pedido"
    assert client.delete(f"/api/colaborador/documentos/{f['id']}", headers=col).status_code == 400
    assert client.delete(f"/api/colaborador/documentos/{dp['id']}", headers=col).json()["ok"]
    # otro colaborador no ve lo de esta empresa
    col2, _ = _user(client, admin, ids, "colab@otra.es", "Otra Colab", "Colaborador", supplier_id=otro["id"])
    assert f["id"] not in {d["id"] for d in client.get("/api/colaborador/documentos", headers=col2).json()}
    assert client.get(f"/api/colaborador/documentos/{f['id']}/fichero", headers=col2).status_code == 404
    assert [o["id"] for o in client.get("/api/colaborador/ordenes", headers=col2).json()] == [w2["id"]]
    # un usuario normal no usa el portal
    assert client.get("/api/colaborador/resumen", headers=r2).status_code == 403
