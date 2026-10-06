"""Hitos normativos (Verifactu): aviso en el panel y en el resumen diario a dirección y administración."""
from datetime import date, timedelta

from app import avisos, hitos
from test_adjuntos_ot import _usuario


def test_calendario_verifactu():
    assert [h.clave for h in hitos.activos(date(2026, 10, 6))] == []
    assert [h.clave for h in hitos.activos(date(2026, 12, 15))] == ["verifactu_boe"]
    assert [h.clave for h in hitos.activos(date(2028, 1, 10))] == ["verifactu_desarrollo"]
    assert hitos.HITOS[-1].fecha == date(2028, 10, 1)
    # correo: primer día, los lunes y el día límite; el panel, todos los días
    assert hitos.para_correo(date(2026, 12, 1)) and hitos.para_correo(date(2026, 12, 7))  # martes 1 y lunes 7
    assert not hitos.para_correo(date(2026, 12, 2)) and hitos.para_correo(date(2026, 12, 31))


def test_aviso_en_panel_y_correo(client, admin, ids, monkeypatch):
    hoy = avisos.hoy()
    monkeypatch.setattr(hitos, "HITOS", [hitos.Hito("prueba", hoy, hoy + timedelta(days=100), "Verifactu de prueba",
                                                    "Encargar la programación")])
    p = client.get("/api/panel", headers=admin).json()
    assert p["hitos"][0]["titulo"] == "Verifactu de prueba" and p["hitos"][0]["dias"] == 100
    recepcion = _usuario(client, admin, ids, "recepcion.hitos@inversiete.com", "Recepción", "SAE")
    assert client.get("/api/panel", headers=recepcion).json()["hitos"] == []

    avisos.BANDEJA.clear()
    from app.database import SessionLocal
    with SessionLocal() as db:
        avisos.resumen_diario(db, forzar=True)
    alfonso = [m for m in avisos.BANDEJA if m["para"] == "alfonso@inversiete.es"][0]
    assert "Verifactu de prueba" in alfonso["texto"] and "hito(s) normativo(s)" in alfonso["asunto"]
    assert not any("Verifactu" in m["texto"] for m in avisos.BANDEJA if m["para"] == "jaime@apartamentossuitesaeropuerto.es")
