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
    r1_antes = next(a for a in client.get("/api/activos", headers=admin).json() if a["id"] == sfl)["recepcion1_id"]
    client.put(f"/api/activos/{sfl}", headers=admin, json={"recepcion1_id": yo["id"]})  # la aprueba dirección
    v = client.post("/api/ausencias", headers=rec, json={
        "asset_id": sfl, "tipo": "vacaciones", "desde": l1.isoformat(), "hasta": (l1 + timedelta(days=4)).isoformat()})
    assert v.status_code == 201 and v.json()["aviso_saldo"] is None and v.json()["colectivo"] == "recepcion1", v.text
    v = client.post(f"/api/ausencias/{v.json()['id']}/aprobar", headers=admin)
    assert v.json()["estado"] == "aprobada"
    s = client.get(f"/api/personal/{p['id']}/saldo", headers=admin).json()
    if l1.year == anio:  # laborables: sin fines de semana ni festivos
        from app.calendario import laborable
        n = sum(1 for i in range(5) if laborable(l1 + timedelta(days=i)))
        assert (s["aprobadas"], s["restantes"]) == (n, 22 - n)
    l2 = _lunes(12)
    w = client.post("/api/ausencias", headers=rec, json={
        "asset_id": sfl, "tipo": "vacaciones", "desde": l2.isoformat(), "hasta": (l2 + timedelta(days=27)).isoformat()})
    if l2.year == anio and (l2 + timedelta(days=27)).year == anio:
        assert "Supera el saldo" in w.json()["aviso_saldo"]
    todas = client.get("/api/ausencias", headers=admin, params={"estado": "vigentes"}).json()
    assert any(x["id"] == w.json()["id"] and x["activo"] == "Suite Florida" for x in todas)
    assert any(x["id"] == w.json()["id"] and x.get("aviso_saldo") for x in todas) or l2.year != anio
    assert client.get("/api/ausencias/resumen", headers=admin).status_code == 200
    assert client.get("/api/ausencias/excel", headers=admin).status_code == 200
    client.put(f"/api/activos/{sfl}", headers=admin, json={"recepcion1_id": r1_antes})

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


def test_recepcion1_explicita_comprobar_y_borrar_todo(client, admin, ids):
    """Recepción 1 asignada en el activo (no por el nombre), un usuario en una sola ficha, comprobación con corrección
    de solicitudes mal clasificadas y borrado de todo el personal para empezar de nuevo."""
    from test_ausencias import _user
    bab = ids["assets"]["BAB35"]["id"]
    jc = _user(client, admin, ids, "jc.r1@inversiete.com", "Juan Carlos Pruebas", "Recepción", "BAB35")
    yo = client.get("/api/auth/me", headers=jc).json()
    ficha = client.post("/api/personal", headers=admin, json={"asset_id": bab, "area": "recepcion", "nombre": yo["nombre"],
                                                              "user_id": yo["id"]}).json()
    # un usuario, una ficha
    r = client.post("/api/personal", headers=admin, json={"asset_id": bab, "area": "otros", "nombre": "Duplicada",
                                                          "user_id": yo["id"]})
    assert r.status_code == 400 and "ya está enlazado" in r.json()["detail"]
    libres = {u["id"]: u for u in client.get("/api/personal/usuarios", headers=admin).json()}
    assert libres[yo["id"]]["ficha_id"] == ficha["id"]
    assert client.get("/api/personal/usuarios", headers=jc).status_code == 403
    # su nombre no dice «Recepción 1»: se le tomaba por Recepción 2
    x = client.post("/api/ausencias", headers=jc, json={"asset_id": bab, "tipo": "vacaciones",
                                                        "desde": "2099-03-02", "hasta": "2099-03-06"}).json()
    antes = next(a for a in client.get("/api/activos", headers=admin).json() if a["id"] == bab)["recepcion1_id"]
    assert x["colectivo"] == "recepcion2"
    assert client.put(f"/api/activos/{bab}", headers=admin, json={"recepcion1_id": yo["id"]}).status_code == 200
    c = client.get("/api/personal/comprobar", headers=admin).json()
    assert c["puede_borrar"] and any(e["que"] == "Ausencias" and e["corregible"] for e in c["resultados"])
    assert client.post("/api/personal/comprobar/corregir", headers=admin).json()["corregidas"] >= 1
    lista = {a["id"]: a for a in client.get("/api/ausencias", headers=admin, params={"asset_id": bab}).json()}
    assert lista[x["id"]]["colectivo"] == "recepcion1"

    # borrar todo el personal: solo las cuentas autorizadas y con la confirmación escrita
    assert client.post("/api/personal/borrar-todo", headers=jc, json={"confirmacion": "BORRAR PERSONAL"}).status_code == 403
    assert client.post("/api/personal/borrar-todo", headers=admin, json={"confirmacion": "si"}).status_code == 400
    n = client.post("/api/personal/borrar-todo", headers=admin, json={"confirmacion": "borrar personal"}).json()
    assert n["fichas"] >= 1
    assert client.get("/api/personal", headers=admin).json() == []
    lista = {a["id"]: a for a in client.get("/api/ausencias", headers=admin, params={"asset_id": bab}).json()}
    assert x["id"] in lista  # las ausencias de usuarios se conservan
    # se vuelve a empezar: sin ficha no se pueden pedir ausencias
    r = client.post("/api/ausencias", headers=jc, json={"asset_id": bab, "tipo": "dia_libre",
                                                        "desde": "2099-04-01", "hasta": "2099-04-01"})
    assert r.status_code == 400
    # y se vuelven a generar desde los usuarios (una por usuario, sin presidencia ni administrador)
    assert client.post("/api/personal/generar-desde-usuarios", headers=jc).status_code == 403
    g = client.post("/api/personal/generar-desde-usuarios", headers=admin).json()["creadas"]
    assert "Juan Carlos Pruebas" in g and "Presidente" not in g
    assert client.post("/api/personal/generar-desde-usuarios", headers=admin).json()["creadas"] == []
    mia = next(p for p in client.get("/api/personal", headers=admin).json() if p.get("usuario") == "Juan Carlos Pruebas")
    assert mia["area"] == "recepcion" and mia["asset_id"] == bab and mia["propio"]
    assert client.post("/api/ausencias", headers=jc, json={"asset_id": bab, "tipo": "dia_libre", "desde": "2099-04-01",
                                                           "hasta": "2099-04-01"}).status_code == 201
    client.put(f"/api/activos/{bab}", headers=admin, json={"recepcion1_id": antes})


def test_vacaciones_registro_calendario_y_recordatorio(client, admin, ids):
    """El Director Técnico registra en la ficha las vacaciones ya disfrutadas y acordadas; el saldo distingue
    disfrutadas, solicitadas y pendientes de solicitar; cada cambio envía el calendario a todos los usuarios (también a
    los colaboradores) y cada lunes se recuerda a quien tiene días sin solicitar."""
    from app import informe_vacaciones
    from test_ausencias import _user
    sae = ids["assets"]["SAE"]["id"]
    tec = _user(client, admin, ids, "tec.vac@inversiete.com", "Técnico Vacaciones", "Técnico Mantenimiento", "SAE")
    yo = client.get("/api/auth/me", headers=tec).json()
    f = client.post("/api/personal", headers=admin, json={"asset_id": sae, "area": "mantenimiento", "nombre": yo["nombre"],
                                                          "user_id": yo["id"], "email": yo["email"], "vacaciones_dias": 30,
                                                          "vacaciones_tipo": "naturales"})
    assert f.status_code == 201, f.text
    f = f.json()
    hoy = date.today()
    pasado = (hoy - timedelta(days=20), hoy - timedelta(days=11)) if hoy.timetuple().tm_yday > 25 else None
    futuro = (hoy + timedelta(days=10), hoy + timedelta(days=14))
    periodos = ([{"desde": pasado[0].isoformat(), "hasta": pasado[1].isoformat()}] if pasado else []) + \
        [{"desde": futuro[0].isoformat(), "hasta": futuro[1].isoformat()}]
    assert client.post(f"/api/personal/{f['id']}/vacaciones", headers=tec, json={"periodos": periodos}).status_code == 403
    from test_colaborador import _user as _colab
    prov = client.post("/api/proveedores", headers=admin, json={"nombre": "Mantenimiento Colab Vac SL"}).json()
    _colab(client, admin, ids, "colab.vac@inversiete.com", "Colaborador Vacaciones", "Colaborador", supplier_id=prov["id"])
    with SessionLocal() as db:  # la cola empieza vacía (cambios de otras pruebas)
        informe_vacaciones.enviar_pendientes(db, forzar=True)
    avisos.BANDEJA.clear()
    r = client.post(f"/api/personal/{f['id']}/vacaciones", headers=admin, json={"periodos": periodos})
    assert r.status_code == 201, r.text
    s = r.json()["saldo"]
    if futuro[1].year == hoy.year:
        assert s["disfrutadas"] == (10 if pasado else 0) and s["solicitadas"] == 5
        assert s["pendientes_solicitar"] == s["corresponden"] - s["disfrutadas"] - 5
    # solapado: no
    assert client.post(f"/api/personal/{f['id']}/vacaciones", headers=admin, json={"periodos": [periodos[-1]]}).status_code == 400
    # los cambios se agrupan: no sale ningún correo hasta la siguiente revisión
    assert not [x for x in avisos.BANDEJA if x["asunto"].startswith("Calendario de vacaciones")]
    cola = client.get("/api/ausencias/calendario-vacaciones/pendientes", headers=admin).json()
    assert len(cola["cambios"]) == len(periodos) and cola["puede_enviar"]
    assert client.post("/api/ausencias/calendario-vacaciones/enviar", headers=tec).status_code == 403
    r = client.post("/api/ausencias/calendario-vacaciones/enviar", headers=admin).json()
    assert r["cambios"] == len(periodos)
    assert client.post("/api/ausencias/calendario-vacaciones/enviar", headers=admin).status_code == 400  # ya no queda nada
    # una sola revisión, a todos los usuarios activos, colaboradores incluidos
    with SessionLocal() as db:
        todos = {u.email for u in informe_vacaciones.destinatarios(db)}
    assert "colab.vac@inversiete.com" in todos
    m = [x for x in avisos.BANDEJA if x["asunto"].startswith("Calendario de vacaciones")]
    assert len(m) == len(todos)
    assert {x["para"] for x in m} == todos and m[0]["adjuntos"][0][0].endswith(".pdf")
    assert "Técnico Vacaciones: registradas las vacaciones" in m[0]["texto"]
    pdf = client.get("/api/ausencias/calendario-vacaciones.pdf", headers=tec)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    v = client.get(f"/api/personal/{f['id']}/vacaciones", headers=admin).json()
    assert v["registrar"] and len(v["periodos"]) == len(periodos) and v["periodos"][-1]["registrada_por"]
    # su propia solicitud se anota y sale en la revisión agrupada, pasado el intervalo y en horario de 8 a 20
    avisos.BANDEJA.clear()
    lejos = hoy + timedelta(days=40)
    x = client.post("/api/ausencias", headers=tec, json={"asset_id": sae, "tipo": "vacaciones", "desde": lejos.isoformat(),
                                                         "hasta": (lejos + timedelta(days=1)).isoformat()})
    assert x.status_code == 201, x.text
    client.post(f"/api/ausencias/{x.json()['id']}/anular", headers=tec, json={})
    from datetime import datetime as dt
    with SessionLocal() as db:
        assert len(informe_vacaciones.pendientes(db)) == 2
        from app.calendario import laborable
        dia = hoy + timedelta(days=1)
        while not laborable(dia):
            dia += timedelta(days=1)
        festivo = dia + timedelta(days=1)
        while laborable(festivo):  # siguiente sábado, domingo o festivo
            festivo += timedelta(days=1)
        manana = dt.combine(dia, dt.min.time())
        assert informe_vacaciones.enviar_pendientes(db, manana.replace(hour=3)) == 0  # de madrugada no
        assert informe_vacaciones.enviar_pendientes(db, dt.combine(festivo, dt.min.time()).replace(hour=10)) == 0  # ni en festivo
        assert informe_vacaciones.enviar_pendientes(db, manana.replace(hour=10)) >= 1
        assert informe_vacaciones.pendientes(db) == []
    cal = [z for z in avisos.BANDEJA if z["asunto"].startswith("Calendario")]
    assert len(cal) == len(todos) and "solicita vacaciones" in cal[0]["texto"] and "anuladas" in cal[0]["texto"]

    # recordatorio semanal (lunes), una vez por semana y persona
    lunes = hoy - timedelta(days=hoy.weekday())
    avisos.BANDEJA.clear()
    with SessionLocal() as db:
        assert informe_vacaciones.recordatorio_semanal(db, lunes + timedelta(days=1)) == 0  # martes: nada
        assert informe_vacaciones.recordatorio_semanal(db, lunes) >= 1
        assert informe_vacaciones.recordatorio_semanal(db, lunes) == 0
    r = next(z for z in avisos.BANDEJA if z["para"] == "tec.vac@inversiete.com")
    assert "por solicitar" in r["asunto"] and "31 de diciembre" in r["texto"]
