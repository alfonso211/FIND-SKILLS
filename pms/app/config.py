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


settings = Settings()
