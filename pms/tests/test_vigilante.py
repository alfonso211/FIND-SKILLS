"""Vigilante: turnos con límite de espera, trabajos pesados limitados, detección de cuelgues y respuestas 503."""
import asyncio
import threading

import pytest
from sqlalchemy.exc import OperationalError

from app import vigilante


def test_salud_sin_turno(client):
    r = client.get("/salud")
    assert r.status_code == 200 and r.json()["ok"] is True and "en_curso" in r.json()


def test_deteccion_de_cuelgue():
    v = vigilante.Vigilante(None)
    ahora = v.latido + 10
    assert v.colgado(ahora) is None
    assert "no responde" in v.colgado(v.latido + vigilante.SIN_LATIDO + 1)
    v.latido = v.ultima_fin = 1000.0
    for i in range(vigilante.MAX_EN_CURSO):
        v.en_curso[i] = ("GET", f"/api/x/{i}", 1000.0)
    assert v.colgado(1000.0 + 30) is None  # todos ocupados pero hace poco que terminó una: no es un cuelgue
    v.latido = 1000.0 + vigilante.ATASCO
    assert "turnos están ocupados" in v.colgado(1000.0 + vigilante.ATASCO + 1)
    texto = v.diagnostico("prueba")
    assert "/api/x/0" in texto and "--- hilo" in texto


def test_sin_peticiones_desde_el_arranque_no_es_un_cuelgue(monkeypatch):
    """Tras un reinicio, la primera petición llega minutos después: la vigilancia no debe tomar ese tiempo sin
    peticiones por un bucle colgado (reiniciaba el PMS a los 5 s de volver a usarlo)."""
    monkeypatch.setattr(vigilante, "INTERVALO", 0.05)
    monkeypatch.setattr(vigilante, "ACTIVO", True)
    salidas = []
    monkeypatch.setattr(vigilante.os, "_exit", lambda c: salidas.append(c))

    async def app(scope, receive, send):
        pass

    async def prueba():
        v = vigilante.Vigilante(app)
        v.latido -= 1800  # arrancó hace media hora y nadie lo ha usado
        v.ultima_fin -= 1800
        await v({"type": "http", "path": "/api/primera", "method": "GET"}, None, None)
        await asyncio.sleep(0.4)  # varias vueltas del vigilante
        return v
    v = asyncio.run(prueba())
    assert salidas == [] and v.colgado(v.latido + 1) is None


def test_sin_turno_responde_ocupado(monkeypatch):
    monkeypatch.setattr(vigilante, "ESPERA_TURNO", 0.2)
    monkeypatch.setattr(vigilante, "ACTIVO", False)
    llegadas = []

    async def app(scope, receive, send):
        llegadas.append(scope["path"])

    async def prueba():
        v = vigilante.Vigilante(app)
        v.turno = asyncio.Semaphore(0)  # sin turnos libres
        v.bucle = asyncio.get_running_loop()
        enviado = []

        async def send(m):
            enviado.append(m)
        await v({"type": "http", "path": "/api/lento", "method": "GET"}, None, send)
        return enviado
    enviado = asyncio.run(prueba())
    assert enviado[0]["status"] == 503 and llegadas == []


def test_trabajos_pesados_limitados(monkeypatch):
    monkeypatch.setattr(vigilante, "ESPERA_PESADO", 0.2)
    monkeypatch.setattr(vigilante, "_pesados", threading.BoundedSemaphore(1))
    with vigilante.trabajo_pesado("uno"):
        with pytest.raises(vigilante.Ocupado):
            with vigilante.trabajo_pesado("dos"):
                pass
    with vigilante.trabajo_pesado("tres"):  # liberado: vuelve a admitir
        pass


def test_base_de_datos_ocupada_responde_503(client, admin, monkeypatch):
    from app.routers import agenda

    def falla(*a, **k):
        raise OperationalError("SELECT 1", {}, Exception("canceling statement due to statement timeout"))
    monkeypatch.setattr(agenda, "_nombres", falla)
    r = client.get("/api/agenda", headers=admin, params={"desde": "2030-01-01", "hasta": "2030-01-31"})
    assert r.status_code == 503 and "ocupada" in r.json()["detail"]


def test_ocr_con_limite_de_tiempo(monkeypatch):
    import pytesseract

    from app import ocr_documentos

    def lento(*a, **k):
        assert k.get("timeout") == ocr_documentos.OCR_TIEMPO
        raise RuntimeError("Tesseract process timeout")
    monkeypatch.setattr(pytesseract, "image_to_string", lento)
    from PIL import Image
    assert ocr_documentos._ocr(Image.new("L", (10, 10))) == ""
