"""Protección del acceso: límite de intentos por conexión, cabeceras de seguridad y aviso a la Dirección.

- Cuenta: 5 contraseñas mal en 15 min bloquean ese usuario 15 min (security.login_bloqueado). Se avisa por correo.
- Conexión (dirección IP): LIMITES[tipo] fallos en VENTANA_MIN bloquean esa conexión VENTANA_MIN minutos.
  · login: contraseñas mal desde la misma conexión, aunque se prueben usuarios distintos.
  · enlace: enlaces públicos (técnico, fichaje, revisión, ofertas, aprobaciones…) con firma mala, caducada o inexistente.
  Al bloquear se avisa por correo a PMS_SEGURIDAD_AVISOS (como mucho un aviso por conexión y hora).
- Cabeceras (PMS_CSP): la política de contenido solo deja ejecutar el código del propio PMS, así un texto malicioso
  guardado en una ficha no puede ejecutar nada ni enviar datos fuera. «informe» solo la anota en el navegador sin
  bloquear; «0» la quita (para salir del paso si una pantalla dejara de funcionar).

Los contadores van en memoria (un solo proceso): un reinicio los pone a cero.
"""
import base64
import hashlib
import logging
import re
import threading
from datetime import datetime, timedelta
from html import escape

from .config import BASE_DIR, settings

log = logging.getLogger("pms.proteccion")

VENTANA_MIN = 15
LIMITES = {"login": 20, "enlace": 30}
NOMBRES = {"login": "Inicio de sesión", "enlace": "Enlaces públicos", "cuenta": "Usuario"}
AVISOS_HORA = 10  # tope de correos de seguridad por hora (un ataque desde muchas conexiones no llena el buzón)
MAX_CLAVES = 5000  # conexiones vigiladas a la vez; por encima se descartan las más antiguas

_lock = threading.Lock()
_fallos: dict[tuple[str, str], list[datetime]] = {}
_ultimo: dict[tuple[str, str], str] = {}  # último intento (usuario probado o dirección del enlace)
_avisado: dict[tuple[str, str], datetime] = {}


def ip_de(request) -> str:
    # Caddy pone la conexión real en X-Forwarded-For y uvicorn (--proxy-headers) la deja en request.client
    return request.client.host if request.client else "desconocida"


def _vivos(clave: tuple[str, str], ahora: datetime) -> list[datetime]:
    limite = ahora - timedelta(minutes=VENTANA_MIN)
    lista = [t for t in _fallos.get(clave, []) if t > limite]
    if lista:
        _fallos[clave] = lista
    else:
        _fallos.pop(clave, None)
        _ultimo.pop(clave, None)
    return lista


def bloqueada(tipo: str, ip: str) -> bool:
    with _lock:
        return len(_vivos((tipo, ip), datetime.now())) >= LIMITES[tipo]


def fallo(tipo: str, ip: str, detalle: str = "") -> None:
    ahora = datetime.now()
    with _lock:
        if len(_fallos) >= MAX_CLAVES:
            for k in sorted(_fallos, key=lambda k: _fallos[k][-1])[:MAX_CLAVES // 10]:
                _fallos.pop(k, None)
                _ultimo.pop(k, None)
        lista = _vivos((tipo, ip), ahora)
        lista.append(ahora)
        _fallos[(tipo, ip)] = lista
        _ultimo[(tipo, ip)] = detalle[:120]
        n = len(lista)
    if n == LIMITES[tipo]:
        log.warning("Conexión %s bloqueada (%s): %d fallos en %d min", ip, tipo, n, VENTANA_MIN)
        avisar(tipo, ip, n, detalle)


def desbloquear(tipo: str, clave: str) -> bool:
    with _lock:
        _ultimo.pop((tipo, clave), None)
        return _fallos.pop((tipo, clave), None) is not None


def bloqueos() -> list[dict]:
    """Conexiones bloqueadas ahora mismo (para la pantalla de Usuarios)."""
    ahora, out = datetime.now(), []
    with _lock:
        for (tipo, ip) in list(_fallos):
            lista = _vivos((tipo, ip), ahora)
            if len(lista) >= LIMITES[tipo]:
                out.append({"tipo": tipo, "nombre": NOMBRES[tipo], "clave": ip, "intentos": len(lista),
                            "ultimo": _ultimo.get((tipo, ip), ""),
                            "hasta": (lista[-LIMITES[tipo]] + timedelta(minutes=VENTANA_MIN)).isoformat(timespec="minutes")})
    return out


def avisar(tipo: str, clave: str, intentos: int, detalle: str = "") -> None:
    """Correo a la Dirección en otro hilo (no retrasa la respuesta). Un aviso por bloqueo y hora."""
    ahora = datetime.now()
    with _lock:
        if (ahora - _avisado.get((tipo, clave), datetime.min)) < timedelta(hours=1):
            return
        if sum(1 for t in _avisado.values() if ahora - t < timedelta(hours=1)) >= AVISOS_HORA:
            return
        _avisado[(tipo, clave)] = ahora
        for k in [k for k, t in _avisado.items() if ahora - t > timedelta(hours=2)]:
            _avisado.pop(k, None)
    threading.Thread(target=_enviar, args=(tipo, clave, intentos, detalle, ahora), daemon=True,
                     name="aviso-seguridad").start()


def _enviar(tipo: str, clave: str, intentos: int, detalle: str, ahora: datetime) -> None:
    from . import avisos
    from .database import SessionLocal
    if tipo == "cuenta":
        asunto = f"Seguridad INVERPMS: usuario bloqueado por contraseñas incorrectas ({clave})"
        filas = [["Usuario", clave], ["Intentos fallidos", intentos], ["Desde la conexión", detalle or "—"]]
        que = ("Se ha bloqueado el usuario durante 15 minutos. Si no ha sido la propia persona al equivocarse, "
               "alguien está probando su contraseña: conviene cambiarla.")
    else:
        asunto = f"Seguridad INVERPMS: conexión bloqueada ({NOMBRES[tipo].lower()}) · {clave}"
        filas = [["Conexión (IP)", clave], ["Qué intentaba", NOMBRES[tipo]], ["Intentos fallidos", intentos],
                 ["Último intento", detalle or "—"]]
        que = (f"Se ha bloqueado esa conexión durante {VENTANA_MIN} minutos. Si es una oficina propia (varias personas "
               "equivocándose), se puede desbloquear en Usuarios.")
    filas.append(["Hora", f"{ahora:%d/%m/%Y %H:%M}"])
    texto = asunto + "\n\n" + "\n".join(f"{k}: {v}" for k, v in filas) + "\n\n" + que
    html = avisos._html("Aviso de seguridad", avisos._tabla(["", ""], filas) + f"<p>{escape(que)}</p>")
    try:
        with SessionLocal() as db:
            for e in settings.seguridad_avisos:
                avisos._enviar_registrado(db, None, e, f"seguridad:{tipo}:{clave}:{ahora:%Y%m%d%H%M}", "seguridad",
                                          asunto, texto, html)
            db.commit()
    except Exception:  # noqa: BLE001 — el aviso nunca debe tumbar el PMS
        log.exception("Aviso de seguridad no enviado")


# --------------------------------------------------------------------------- cabeceras de seguridad
_SCRIPT = re.compile(r"<script>(.*?)</script>", re.S)


def _hash(js: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(js.encode()).digest()).decode() + "'"


def politica(scripts_extra: tuple[str, ...] = ()) -> str:
    """Política de contenido: código solo del PMS (los <script> en línea de sus páginas van por su huella)."""
    hashes = {_hash(js) for f in sorted((BASE_DIR / "static").glob("*.html"))
              for js in _SCRIPT.findall(f.read_text(encoding="utf-8"))}
    hashes |= {_hash(js) for js in scripts_extra}
    return ("default-src 'self'; "
            f"script-src 'self' {' '.join(sorted(hashes))}; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; font-src 'self' data:; media-src 'self' blob:; "
            "connect-src 'self'; frame-src 'self' blob:; worker-src 'self' blob:; "
            "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'")


PERMISOS_NAVEGADOR = "camera=(self), geolocation=(self), microphone=(), payment=(), usb=()"
SIN_POLITICA = ("/docs", "/redoc", "/openapi.json")  # documentación de la API (usa código externo)


def cabeceras(path: str, csp: str) -> dict[str, str]:
    if settings.csp == "0" or path.startswith(SIN_POLITICA):
        return {}
    nombre = "Content-Security-Policy-Report-Only" if settings.csp == "informe" else "Content-Security-Policy"
    return {nombre: csp, "Permissions-Policy": PERMISOS_NAVEGADOR}
