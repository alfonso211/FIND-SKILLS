"""Versión 1.58: fianzas contabilizadas desde los avisos a gestión. Asiento sugerido en cada aviso fianza.*, saldo
en custodia del activo, libro de fianzas con su cuadre y Excel, CSV de la exportación como control y avisos que
faltan generados sin duplicar."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app import libro_fianzas as lf
from app.config import settings
from app.database import SessionLocal
from app.models import GestionEvento
from test_mejoras_150 import _apto_libre, _eventos
from test_pms import _new_user

HOY = date.today()
IBAN = "ES9121000418450200051332"


@pytest.fixture
def desde_avisos(monkeypatch):
    monkeypatch.setattr(settings, "fianzas_origen", "avisos")
    monkeypatch.setattr(settings, "fianzas_avisos_desde", (HOY - timedelta(days=30)).isoformat())


def _cuentas(asiento):
    return [(x["cuenta"], x["debe"], x["haber"]) for x in asiento]


def test_asiento_de_cada_caso():
    r = SimpleNamespace(fianza_cobro={"importe": 200, "forma": "efectivo"})
    assert _cuentas(lf.asiento("fianza.cobrada", r)) == [("570", 200, 0), ("560", 0, 200)]
    d = SimpleNamespace(fianza=200, importe=150, forma="tarjeta")
    # 50 retenidos pasan a ingreso; 150 salen a la tarjeta
    assert _cuentas(lf.asiento("fianza.devolucion", r, d)) == [("560", 50, 0), ("778", 0, 50), ("560", 150, 0), ("572", 0, 150)]
    # por transferencia, lo devuelto sigue en la 560 hasta que se hace
    d = SimpleNamespace(fianza=200, importe=150, forma="transferencia")
    assert _cuentas(lf.asiento("fianza.devolucion", r, d)) == [("560", 50, 0), ("778", 0, 50)]
    assert _cuentas(lf.asiento("fianza.transferida", r, d)) == [("560", 150, 0), ("572", 0, 150)]
    # no procede: todo retenido
    d = SimpleNamespace(fianza=200, importe=0, forma="no_procede")
    assert _cuentas(lf.asiento("fianza.devolucion", r, d)) == [("560", 200, 0), ("778", 0, 200)]
    # preautorización: no hay dinero hasta la salida; solo se cobra lo retenido
    p = SimpleNamespace(fianza_cobro={"importe": 300, "forma": "preautorizacion"})
    assert lf.asiento("fianza.cobrada", p) == []
    assert _cuentas(lf.asiento("fianza.devolucion", p, SimpleNamespace(fianza=300, importe=270, forma="tarjeta"))) == \
        [("572", 30, 0), ("778", 0, 30)]
    assert lf.asiento("fianza.devolucion", p, SimpleNamespace(fianza=300, importe=300, forma="tarjeta")) == []


def test_avisos_con_asiento_saldo_libro_y_control(client, admin, ids, desde_avisos):
    sae = ids["assets"]["SAE"]["id"]
    with SessionLocal() as db:
        antes = lf.saldo(db, sae)
    r = _apto_libre(client, admin, sae, HOY - timedelta(days=2), HOY + timedelta(days=1), importe=200)
    client.put(f"/api/turistico/reservas/{r['id']}", headers=admin, json={"estado": "checkin"})
    c = client.post(f"/api/turistico/reservas/{r['id']}/fianza/cobro", headers=admin, json={"importe": 200, "forma": "efectivo"})
    assert c.status_code == 200, c.text
    ev = _eventos("fianza.cobrada", reserva_id=r["id"])[0].datos
    assert ev["fianza"] == 200 and ev["forma"] == "efectivo"  # lo de siempre no cambia
    assert ev["origen_contable"] == "avisos" and ev["contabilizar"] is True and ev["cobro_registrado"] is True
    assert ev["empresa"]["nombre"] and _cuentas(ev["asiento"]) == [("570", 200, 0), ("560", 0, 200)]
    assert round(ev["saldo_activo"] - antes["custodia"], 2) == 200

    # salida: 50 retenidos por un vaso roto, 150 por transferencia
    out = client.post(f"/api/turistico/reservas/{r['id']}/checkout", headers=admin, json={"fianza": {
        "forma": "transferencia", "iban": IBAN, "importe": 150, "retenido_motivo": "Vaso roto"}})
    assert out.status_code == 200, out.text
    ev = _eventos("fianza.devolucion", reserva_id=r["id"])[0].datos
    assert ev["retenido"] == 50 and _cuentas(ev["asiento"]) == [("560", 50, 0), ("778", 0, 50)]
    assert round(ev["saldo_activo"] - antes["custodia"], 2) == 150  # sigue en custodia hasta transferirla
    fid = ev["devolucion_id"]
    assert client.post(f"/api/turistico/fianzas/{fid}/devuelta", headers=admin, json={}).status_code == 200
    ev = _eventos("fianza.transferida", reserva_id=r["id"])[0].datos
    assert _cuentas(ev["asiento"]) == [("560", 150, 0), ("572", 0, 150)]
    assert round(ev["saldo_activo"], 2) == round(antes["custodia"], 2)

    # libro: los tres movimientos con su aviso, el resumen y el Excel
    q = {"asset_id": sae, "desde": (HOY - timedelta(days=5)).isoformat(), "hasta": HOY.isoformat()}
    lib = client.get("/api/turistico/fianzas/libro", headers=admin, params=q).json()
    mios = [m for m in lib["movimientos"] if m["reserva_id"] == r["id"]]
    assert [m["tipo"] for m in mios] == ["fianza.cobrada", "fianza.devolucion", "fianza.transferida"]
    assert all(m["aviso_estado"] == "pendiente" for m in mios)
    assert lib["origen"] == "avisos" and lib["puede_generar"] is True
    res = next(x for x in lib["resumen"] if x["asset_id"] == sae)
    assert res["cobrado"] >= 200 and res["retenido"] >= 50 and res["transferido"] >= 150
    xls = client.get("/api/turistico/fianzas/libro", headers=admin, params={**q, "formato": "xlsx"})
    assert xls.status_code == 200 and xls.content[:2] == b"PK"

    # si falta un aviso, el cuadre lo dice y se genera una sola vez (id fijo)
    with SessionLocal() as db:
        db.query(GestionEvento).filter(GestionEvento.id == _eventos("fianza.cobrada", reserva_id=r["id"])[0].id).delete()
        db.commit()
    lib = client.get("/api/turistico/fianzas/libro", headers=admin, params=q).json()
    assert any(x["tipo"] == "sin_aviso" and x["reserva_id"] == r["id"] for x in lib["cuadre"])
    g = client.post("/api/turistico/fianzas/libro/avisos", headers=admin, params=q)
    assert g.status_code == 200 and len(g.json()["creados"]) >= 1
    nuevo = _eventos("fianza.cobrada", reserva_id=r["id"])
    assert len(nuevo) == 1 and nuevo[0].datos["generado_desde_libro"] and nuevo[0].id_evento == f"pms-fianza.cobrada-r{r['id']}"
    assert client.post("/api/turistico/fianzas/libro/avisos", headers=admin, params=q).json()["creados"] == []

    # exportación: el CSV de fianzas sale como control y el manifest lo dice
    chk = client.get("/api/exportacion/invergestion/comprobar", headers=admin, params={
        "desde": (HOY - timedelta(days=1)).isoformat(), "hasta": HOY.isoformat(), "tipos": "fianzas"}).json()
    assert chk["fianzas"]["csv"].startswith("CONTROL_FIANZAS_") and chk["fianzas"]["solo_control"] is True


def test_sin_activar_sigue_el_csv(client, admin, ids, monkeypatch):
    monkeypatch.setattr(settings, "fianzas_origen", "csv")
    chk = client.get("/api/exportacion/invergestion/comprobar", headers=admin, params={
        "desde": HOY.isoformat(), "hasta": HOY.isoformat(), "tipos": "fianzas"}).json()
    assert chk["fianzas"]["csv"].startswith("FIANZAS_") and chk["fianzas"]["solo_control"] is False
    lib = client.get("/api/turistico/fianzas/libro", headers=admin).json()
    assert lib["origen"] == "csv" and lib["puede_generar"] is False
    r = client.post("/api/turistico/fianzas/libro/avisos", headers=admin,
                    params={"desde": HOY.isoformat(), "hasta": HOY.isoformat()})
    assert r.status_code == 400 and "PMS_FIANZAS_ORIGEN" in r.json()["detail"]


def test_preautorizacion_y_permisos(client, admin, ids, desde_avisos):
    sfl = ids["assets"]["SFL"]["id"]
    r = _apto_libre(client, admin, sfl, HOY - timedelta(days=1), HOY + timedelta(days=2), importe=150)
    client.put(f"/api/turistico/reservas/{r['id']}", headers=admin, json={"estado": "checkin"})
    client.post(f"/api/turistico/reservas/{r['id']}/fianza/cobro", headers=admin, json={"importe": 300, "forma": "preautorizacion"})
    ev = _eventos("fianza.cobrada", reserva_id=r["id"])[0].datos
    assert ev["asiento"] == [] and ev["preautorizado_activo"] >= 300
    out = client.post(f"/api/turistico/reservas/{r['id']}/checkout", headers=admin, json={"fianza": {
        "forma": "tarjeta", "importe": 270, "retenido_motivo": "Mando perdido"}})
    assert out.status_code == 200, out.text
    assert _cuentas(_eventos("fianza.devolucion", reserva_id=r["id"])[0].datos["asiento"]) == [("572", 30, 0), ("778", 0, 30)]
    # Recepción no ve el libro (es de finanzas) ni puede generar avisos
    rec = _new_user(client, admin, "recepcion.libro158@inversiete.com", [{"role_id": ids["roles"]["Recepción"], "asset_id": sfl}])
    assert client.get("/api/turistico/fianzas/libro", headers=rec, params={"asset_id": sfl}).status_code == 403
    assert client.post("/api/turistico/fianzas/libro/avisos", headers=rec,
                       params={"desde": HOY.isoformat(), "hasta": HOY.isoformat()}).status_code == 403
