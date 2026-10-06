from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

if settings.database_url.startswith("sqlite"):
    engine = create_engine(settings.database_url, connect_args={"check_same_thread": False})
else:
    # Postgres: margen para los picos (el panel pide varias cosas a la vez por usuario), conexiones comprobadas
    # antes de usarlas y renovadas cada 30 min
    engine = create_engine(settings.database_url, pool_size=20, max_overflow=30, pool_timeout=60,
                           pool_pre_ping=True, pool_recycle=1800)
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
