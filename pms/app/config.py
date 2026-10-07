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


settings = Settings()
