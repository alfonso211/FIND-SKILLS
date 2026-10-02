"""Actualización automática del esquema de base de datos al arrancar (Alembic)."""
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from .config import BASE_DIR
from .database import engine as engine_app

# Migración que corresponde al esquema con el que se puso en marcha el PMS (creado sin Alembic)
REVISION_BASE = "0001"


def _config(connection) -> Config:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    cfg.attributes["connection"] = connection
    return cfg


def migrar(engine: Engine | None = None) -> None:
    """Deja la base de datos en la última versión sin perder datos.
    - Base vacía: crea todas las tablas.
    - Base creada antes de existir las migraciones: se marca como versión inicial y se actualiza desde ahí.
    - Base ya migrada: aplica solo las migraciones pendientes.
    """
    eng = engine or engine_app
    with eng.begin() as conn:
        tablas = set(inspect(conn).get_table_names())
        cfg = _config(conn)
        if tablas and "alembic_version" not in tablas:
            command.stamp(cfg, REVISION_BASE)
        command.upgrade(cfg, "head")
