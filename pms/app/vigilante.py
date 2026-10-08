"""Vigilante del PMS: turnos de la API, trabajos pesados limitados y reinicio automático si se cuelga.

- Turnos: como mucho MAX_EN_CURSO peticiones a la API a la vez (por debajo del pool de conexiones y de los hilos).
  Quien no consigue turno en ESPERA_TURNO segundos recibe «servidor ocupado» (503) en vez de esperar para siempre.
- Trabajos pesados (OCR de documentos y conversión de contratos con LibreOffice): como mucho PESADOS_A_LA_VEZ;
  varios a la vez agotan la memoria y la CPU del servidor y lo dejan todo parado.
- Vigilancia: un hilo comprueba cada pocos segundos que el bucle de peticiones responde y que las peticiones
  terminan. Si el PMS está colgado, deja el diagnóstico (qué peticiones había y dónde estaba cada hilo) en el
  registro y en un fichero, y termina el proceso: Docker lo arranca de nuevo en segundos (restart: unless-stopped).
"""
import asyncio
import json
import logging
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime

from .config import settings

log = logging.getLogger("pms.vigilante")

MAX_EN_CURSO = 16
ESPERA_TURNO = 45  # s esperando turno antes de responder «ocupado»
LENTA = 15  # s: se anota en el registro como petición lenta
SIN_LATIDO = 60  # s sin que el bucle de peticiones responda -> colgado
ATASCO = 150  # s con todos los turnos ocupados y ninguna petición terminada -> colgado
INTERVALO = 5  # s entre comprobaciones
PESADOS_A_LA_VEZ = 2
ESPERA_PESADO = 90
ACTIVO = (os.environ.get("PMS_VIGILANTE") or "1") != "0"

_pesados = threading.BoundedSemaphore(PESADOS_A_LA_VEZ)


class Ocupado(Exception):
    """El servidor está al límite: se responde 503 y el usuario lo reintenta en unos segundos."""


@contextmanager
def trabajo_pesado(que: str):
    if not _pesados.acquire(timeout=ESPERA_PESADO):
        raise Ocupado(f"Hay otros documentos procesándose ({que}). Reintente en unos segundos.")
    t0 = time.monotonic()
    try:
        yield
    finally:
        _pesados.release()
        dur = time.monotonic() - t0
        if dur > LENTA:
            log.warning("Trabajo pesado lento: %s %.1f s", que, dur)


async def _responder(send, status: int, datos: dict) -> None:
    cuerpo = json.dumps(datos).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
                            (b"content-length", str(len(cuerpo)).encode())]})
    await send({"type": "http.response.body", "body": cuerpo})


class Vigilante:
    """Middleware ASGI (sustituye al antiguo límite de peticiones) + hilo de vigilancia."""

    def __init__(self, app):
        self.app = app
        self.turno: asyncio.Semaphore | None = None
        self.bucle: asyncio.AbstractEventLoop | None = None
        self.en_curso: dict[int, tuple[str, str, float]] = {}
        self.esperando = 0
        self.ultima_fin = time.monotonic()
        self.latido = time.monotonic()
        self._n = 0

    # ----------------------------------------------------------------- peticiones
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        if scope["path"] == "/salud":  # sin turno ni base de datos: responde aunque la API esté saturada
            return await _responder(send, 200, self.estado())
        if not scope["path"].startswith("/api/"):
            return await self.app(scope, receive, send)
        if self.turno is None:  # se crea dentro del bucle de eventos que atiende las peticiones
            self.turno = asyncio.Semaphore(MAX_EN_CURSO)
            self.bucle = asyncio.get_running_loop()
            # la vigilancia empieza ahora (con la primera petición), no al arrancar el proceso: si no, el tiempo
            # sin peticiones desde el arranque se tomaba por un bucle colgado y se reiniciaba el PMS sin motivo
            self.latido = self.ultima_fin = time.monotonic()
            if ACTIVO:
                threading.Thread(target=self._vigilar, name="vigilante", daemon=True).start()
        self.esperando += 1
        try:
            await asyncio.wait_for(self.turno.acquire(), ESPERA_TURNO)
        except TimeoutError:
            log.warning("Sin turno en %d s: %s %s (en curso %d)", ESPERA_TURNO, scope["method"], scope["path"],
                        len(self.en_curso))
            return await _responder(send, 503, {"detail": "El servidor está muy ocupado en este momento. "
                                                          "Reintente en unos segundos."})
        finally:
            self.esperando -= 1
        self._n += 1
        clave, t0 = self._n, time.monotonic()
        self.en_curso[clave] = (scope["method"], scope["path"], t0)
        try:
            await self.app(scope, receive, send)
        finally:
            self.turno.release()
            del self.en_curso[clave]
            self.ultima_fin = time.monotonic()
            if self.ultima_fin - t0 > LENTA:
                log.warning("Petición lenta: %s %s %.1f s", scope["method"], scope["path"], self.ultima_fin - t0)

    def estado(self) -> dict:
        ahora = time.monotonic()
        mas_antigua = max((ahora - t for _, _, t in self.en_curso.values()), default=0)
        return {"ok": True, "en_curso": len(self.en_curso), "esperando": self.esperando,
                "mas_antigua_s": round(mas_antigua, 1)}

    # ----------------------------------------------------------------- vigilancia
    def _latir(self) -> None:
        self.latido = time.monotonic()

    def colgado(self, ahora: float | None = None) -> str | None:
        ahora = ahora or time.monotonic()
        if ahora - self.latido > SIN_LATIDO:
            return f"el bucle de peticiones no responde desde hace {ahora - self.latido:.0f} s"
        if len(self.en_curso) >= MAX_EN_CURSO and ahora - self.ultima_fin > ATASCO:
            return (f"los {MAX_EN_CURSO} turnos están ocupados y no termina ninguna petición desde hace "
                    f"{ahora - self.ultima_fin:.0f} s")
        return None

    def diagnostico(self, motivo: str) -> str:
        ahora = time.monotonic()
        lineas = [f"PMS COLGADO {datetime.now():%d/%m/%Y %H:%M:%S}: {motivo}",
                  f"Peticiones en curso ({len(self.en_curso)}), esperando turno: {self.esperando}"]
        for m, p, t in sorted(self.en_curso.values(), key=lambda x: x[2]):
            lineas.append(f"  {ahora - t:7.1f} s  {m} {p}")
        nombres = {t.ident: t.name for t in threading.enumerate()}
        for ident, marco in sys._current_frames().items():
            pila = "".join(traceback.format_stack(marco)[-8:])
            lineas.append(f"\n--- hilo {nombres.get(ident, ident)} ---\n{pila}")
        return "\n".join(lineas)

    def _vigilar(self) -> None:
        while True:
            try:  # se pide el latido y se comprueba después de dar tiempo a que el bucle lo atienda
                self.bucle.call_soon_threadsafe(self._latir)
            except RuntimeError:  # el bucle se ha cerrado: el proceso está terminando
                return
            time.sleep(INTERVALO)
            motivo = self.colgado()
            if not motivo:
                continue
            texto = self.diagnostico(motivo)
            log.critical(texto)
            try:
                carpeta = settings.docs_dir / "_diagnostico"
                carpeta.mkdir(parents=True, exist_ok=True)
                (carpeta / f"cuelgue_{datetime.now():%Y%m%d_%H%M%S}.txt").write_text(texto, encoding="utf-8")
                for viejo in sorted(carpeta.glob("cuelgue_*.txt"))[:-30]:
                    viejo.unlink()
            except OSError:
                pass
            sys.stderr.write(texto + "\nReiniciando el PMS…\n")
            sys.stderr.flush()
            os._exit(3)  # Docker vuelve a arrancar el contenedor
