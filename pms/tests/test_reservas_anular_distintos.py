"""Fichas con el mismo nombre que no son la misma persona y anulación de reservas y alquileres desde su ficha."""
from datetime import date, timedelta

from conftest import domicilio_fiscal

HOY = date.today()


def _unidad(client, h, asset_id, codigo):
    return next(u for u in client.get(f"/api/unidades?asset_id={asset_id}&q={codigo}", headers=h).json()
                if u["codigo"] == codigo)


def _grupo(client, h, nombre):
    return [g for g in client.get("/api/terceros/duplicados?tipo=huesped", headers=h).json() if g["nombre"] == nombre]


def test_no_son_la_misma_persona(client, admin, ids):
    sae = ids["assets"]["SAE"]
    alta = {"company_id": sae["company_id"], "asset_id": sae["id"], "tipo": "huesped", "nombre": "Homónimo",
            "apellidos": "De Prueba"}
    a = client.post("/api/terceros", headers=admin, json={**alta, "telefono": "600000001"}).json()["id"]
    b = client.post("/api/terceros", headers=admin, json={**alta, "apellidos": "de prueba", "telefono": "600000002"}).json()["id"]
    assert len(_grupo(client, admin, "Homónimo De Prueba")) == 1
    ficha = client.get(f"/api/terceros/{a}", headers=admin).json()
    assert [o["id"] for o in ficha["repetidas"]] == [b]
    # recepción abre la ficha, comprueba que son personas distintas y quita el aviso
    assert client.post("/api/terceros/distintos", headers=admin, json={"ids": [a, b]}).json()["parejas"] == 1
    assert _grupo(client, admin, "Homónimo De Prueba") == []
    assert client.get(f"/api/terceros/{a}", headers=admin).json()["repetidas"] == []
    # llega una tercera ficha con el mismo nombre: vuelve el aviso para revisarla
    c = client.post("/api/terceros", headers=admin, json={**alta, "telefono": "600000003"}).json()["id"]
    g = _grupo(client, admin, "Homónimo De Prueba")
    assert len(g) == 1 and c in [f["id"] for f in g[0]["fichas"]]
    assert [o["id"] for o in client.get(f"/api/terceros/{c}", headers=admin).json()["repetidas"]] == [a, b]
    assert client.post("/api/terceros/distintos", headers=admin, json={"ids": [a, b, c]}).json()["parejas"] == 2
    assert _grupo(client, admin, "Homónimo De Prueba") == []


def test_anular_reserva(client, admin, ids):
    domicilio_fiscal(client, admin)
    sae = ids["assets"]["SAE"]["id"]
    disp = client.get("/api/turistico/disponibilidad", headers=admin, params={
        "asset_id": sae, "desde": (HOY + timedelta(days=500)).isoformat(), "hasta": (HOY + timedelta(days=503)).isoformat()}).json()
    u1, u2 = disp["unidades"][:2]

    def reservar(u, **extra):
        r = client.post("/api/turistico/reservas", headers=admin, json={
            "unit_id": u["id"], "fecha_entrada": (HOY + timedelta(days=500)).isoformat(),
            "fecha_salida": (HOY + timedelta(days=503)).isoformat(), "guest": {"nombre": "Anula", "apellidos": "Prueba"},
            "importe_total": 150, **extra})
        assert r.status_code == 201, r.text
        return r.json()
    r = reservar(u1)
    assert client.post(f"/api/turistico/reservas/{r['id']}/anular", headers=admin, json={"motivo": ""}).status_code == 422
    x = client.post(f"/api/turistico/reservas/{r['id']}/anular", headers=admin, json={"motivo": "Reserva duplicada"}).json()
    assert x["estado"] == "cancelada" and "Reserva duplicada" in x["notas"]
    assert client.post(f"/api/turistico/reservas/{r['id']}/anular", headers=admin, json={"motivo": "otra vez"}).status_code == 400
    # facturada: primero la rectificativa
    f = reservar(u2, facturar_pendiente=True, forma_pago="transferencia")
    res = client.post(f"/api/turistico/reservas/{f['id']}/anular", headers=admin, json={"motivo": "No viene"})
    assert res.status_code == 400 and "rectificativa" in res.json()["detail"]


def test_anular_alquiler_de_garaje(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    plaza = _unidad(client, admin, sae, "EXT-44")
    inicio = (HOY.replace(day=1) + timedelta(days=40)).replace(day=1)  # empieza el mes que viene: sin recibos
    c = client.post("/api/garajes/contratos", headers=admin, json={
        "unit_id": plaza["id"], "cliente": {"nombre": "Anula", "apellidos": "Garaje"}, "fecha_inicio": inicio.isoformat(),
        "renta_mensual": 80}).json()
    x = client.post(f"/api/garajes/contratos/{c['id']}/anular", headers=admin, json={"motivo": "Se equivocó de plaza"})
    assert x.status_code == 200 and x.json()["estado"] == "anulado"
    assert client.post(f"/api/garajes/contratos/{c['id']}/anular", headers=admin, json={"motivo": "otra"}).status_code == 400
    # con recibos cobrados no se anula: se da de baja
    plaza2 = _unidad(client, admin, sae, "EXT-45")
    c2 = client.post("/api/garajes/contratos", headers=admin, json={
        "unit_id": plaza2["id"], "cliente": {"nombre": "Anula", "apellidos": "Cobrado"},
        "fecha_inicio": HOY.replace(day=1).isoformat(), "renta_mensual": 80}).json()
    rec = client.get(f"/api/garajes/recibos?lease_id={c2['id']}", headers=admin).json()[0]
    assert client.post(f"/api/garajes/recibos/{rec['id']}/cobro", headers=admin,
                       json={"importe": rec["importe"], "forma_pago": "efectivo"}).status_code == 200
    r = client.post(f"/api/garajes/contratos/{c2['id']}/anular", headers=admin, json={"motivo": "Error"})
    assert r.status_code == 400 and "baja" in r.json()["detail"]
