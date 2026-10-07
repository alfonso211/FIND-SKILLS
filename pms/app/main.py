import hashlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from . import avisos, vigilante
from .config import BASE_DIR
from .database import SessionLocal
from .migraciones import migrar
from .routers import (admin, agenda, alquiler, auth, buscar, documentos, estructura, expedientes, exportacion, facturas,
                      garajes, gastos, historico, informes, mantenimiento, manual, panel, personal, plano, presidencia,
                      proveedores, turistico)
from .routers import limpieza
from .seed import seed

STATIC = BASE_DIR / "static"
log = logging.getLogger("pms")

# Versión de la interfaz: huella de sus ficheros. Cambia con cada actualización del programa; el navegador
# descarga entonces los ficheros nuevos (van con ?v=) y las pestañas abiertas se recargan solas.
VERSION = hashlib.sha256(b"".join((STATIC / f).read_bytes()
                                  for f in ("app.js", "styles.css", "index.html"))).hexdigest()[:12]


@asynccontextmanager
async def lifespan(_: FastAPI):
    migrar()
    with SessionLocal() as db:
        seed(db)
    avisos.arrancar_programador()
    yield


app = FastAPI(title="INVERPMS", version="0.1.0", lifespan=lifespan)
for r in (auth, estructura, alquiler, garajes, gastos, turistico, plano, facturas, mantenimiento, personal, proveedores,
          informes, admin, panel, documentos, buscar, agenda, expedientes, historico, exportacion, manual, presidencia,
          limpieza):
    app.include_router(r.router)
app.include_router(facturas.router_servicios)
app.include_router(turistico.publico)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(vigilante.Ocupado)
async def ocupado(_: Request, exc: vigilante.Ocupado):
    return JSONResponse({"detail": str(exc)}, status_code=503)


@app.exception_handler(OperationalError)
async def base_ocupada(request: Request, exc: OperationalError):
    # Consulta cancelada por tiempo (statement_timeout / lock_timeout) o conexión perdida: se responde en vez de
    # dejar la petición colgada, y se anota para saber qué la provocó
    log.warning("Base de datos: %s %s -> %s", request.method, request.url.path, (str(exc.orig or exc).splitlines() or [""])[0])
    return JSONResponse({"detail": "La base de datos está ocupada en este momento. Reintente en unos segundos."},
                        status_code=503)


app.add_middleware(vigilante.Vigilante)


@app.middleware("http")
async def version_interfaz(request: Request, call_next):
    resp = await call_next(request)
    if request.url.path.startswith("/api/"):
        resp.headers["X-PMS-Version"] = VERSION
    return resp


@app.get("/", include_in_schema=False)
def index():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = (html.replace('/static/app.js"', f'/static/app.js?v={VERSION}"')
                .replace('/static/styles.css"', f'/static/styles.css?v={VERSION}"')
                .replace("</head>", f'  <script>window.PMS_VERSION = "{VERSION}";</script>\n</head>'))
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
