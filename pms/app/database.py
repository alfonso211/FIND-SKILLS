from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

if settings.database_url.startswith("sqlite"):
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
else:
    # Postgres: margen para los picos (el panel pide varias cosas a la vez por usuario), conexiones comprobadas
    # antes de usarlas y renovadas cada 30 min. Ninguna espera es infinita: una consulta se cancela a los 90 s,
    # esperar un bloqueo de fila (p. ej. la numeración de facturas) a los 20 s, y una transacción abierta y
    # olvidada se cierra a los 10 min. Así una petición atascada no arrastra a las demás.
    engine = create_engine(settings.database_url, pool_size=20, max_overflow=30, pool_timeout=30,
                           pool_pre_ping=True, pool_recycle=1800,
                           connect_args={"options": "-c statement_timeout=90000 -c lock_timeout=20000 "
                                                    "-c idle_in_transaction_session_timeout=600000"})
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    def to_dict(self, exclude: tuple[str, ...] = ()) -> dict:
        out = {}
        for col in self.__table__.columns:
            if col.name in exclude:
                continue
            val = getattr(self, col.name)
            if isinstance(val, Decimal):
                val = float(val)
            elif isinstance(val, (date, datetime)):
                val = val.isoformat()
            out[col.name] = val
        return out


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
