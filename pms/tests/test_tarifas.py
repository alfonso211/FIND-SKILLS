"""Tarifas estándar por noches: tramos, precio de 30 noches, propuesta en la disponibilidad y precio aceptado."""
from datetime import date, timedelta

from app import tarifas

D = date(2031, 3, 1)


def _t(tipo, noches):
    return tarifas.calcular(tipo, D, D + timedelta(days=noches))


def test_tramos_de_la_tabla():
    # 1 a 6 noches: tarifa base
    assert (_t("estudio", 1)["por_noche"], _t("1d", 6)["por_noche"], _t("2d", 3)["total"]) == (50.0, 55.0, 225.0)
    # 7 a 13: -10 %
    assert [_t(x, 7)["por_noche"] for x in ("estudio", "1d", "2d")] == [45.0, 49.5, 67.5]
    assert _t("1d", 13)["total"] == 643.5
    # 14 a 29: -19 %
    assert [_t(x, 14)["por_noche"] for x in ("estudio", "1d", "2d")] == [40.5, 44.55, 60.75]
    assert _t("2d", 29)["total"] == 1761.75
    # 30 noches: precio total de la estancia; más de 30, proporcional
    assert [_t(x, 30)["total"] for x in ("estudio", "1d", "2d")] == [950.0, 1100.0, 1400.0]
    assert _t("estudio", 31)["total"] == 981.67 and _t("1d", 60)["total"] == 2200.0
    assert _t("estudio", 0) is None and _t(None, 5) is None


def test_tipo_de_unidad():
    assert tarifas.tipo_de(0) == "estudio" and tarifas.tipo_de(1) == "1d" and tarifas.tipo_de(3) == "2d"
    assert tarifas.tipo_de(None, "Estudio") == "estudio" and tarifas.tipo_de(None, "Apartamento 2 dormitorios") == "2d"
    assert tarifas.tipo_de(1, uso="garaje") is None and tarifas.tipo_de(None, "Vivienda") is None


def test_propuesta_y_precio_aceptado(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    ent, sal = date.today() + timedelta(days=400), date.today() + timedelta(days=410)  # 10 noches: -10 %
    disp = client.get("/api/turistico/disponibilidad", headers=admin,
                      params={"asset_id": sae, "desde": ent.isoformat(), "hasta": sal.isoformat()}).json()
    u = next(x for x in disp["unidades"] if x["dormitorios"] == 2)
    assert u["tarifa"]["total"] == 675.0 and "7 a 13" in u["tarifa"]["tramo"]
    t = client.get("/api/turistico/tarifa", headers=admin,
                   params={"unit_id": u["id"], "entrada": ent.isoformat(), "salida": sal.isoformat()}).json()
    assert t == u["tarifa"]

    alta = {"unit_id": u["id"], "fecha_entrada": ent.isoformat(), "fecha_salida": sal.isoformat(),
            "guest": {"nombre": "Tarifa", "apellidos": "Prueba"}, "importe_total": 600}
    r = client.post("/api/turistico/reservas", headers=admin, json={**alta, "precio_aceptado": False})
    assert r.status_code == 400 and "Acepto el precio" in r.json()["detail"]
    r = client.post("/api/turistico/reservas", headers=admin, json={**alta, "precio_aceptado": True})
    assert r.status_code == 201 and r.json()["importe_total"] == 600  # recepción lo cambió y lo aceptó
