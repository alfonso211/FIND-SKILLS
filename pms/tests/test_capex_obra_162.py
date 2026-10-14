"""CAPEX fase 2, primera entrega: documentación PRL de cada contrata con semáforo, condiciones y contrato, enlace de
obra para el contratista y acta de replanteo (solo con todo en regla)."""
import io
import re
from datetime import date, timedelta

import docx

from app import avisos, capex_obra
from app.models import CapexPrl

PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
HOY = date.today()


def _pdf(nombre="doc.pdf"):
    return {"fichero": (nombre, io.BytesIO(PDF), "application/pdf")}


def _adjudicado(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    r = client.post("/api/proveedores", headers=admin, json={"nombre": "Obras Replanteo SL", "nif": "B11223344",
                                                               "email": "replanteo@inversiete.com", "telefono": "600222444"})
    s = r.json()["id"]
    p = client.post("/api/capex", headers=admin, json={"asset_id": sae, "titulo": "Reforma de baños planta 2"}).json()
    client.post(f"/api/capex/{p['id']}/partidas", headers=admin, json={
        "capitulo": "01", "capitulo_nombre": "FONTANERÍA", "descripcion": "Sustitución de plato de ducha",
        "unidad": "ud", "cantidad": 4, "precio": 900})
    avisos.BANDEJA.clear()
    client.post(f"/api/capex/{p['id']}/licitacion", headers=admin, json={"proveedor_ids": [s], "fecha_limite": "2099-01-31"})
    iid, k = re.search(r"/oferta/(\d+)\?k=([\w-]+)", avisos.BANDEJA[0]["texto"]).groups()
    ruta = f"/api/publico/oferta/{iid}"
    pid = client.get(ruta, params={"k": k}).json()["partidas"][0]["id"]
    client.post(ruta, params={"k": k}, json={"precios": {str(pid): 850}, "plazo_dias": 45, "enviar": True})
    cmp = client.get(f"/api/capex/{p['id']}/comparativo", headers=admin).json()
    r = client.post(f"/api/capex/{p['id']}/adjudicar", headers=admin, json={"lotes": [{"bid_id": cmp["ofertas"][0]["bid_id"]}]})
    assert r.json()["proyecto"]["estado"] == "adjudicado", r.text
    return p["id"]


def test_semaforo_prl():
    x = CapexPrl(tipo="rc", estado="falta")
    assert capex_obra.semaforo(x, HOY)[0] == "rojo" and not capex_obra.en_regla(x, HOY)
    x.estado = "por_revisar"
    assert capex_obra.semaforo(x, HOY)[0] == "amarillo" and not capex_obra.en_regla(x, HOY)
    x.estado, x.vence = "valido", HOY + timedelta(days=200)
    assert capex_obra.semaforo(x, HOY)[0] == "verde" and capex_obra.en_regla(x, HOY)
    x.vence = HOY + timedelta(days=10)  # caduca pronto: amarillo, pero sirve
    assert capex_obra.semaforo(x, HOY)[0] == "amarillo" and capex_obra.en_regla(x, HOY)
    x.vence = HOY - timedelta(days=1)
    assert capex_obra.semaforo(x, HOY) == ("rojo", f"Vencido el {x.vence:%d/%m/%Y}") and not capex_obra.en_regla(x, HOY)
    x.estado = "no_aplica"
    assert capex_obra.semaforo(x, HOY)[0] == "gris" and capex_obra.en_regla(x, HOY)
    x.estado = "rechazado"
    assert capex_obra.semaforo(x, HOY)[0] == "rojo"


def test_obra_prl_contrato_y_replanteo(client, admin, ids):
    pid = _adjudicado(client, admin, ids)
    O = client.get(f"/api/capex/{pid}/obra", headers=admin).json()
    a = O["adjudicaciones"][0]
    assert a["retencion_pct"] == 5 and a["garantia_meses"] == 12 and a["plazo_dias"] == 45  # plazo ofertado
    assert len(a["prl"]) == 8 and a["prl_resumen"]["rojo"] == 8 and not O["puede_replanteo"]
    assert any("contrato firmado" in f for f in O["faltan"]) and any("PRL" in f for f in O["faltan"])
    assert client.post(f"/api/capex/{pid}/replanteo", headers=admin, data={"fecha": HOY.isoformat()}).status_code == 400
    assert any(p["id"] == pid for p in client.get("/api/capex", headers=admin, params={"estado": "abiertos"}).json())

    # condiciones y borrador del contrato
    aid = a["id"]
    assert client.put(f"/api/capex/obra/adjudicaciones/{aid}", headers=admin,
                      json={"retencion_pct": 3, "garantia_meses": 24}).status_code == 200
    r = client.get(f"/api/capex/obra/adjudicaciones/{aid}/contrato.docx", headers=admin)
    texto = "\n".join(q.text for q in docx.Document(io.BytesIO(r.content)).paragraphs)
    assert "BORRADOR" in texto and "Obras Replanteo SL" in texto and "B11223344" in texto
    assert "el 3 % de su importe" in texto and "a los 24 meses" in texto and "45 días naturales" in texto
    assert "4.046,00 €" in texto  # 4 × 850 = 3.400 de PEM + 13 % GG + 6 % BI
    # enlace de obra para el contratista
    avisos.BANDEJA.clear()
    r = client.post(f"/api/capex/obra/adjudicaciones/{aid}/enlace", headers=admin).json()
    assert r["ok"] and avisos.BANDEJA[0]["para"] == "replanteo@inversiete.com"
    _, k = re.search(r"/obra/(\d+)\?k=([\w-]+)", avisos.BANDEJA[0]["texto"]).groups()
    pub = f"/api/publico/obra/{aid}"
    assert client.get(pub, params={"k": "mala"}).status_code == 404
    P = client.get(pub, params={"k": k}).json()
    assert P["proveedor"] == "Obras Replanteo SL" and P["retencion_pct"] == 3 and len(P["prl"]) == 8
    assert "documento" not in P["prl"][0]  # el contratista no descarga lo subido
    assert client.get(f"{pub}/contrato.docx", params={"k": k}).status_code == 200

    # el contratista sube: hace falta fecha de caducidad en vigor
    assert client.post(f"{pub}/prl", params={"k": k}, data={"tipo": "rc"}, files=_pdf()).status_code == 400
    assert client.post(f"{pub}/prl", params={"k": k}, data={"tipo": "rc", "vence": (HOY - timedelta(days=1)).isoformat()},
                       files=_pdf()).status_code == 400
    avisos.BANDEJA.clear()
    r = client.post(f"{pub}/prl", params={"k": k}, data={"tipo": "rc", "vence": (HOY + timedelta(days=300)).isoformat()},
                    files=_pdf("rc.pdf"))
    assert r.status_code == 200 and r.json()["color"] == "amarillo" and r.json()["estado"] == "por_revisar"
    assert any("Documentación PRL recibida" in m["asunto"] for m in avisos.BANDEJA)  # aviso a la Dirección Técnica
    client.post(f"{pub}/prl", params={"k": k}, data={"tipo": "hacienda", "vence": (HOY + timedelta(days=90)).isoformat()},
                files=_pdf())
    O = client.get(f"/api/capex/{pid}/obra", headers=admin).json()
    prl = {x["tipo"]: x for x in O["adjudicaciones"][0]["prl"]}
    assert prl["rc"]["subido_por"] == "contratista" and prl["rc"]["documento"]

    # la Dirección Técnica revisa
    assert client.post(f"/api/capex/obra/prl/{prl['rc']['id']}/revisar", headers=admin,
                       json={"decision": "validar"}).json()["color"] == "verde"
    assert client.post(f"/api/capex/obra/prl/{prl['hacienda']['id']}/revisar", headers=admin,
                       json={"decision": "rechazar"}).status_code == 400  # sin motivo
    r = client.post(f"/api/capex/obra/prl/{prl['hacienda']['id']}/revisar", headers=admin,
                    json={"decision": "rechazar", "nota": "Certificado sin firma electrónica"}).json()
    assert r["color"] == "rojo" and "sin firma" in r["texto"]
    # lo validado ya no lo cambia el contratista; lo rechazado sí
    assert client.post(f"{pub}/prl", params={"k": k}, data={"tipo": "rc", "vence": (HOY + timedelta(days=99)).isoformat()},
                       files=_pdf()).status_code == 400
    assert client.post(f"{pub}/prl", params={"k": k}, data={"tipo": "hacienda", "vence": (HOY + timedelta(days=90)).isoformat()},
                       files=_pdf()).status_code == 200
    client.post(f"/api/capex/obra/prl/{prl['hacienda']['id']}/revisar", headers=admin, json={"decision": "validar"})

    # el resto lo sube la Dirección Técnica (queda validado); uno caduca pronto (amarillo, pero vale)
    base = f"/api/capex/obra/adjudicaciones/{aid}/prl"
    for tipo, dias in (("seg_social", 10), ("rnt", 120), ("rea", 700), ("formacion", None), ("recurso_preventivo", None)):
        data = {"tipo": tipo, **({"vence": (HOY + timedelta(days=dias)).isoformat()} if dias else {})}
        assert client.post(base, headers=admin, data=data, files=_pdf()).json()["estado"] == "valido"
    assert client.post(f"/api/capex/obra/prl/{prl['plan_ss']['id']}/revisar", headers=admin,
                       json={"decision": "no_aplica"}).status_code == 400  # sin motivo
    assert client.post(f"/api/capex/obra/prl/{prl['plan_ss']['id']}/revisar", headers=admin,
                       json={"decision": "no_aplica", "nota": "Obra sin proyecto: basta la evaluación de riesgos"}).json()["color"] == "gris"
    O = client.get(f"/api/capex/{pid}/obra", headers=admin).json()
    a = O["adjudicaciones"][0]
    assert a["prl_en_regla"] and a["prl_resumen"]["amarillo"] == 1 and not O["puede_replanteo"]
    assert O["faltan"] == ["Obras Replanteo SL: falta subir el contrato firmado"]

    # contrato firmado y acta de replanteo
    contrato = f"/api/capex/obra/adjudicaciones/{aid}/contrato"
    assert client.post(contrato, headers=admin, data={"fecha": (HOY + timedelta(days=1)).isoformat()},
                       files=_pdf()).status_code == 400
    assert client.post(contrato, headers=admin, data={"fecha": HOY.isoformat()}, files=_pdf("contrato.pdf")).status_code == 200
    O = client.get(f"/api/capex/{pid}/obra", headers=admin).json()
    assert O["puede_replanteo"] and O["faltan"] == [] and O["adjudicaciones"][0]["contrato"]["nombre"] == "contrato.pdf"
    assert client.post(f"/api/capex/{pid}/replanteo", headers=admin,
                       data={"fecha": (HOY + timedelta(days=2)).isoformat()}).status_code == 400
    r = client.post(f"/api/capex/{pid}/replanteo", headers=admin, data={"fecha": HOY.isoformat(), "nota": "Sin incidencias"},
                    files={"fichero": ("acta.pdf", io.BytesIO(PDF), "application/pdf")})
    assert r.status_code == 200 and r.json()["estado"] == "en_ejecucion" and r.json()["fecha_inicio"] == HOY.isoformat()
    O = client.get(f"/api/capex/{pid}/obra", headers=admin).json()
    assert O["replanteo"]["fecha"] == HOY.isoformat() and O["replanteo"]["documento"]["etiqueta"] == "acta"
    # en ejecución: la retención ya no cambia, el plazo sí; no se cancela; el enlace sigue activo
    assert client.put(f"/api/capex/obra/adjudicaciones/{aid}", headers=admin, json={"retencion_pct": 5}).status_code == 400
    assert client.put(f"/api/capex/obra/adjudicaciones/{aid}", headers=admin, json={"plazo_dias": 60}).status_code == 200
    assert client.post(f"/api/capex/{pid}/estado", headers=admin, json={"estado": "cancelado", "motivo": "x"}).status_code == 400
    assert client.get(pub, params={"k": k}).json()["proyecto"]["replanteo"] == HOY.isoformat()
    # un enlace nuevo invalida el anterior
    client.post(f"/api/capex/obra/adjudicaciones/{aid}/enlace", headers=admin, params={"nuevo": "true"})
    assert client.get(pub, params={"k": k}).status_code == 404
    # los documentos de obra no van a licitación
    docs = client.get(f"/api/capex/{pid}", headers=admin).json()["documentos"]
    assert {d["etiqueta"] for d in docs} >= {"prl", "contrato", "acta"} and not any(
        d["licitacion"] for d in docs if d["etiqueta"] in ("prl", "contrato", "acta"))


def test_obra_solo_adjudicados(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    p = client.post("/api/capex", headers=admin, json={"asset_id": sae, "titulo": "Proyecto sin adjudicar"}).json()
    O = client.get(f"/api/capex/{p['id']}/obra", headers=admin).json()
    assert O["adjudicaciones"] == [] and not O["puede_replanteo"]
    assert client.post(f"/api/capex/{p['id']}/replanteo", headers=admin, data={"fecha": HOY.isoformat()}).status_code == 400
