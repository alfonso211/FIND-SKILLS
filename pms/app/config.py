"""Configuración por variables de entorno."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _secret_key() -> str:
    key = os.environ.get("PMS_SECRET_KEY")
    if key:
        return key
    path = BASE_DIR / ".secret_key"
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key)
    path.chmod(0o600)
    return key


class Settings:
    database_url: str = os.environ.get("PMS_DATABASE_URL", f"sqlite:///{BASE_DIR / 'pms.db'}")
    secret_key: str = _secret_key()
    token_hours: int = int(os.environ.get("PMS_TOKEN_HOURS", "12"))
    admin_email: str = os.environ.get("PMS_ADMIN_EMAIL", "admin@inversiete.com")
    admin_password: str | None = os.environ.get("PMS_ADMIN_PASSWORD")
    # Copias de documentos de identidad (cifradas). Sin PMS_DOCS_KEY se deriva de PMS_SECRET_KEY.
    docs_dir: Path = Path(os.environ.get("PMS_DOCS_DIR", str(BASE_DIR / "documentos")))
    docs_key: str | None = os.environ.get("PMS_DOCS_KEY") or None
    # Avisos por correo. Sin PMS_SMTP_HOST no se envía nada ("memoria" = solo pruebas automáticas).
    smtp_host: str | None = os.environ.get("PMS_SMTP_HOST") or None
    smtp_port: int = int(os.environ.get("PMS_SMTP_PORT") or "587")
    smtp_user: str | None = os.environ.get("PMS_SMTP_USER") or None
    smtp_password: str | None = os.environ.get("PMS_SMTP_PASSWORD") or None
    smtp_from: str | None = os.environ.get("PMS_SMTP_FROM") or None
    smtp_seguridad: str = (os.environ.get("PMS_SMTP_SEGURIDAD") or "starttls").lower()  # starttls | ssl | ninguna
    avisos_hora: str = os.environ.get("PMS_AVISOS_HORA") or "07:30"  # hora del resumen diario
    avisos_auto: bool = (os.environ.get("PMS_AVISOS_AUTO") or "1") != "0"
    url: str = (os.environ.get("PMS_URL") or "").rstrip("/")  # enlace en los correos (https://pms.inversiete.es)
    # Mantenimiento diario (deploy/mantenimiento.sh): a quién se avisa si hay un fallo grave
    mantenimiento_email: str = os.environ.get("PMS_MANTENIMIENTO_EMAIL") or "alfonso@inversiete.es"
    # Únicas cuentas que pueden borrar usuarios (además del administrador inicial, PMS_ADMIN_EMAIL)
    borrar_usuarios: tuple[str, ...] = tuple(
        e.strip().lower() for e in (os.environ.get("PMS_BORRAR_USUARIOS") or "alfonso@inversiete.es,admin@inversiete.es")
        .split(",") if e.strip())
    # CAPEX: adjudicaciones por encima del umbral (sin IVA) las aprueba la Dirección General por correo
    capex_aprobadores: tuple[str, ...] = tuple(
        e.strip().lower() for e in (os.environ.get("PMS_CAPEX_APROBADORES") or "barbara@inversiete.es").split(",")
        if e.strip())
    capex_umbral: float = float(os.environ.get("PMS_CAPEX_UMBRAL") or 30000)
    # Calendario de vacaciones: los cambios se agrupan y se envían juntos cada N horas (en horario de 8 a 20)
    vacaciones_envio_horas: float = float(os.environ.get("PMS_VACACIONES_ENVIO_HORAS") or 3)
    # Botón «Gestión» (INVERGESTION): solo el superadministrador y estas cuentas
    gestion_usuarios: tuple[str, ...] = tuple(
        e.strip().lower() for e in (os.environ.get("PMS_GESTION_USUARIOS") or "alfonso@inversiete.es,barbara@inversiete.es")
        .split(",") if e.strip())
    # Devolución de fianzas por transferencia: aviso por correo y WhatsApp a la Dirección para hacerla
    fianza_avisos: tuple[str, ...] = tuple(
        e.strip().lower() for e in (os.environ.get("PMS_FIANZA_AVISOS") or "barbara@inversiete.es,alfonso@inversiete.es")
        .split(",") if e.strip())

    # Informe diario de dirección (ocupación, ADR, RevPAR, cobros pendientes, fianzas por transferir…) a primera hora
    informe_direccion: tuple[str, ...] = tuple(
        e.strip().lower() for e in (os.environ.get("PMS_INFORME_DIRECCION") or "barbara@inversiete.es,alfonso@inversiete.es")
        .split(",") if e.strip())
    # Mensaje al cliente la víspera de la llegada (documentos para el registro de viajeros, hora de entrada, fianza)
    aviso_llegada: bool = (os.environ.get("PMS_AVISO_LLEGADA") or "1") != "0"
    # Preventivo: el programador genera solo las OT que vencen en los próximos días
    preventivo_auto: bool = (os.environ.get("PMS_PREVENTIVO_AUTO") or "1") != "0"
    # Seguridad: a quién se avisa de usuarios y conexiones bloqueados por intentos fallidos
    seguridad_avisos: tuple[str, ...] = tuple(
        e.strip().lower() for e in (os.environ.get("PMS_SEGURIDAD_AVISOS") or mantenimiento_email).split(",")
        if e.strip())
    # Política de contenido del navegador: 1 (aplicada), informe (solo la anota) o 0 (sin ella)
    csp: str = (os.environ.get("PMS_CSP") or "1").strip().lower()


settings = Settings()
