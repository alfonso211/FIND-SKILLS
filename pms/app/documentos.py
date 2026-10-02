"""Almacén cifrado de copias de documentos de identidad (Fernet: AES-128-CBC + HMAC-SHA256)."""
import base64
import hashlib
import uuid

from cryptography.fernet import Fernet

from .config import settings


def _fernet() -> Fernet:
    clave = settings.docs_key
    if not clave:  # derivada de la clave de sesiones (instalaciones sin PMS_DOCS_KEY)
        clave = base64.urlsafe_b64encode(hashlib.sha256(b"pms-documentos:" + settings.secret_key.encode()).digest())
    return Fernet(clave)


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
