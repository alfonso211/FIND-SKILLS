"""Pedidos de material: catálogo con referencia automática, pedidos que autoriza Recepción 1, PDF, envío al
proveedor e intercambio del catálogo con INVERGESTION (CSV en ZIP)."""
import csv
import io
import json
import zipfile

from conftest import login

def _recepcion(client, admin, ids, email, nombre, codigo):
    """Usuario de recepción propio de la prueba (Babilonia 35 no tiene recepción inicial: el «Recepción 1» es este)."""
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": nombre, "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"]["Recepción"], "asset_id": ids["assets"][codigo]["id"]}]})
    assert r.status_code == 201, r.text
    h = login(client, email, "Provisional1")
    client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "PedidosPrueba2026"})
    return login(client, email, "PedidosPrueba2026")


def _zip(filas, manifest=None):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        cab = "referencia;articulo;familia;unidad;precio;tipo_iva;marca;ref_proveedor;proveedor;proveedor_nif;" \
              "fecha_factura;num_factura;accion\n"
        z.writestr("productos.csv", (cab + "".join(";".join(f) + "\n" for f in filas)).encode("utf-8"))
        z.writestr("manifest.json", json.dumps(manifest or {"tipo": "CAMBIOS", "fecha": "2026-10-08", "filas": len(filas)}))
    return out.getvalue()


def _csv(zip_bytes):
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    texto = z.read("productos.csv").decode("utf-8")
    assert not texto.startswith("﻿") and "\r" not in texto
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def test_catalogo_e_importacion(client, admin):
    p = client.post("/api/productos", headers=admin, json={"articulo": "Bombilla LED E27 9W", "familia": "electricidad e iluminacion",
                                                            "precio": 1.85}).json()
    assert p["referencia"].startswith("PMS-") and p["familia"] == "ELECTRICIDAD E ILUMINACIÓN" and p["precio_iva"] == 2.24
    assert client.post("/api/productos", headers=admin, json={"articulo": "Otra", "referencia": p["referencia"]}).status_code == 400

    filas = [["INV-000010", "Grifo monomando lavabo", "FONTANERÍA", "ud", "38.50", "21", "Roca", "RC-1", "Fontanería Rápida SL",
              "B11111111", "2026-09-30", "F-77", "ALTA"],
             ["RF-555", "\"Silicona; blanca\"", "PINTURA", "ud", "4.1", "21", "", "", "", "", "", "", "ALTA"]]
    datos = _zip(filas)
    subir = lambda d, conf: client.post("/api/productos/importar", headers=admin,  # noqa: E731
                                        files={"fichero": ("INVERGESTION_PRODUCTOS_20261008_100000.zip", d)},
                                        data={"confirmar": str(conf).lower()}).json()
    prev = subir(datos, False)
    assert prev["altas"] == 2 and prev["errores"] == [] and not client.get("/api/productos?q=Grifo", headers=admin).json()
    assert subir(datos, True)["altas"] == 2
    again = subir(datos, True)  # volver a cargar el mismo fichero no duplica
    assert again["altas"] == 0 and again["sin_cambios"] == 2
    filas[0][4] = "41.20"
    cambio = subir(_zip(filas), True)
    assert cambio["modificaciones"] == 1 and cambio["sin_cambios"] == 1
    g = client.get("/api/productos?q=grifo roca", headers=admin).json()
    assert len(g) == 1 and g[0]["precio"] == 41.2 and g[0]["origen"] == "INVERGESTION"
    assert client.get("/api/productos?q=silicona", headers=admin).json()[0]["articulo"] == "Silicona; blanca"


def test_pedido_autorizacion_pdf_envio_y_exportacion(client, admin, ids):
    sfl = ids["assets"]["BAB35"]["id"]
    prov = client.post("/api/proveedores", headers=admin, json={"nombre": "Suministros Pedidos SL", "nif": "B22222228",
                                                                "telefono": "600123123"}).json()
    grifo = client.get("/api/productos?q=grifo", headers=admin).json()[0]
    r1 = _recepcion(client, admin, ids, "r1.pedidos@inversiete.com", "Recepción 1 · Pruebas pedidos", "BAB35")
    r2 = _recepcion(client, admin, ids, "r2.pedidos@inversiete.com", "Recepción 2 · Pruebas pedidos", "BAB35")
    alta = {"asset_id": sfl, "supplier_id": prov["id"], "lineas": [
        {"product_id": grifo["id"], "cantidad": 2},
        {"nuevo": {"articulo": "Junta tórica 20 mm", "familia": "FONTANERÍA"}, "cantidad": 10, "precio": 0.35}]}
    # Recepción 2: queda pendiente de que lo autorice Recepción 1
    p = client.post("/api/pedidos", headers=r2, json=alta).json()
    assert p["estado"] == "pendiente" and p["numero"].startswith("PED-") and p["base"] == 85.9
    junta = p["lineas"][1]["producto"]
    assert junta["referencia"].startswith("PMS-") and junta["asset_id"] == sfl and junta["proveedor"] == "Suministros Pedidos SL"
    assert client.post(f"/api/pedidos/{p['id']}/autorizar", headers=r2).status_code == 403
    a = client.post(f"/api/pedidos/{p['id']}/autorizar", headers=r1).json()
    assert a["estado"] == "autorizado" and a["autorizado_por_nombre"].startswith("Recepción 1")
    # Recepción 1 (y dirección) lo hacen ya autorizado
    assert client.post("/api/pedidos", headers=r1, json={**alta, "lineas": alta["lineas"][:1]}).json()["estado"] == "autorizado"
    pdf = client.get(f"/api/pedidos/{p['id']}/pdf", headers=r1)
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    env = client.post(f"/api/pedidos/{p['id']}/enviar", headers=r1, json={"canales": ["whatsapp"]}).json()
    assert env["pedido"]["estado"] == "enviado" and env["enviados"][0]["whatsapp"].startswith("https://wa.me/34600123123")
    assert client.post(f"/api/pedidos/{p['id']}/enviar", headers=r1, json={"canales": ["email"]}).status_code == 400  # sin correo

    # a INVERGESTION: alta de la junta (con su pedido) y pedido del grifo; solo lo nuevo
    prueba = client.get("/api/productos/exportar?activo=BABILONIA35&prueba=true", headers=admin)
    assert prueba.headers["content-disposition"].endswith('_BABILONIA35_' + prueba.headers["content-disposition"][-13:])
    filas = _csv(prueba.content)
    assert {(f["referencia"], f["accion"]) for f in filas} >= {(junta["referencia"], "ALTA"), (grifo["referencia"], "PEDIDO")}
    f = next(f for f in filas if f["referencia"] == grifo["referencia"] and f["num_pedido"] == p["numero"])
    assert f["precio"] == "41.20" and f["cantidad"] == "2" and f["activo"] == "BABILONIA35" and f["proveedor_nif"] == "B22222228"
    assert len(_csv(client.get("/api/productos/exportar?activo=BABILONIA35&prueba=true", headers=admin).content)) == len(filas)
    assert len(_csv(client.get("/api/productos/exportar?activo=BABILONIA35", headers=admin).content)) == len(filas)
    assert _csv(client.get("/api/productos/exportar?activo=BABILONIA35", headers=admin).content) == []
