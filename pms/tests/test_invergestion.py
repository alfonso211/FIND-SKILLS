"""Exportación a INVERGESTION: un solo ZIP (CSV en la raíz, manifest.json y PDF en pdf/emitidas y pdf/recibidas),
CSV UTF-8 sin BOM con LF y «;», una fila por tipo de IVA, cuadre, nº de factura = nombre del PDF, país ISO, conceptos
con «|», avisos de lo que INVERGESTION rechazaría y bloqueo si falta algún PDF."""
import hashlib
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
    crudo = ex.a_csv(["a", "b"], [{"a": 'texto; con "comillas"', "b": "dos\nlíneas"}])
    datos = crudo.decode("utf-8")
    assert not crudo.startswith(b"\xef\xbb\xbf") and "\r" not in datos  # sin BOM y con LF
    assert datos.startswith("a;b\n") and '"texto; con ""comillas"""' in datos and '"dos\nlíneas"' in datos
    assert ex.conceptos(["Alojamiento 4 noches", "Parking | plaza 3", " "]) == "Alojamiento 4 noches|Parking / plaza 3"
    assert ex.pais_iso(None, nif_="00000023T") == ("ES", True) and ex.pais_iso("Francia") == ("FR", False)
    assert ex.pais_iso(None, nif_="NL000000000B01") == ("NL", True)
    assert ex.nombre_fichero("EMITIDAS", "TODOS", date(2026, 10, 1), date(2026, 10, 7), "csv") == \
        "EMITIDAS_TODOS_20261001_20261007.csv"


def _csv(z: zipfile.ZipFile, nombre: str) -> list[dict]:
    crudo = z.read(nombre)
    assert not crudo.startswith(b"\xef\xbb\xbf") and b"\r\n" not in crudo
    return list(csv.DictReader(io.StringIO(crudo.decode("utf-8")), delimiter=";"))


def test_paquete_emitidas_y_recibidas(client, admin, ids):
    bab = ids["assets"]["BAB35"]["id"]
    # proveedor con NIF y gasto con factura escaneada y vencimiento
    client.post("/api/proveedores", headers=admin, json={"nombre": "Lavandería Prueba Export SL", "nif": "00000023T",
                                                         "tipo_persona": "autonomo"})
    r = client.post("/api/documentos-recibidos", headers=admin, data={
        "asset_id": str(bab), "tipo": "factura", "fecha": HOY.isoformat(), "vencimiento": (HOY + timedelta(days=30)).isoformat(),
        "emisor": "Lavandería Prueba Export SL", "referencia": "LAV-77",
        "gasto": '{"categoria": "limpieza", "concepto": "Lavandería", "total": 121, "tipo_iva": 21, "forma_pago": "domiciliacion", "naturaleza": "OPEX", '
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
             "forma_pago": "transferencia", "naturaleza": "CAPEX"}
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

    resp = client.get("/api/exportacion/invergestion", headers=admin, params=q)
    assert resp.status_code == 200, resp.text
    periodo = f"{(HOY - timedelta(days=1)):%Y%m%d}_{HOY:%Y%m%d}"
    assert resp.headers["content-disposition"].endswith(f'"INVERGESTION_TODOS_{periodo}.zip"')
    assert c["paquete"] == f"INVERGESTION_TODOS_{periodo}.zip"
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    nombres = set(z.namelist())
    em, re_ = f"EMITIDAS_TODOS_{periodo}.csv", f"RECIBIDAS_TODOS_{periodo}.csv"
    # un solo ZIP, sin ZIP dentro: CSV y manifest en la raíz, PDF en sus carpetas
    assert {em, re_, "manifest.json"} <= nombres and not any(n.endswith(".zip") for n in nombres)
    assert all(n in (em, re_, "manifest.json") or n.startswith(("pdf/emitidas/", "pdf/recibidas/")) for n in nombres)

    emitidas = _csv(z, em)
    assert list(emitidas[0]) == ex.COLUMNAS_EMITIDAS
    for f in emitidas:  # fecha de la factura: último día del mes; código de activo de la especificación
        assert f["activo"] in ("SFLORIDA", "SAEROPUERTO", "BABILONIA35") and f["tipo_factura"] in ("COMPLETA", "RECTIFICATIVA")
        if f["tipo_factura"] == "COMPLETA":
            assert date.fromisoformat(f["fecha_expedicion"]) == fin_de_mes(date.fromisoformat(f["fecha_expedicion"]))
        assert "," not in f["base"] and f["estado"] == "EMITIDA" and f["cliente_pais"] == "ES"
        # nº de factura único: el mismo que el nombre del PDF (SF-00001-2026), que está en el paquete
        assert f["numero"].startswith(f["serie"] + "-") and f["archivo_pdf"] == f"pdf/emitidas/{f['numero']}.pdf"
        assert f["archivo_pdf"] in nombres
    # cuadre por factura (todas sus filas de IVA): base + cuota = total
    por_factura = {}
    for f in emitidas:
        k = (f["nif_emisor"], f["serie"], f["numero"])
        por_factura.setdefault(k, [Decimal(0), Decimal(f["total"])])
        por_factura[k][0] += Decimal(f["base"]) + Decimal(f["cuota_iva"])
    assert all(abs(s - t) <= Decimal("0.02") for s, t in por_factura.values())
    numeros = {f["numero"] for f in emitidas}
    rect = [f for f in emitidas if f["tipo_factura"] == "RECTIFICATIVA"]
    assert all(f["numero_rectificada"] and Decimal(f["total"]) < 0 for f in rect)
    assert all("/" not in f["numero_rectificada"] and "-" in f["numero_rectificada"] for f in rect)
    assert numeros

    recibidas = _csv(z, re_)
    assert list(recibidas[0]) == ex.COLUMNAS_RECIBIDAS
    lav = next(f for f in recibidas if f["numero"] == "LAV-77")
    assert lav["forma_pago"] == "DOMICILIACION" and lav["proveedor_pais"] == "ES"
    assert next(f for f in recibidas if f["numero"] == "F26/5594")["forma_pago"] == "TRANSFERENCIA"
    assert (lav["proveedor_nif"], lav["categoria"], lav["inversion_sujeto_pasivo"], lav["base"], lav["cuota_iva"],
            lav["total"], lav["fecha_vencimiento"], lav["importe_pagado"], lav["estado"]) == (
        "00000023T", "LIMPIEZA", "N", "100.00", "21.00", "121.00", (HOY + timedelta(days=30)).isoformat(), "0.00",
        "REGISTRADA")
    ago = next(f for f in recibidas if f["numero"] == "F26/5594")
    assert (ago["fecha_factura"], ago["fecha_recepcion"], ago["archivo_pdf"]) == (
        agosto.isoformat(), HOY.isoformat(), "pdf/recibidas/00000023T-F26-5594.pdf")
    assert next(f for f in recibidas if f["numero"] == "ANT-1")["archivo_pdf"] == ""  # sin documento: vacío
    for f in recibidas:
        assert not f["archivo_pdf"] or f["archivo_pdf"] in nombres
    pdfs = [n for n in nombres if n.startswith("pdf/")]
    assert pdfs and all(z.read(n).startswith(b"%PDF") for n in pdfs)

    # manifest: activo, periodo, filas de cada CSV y ruta + SHA-256 de cada PDF
    m = json.loads(z.read("manifest.json"))
    assert (m["activo"], m["desde"], m["hasta"]) == ("TODOS", q["desde"], q["hasta"])
    assert {x["fichero"]: x["filas"] for x in m["csv"]} == {em: len(emitidas), re_: len(recibidas)}
    assert {x["ruta"] for x in m["pdf"]} == set(pdfs)
    assert all(x["sha256"] == hashlib.sha256(z.read(x["ruta"])).hexdigest() for x in m["pdf"])

    # si falta el PDF de una fila, la exportación no se genera (ni a medias) y se dice cuál
    from app import documentos
    with SessionLocal() as db:
        from app.models import ReceivedDocument
        d = db.scalar(__import__("sqlalchemy").select(ReceivedDocument).where(ReceivedDocument.referencia == "LAV-77"))
        documentos.borrar(d.fichero)
    c = client.get("/api/exportacion/invergestion/comprobar", headers=admin, params=q).json()
    assert any("00000023T-LAV-77.pdf" in x for x in c["recibidas"]["bloquea"])
    falla = client.get("/api/exportacion/invergestion", headers=admin, params=q)
    assert falla.status_code == 409 and "pdf/recibidas/00000023T-LAV-77.pdf" in falla.json()["detail"]
    assert client.get("/api/exportacion/invergestion", headers=admin, params={**q, "tipos": "emitidas"}).status_code == 200

    # un activo concreto y un periodo sin nada
    solo = client.get("/api/exportacion/invergestion/comprobar", headers=admin,
                      params={**q, "activo": "BABILONIA35", "tipos": "recibidas"}).json()
    assert set(solo) == {"recibidas", "paquete"} and solo["recibidas"]["csv"].startswith("RECIBIDAS_BABILONIA35_")
    assert solo["paquete"].startswith("INVERGESTION_BABILONIA35_")
    assert client.get("/api/exportacion/invergestion/comprobar", headers=admin,
                      params={"desde": "2026-12-01", "hasta": "2026-01-01"}).status_code == 400


def test_avisos_de_validacion():
    filas = [{"numero": "1", "serie": "X", "nif_emisor": "A28362309", "cliente_nif": "12345678A", "cliente_pais": "ES",
              "base": "100.00", "cuota_iva": "10.00", "total": "111.00", "retencion": "", "activo": "SFLORIDA"}]
    avisos = ex.validar(filas, ["activo", "concepto"], "numero", "cliente_nif", "cliente_pais")
    assert any("falta concepto" in a for a in avisos)
    assert any("NIF «12345678A» no válido" in a for a in avisos)
    assert any("no cuadra" in a for a in avisos)
