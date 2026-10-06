"""Exportación a INVERGESTION: formato (CSV «;», UTF-8, fechas ISO, importes con punto), una fila por tipo de IVA,
cuadre, PDF en un .zip con el mismo nombre que su CSV, y avisos de lo que INVERGESTION rechazaría."""
import csv
import io
import json
import zipfile
from datetime import date, timedelta
from decimal import Decimal

from PIL import Image

from app import export_invergestion as ex
from app.database import SessionLocal
from app.facturacion import fin_de_mes
from app.models import Expense

HOY = date.today()


def test_formato():
    assert ex.iso2("España") == "ES" and ex.iso2("Francia") == "FR" and ex.iso2("GBR") == "GB" and ex.iso2("") == ""
    assert ex.importe(1234.5) == "1234.50" and ex.porcentaje(10) == "10" and ex.porcentaje(0) == "0"
    datos = ex.a_csv(["a", "b"], [{"a": 'texto; con "comillas"', "b": None}]).decode("utf-8")
    assert datos.startswith("﻿a;b\r\n") and '"texto; con ""comillas"""' in datos and datos.endswith(";\r\n")
    assert ex.nombre_fichero("EMITIDAS", "TODOS", date(2026, 10, 1), date(2026, 10, 7), "csv") == \
        "EMITIDAS_TODOS_20261001_20261007.csv"


def _csv(z: zipfile.ZipFile, nombre: str) -> list[dict]:
    return list(csv.DictReader(io.StringIO(z.read(nombre).decode("utf-8-sig")), delimiter=";"))


def test_paquete_emitidas_y_recibidas(client, admin, ids):
    bab = ids["assets"]["BAB35"]["id"]
    # proveedor con NIF y gasto con factura escaneada y vencimiento
    client.post("/api/proveedores", headers=admin, json={"nombre": "Lavandería Prueba Export SL", "nif": "00000023T",
                                                         "tipo_persona": "autonomo"})
    r = client.post("/api/documentos-recibidos", headers=admin, data={
        "asset_id": str(bab), "tipo": "factura", "fecha": HOY.isoformat(), "vencimiento": (HOY + timedelta(days=30)).isoformat(),
        "emisor": "Lavandería Prueba Export SL", "referencia": "LAV-77",
        "gasto": '{"categoria": "limpieza", "concepto": "Lavandería", "total": 121, "tipo_iva": 21, "forma_pago": "domiciliacion", '
                 '"proveedor": "Lavandería Prueba Export SL", "numero_factura": "LAV-77", '
                 f'"fecha": "{HOY.isoformat()}", "vencimiento": "{(HOY + timedelta(days=30)).isoformat()}"}}'},
        files={"ficheros": ("f.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")})
    assert r.status_code == 201, r.text

    # factura de agosto registrada hoy con una foto: sale con su fecha (no la de registro) y como PDF
    agosto = date(HOY.year if HOY.month > 8 else HOY.year - 1, 8, 7)
    foto = io.BytesIO()
    Image.new("RGB", (60, 80), "white").save(foto, "JPEG")
    gasto = {"categoria": "mantenimiento", "concepto": "Reparación", "total": 3275.48, "tipo_iva": 21,
             "proveedor": "Lavandería Prueba Export SL", "numero_factura": "F26/5594", "fecha": agosto.isoformat(),
             "forma_pago": "transferencia"}
    r = client.post("/api/documentos-recibidos", headers=admin, data={
        "asset_id": str(bab), "tipo": "factura", "fecha": agosto.isoformat(), "emisor": "Lavandería Prueba Export SL",
        "referencia": "F26/5594", "gasto": json.dumps(gasto)},
        files={"ficheros": ("foto.jpg", foto.getvalue(), "image/jpeg")})
    assert r.status_code == 201, r.text
    futura = {**gasto, "fecha": (HOY + timedelta(days=1)).isoformat()}
    r = client.post("/api/documentos-recibidos", headers=admin, data={
        "asset_id": str(bab), "tipo": "factura", "fecha": futura["fecha"], "gasto": json.dumps(futura)},
        files={"ficheros": ("f.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")})
    assert r.status_code == 400 and "posterior a hoy" in r.json()["detail"]

    # gasto antiguo, registrado sin forma de pago: se avisa antes de enviar
    with SessionLocal() as db:
        db.add(Expense(asset_id=bab, fecha=HOY, categoria="limpieza", concepto="Antiguo", proveedor="Antiguo SL",
                       numero_factura="ANT-1", base=10, tipo_iva=0, cuota=0, total=10))
        db.commit()

    q = {"desde": (HOY - timedelta(days=1)).isoformat(), "hasta": HOY.isoformat()}
    c = client.get("/api/exportacion/invergestion/comprobar", headers=admin, params=q).json()
    assert any("ANT-1" in a and "sin forma de pago" in a for a in c["recibidas"]["avisos"])
    assert any("LAV-77" in a and "día en que se registró" in a for a in c["recibidas"]["avisos"])
    assert not any("F26/5594" in a and "día en que se registró" in a for a in c["recibidas"]["avisos"])
    assert c["emitidas"]["facturas"] >= 1 and c["recibidas"]["facturas"] >= 1
    assert c["emitidas"]["csv"].startswith("EMITIDAS_TODOS_")

    z = zipfile.ZipFile(io.BytesIO(client.get("/api/exportacion/invergestion", headers=admin, params=q).content))
    nombres = set(z.namelist())
    em = f"EMITIDAS_TODOS_{(HOY - timedelta(days=1)):%Y%m%d}_{HOY:%Y%m%d}"
    re_ = f"RECIBIDAS_TODOS_{(HOY - timedelta(days=1)):%Y%m%d}_{HOY:%Y%m%d}"
    assert {em + ".csv", em + ".zip", re_ + ".csv", re_ + ".zip"} <= nombres

    emitidas = _csv(z, em + ".csv")
    assert list(emitidas[0]) == ex.COLUMNAS_EMITIDAS
    pdfs = set(zipfile.ZipFile(io.BytesIO(z.read(em + ".zip"))).namelist())
    assert {f["archivo_pdf"] for f in emitidas} == pdfs
    for f in emitidas:  # fecha de la factura: último día del mes; código de activo de la especificación
        assert f["activo"] in ("SFLORIDA", "SAEROPUERTO", "BABILONIA35") and f["tipo_factura"] in ("COMPLETA", "RECTIFICATIVA")
        if f["tipo_factura"] == "COMPLETA":
            assert date.fromisoformat(f["fecha_expedicion"]) == fin_de_mes(date.fromisoformat(f["fecha_expedicion"]))
        assert "," not in f["base"] and f["estado"] == "EMITIDA"
    # cuadre por factura (todas sus filas de IVA): base + cuota = total
    por_factura = {}
    for f in emitidas:
        k = (f["nif_emisor"], f["serie"], f["numero"])
        por_factura.setdefault(k, [Decimal(0), Decimal(f["total"])])
        por_factura[k][0] += Decimal(f["base"]) + Decimal(f["cuota_iva"])
    assert all(abs(s - t) <= Decimal("0.02") for s, t in por_factura.values())
    rect = [f for f in emitidas if f["tipo_factura"] == "RECTIFICATIVA"]
    assert all(f["numero_rectificada"] and Decimal(f["total"]) < 0 for f in rect)

    recibidas = _csv(z, re_ + ".csv")
    assert list(recibidas[0]) == ex.COLUMNAS_RECIBIDAS
    lav = next(f for f in recibidas if f["numero"] == "LAV-77")
    assert lav["forma_pago"] == "DOMICILIACION"
    assert next(f for f in recibidas if f["numero"] == "F26/5594")["forma_pago"] == "TRANSFERENCIA"
    assert (lav["proveedor_nif"], lav["categoria"], lav["inversion_sujeto_pasivo"], lav["base"], lav["cuota_iva"],
            lav["total"], lav["fecha_vencimiento"], lav["importe_pagado"], lav["estado"]) == (
        "00000023T", "LIMPIEZA", "N", "100.00", "21.00", "121.00", (HOY + timedelta(days=30)).isoformat(), "0.00",
        "REGISTRADA")
    pdfs = zipfile.ZipFile(io.BytesIO(z.read(re_ + ".zip")))
    assert {f["archivo_pdf"] for f in recibidas if f["archivo_pdf"]} == set(pdfs.namelist())
    ago = next(f for f in recibidas if f["numero"] == "F26/5594")
    assert (ago["fecha_factura"], ago["fecha_recepcion"], ago["archivo_pdf"]) == (
        agosto.isoformat(), HOY.isoformat(), "00000023T-F26-5594.pdf")
    assert all(pdfs.read(n).startswith(b"%PDF") for n in pdfs.namelist())

    # un activo concreto y un periodo sin nada
    solo = client.get("/api/exportacion/invergestion/comprobar", headers=admin,
                      params={**q, "activo": "BABILONIA35", "tipos": "recibidas"}).json()
    assert set(solo) == {"recibidas"} and solo["recibidas"]["csv"].startswith("RECIBIDAS_BABILONIA35_")
    assert client.get("/api/exportacion/invergestion/comprobar", headers=admin,
                      params={"desde": "2026-12-01", "hasta": "2026-01-01"}).status_code == 400


def test_avisos_de_validacion():
    filas = [{"numero": "1", "serie": "X", "nif_emisor": "A28362309", "cliente_nif": "12345678A", "cliente_pais": "ES",
              "base": "100.00", "cuota_iva": "10.00", "total": "111.00", "retencion": "", "activo": "SFLORIDA"}]
    avisos = ex.validar(filas, ["activo", "concepto"], "numero", "cliente_nif", "cliente_pais")
    assert any("falta concepto" in a for a in avisos)
    assert any("NIF «12345678A» no válido" in a for a in avisos)
    assert any("no cuadra" in a for a in avisos)
