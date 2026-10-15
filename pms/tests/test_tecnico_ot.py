"""Órdenes de trabajo, fase 2: recepción asigna y envía la OT con un enlace firmado; el técnico, desde el móvil y sin
usuario, inicia el trabajo, anota trabajos y materiales, marca el estado al finalizar y firma; recepción recibe el aviso,
las OT en pausa se recuerdan cada día hasta que alguien actúa y al cerrar se da la conformidad de la propiedad."""
import base64
import io
import re
from datetime import date, timedelta

from PIL import Image

from app import avisos
from app.database import SessionLocal
from app.models import WorkOrder
from test_pms import _new_user


def _firma() -> str:
    out = io.BytesIO()
    Image.new("RGB", (300, 120), "white").save(out, "PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def _enlace(client, h, wid) -> str:
    """Envía la OT a quien la tiene asignada y devuelve el enlace del técnico (del WhatsApp)."""
    r = client.post(f"/api/mantenimiento/ordenes/{wid}/enviar-asignado", headers=h,
                    json={"canales": ["whatsapp"], "copia_mantenimiento": False})
    assert r.status_code == 200, r.text
    wa = r.json()["enviados"][0]["whatsapp"]
    from urllib.parse import unquote
    texto = unquote(wa.split("text=", 1)[1])
    assert re.search(r"Tiene una nueva orden de trabajo OT-\d{5} en ", texto) and "Acceda aquí para gestionarla" in texto
    return re.search(r"(/tecnico/\d+\?c=\d+&f=\w+)", texto).group(1)


def _api(enlace: str, ruta: str) -> str:
    wid, q = re.match(r"/tecnico/(\d+)\?(.*)", enlace).groups()
    return f"/api/publico/ot/{wid}{ruta}?{q}"


def _fin(**extra):
    return {"empresa": "Fontanería Pruebas SL", "tecnico": "Luis Técnico", "trabajos": "Cambio de latiguillo",
            "materiales": [{"material": "Latiguillo 30 cm", "cantidad": "2"}], "firma": _firma(), **extra}


def test_flujo_del_tecnico(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    rec = _new_user(client, admin, "rec.tecnico@inversiete.com", [{"role_id": ids["roles"]["Recepción"], "asset_id": sfl}])
    propio = client.post("/api/personal", headers=admin, json={
        "asset_id": sfl, "area": "mantenimiento", "nombre": "Pedro Propio", "telefono": "600111222"}).json()
    client.post("/api/proveedores", headers=admin, json={"nombre": "Fontanería Pruebas SL", "telefono": "600333444",
                                                         "email": "fontaneria.pruebas@inversiete.com"})
    unit = client.get(f"/api/unidades?asset_id={sfl}&q=P3-1A", headers=admin).json()[0]
    w = client.post("/api/mantenimiento/ordenes", headers=rec, json={
        "asset_id": sfl, "unit_id": unit["id"], "titulo": "Fuga en fregadero", "categoria": "fontaneria"}).json()

    # recepción asigna (personal propio) y envía: el enlace abre la pantalla del técnico
    r = client.post(f"/api/mantenimiento/ordenes/{w['id']}/asignar", headers=rec,
                    json={"asignacion": "propio", "personal_id": propio["id"]})
    assert r.status_code == 200 and r.json()["asignado_a"] == "Pedro Propio"
    enlace = _enlace(client, rec, w["id"])
    assert client.get(enlace).status_code == 200
    assert client.get(_api(enlace, "/datos").replace("f=", "f=x")).status_code == 404  # firma manipulada
    d = client.get(_api(enlace, "/datos")).json()
    assert d["propuesta"]["tecnico"] == "Pedro Propio" and d["permite_escalar"] and not d["finalizada"]

    # inicia el trabajo (llegada) y pide derivar a una subcontrata (supera su capacidad)
    assert client.post(_api(enlace, "/iniciar"), json={}).json()["llegada"]
    assert client.post(_api(enlace, "/finalizar"), json=_fin(resultado="escalar", firma="x" * 60)).status_code == 400
    avisos.BANDEJA.clear()
    r = client.post(_api(enlace, "/finalizar"), json=_fin(resultado="escalar", tecnico="Pedro Propio",
                                                          trabajos="Requiere soldadura de cobre certificada"))
    assert r.status_code == 200, r.text
    m = [x for x in avisos.BANDEJA if x["para"] == "rec.tecnico@inversiete.com"]
    assert m and "DERIVAR A SUBCONTRATA" in m[0]["asunto"]
    assert f"El personal propio solicita derivar la orden OT-{w['id']:05d} a una subcontrata" in m[0]["texto"]
    ot = client.get(f"/api/mantenimiento/ordenes?asset_id={sfl}&abiertas=true", headers=rec).json()
    ot = next(x for x in ot if x["id"] == w["id"])
    assert ot["estado"] == "escalada" and ot["alerta_tecnico"] == "escalar"
    assert any(x["id"] == w["id"] for x in client.get("/api/panel", headers=rec).json()["ot_tecnico"])

    # recepción la deriva a la subcontrata (deja de avisarse) y la reenvía
    r = client.post(f"/api/mantenimiento/ordenes/{w['id']}/asignar", headers=rec,
                    json={"asignacion": "subcontrata", "proveedor": "Fontanería Pruebas SL"}).json()
    assert r["estado"] == "asignada" and r["alerta_tecnico"] is None
    enlace = _enlace(client, rec, w["id"])
    d = client.get(_api(enlace, "/datos")).json()
    assert d["propuesta"]["empresa"] == "Fontanería Pruebas SL" and not d["permite_escalar"]
    assert client.post(_api(enlace, "/finalizar"), json=_fin(resultado="escalar")).status_code == 400

    # validaciones: otra visita sin fecha, «otro» sin justificación
    assert client.post(_api(enlace, "/finalizar"), json=_fin(resultado="otra_visita")).status_code == 400
    assert client.post(_api(enlace, "/finalizar"), json=_fin(resultado="otro")).status_code == 400
    # pendiente de material: en pausa, recordatorio diario hasta que alguien actúe
    r = client.post(_api(enlace, "/finalizar"), json=_fin(resultado="pendiente_material"))
    assert r.json()["estado"] == "pendiente_material"
    avisos.BANDEJA.clear()
    with SessionLocal() as db:
        assert avisos.recordatorio_ot_pausadas(db, date.today()) >= 1
        assert avisos.recordatorio_ot_pausadas(db, date.today()) == 0  # uno al día
    assert any("en pausa" in x["asunto"] for x in avisos.BANDEJA if x["para"] == "rec.tecnico@inversiete.com")
    # requiere otra visita: fecha propuesta como fecha prevista
    manana = (date.today() + timedelta(days=1)).isoformat()
    r = client.post(_api(enlace, "/finalizar"), json=_fin(resultado="otra_visita", fecha_propuesta=manana))
    assert r.json()["estado"] == "pendiente_visita"
    # recepción reprograma: deja de recordarse
    client.post(f"/api/mantenimiento/ordenes/{w['id']}/asignar", headers=rec,
                json={"asignacion": "subcontrata", "proveedor": "Fontanería Pruebas SL", "fecha_prevista": manana})
    with SessionLocal() as db:
        assert avisos.recordatorio_ot_pausadas(db, date.today() + timedelta(days=1)) == 0

    # resuelta (subcontrata): hace falta al menos una foto de la reparación y el tiempo (hora de llegada); queda
    # finalizada para que la cierre recepción o el Director Técnico; el enlace queda en solo lectura
    # correctiva: primero la foto del «antes» (el técnico la hace al llegar desde su enlace)
    fotos = {"ficheros": ("trabajo.png", io.BytesIO(base64.b64decode(_firma().split(",")[1])).getvalue(), "image/png")}
    sin_antes = client.post(_api(enlace, "/finalizar"), json=_fin(resultado="resuelta"))
    assert sin_antes.status_code == 400 and "antes" in sin_antes.json()["detail"]
    d = client.get(_api(enlace, "/datos")).json()
    assert d["exige_foto_antes"] and d["fotos_antes"] == 0
    assert client.post(_api(enlace, "/fotos") + "&tipo=otro", files=fotos).status_code == 400
    assert client.post(_api(enlace, "/fotos") + "&tipo=averia", files=fotos).status_code == 201
    d = client.get(_api(enlace, "/datos")).json()
    assert d["fotos_antes"] == 1 and d["fotos_trabajo"] == 0
    sin_foto = client.post(_api(enlace, "/finalizar"), json=_fin(resultado="resuelta"))
    assert sin_foto.status_code == 400 and "reparación" in sin_foto.json()["detail"]
    assert client.post(_api(enlace, "/fotos"), files=fotos).status_code == 201
    sin_llegada = client.post(_api(enlace, "/finalizar"), json=_fin(resultado="resuelta"))
    assert sin_llegada.status_code == 400 and "llegada" in sin_llegada.json()["detail"]
    from datetime import datetime
    llegada = (datetime.now() - timedelta(minutes=90)).replace(microsecond=0).isoformat()
    r = client.post(_api(enlace, "/finalizar"), json=_fin(resultado="resuelta", observaciones="Revisar en 6 meses",
                                                         llegada=llegada))
    assert r.status_code == 200, r.text
    assert r.json()["estado"] == "pendiente_cierre"
    assert client.get(_api(enlace, "/datos")).json()["finalizada"]
    # más de 48 h sin cerrar: aviso diario a recepción y al Director Técnico (una vez al día)
    with SessionLocal() as db:
        avisos.BANDEJA.clear()
        assert avisos.recordatorio_ot_sin_cerrar(db, date.today()) == 0  # aún no han pasado 48 h
        o = db.get(WorkOrder, w["id"])
        o.conf_mto_fecha = o.conf_mto_fecha - timedelta(hours=49)
        db.commit()
        assert avisos.recordatorio_ot_sin_cerrar(db, date.today()) >= 1
        assert avisos.recordatorio_ot_sin_cerrar(db, date.today()) == 0
    assert any("sin cerrar" in x["asunto"] for x in avisos.BANDEJA if x["para"] == "rec.tecnico@inversiete.com")
    o = next(x for x in client.get(f"/api/mantenimiento/ordenes?asset_id={sfl}&abiertas=true", headers=rec).json()
             if x["id"] == w["id"])
    assert o["sin_cerrar_48h"]
    assert client.post(_api(enlace, "/finalizar"), json=_fin(resultado="resuelta")).status_code == 400
    vis = client.get(f"/api/mantenimiento/ordenes/{w['id']}/intervenciones", headers=rec).json()
    assert [v["resultado"] for v in vis] == ["escalar", "pendiente_material", "otra_visita", "resuelta"]
    assert vis[0]["minutos"] is not None and vis[-1]["materiales"][0]["material"] == "Latiguillo 30 cm"
    firma = client.get(f"/api/mantenimiento/intervenciones/{vis[-1]['id']}/firma", headers=rec)
    assert firma.status_code == 200 and firma.content.startswith(b"\x89PNG")
    nuevos = client.get("/api/mantenimiento/resultados", headers=rec,
                        params={"desde": (date.today() - timedelta(days=1)).isoformat()}).json()
    assert nuevos[-1]["resultado"] == "resuelta"

    # recepción la cierra (conformidad de la propiedad): el parte lleva firma y conformidad
    c = client.post(f"/api/mantenimiento/ordenes/{w['id']}/cerrar", headers=rec, json={}).json()
    assert c["estado"] == "cerrada" and c["conformidad_en"] and c["conf_mto_por_nombre"].endswith("(enlace)")
    assert c["minutos"] >= 90
    pdf = client.get(f"/api/mantenimiento/ordenes/{w['id']}/parte", headers=rec)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_personal_propio_cierra_desde_su_enlace(client, admin, ids):
    """1.70: el personal propio que termina desde su enlace (foto, llegada y salida, firma) deja la OT cerrada; la
    unidad queda pendiente de limpieza y recepción puede reabrirla en 7 días."""
    from datetime import datetime
    sfl = ids["assets"]["SFL"]["id"]
    rec = _new_user(client, admin, "rec.propio170@inversiete.com",
                    [{"role_id": ids["roles"]["Recepción"], "asset_id": sfl}])
    propio = client.post("/api/personal", headers=admin, json={
        "asset_id": sfl, "area": "mantenimiento", "nombre": "Juan Propio", "telefono": "600111333"}).json()
    unit = client.get(f"/api/unidades?asset_id={sfl}&q=P3-1B", headers=admin).json()[0]
    w = client.post("/api/mantenimiento/ordenes", headers=rec, json={
        "asset_id": sfl, "unit_id": unit["id"], "titulo": "Enchufe sin corriente", "bloquea_unidad": True}).json()
    client.post(f"/api/mantenimiento/ordenes/{w['id']}/asignar", headers=rec,
                json={"asignacion": "propio", "personal_id": propio["id"]})
    enlace = _enlace(client, rec, w["id"])
    fotos = {"ficheros": ("enchufe.png", base64.b64decode(_firma().split(",")[1]), "image/png")}
    assert client.post(_api(enlace, "/fotos") + "&tipo=averia", files=fotos).status_code == 201
    assert client.post(_api(enlace, "/fotos"), files=fotos).status_code == 201
    llegada = (datetime.now() - timedelta(minutes=30)).replace(microsecond=0).isoformat()
    r = client.post(_api(enlace, "/finalizar"), json=_fin(resultado="resuelta", empresa="Personal propio",
                                                         tecnico="Juan Propio", llegada=llegada))
    assert r.status_code == 200 and r.json()["estado"] == "cerrada", r.text
    o = next(x for x in client.get(f"/api/mantenimiento/ordenes?asset_id={sfl}&abiertas=false", headers=rec).json()
             if x["id"] == w["id"])
    assert o["minutos"] >= 30 and o["fotos_trabajo"] == 1 and o["reabrible"]
    assert client.get(f"/api/unidades?asset_id={sfl}&q=P3-1B", headers=admin).json()[0]["estado"] == "pendiente_limpieza"
