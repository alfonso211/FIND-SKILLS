"""INVERPMS. La hora del programa es siempre la de Madrid, aunque el servidor o el contenedor estén en UTC:
todas las horas que se guardan (fichajes, partes de trabajo, limpiezas, OT…) son horas de Madrid."""
import os
import time

ZONA = os.environ.get("PMS_ZONA_HORARIA") or "Europe/Madrid"


def _fichero_zona(zona: str) -> str:
    """La zona del sistema (/usr/share/zoneinfo) o, si el sistema no la tiene, la del paquete tzdata de Python."""
    if os.path.exists(os.path.join("/usr/share/zoneinfo", zona)):
        return zona
    try:
        import tzdata
        ruta = os.path.join(os.path.dirname(tzdata.__file__), "zoneinfo", *zona.split("/"))
        if os.path.exists(ruta):
            return ":" + ruta
    except ImportError:
        pass
    return zona


os.environ["TZ"] = _fichero_zona(ZONA)
if hasattr(time, "tzset"):
    time.tzset()
