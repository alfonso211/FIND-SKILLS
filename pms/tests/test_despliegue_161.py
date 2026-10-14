"""El arranque del servidor (deploy/docker-compose.yml) no debe exigir PMS_ADMIN_PASSWORD: solo crea el administrador
con la base vacía y, si faltara en el .env, docker compose dejaría de funcionar (copias de seguridad incluidas)."""
from pathlib import Path

COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "docker-compose.yml"


def test_admin_password_opcional_en_compose():
    linea = next(x for x in COMPOSE.read_text().splitlines() if x.strip().startswith("PMS_ADMIN_PASSWORD:"))
    assert ":?" not in linea and "${PMS_ADMIN_PASSWORD:-}" in linea


def test_sin_admin_password_la_base_vacia_crea_administrador_provisional(tmp_path, monkeypatch):
    """Con PMS_ADMIN_PASSWORD vacía se crea el administrador con contraseña provisional (debe cambiarla al entrar)."""
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app import seed
    from app.config import settings
    from app.migraciones import migrar
    from app.models import User
    monkeypatch.setattr(settings, "admin_password", "")
    eng = create_engine(f"sqlite:///{tmp_path}/vacia.db")
    migrar(eng)
    with Session(eng) as db:
        seed.seed(db)
        u = db.scalar(select(User).where(User.email == settings.admin_email))
        assert u is not None and u.debe_cambiar_password
