"""Agenda: reuniones, tareas y recordatorios privados, compartidos o públicos; presidencia no recibe asignaciones."""
from datetime import date, datetime, timedelta

from app import avisos
from app.database import SessionLocal
from test_adjuntos_ot import _usuario

HOY = date.today()


def _uid(client, admin, email):
    return next(u["id"] for u in client.get("/api/admin/usuarios", headers=admin).json() if u["email"] == email)


def _cita(client, h, **kw):
    body = {"tipo": "evento", "titulo": "Cita", "inicio": f"{HOY + timedelta(days=2)}T10:00:00", **kw}
    return client.post("/api/agenda", headers=h, json=body)


def _ver(client, h, dias=40):
    return client.get("/api/agenda", headers=h, params={"desde": str(HOY - timedelta(days=5)),
                                                         "hasta": str(HOY + timedelta(days=dias))}).json()


def test_visibilidad_tareas_y_presidencia(client, admin, ids):
    tec = _usuario(client, admin, ids, "tecnico.agenda@inversiete.com", "Técnico Mantenimiento", "SAE")
    rec = _usuario(client, admin, ids, "recepcion.agenda@inversiete.com", "Recepción", "SAE")
    otro = _usuario(client, admin, ids, "otro.agenda@inversiete.com", "Recepción", "SFL")
    id_rec = _uid(client, admin, "recepcion.agenda@inversiete.com")
    presidente = _uid(client, admin, "jr@inversiete.es")

    # privada: solo la ve quien la crea; no admite participantes
    assert _cita(client, tec, titulo="Médico", visibilidad="privada").status_code == 201
    assert _cita(client, tec, titulo="XX", visibilidad="privada", participantes=[id_rec]).status_code == 400
    # tarea del técnico a recepción (compartida): la ven los dos, no un tercero
    t = _cita(client, tec, tipo="tarea", titulo="Revisar llaves A-127", visibilidad="compartida",
              participantes=[id_rec], prioridad="alta", inicio=f"{HOY - timedelta(days=1)}T09:00:00")
    assert t.status_code == 201, t.text
    t = t.json()
    assert {"Médico", "Revisar llaves A-127"} <= {e["titulo"] for e in _ver(client, tec)}
    vistas = {e["titulo"]: e for e in _ver(client, rec)}
    assert "Médico" not in vistas and vistas["Revisar llaves A-127"]["para_mi"] and vistas["Revisar llaves A-127"]["vencida"]
    assert "Revisar llaves A-127" not in {e["titulo"] for e in _ver(client, otro)}
    # pública: la ven todos
    assert _cita(client, rec, titulo="Inspección de Sanidad", visibilidad="publica", todo_el_dia=True).status_code == 201
    assert "Inspección de Sanidad" in {e["titulo"] for e in _ver(client, otro)}

    # recepción tiene la tarea como nueva y pendiente; la termina; solo el autor la edita o borra
    p = client.get("/api/agenda/pendientes", headers=rec).json()
    assert [x["id"] for x in p["nuevas"]] == [t["id"]] and t["id"] in [x["id"] for x in p["tareas"]]
    client.post(f"/api/agenda/{t['id']}/visto", headers=rec)
    assert client.get("/api/agenda/pendientes", headers=rec).json()["nuevas"] == []
    assert client.put(f"/api/agenda/{t['id']}", headers=rec, json={"titulo": "Otra", "inicio": t["inicio"]}).status_code == 403
    assert client.post(f"/api/agenda/{t['id']}/hecha", headers=otro, json={"hecha": True}).status_code == 404
    h = client.post(f"/api/agenda/{t['id']}/hecha", headers=rec, json={"hecha": True}).json()
    assert h["hecha"] and h["hecha_por_nombre"] == "recepcion.agenda"
    assert t["id"] not in [x["id"] for x in client.get("/api/agenda/pendientes", headers=tec).json()["tareas"]]

    # a presidencia no se le envían tareas ni convocatorias; presidencia sí a los demás
    r = _cita(client, tec, tipo="reunion", titulo="Comité", visibilidad="compartida", participantes=[presidente])
    assert r.status_code == 400 and "no se le pueden enviar" in r.json()["detail"]
    lista = {u["id"]: u for u in client.get("/api/agenda/usuarios", headers=tec).json()}
    assert lista[presidente]["asignable"] is False and lista[id_rec]["asignable"] is True
    # presidencia (marcada al crear el usuario o en su ficha) sí puede enviar a los demás
    jr = _usuario(client, admin, ids, "presi.agenda@inversiete.com", "Dirección Sociedad", "SAE")
    client.put(f"/api/admin/usuarios/{_uid(client, admin, 'presi.agenda@inversiete.com')}", headers=admin,
               json={"no_asignable": True})
    reu = _cita(client, jr, tipo="reunion", titulo="Consejo", visibilidad="compartida", participantes=[id_rec])
    assert reu.status_code == 201, reu.text
    # la recepción responde a la convocatoria
    assert client.post(f"/api/agenda/{reu.json()['id']}/respuesta", headers=rec, json={"respuesta": "acepta"}).json()[
        "mi_respuesta"] == "acepta"


def test_repeticion_ics_y_avisos(client, admin, ids):
    alf = _usuario(client, admin, ids, "dt.agenda@inversiete.com", "Dirección Sociedad", "SAE")
    rec = _usuario(client, admin, ids, "rec2.agenda@inversiete.com", "Recepción", "SAE")
    id_rec = _uid(client, admin, "rec2.agenda@inversiete.com")
    # recordatorio semanal: aparece cada semana
    r = _cita(client, alf, tipo="recordatorio", titulo="Revisar caja", repeticion="semanal",
              inicio=f"{HOY}T09:00:00").json()
    ocurr = [e for e in _ver(client, alf, 28) if e["id"] == r["id"]]
    assert len(ocurr) == 5 and ocurr[1]["ocurrencia"][:10] == str(HOY + timedelta(days=7))
    assert _cita(client, alf, tipo="tarea", titulo="XX", repeticion="semanal").status_code == 400
    # fichero de calendario para el móvil
    ics = client.get(f"/api/agenda/{r['id']}/ics", headers=alf)
    assert ics.status_code == 200 and "RRULE:FREQ=WEEKLY" in ics.text and "SUMMARY:Recordatorio: Revisar caja" in ics.text

    # correo al recibir la tarea y recordatorio antes de la cita
    avisos.BANDEJA.clear()
    inicio = datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=20)
    t = _cita(client, alf, tipo="reunion", titulo="Revisión de tarifas", visibilidad="compartida",
              participantes=[id_rec], inicio=inicio.isoformat(), aviso_min=30, lugar="Oficina")
    assert t.status_code == 201
    assert any(m["para"] == "rec2.agenda@inversiete.com" and "Convocatoria" in m["asunto"] for m in avisos.BANDEJA)
    avisos.BANDEJA.clear()
    with SessionLocal() as db:
        assert avisos.recordatorios_agenda(db, datetime.now()) >= 2  # autor y convocada
        assert avisos.recordatorios_agenda(db, datetime.now()) == 0  # no se repite
    assert {m["para"] for m in avisos.BANDEJA} >= {"dt.agenda@inversiete.com", "rec2.agenda@inversiete.com"}
    # la cita del día aparece en el resumen diario
    with SessionLocal() as db:
        filas = avisos._agenda_del_dia(db, db.get(__import__("app.models", fromlist=["User"]).User, id_rec), inicio.date())
    assert any(f[2] == "Revisión de tarifas" for f in filas)
