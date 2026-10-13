"""Partes de estado: mantenimiento y limpieza no abren órdenes de trabajo; registran un parte con listas encadenadas y
foto obligatoria. El motor de reglas propone departamento y prioridad, el parte crítico deja la unidad fuera de
servicio, recepción genera la OT (o lo descarta) y, al cerrarse la OT, el parte queda resuelto (tiempo de reparación)."""
import io

from PIL import Image

from app import avisos
from app import partes_estado as pe
from test_pms import _new_user


def _foto() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 48), (120, 90, 60)).save(out, "PNG")
    return out.getvalue()


def _parte(client, h, aid, uid=None, foto=True, **campos):
    datos = {"asset_id": aid, **({"unit_id": uid} if uid else {}), **campos}
    files = [("fotos", ("averia.png", _foto(), "image/png"))] if foto else [("fotos", ("", b"", "image/png"))]
    return client.post("/api/partes-estado", headers=h, data=datos, files=files)


def test_motor_de_reglas():
    r = pe.reglas("lavavajillas", "atasco", "leve")
    assert (r["departamento"], r["prioridad"], r["categoria"]) == ("mantenimiento", "baja", "electrodomesticos")
    assert pe.reglas("lavavajillas", "averia_electronica", "media")["prioridad"] == "alta"
    r = pe.reglas("lavavajillas", "fuga", "leve")
    assert r["prioridad"] == "urgente" and any("daño" in a for a in r["alertas"])
    r = pe.reglas("lavavajillas", "malos_olores", "leve")
    assert (r["departamento"], r["categoria"], r["tipo_aviso"]) == ("limpieza", "limpieza", "Alerta operativa")
    assert pe.reglas("termos", "rotura", "critica")["prioridad"] == "urgente"
    assert pe.tipologia_unidad(0, None) == "T0" and pe.tipologia_unidad(None, "Apartamento 2 dormitorios") == "T2"
    assert pe.tipologia_unidad(None, "Vivienda") is None
    # cada estancia ofrece solo sus elementos
    bano = {e["clave"] for f in pe.elementos_de("humeda") for e in f["elementos"]}
    assert "sanitarios" in bano and "cama" not in bano and "nevera" not in bano


def test_flujo_parte_de_estado(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    tec = _new_user(client, admin, "tec.estado@inversiete.com",
                    [{"role_id": ids["roles"]["Técnico Mantenimiento"], "asset_id": sfl}])
    lim = _new_user(client, admin, "lim.estado@inversiete.com",
                    [{"role_id": ids["roles"]["Gobernanta / Limpieza"], "asset_id": sfl}])
    rec = _new_user(client, admin, "rec.estado@inversiete.com", [{"role_id": ids["roles"]["Recepción"], "asset_id": sfl}])

    # mantenimiento y limpieza ya no abren órdenes de trabajo
    ot = {"asset_id": sfl, "titulo": "Prueba", "categoria": "general"}
    assert client.post("/api/mantenimiento/ordenes", headers=tec, json=ot).status_code == 403
    assert client.post("/api/mantenimiento/ordenes", headers=lim, json=ot).status_code == 403

    ubic = client.get("/api/partes-estado/ubicaciones", headers=lim, params={"asset_id": sfl}).json()
    libres = [u for u in ubic["unidades"] if u["estado"] == "disponible" and u["tipologia"] == "T1"]
    u1, u2 = libres[0], libres[1]
    cat = client.get("/api/partes-estado/catalogo", headers=lim).json()
    assert [e["clave"] for e in cat["estancias"]["T1"]] == ["hall", "salon", "cocina", "dormitorio", "bano"]

    # validaciones: foto obligatoria, estancia de la tipología, elemento de la estancia
    base = {"estancia": "cocina", "elemento": "lavavajillas", "deficiencia": "fuga", "gravedad": "media"}
    assert _parte(client, tec, sfl, u1["id"], foto=False, **base).status_code in (400, 422)
    assert _parte(client, tec, sfl, u1["id"], **{**base, "estancia": "aseo"}).status_code == 400
    assert _parte(client, tec, sfl, u1["id"], **{**base, "estancia": "bano", "elemento": "cama"}).status_code == 400

    avisos.BANDEJA.clear()
    r = _parte(client, tec, sfl, u1["id"], lat=40.4, lon=-3.7, precision=12, **base)
    assert r.status_code == 201, r.text
    p = r.json()
    assert (p["departamento"], p["prioridad"], p["estado"], p["bloquea_unidad"]) == ("mantenimiento", "urgente",
                                                                                      "pendiente", False)
    assert p["lat"] == 40.4 and len(p["fotos"]) == 1 and p["codigo"].startswith("PE-")
    assert "rec.estado@inversiete.com" in {m["para"] for m in avisos.BANDEJA}  # aviso a recepción
    # limpieza: deficiencia operativa en zona común
    z = _parte(client, lim, sfl, estancia="recepcion", elemento="suelos", deficiencia="limpieza_profunda",
               gravedad="leve").json()
    assert (z["tipologia"], z["departamento"], z["ubicacion"]) == ("ZC", "limpieza", "Zonas comunes")
    # cada uno ve los suyos; recepción los de su activo y en el panel hasta resolverlos
    assert {x["id"] for x in client.get("/api/partes-estado", headers=lim).json()} == {z["id"]}
    pend = {x["id"] for x in client.get("/api/panel", headers=rec).json()["partes_estado"]}
    assert {p["id"], z["id"]} <= pend
    assert client.post(f"/api/partes-estado/{z['id']}/descartar", headers=lim, json={"motivo": "No procede"}).status_code == 403
    assert client.post(f"/api/partes-estado/{z['id']}/descartar", headers=rec,
                       json={"motivo": "Ya limpiado en la ronda de la tarde"}).json()["estado"] == "descartado"

    # crítico: la unidad queda fuera de servicio; al descartarlo vuelve a estar disponible
    c = _parte(client, lim, sfl, u2["id"], estancia="bano", elemento="sanitarios", deficiencia="rotura",
               gravedad="critica").json()
    assert c["bloquea_unidad"] and _estado(client, rec, sfl, u2["id"]) == "mantenimiento"
    client.post(f"/api/partes-estado/{c['id']}/descartar", headers=rec, json={"motivo": "Error de unidad"})
    assert _estado(client, rec, sfl, u2["id"]) == "disponible"

    # crítico -> recepción genera la OT desde el parte (fotos copiadas, sigue bloqueada) -> cierre: resuelto
    c = _parte(client, lim, sfl, u2["id"], estancia="bano", elemento="sanitarios", deficiencia="rotura",
               gravedad="critica").json()
    w = client.post("/api/mantenimiento/ordenes", headers=rec, json={
        "asset_id": sfl, "unit_id": u2["id"], "titulo": "Inodoro roto", "categoria": "fontaneria",
        "prioridad": "urgente", "parte_estado_id": c["id"]})
    assert w.status_code == 201, w.text
    w = w.json()
    assert w["bloquea_unidad"] and w["n_adjuntos"] == 1
    assert client.post("/api/mantenimiento/ordenes", headers=rec, json={
        "asset_id": sfl, "unit_id": u2["id"], "titulo": "Otra", "parte_estado_id": c["id"]}).status_code == 400
    lista = {x["id"]: x for x in client.get("/api/partes-estado", headers=rec).json()}
    assert lista[c["id"]]["estado"] == "ot_generada" and lista[c["id"]]["ot"]["id"] == w["id"]
    client.post(f"/api/mantenimiento/ordenes/{w['id']}/confirmar-mantenimiento", headers=tec, json={"solucion": "Cambiado"})
    client.post(f"/api/mantenimiento/ordenes/{w['id']}/confirmar-limpieza", headers=lim)
    assert client.post(f"/api/mantenimiento/ordenes/{w['id']}/cerrar", headers=rec, json={}).json()["estado"] == "cerrada"
    assert _estado(client, rec, sfl, u2["id"]) == "disponible"
    lista = {x["id"]: x for x in client.get("/api/partes-estado", headers=rec).json()}
    assert lista[c["id"]]["estado"] == "resuelto"
    assert c["id"] not in {x["id"] for x in client.get("/api/panel", headers=rec).json()["partes_estado"]}

    # panel técnico: Pareto, tiempo de reparación e intervenciones por unidad
    k = client.get("/api/partes-estado/kpis", headers=admin, params={"asset_id": sfl}).json()
    assert k["pareto"][0]["partes"] >= 1 and k["pareto"][-1]["acumulado"] == 100.0
    assert k["mttr"]["global"]["resueltos"] >= 1 and k["mttr"]["critica"]["resueltos"] >= 1
    assert any(f["ubicacion"] == u2["codigo"] for f in k["intervenciones"]["filas"])
    assert client.get("/api/partes-estado/kpis", headers=lim).status_code == 200  # ve los de su activo
    qr = client.get("/api/partes-estado/qr.pdf", headers=rec, params={"asset_id": sfl})
    assert qr.status_code == 200 and qr.content.startswith(b"%PDF")
    foto = client.get(f"/api/partes-estado/fotos/{p['fotos'][0]['id']}", headers=rec)
    assert foto.status_code == 200 and foto.headers["content-type"] == "image/jpeg"


def _estado(client, h, aid, uid):
    return next(u["estado"] for u in client.get("/api/partes-estado/ubicaciones", headers=h,
                                                params={"asset_id": aid}).json()["unidades"] if u["id"] == uid)
