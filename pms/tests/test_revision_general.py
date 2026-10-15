"""Errores corregidos en la revisión general del PMS (octubre 2026)."""
from datetime import date, timedelta

from app import empleados
from app.database import SessionLocal
from app.models import StaffMember, TimeEntry

HOY = date.today()


def _libre(client, admin, asset_id, ent, sal, guest, desde_final=80):
    unidades = [u for u in client.get(f"/api/unidades?asset_id={asset_id}", headers=admin).json() if u["uso"] == "apartamento"]
    for u in unidades[-desde_final:]:
        r = client.post("/api/turistico/reservas", headers=admin, json={
            "unit_id": u["id"], "fecha_entrada": ent.isoformat(), "fecha_salida": sal.isoformat(), "importe_total": 500,
            **guest})
        if r.status_code == 201:
            return u, r.json()
    raise AssertionError("sin apartamento libre")


def test_no_dos_alojados_y_estado_desde_editar(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    u, vieja = _libre(client, admin, sfl, HOY - timedelta(days=10), HOY - timedelta(days=2), {"guest": {"nombre": "Vencido"}})
    assert client.put(f"/api/turistico/reservas/{vieja['id']}", headers=admin, json={"estado": "checkin"}).status_code == 200
    nueva = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": u["id"], "fecha_entrada": HOY.isoformat(), "fecha_salida": (HOY + timedelta(days=3)).isoformat(),
        "guest": {"nombre": "Llega Hoy"}}).json()
    x = client.put(f"/api/turistico/reservas/{nueva['id']}", headers=admin, json={"estado": "checkin"})
    assert x.status_code == 400 and "sigue alojado" in x.json()["detail"]
    for estado in ("cancelada", "checkout", "no_show"):  # tienen sus botones (facturas, fianza, limpieza)
        y = client.put(f"/api/turistico/reservas/{nueva['id']}", headers=admin, json={"estado": estado})
        assert y.status_code == 400 and "Editar" in y.json()["detail"]


def test_importe_no_baja_de_lo_facturado(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    from tests.conftest import domicilio_fiscal
    domicilio_fiscal(client, admin)
    _, r = _libre(client, admin, sfl, HOY + timedelta(days=150), HOY + timedelta(days=153), {"guest": {"nombre": "Factura"}})
    # estancia facturada sin cobrar (pagará por transferencia): 500 €
    f = client.post(f"/api/turistico/reservas/{r['id']}/facturar", headers=admin, json={})
    assert f.status_code == 200, f.text
    z = client.put(f"/api/turistico/reservas/{r['id']}", headers=admin, json={"importe_total": 100})
    assert z.status_code == 400 and "facturado" in z.json()["detail"]


def test_lista_negra_con_documento_en_otro_formato(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    _, r = _libre(client, admin, sae, HOY + timedelta(days=170), HOY + timedelta(days=172),
                  {"guest": {"nombre": "Formato", "documento_tipo": "DNI", "documento_num": "22222222-J"}})
    client.put(f"/api/terceros/{r['guest_id']}/lista-negra", headers=admin, json={"activa": True, "motivo": "Impago"})
    for doc in ("22222222J", "22.222.222 j"):
        assert client.get("/api/lista-negra/comprobar", headers=admin, params={"documento": doc}).json()
    unidades = [u for u in client.get(f"/api/unidades?asset_id={sae}", headers=admin).json() if u["uso"] == "apartamento"]
    no = client.post("/api/turistico/reservas", headers=admin, json={
        "unit_id": unidades[5]["id"], "fecha_entrada": (HOY + timedelta(days=300)).isoformat(),
        "fecha_salida": (HOY + timedelta(days=301)).isoformat(),
        "guest": {"nombre": "Formato", "documento_tipo": "DNI", "documento_num": "22222222J"}})
    assert no.status_code == 409 and "Impago" in no.json()["detail"], no.text


def test_fichaje_olvidado_no_cierra_el_de_hoy(client, admin, ids):
    from datetime import datetime
    with SessionLocal() as db:
        p = StaffMember(nombre="Fichaje Olvido", area="mantenimiento", activo=True)
        db.add(p)
        db.flush()
        ayer = datetime.now().replace(microsecond=0) - timedelta(days=1)
        db.add(TimeEntry(staff_id=p.id, entrada=ayer, origen="web"))
        db.commit()
        t = empleados.fichar(db, p, "web")
        db.commit()
        assert t.salida is None and t.entrada.date() == date.today()  # entrada nueva hoy
        abiertos = db.query(TimeEntry).filter(TimeEntry.staff_id == p.id, TimeEntry.salida.is_(None)).count()
        assert abiertos == 2  # el de ayer queda como olvido para corregirlo
