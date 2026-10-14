"""Versión 1.57: los informes pesados (ocupación, presidencia, INE) no hacen una consulta por reserva y el reparto de
noches por mes da lo mismo que contarlas mes a mes."""
import random
from datetime import date, timedelta
from types import SimpleNamespace

from app.routers.informes import _meses, _noches, noches_por_mes
from tests.test_rendimiento_156 import HOY, _borrar, _datos, consultas


def test_noches_por_mes_igual_que_mes_a_mes():
    random.seed(157)
    desde, hasta = date(2025, 1, 15), date(2026, 3, 10)
    res = []
    for _ in range(400):
        e = date(2024, 11, 1) + timedelta(days=random.randint(0, 560))
        res.append(SimpleNamespace(fecha_entrada=e, fecha_salida=e + timedelta(days=random.choice((1, 3, 7, 30, 75)))))
    rapido = noches_por_mes(res, desde, hasta)
    for _, ini, fin in _meses(desde, hasta):
        lento = sum(_noches(r.fecha_entrada, r.fecha_salida, ini, fin) for r in res)
        assert rapido.get(f"{ini:%Y-%m}", 0) == lento, ini


def test_informes_sin_una_consulta_por_reserva(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    llegada = HOY + timedelta(days=900)
    ini, fin = llegada.replace(day=1), llegada + timedelta(days=40)
    pantallas = [("/api/informes/ocupacion", {"asset_id": sae, "desde": ini.isoformat(), "hasta": fin.isoformat()}),
                 ("/api/informes/morosidad", {"asset_id": sae, "desde": ini.isoformat(), "hasta": fin.isoformat()}),
                 ("/api/turistico/ine", {"asset_id": sae, "anio": llegada.year, "mes": llegada.month})]
    medidas = {}
    try:
        for marca, n in (("R157A", 5), ("R157B", 35)):
            _datos(sae, n, marca)
            for url, q in pantallas:
                client.get(url, headers=admin, params=q)
                with consultas() as c:
                    r = client.get(url, headers=admin, params=q)
                assert r.status_code == 200, (url, r.text)
                medidas.setdefault(url, []).append(c["n"])
    finally:
        _borrar("R157A")
        _borrar("R157B")
    for url, (pocas, muchas) in medidas.items():
        assert muchas - pocas <= 4, (url, pocas, muchas)
