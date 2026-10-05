"""El esquema que generan las migraciones debe coincidir con los modelos, y una base de datos
existente (creada antes de las migraciones) debe adoptarse sin perder datos."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text

from app.database import Base
from alembic import command

from app.migraciones import REVISION_BASE, _config, migrar


def _diferencias(engine):
    with engine.connect() as conn:
        return compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)


def test_modelos_sin_migracion_pendiente(client):
    """Si falla: se ha cambiado app/models.py sin crear la migración (alembic revision --autogenerate)."""
    from app.database import engine
    assert _diferencias(engine) == []


def test_base_vacia(tmp_path):
    eng = create_engine(f"sqlite:///{tmp_path}/nueva.db")
    migrar(eng)
    assert _diferencias(eng) == []
    with eng.connect() as c:
        assert c.execute(text("select version_num from alembic_version")).scalar()


def test_base_existente_se_conserva(tmp_path):
    """Simula la base de producción creada con create_all y con datos."""
    eng = create_engine(f"sqlite:///{tmp_path}/prod.db")
    with eng.begin() as conn:  # esquema de la versión 1, tal como lo creó create_all en producción
        command.upgrade(_config(conn), REVISION_BASE)
        conn.exec_driver_sql("DROP TABLE alembic_version")
    with eng.begin() as c:
        c.execute(text("insert into sociedades (nombre, activa) values ('INVERSIETE SA', 1)"))
    migrar(eng)
    migrar(eng)  # repetir no hace nada
    with eng.connect() as c:
        # la migración 0010 completa la razón social oficial, el CIF y el domicilio fiscal
        assert c.execute(text("select nombre, cif, direccion, cp from sociedades")).all() == [
            ("INVERSIETE S.A.", "A78072915", "C/ Campezo 8", "28022")]
        assert c.execute(text("select count(*) from alembic_version")).scalar() == 1
    assert _diferencias(eng) == []
