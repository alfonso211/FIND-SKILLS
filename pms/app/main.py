from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR
from .database import SessionLocal
from .migraciones import migrar
from .routers import admin, alquiler, auth, documentos, estructura, mantenimiento, panel, turistico
from .seed import seed

STATIC = BASE_DIR / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrar()
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="PMS Grupo INVERSIETE", version="0.1.0", lifespan=lifespan)
for r in (auth, estructura, alquiler, turistico, mantenimiento, admin, panel, documentos):
    app.include_router(r.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
