"""Almacén cifrado de copias de documentos de identidad (Fernet: AES-128-CBC + HMAC-SHA256)."""
import base64
import hashlib
import uuid

from cryptography.fernet import Fernet, MultiFernet

from .config import settings


def clave_actual() -> bytes | str:
    clave = settings.docs_key
    if not clave:  # derivada de la clave de sesiones (instalaciones sin PMS_DOCS_KEY)
        clave = base64.urlsafe_b64encode(hashlib.sha256(b"pms-documentos:" + settings.secret_key.encode()).digest())
    return clave


def _fernet() -> Fernet | MultiFernet:
    """Cifra siempre con la clave actual. Durante un cambio de clave (PMS_DOCS_KEY_ANTERIOR) lee con las dos."""
    if settings.docs_key_anterior:
        return MultiFernet([Fernet(clave_actual()), Fernet(settings.docs_key_anterior)])
    return Fernet(clave_actual())


def guardar(datos: bytes) -> str:
    settings.docs_dir.mkdir(parents=True, exist_ok=True)
    nombre = f"{uuid.uuid4().hex}.bin"
    (settings.docs_dir / nombre).write_bytes(_fernet().encrypt(datos))
    return nombre


def leer(nombre: str) -> bytes:
    return _fernet().decrypt((settings.docs_dir / nombre).read_bytes())


def borrar(nombre: str) -> None:
    (settings.docs_dir / nombre).unlink(missing_ok=True)


def huella(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()
