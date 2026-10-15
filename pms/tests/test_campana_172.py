"""1.72: la campana lleva al asunto. Cada tipo de aviso tiene una pantalla que existe en el menú y los que se refieren
a un registro concreto llevan su id (OT, parte de estado, gasto); las listas aceptan ?id= para mostrar solo ese."""
import re
from pathlib import Path

from sqlalchemy import select

from app import avisos
from app.database import SessionLocal
from app.models import Notificacion, User

APP = Path(__file__).resolve().parent.parent / "static" / "app.js"


def _vistas_menu() -> set[str]:
    js = APP.read_text(encoding="utf-8")
    menu = js[js.index("const MENU = ["):js.index("];", js.index("const MENU = ["))]
    return set(re.findall(r'\["(\w+)", "[^"]+", ', menu))


def test_cada_tipo_lleva_a_una_pantalla_que_existe():
    vistas = _vistas_menu()
    assert {"ordenes", "estado", "gastos", "agenda", "usuarios", "gestion"} <= vistas
    for tipo, vista in avisos.VISTA_AVISO.items():
        assert vista.split("?")[0] in vistas, f"{tipo} → {vista} no está en el menú"
    # todos los tipos que pueden sonar en la campana tienen destino (si no, irían al panel sin explicación)
    usados = set()
    for f in (Path(avisos.__file__).parent).rglob("*.py"):
        txt = f.read_text(encoding="utf-8")
        usados |= set(re.findall(r'_enviar_registrado\([^)]*?"(\w+)",\s*(?:asunto|f"|titulo)', txt, re.S))
        usados |= set(re.findall(r'notificar\(db, \w+, None, "(\w+)"', txt))
    usados.discard("chat_mencion")  # lleva su propia vista: la conversación («chat:<id>»)
    assert {"ot_urgente", "parte_estado", "pagos_retenidos", "seguridad", "caja"} <= usados  # la búsqueda funciona
    sin = {t for t in usados if t not in avisos.VISTA_AVISO and t not in avisos.SIN_CAMPANA}
    assert not sin, f"Tipos de aviso sin pantalla: {sin}"


def test_aviso_de_ot_lleva_a_esa_orden(client, admin, ids):
    sfl = ids["assets"]["SFL"]["id"]
    w = client.post("/api/mantenimiento/ordenes", headers=admin, json={
        "asset_id": sfl, "titulo": "ZZ-PRUEBA campana", "prioridad": "media"}).json()
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == "admin@inversiete.com"))
        avisos.notificar(db, u, None, "ot_urgente", "ZZ-PRUEBA aviso", vista=f"ordenes?id={w['id']}")
        db.commit()
    n = next(x for x in client.get("/api/notificaciones", headers=admin).json() if x["titulo"] == "ZZ-PRUEBA aviso")
    assert n["vista"] == f"ordenes?id={w['id']}"
    # la lista con ?id= devuelve solo esa orden, aunque no esté entre las abiertas ni sea del activo elegido
    r = client.get(f"/api/mantenimiento/ordenes?id={w['id']}&abiertas=true&asset_id=999999", headers=admin).json()
    assert [x["id"] for x in r] == [w["id"]]
    assert client.get("/api/partes-estado?id=999999", headers=admin).json() == []
    assert client.get("/api/gastos?id=999999", headers=admin).json()["gastos"] == []
    with SessionLocal() as db:
        for x in db.scalars(select(Notificacion).where(Notificacion.titulo.like("ZZ-PRUEBA%"))):
            db.delete(x)
        db.commit()
