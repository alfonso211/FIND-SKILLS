"""Localizador automático y correlativo por suite (SF… Suite Florida, SA… Suite Aeropuerto)."""
from datetime import date, timedelta

HOY = date.today()


def _reservar(client, h, asset_id, dias, **extra):
    ent, sal = HOY + timedelta(days=dias), HOY + timedelta(days=dias + 2)
    u = client.get("/api/turistico/disponibilidad", headers=h, params={
        "asset_id": asset_id, "desde": ent.isoformat(), "hasta": sal.isoformat()}).json()["unidades"][0]
    r = client.post("/api/turistico/reservas", headers=h, json={
        "unit_id": u["id"], "fecha_entrada": ent.isoformat(), "fecha_salida": sal.isoformat(),
        "guest": {"nombre": "Localizador", "apellidos": "Prueba"}, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_localizador_automatico(client, admin, ids):
    sfl, sae = ids["assets"]["SFL"]["id"], ids["assets"]["SAE"]["id"]
    a = _reservar(client, admin, sfl, 700)["localizador"]
    b = _reservar(client, admin, sfl, 703)["localizador"]
    c = _reservar(client, admin, sae, 700)["localizador"]
    assert a.startswith("SF") and len(a) == 12 and a[2:].isdigit()
    assert int(b[2:]) == int(a[2:]) + 1  # correlativo dentro de la suite
    assert c.startswith("SA") and len(c) == 12
    # el que trae el canal se respeta
    assert _reservar(client, admin, sfl, 706, localizador="BK-123")["localizador"] == "BK-123"
    # si al editar se borra, vuelve a ponerse uno automático
    r = _reservar(client, admin, sfl, 709)
    x = client.put(f"/api/turistico/reservas/{r['id']}", headers=admin, json={"localizador": ""}).json()
    assert x["localizador"].startswith("SF") and int(x["localizador"][2:]) == int(r["localizador"][2:]) + 1
