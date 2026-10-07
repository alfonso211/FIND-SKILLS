"""Lector de facturas (PDF con texto y foto), facturas duplicadas, OPEX/CAPEX y datos de dirección completos.
Facturas ficticias generadas en la propia prueba."""
import io
from datetime import date, timedelta

import pypdfium2 as pdfium
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app import lector_facturas as lf
from app.facturacion import datos_cliente
from app.models import Contact

HOY = date.today()
FECHA = HOY - timedelta(days=20)


def _factura(lineas: list[str]) -> bytes:
    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4)
    y = 800
    for ln in lineas:
        c.setFont("Helvetica", 11)
        c.drawString(60, y, ln)
        y -= 18
    c.save()
    return out.getvalue()


LINEAS = ["INSTALACIONES LECTOR PRUEBA S.L.", "C/ Industria 12, 28001 Madrid", "CIF: B12345674", "", "FACTURA",
          "Nº Factura: F26/9001", f"Fecha factura: {FECHA:%d/%m/%Y}", f"Vencimiento: {FECHA + timedelta(days=30):%d/%m/%Y}",
          "", "Cliente: INVERSIETE S.A.  CIF A78072915", "", "Revisión grupo de presión      2.707,01 €", "",
          "Base imponible      2.707,01 €", "IVA 21%      568,47 €", "Retención IRPF 15%      406,05 €",
          "TOTAL FACTURA      2.869,43 €", "", "Forma de pago: transferencia bancaria"]


def test_lector_pdf_y_foto():
    pdf = _factura(LINEAS)
    r = lf.leer(pdf, {"A78072915"})
    c = r["campos"]
    assert r["metodo"] == "pdf"
    assert (c["nif"], c["referencia"], c["fecha"], c["total"], c["tipo_iva"], c["retencion_tipo"], c["retencion_pct"],
            c["forma_pago"]) == ("B12345674", "F26/9001", FECHA.isoformat(), 2869.43, 21, "irpf_profesional", 15,
                                 "transferencia")
    assert c["vencimiento"] == (FECHA + timedelta(days=30)).isoformat()
    assert r["dudosos"] == ["emisor"]  # el nombre sacado del texto se revisa siempre
    # proveedor conocido por su NIF: nombre de la ficha y nada que revisar
    assert lf.leer(pdf, {"A78072915"}, {"B12345674": "Instalaciones Lector Prueba SL"})["dudosos"] == []
    # la misma factura en foto (OCR)
    img = pdfium.PdfDocument(pdf)[0].render(scale=2.2).to_pil().convert("RGB")
    foto = io.BytesIO()
    img.save(foto, "JPEG", quality=85)
    r = lf.leer(foto.getvalue(), {"A78072915"})
    assert r["metodo"] == "ocr" and r["campos"]["total"] == 2869.43 and r["campos"]["referencia"] == "F26/9001"


def test_lector_marca_lo_que_no_cuadra():
    # cuadro de totales en columnas
    t = ("SUMINISTROS TABLA SL\nCIF B12345674\nFactura nº: A-2026-00881\nFecha: 15 de septiembre de 2025\n"
         "Base imponible   % IVA   Cuota IVA   Total\n1.000,00   21,00   210,00   1.210,00\nRecibo domiciliado")
    r = lf.extraer(t)
    assert (r["campos"]["total"], r["campos"]["tipo_iva"], r["campos"]["forma_pago"], r["campos"]["fecha"]) == (
        1210.0, 21, "domiciliacion", "2025-09-15")
    assert "total" not in r["dudosos"]
    # no cuadra (100 + 21 ≠ 150) y sin forma de pago ni nº: todo eso, a revisar
    r = lf.extraer("LIMPIEZAS X SL\nCIF B12345674\nFecha factura 01/09/2025\nBase imponible 100,00\nIVA 21% 21,00\n"
                   "TOTAL 150,00 €")
    assert {"total", "base", "forma_pago", "referencia"} <= set(r["dudosos"])
    assert lf.importe("1.234,56") == lf.importe("1234.56") == lf.importe("1 234,56")


def test_leer_endpoint(client, admin):
    r = client.post("/api/documentos-recibidos/leer", headers=admin,
                    files=[("ficheros", ("f.pdf", _factura(LINEAS), "application/pdf"))])
    assert r.status_code == 200, r.text
    assert r.json()["campos"]["referencia"] == "F26/9001"
    assert client.post("/api/documentos-recibidos/leer", headers=admin,
                       files=[("ficheros", ("x.pdf", b"no es nada", "application/pdf"))]).status_code == 400


def test_duplicados_y_opex(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    base = {"asset_id": sfl, "fecha": FECHA.isoformat(), "categoria": "mantenimiento", "naturaleza": "CAPEX",
            "concepto": "Sustitución bomba", "proveedor": "Fontanería Duplicada, S.L.", "numero_factura": "FD-0042",
            "total": 605, "forma_pago": "transferencia"}
    g = client.post("/api/gastos", headers=admin, json=base)
    assert g.status_code == 201, g.text
    assert g.json()["naturaleza"] == "CAPEX"
    # mismo proveedor (escrito de otra forma) y mismo nº (con otros separadores): no se registra
    dup = client.post("/api/gastos", headers=admin, json={**base, "proveedor": "FONTANERIA DUPLICADA SL",
                                                          "numero_factura": "fd 0042", "total": 10})
    assert dup.status_code == 409 and dup.json()["detail"].startswith("Factura duplicada")
    assert client.post("/api/gastos", headers=admin, json={**base, "numero_factura": "FD-0042",
                                                           "confirmar_duplicado": True}).status_code == 409
    # mismo nº e importe con otro nombre de proveedor: posible duplicado, se registra solo si se confirma
    otro = {**base, "proveedor": "Otra Empresa Distinta SL"}
    assert client.post("/api/gastos", headers=admin, json=otro).json()["detail"].startswith("Posible duplicado")
    assert client.post("/api/gastos", headers=admin, json={**otro, "confirmar_duplicado": True}).status_code == 201
    # al editar otro apunte no se le puede poner el nº de una factura ya registrada del mismo proveedor
    g3 = client.post("/api/gastos", headers=admin, json={**base, "numero_factura": "FD-0043", "total": 70}).json()
    ed = client.put(f"/api/gastos/{g3['id']}", headers=admin, json={**base, "numero_factura": "FD-0042",
                                                                     "total": 70})
    assert ed.status_code == 409
    # el mismo fichero subido dos veces: posible duplicado
    pdf = _factura(["CARTA DE PRUEBA DUPLICADA", str(HOY)])
    sube = lambda **kw: client.post("/api/documentos-recibidos", headers=admin, data={  # noqa: E731
        "asset_id": str(sfl), "tipo": "carta", "fecha": HOY.isoformat(), **kw},
        files=[("ficheros", ("c.pdf", pdf, "application/pdf"))])
    assert sube().status_code == 201
    assert sube().json()["detail"].startswith("Posible duplicado")
    assert sube(confirmar_duplicado="true").status_code == 201
    # sin OPEX/CAPEX no se registra; totales por naturaleza
    sin = client.post("/api/gastos", headers=admin, json={**base, "naturaleza": None, "numero_factura": "FD-9"})
    assert sin.status_code == 400 and "CAPEX" in sin.json()["detail"]
    t = client.get("/api/gastos", headers=admin, params={"asset_id": sfl}).json()["totales"]
    assert t["capex"] >= 500


def test_direccion_completa(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    a = client.put(f"/api/activos/{sfl}", headers=admin, json={"pais": "España", "provincia": "Madrid",
                                                               "cp": "28042"}).json()
    assert (a["pais"], a["provincia"], a["cp"]) == ("España", "Madrid", "28042")
    cid = ids["assets"]["SFL"].get("company_id") or a["company_id"]
    soc = client.get("/api/sociedades", headers=admin).json()
    s = next(x for x in soc if x["id"] == cid)
    s2 = client.put(f"/api/sociedades/{cid}", headers=admin, json={**{k: s.get(k) for k in (
        "nombre", "cif", "direccion", "cp", "municipio", "provincia", "parent_id", "activa", "contratos")},
        "pais": "España"}).json()
    assert s2["pais"] == "España"
    c = client.post("/api/terceros", headers=admin, json={
        "company_id": cid, "asset_id": sfl, "tipo": "huesped", "nombre": "Cliente", "apellidos": "Con Provincia",
        "direccion": "C/ Mayor 1", "cp": "41001", "municipio": "Sevilla", "provincia": "Sevilla", "pais": "España"})
    assert c.status_code == 201, c.text
    assert c.json()["provincia"] == "Sevilla"
    dom = datos_cliente(Contact(nombre="X", direccion="C/ Mayor 1", cp="41001", municipio="Écija",
                                provincia="Sevilla", pais="España"))["domicilio"]
    assert dom == "C/ Mayor 1, 41001, Écija, Sevilla, España"
    p = client.post("/api/proveedores", headers=admin, json={
        "nombre": "Proveedor Con Dirección SL", "cp": "08001", "municipio": "Barcelona", "provincia": "Barcelona",
        "pais": "España"})
    assert p.status_code == 201 and p.json()["provincia"] == "Barcelona"
