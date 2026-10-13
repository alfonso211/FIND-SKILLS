"""Ausencias del personal: quién registra y quién aprueba según el colectivo, visto bueno de Recepción 1 para
Recepción 2, personal de subcontratas gestionado por Recepción 1, baja médica reservada y resumen anual."""
import io
from datetime import date, timedelta

from openpyxl import load_workbook

from app import ausencias as au
from app import avisos
from conftest import login

LUNES = date.today() + timedelta(days=60 - date.today().weekday())  # un lunes futuro


def _user(client, admin, ids, email, nombre, rol, codigo="BAB35"):
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": email, "nombre": nombre, "password": "Provisional1",
        "asignaciones": [{"role_id": ids["roles"][rol], "asset_id": ids["assets"][codigo]["id"]}]})
    assert r.status_code == 201, r.text
    h = login(client, email, "Provisional1")
    client.post("/api/auth/password", headers=h, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    return h


def _f(n):
    return (LUNES + timedelta(days=n)).isoformat()


def _ficha(client, admin, h, asset_id, area="otros"):
    """Ficha de empleado (la da de alta el Director Técnico / administrador) enlazada al usuario."""
    yo = client.get("/api/auth/me", headers=h).json()
    r = client.post("/api/personal", headers=admin, json={"asset_id": asset_id, "area": area, "nombre": yo["nombre"],
                                                          "user_id": yo["id"], "email": yo["email"]})
    assert r.status_code == 201, r.text
    return r.json()


def test_ausencias_flujo_por_colectivo(client, admin, ids):
    bab = ids["assets"]["BAB35"]["id"]
    tec = _user(client, admin, ids, "tec.aus@inversiete.com", "Técnico Ausencias", "Técnico Mantenimiento")
    r1 = _user(client, admin, ids, "r1.aus@inversiete.com", "Recepción 1 · Zz ausencias", "Recepción")
    r2 = _user(client, admin, ids, "r2.aus@inversiete.com", "Recepción 2 · Babilonia", "Recepción")
    dt = _user(client, admin, ids, "dt.aus@inversiete.com", "Director Técnico Pruebas", "Dirección Técnica")
    dir_ = _user(client, admin, ids, "dir.aus@inversiete.com", "Dirección Pruebas", "Dirección Sociedad")
    # sin ficha de empleado no se pueden pedir ausencias
    r = client.post("/api/ausencias", headers=tec, json={"asset_id": bab, "tipo": "vacaciones", "desde": _f(0), "hasta": _f(1)})
    assert r.status_code == 400 and "ficha" in r.json()["detail"]
    for h, area in ((tec, "mantenimiento"), (r1, "recepcion"), (r2, "recepcion")):
        _ficha(client, admin, h, bab, area)
    avisos.BANDEJA.clear()

    # mantenimiento: lo solicita el técnico, se avisa a todos y solo lo autoriza el director técnico
    v = client.post("/api/ausencias", headers=tec, json={
        "asset_id": bab, "tipo": "vacaciones", "desde": _f(0), "hasta": _f(13)}).json()
    assert v["colectivo"] == "mantenimiento" and v["estado"] == "pendiente"
    assert (v["dias_naturales"], v["dias_laborables"]) == (14, 10)
    para = {m["para"] for m in avisos.BANDEJA if not m["asunto"].startswith("Calendario de vacaciones")}
    assert {"r1.aus@inversiete.com", "r2.aus@inversiete.com", "dt.aus@inversiete.com"} <= para
    assert "tec.aus@inversiete.com" not in para
    assert client.post(f"/api/ausencias/{v['id']}/aprobar", headers=dir_).status_code == 403
    assert client.post(f"/api/ausencias/{v['id']}/aprobar", headers=r1).status_code == 403
    assert client.post(f"/api/ausencias/{v['id']}/aprobar", headers=tec).status_code == 403
    assert client.post(f"/api/ausencias/{v['id']}/aprobar", headers=dt).json()["estado"] == "aprobada"
    assert client.post(f"/api/ausencias/{v['id']}/anular", headers=r1, json={}).status_code == 403
    # no puede solaparse con otra suya
    assert client.post("/api/ausencias", headers=tec, json={
        "asset_id": bab, "tipo": "dia_libre", "desde": _f(5), "hasta": _f(5)}).status_code == 400

    # Recepción 2: primero el visto bueno de Recepción 1 y después dirección
    x = client.post("/api/ausencias", headers=r2, json={
        "asset_id": bab, "tipo": "dia_libre", "desde": _f(20), "hasta": _f(20), "motivo": "Asuntos propios"}).json()
    assert x["colectivo"] == "recepcion2"
    r = client.post(f"/api/ausencias/{x['id']}/aprobar", headers=dir_)
    assert r.status_code == 403 and "visto bueno" in r.json()["detail"]
    assert client.post(f"/api/ausencias/{x['id']}/visto-bueno", headers=r2).status_code == 403
    assert client.post(f"/api/ausencias/{x['id']}/visto-bueno", headers=r1).json()["estado"] == "visto_bueno"
    assert client.post(f"/api/ausencias/{x['id']}/aprobar", headers=r1).status_code == 403
    assert client.post(f"/api/ausencias/{x['id']}/aprobar", headers=dir_).json()["estado"] == "aprobada"

    # Recepción 1 la aprueba dirección; nadie aprueba la suya
    y = client.post("/api/ausencias", headers=r1, json={
        "asset_id": bab, "tipo": "vacaciones", "desde": _f(30), "hasta": _f(31), "aprobar": True})
    assert y.status_code == 403
    y = client.post("/api/ausencias", headers=r1, json={
        "asset_id": bab, "tipo": "vacaciones", "desde": _f(30), "hasta": _f(31)}).json()
    assert y["colectivo"] == "recepcion1" and not y["puede_aprobar"]
    r = client.post(f"/api/ausencias/{y['id']}/denegar", headers=dir_, json={"nota": ""})
    assert r.status_code == 400
    assert client.post(f"/api/ausencias/{y['id']}/denegar", headers=dir_,
                       json={"nota": "Coincide con Recepción 2"}).json()["estado"] == "denegada"

    # fichas: Recepción (1 y 2) solo da de alta personal de subcontratas; el propio, el Director Técnico
    p = {"asset_id": bab, "area": "conserjeria", "nombre": "Conserje Pruebas", "empresa": "Servicios Pruebas SL"}
    assert client.post("/api/personal", headers=r2, json={**p, "empresa": None}).status_code == 403
    staff = client.post("/api/personal", headers=r2, json=p).json()
    assert staff["area_nombre"] == "Conserjería" and not staff["propio"]
    # nadie registra ausencias de otros: cada uno las suyas con su usuario
    assert client.post("/api/ausencias", headers=r1, json={
        "asset_id": bab, "staff_id": staff["id"], "tipo": "falta", "desde": _f(2), "hasta": _f(2)}).status_code == 403
    yo_r2 = client.get("/api/auth/me", headers=r2).json()["id"]
    assert client.post("/api/ausencias", headers=r1, json={
        "asset_id": bab, "user_id": yo_r2, "tipo": "falta", "desde": _f(2), "hasta": _f(2)}).status_code == 403
    b = client.post("/api/ausencias", headers=r2, json={
        "asset_id": bab, "tipo": "baja_medica", "desde": _f(50), "hasta": _f(55), "motivo": "Parte de baja entregado"}).json()
    assert b["colectivo"] == "recepcion2" and b["estado"] == "pendiente"

    # la baja médica es un dato de salud: el técnico solo ve «Ausencia»
    lista = {z["id"]: z for z in client.get("/api/ausencias", headers=tec, params={"asset_id": bab}).json()}
    assert lista[b["id"]]["tipo_nombre"] == "Ausencia" and lista[b["id"]]["motivo"] is None
    assert lista[v["id"]]["tipo_nombre"] == "Vacaciones"
    lista = {z["id"]: z for z in client.get("/api/ausencias", headers=r1, params={"asset_id": bab}).json()}
    assert lista[b["id"]]["tipo_nombre"] == "Baja médica"

    # anular: la propia persona mientras está pendiente
    z = client.post("/api/ausencias", headers=r2, json={
        "asset_id": bab, "tipo": "permiso", "desde": _f(40), "hasta": _f(40)}).json()
    assert client.post(f"/api/ausencias/{z['id']}/anular", headers=tec, json={}).status_code == 403
    assert client.post(f"/api/ausencias/{z['id']}/anular", headers=r2, json={}).json()["estado"] == "anulada"

    # resumen anual y Excel
    anio = LUNES.year
    res = client.get("/api/ausencias/resumen", headers=dir_, params={"asset_id": bab, "anio": anio}).json()
    tecnico = next(q for q in res["personas"] if q["persona"] == "Técnico Ausencias")
    if (LUNES + timedelta(days=13)).year == anio:
        assert tecnico["tipos"]["vacaciones"]["laborables"] == 10
    xl = load_workbook(io.BytesIO(client.get("/api/ausencias/excel", headers=dir_,
                                             params={"asset_id": bab, "anio": anio}).content))
    assert xl.sheetnames == ["Ausencias", "Resumen aprobadas"]
    assert any(c.value == "Recepción 2 · Babilonia" for fila in xl["Ausencias"].iter_rows() for c in fila)


def test_dias():
    assert au.dias(date(2026, 10, 5), date(2026, 10, 11)) == (7, 5)
    assert au.dias(date(2026, 10, 10), date(2026, 10, 10)) == (1, 0)


def test_direccion_aprueba_cualquiera_y_presidencia_no(client, admin, ids):
    """Las ausencias que aprueba dirección se avisan a los directores (no a la presidencia) y basta con que
    apruebe uno; la presidencia no aprueba."""
    bab = ids["assets"]["BAB35"]["id"]
    d1 = _user(client, admin, ids, "dg.aus@inversiete.com", "Directora General Pruebas", "Dirección Sociedad")
    d2 = _user(client, admin, ids, "dt2.aus@inversiete.com", "Director Técnico 2 Pruebas", "Dirección Sociedad")
    r = client.post("/api/admin/usuarios", headers=admin, json={
        "email": "pres.aus@inversiete.com", "nombre": "Presidencia Pruebas", "password": "Provisional1",
        "no_asignable": True, "asignaciones": [{"role_id": ids["roles"]["Dirección Sociedad"], "asset_id": bab}]})
    assert r.status_code == 201
    pres = login(client, "pres.aus@inversiete.com", "Provisional1")
    client.post("/api/auth/password", headers=pres, json={"actual": "Provisional1", "nueva": "ClaveDefinitiva2026"})
    of = _user(client, admin, ids, "oficina.aus@inversiete.com", "Oficina Pruebas", "Consulta")
    _ficha(client, admin, of, bab)
    avisos.BANDEJA.clear()
    x = client.post("/api/ausencias", headers=of, json={
        "asset_id": bab, "tipo": "permiso", "desde": _f(50), "hasta": _f(50), "motivo": "Médico"}).json()
    assert x["colectivo"] == "direccion"
    para = {m["para"] for m in avisos.BANDEJA if not m["asunto"].startswith("Calendario de vacaciones")}
    assert {"dg.aus@inversiete.com", "dt2.aus@inversiete.com"} <= para and "pres.aus@inversiete.com" not in para
    # aparece en el panel de los dos directores, no en el de la presidencia
    assert any(a["id"] == x["id"] for a in client.get("/api/panel", headers=d1).json()["ausencias_pendientes"])
    assert not any(a["id"] == x["id"] for a in client.get("/api/panel", headers=pres).json()["ausencias_pendientes"])
    assert client.post(f"/api/ausencias/{x['id']}/aprobar", headers=pres).status_code == 403
    assert client.post(f"/api/ausencias/{x['id']}/aprobar", headers=d2).json()["estado"] == "aprobada"
    assert client.post(f"/api/ausencias/{x['id']}/aprobar", headers=d1).status_code == 403  # ya está aprobada
    log = client.get("/api/admin/avisos-enviados", headers=admin)
    if log.status_code == 200:
        assert any(e.get("tipo") == "ausencia" for e in log.json())


def test_resolver_y_comunicar(client, admin, ids):
    """Autorizar, desestimar y anular desde el ordenador: se comunica por correo al trabajador y a Recepción; si el
    trabajador no tiene correo, WhatsApp con el mensaje escrito. Para anular la de otro hay que dar el motivo."""
    sae = ids["assets"]["SAE"]["id"]
    r1 = _user(client, admin, ids, "r1.com@inversiete.com", "Recepción 1 · Zz comunica", "Recepción", "SAE")
    r2 = _user(client, admin, ids, "r2.com@inversiete.com", "Recepción 2 · Comunica", "Recepción", "SAE")
    dir_ = _user(client, admin, ids, "dir.com@inversiete.com", "Dirección Comunica", "Dirección Sociedad", "SAE")
    antes = next(a for a in client.get("/api/activos", headers=admin).json() if a["id"] == sae)["recepcion1_id"]
    yo = client.get("/api/auth/me", headers=r1).json()["id"]
    # Recepción 1 del activo: asignada expresamente (no se deduce del nombre)
    assert client.put(f"/api/activos/{sae}", headers=admin, json={"recepcion1_id": yo}).status_code == 200
    assert client.put(f"/api/activos/{sae}", headers=admin, json={
        "recepcion1_id": client.get("/api/auth/me", headers=dir_).json()["id"]}).status_code == 400  # no es Recepción
    for h in (r1, r2):
        _ficha(client, admin, h, sae, "recepcion")

    # autorizar (dirección): correo a la persona y al resto de Recepción del activo
    x = client.post("/api/ausencias", headers=r1, json={
        "asset_id": sae, "tipo": "vacaciones", "desde": _f(70), "hasta": _f(74)}).json()
    avisos.BANDEJA.clear()
    r = client.post(f"/api/ausencias/{x['id']}/aprobar", headers=dir_)
    assert r.status_code == 200, r.text
    r = r.json()
    assert r["estado_nombre"] == "Autorizada" and r["comunicado"]["trabajador_correo"]
    assert {"r1.com@inversiete.com", "r2.com@inversiete.com"} <= set(r["comunicado"]["enviados"])
    m = next(m for m in avisos.BANDEJA if m["para"] == "r1.com@inversiete.com" and "Su solicitud" in m["asunto"])
    assert "AUTORIZADA" in m["texto"] and "Dirección Comunica" in m["texto"]

    # desestimar (Recepción 1, en el visto bueno de Recepción 2): con motivo, que llega al trabajador
    y = client.post("/api/ausencias", headers=r2, json={
        "asset_id": sae, "tipo": "dia_libre", "desde": _f(80), "hasta": _f(80)}).json()
    avisos.BANDEJA.clear()
    assert client.post(f"/api/ausencias/{y['id']}/denegar", headers=r1, json={"nota": " "}).status_code == 400
    r = client.post(f"/api/ausencias/{y['id']}/denegar", headers=r1, json={"nota": "Ocupación completa"}).json()
    assert r["estado_nombre"] == "Desestimada"
    m = next(m for m in avisos.BANDEJA if m["para"] == "r2.com@inversiete.com")
    assert "DESESTIMADA" in m["texto"] and "Ocupación completa" in m["texto"]

    # anular la solicitud de otro (con un error o que no procede): el motivo es obligatorio y le llega
    z = client.post("/api/ausencias", headers=r2, json={
        "asset_id": sae, "tipo": "falta", "desde": _f(3), "hasta": _f(3)}).json()
    assert client.post(f"/api/ausencias/{z['id']}/anular", headers=dir_, json={}).status_code == 400
    avisos.BANDEJA.clear()
    r = client.post(f"/api/ausencias/{z['id']}/anular", headers=dir_, json={"nota": "Fecha equivocada"}).json()
    assert r["estado"] == "anulada" and r["comunicado"]["trabajador_correo"]
    assert any(m["para"] == "r2.com@inversiete.com" and "Fecha equivocada" in m["texto"] for m in avisos.BANDEJA)
    assert any(m["para"] == "r1.com@inversiete.com" and "Fecha equivocada" in m["texto"] for m in avisos.BANDEJA)
    client.put(f"/api/activos/{sae}", headers=admin, json={"recepcion1_id": antes})
