"""Entorno de Alembic: usa la misma conexión y modelos que la aplicación."""
from alembic import context

from app import models  # noqa: F401  (registra las tablas en Base.metadata)
from app.database import Base, engine

target_metadata = Base.metadata


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite no admite ALTER TABLE completo: Alembic recrea la tabla copiando los datos
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


connection = context.config.attributes.get("connection")
if connection is not None:
    _run(connection)
else:
    with engine.connect() as conn:
        _run(conn)
        conn.commit()
