"""Mantenimiento diario del PMS: comprobaciones internas y correo de avisos.

Lo lanza cada día a las 06:00 `deploy/mantenimiento.sh` (cron del servidor), que revisa además los contenedores,
el disco, las copias de seguridad, el certificado HTTPS y la seguridad del servidor.

    python -m app.mantenimiento comprobar          → una línea por comprobación: ESTADO<tab>área<tab>mensaje
    python -m app.mantenimiento correo TIPO < inf  → envía el informe (urgente | avisos | semanal)

Estados: OK, ARREGLADO (había un fallo y se ha corregido solo), AVISO (punto débil o algo que vigilar) y GRAVE
(no se ha podido corregir: se avisa con un correo urgente para resolverlo).
"""
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta
from html import escape

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from cryptography.fernet import InvalidToken
from sqlalchemy import func, select, text

from . import avisos, documentos, migraciones
from .config import BASE_DIR, settings
from .database import SessionLocal
from .models import (AccommodationContract, ContactDocument, EmailLog, LeaseDocument, ReceivedDocument, User,
                     WorkOrderAttachment)

OK, ARREGLADO, AVISO, GRAVE = "OK", "ARREGLADO", "AVISO", "GRAVE"
ORDEN = {GRAVE: 0, ARREGLADO: 1, AVISO: 2, OK: 3}
COLOR = {GRAVE: "#c0392b", ARREGLADO: "#2471a3", AVISO: "#d68910", OK: "#1e8449"}
# tablas con ficheros cifrados en la carpeta de documentos
CON_FICHERO = {"documentos recibidos": ReceivedDocument, "documentos de identidad": ContactDocument,
               "carpeta de contratos de alquiler": LeaseDocument, "contratos de alojamiento": AccommodationContract,
               "adjuntos de órdenes de trabajo": WorkOrderAttachment}
MUESTRA_DESCIFRADO = 3  # últimos ficheros de cada tabla que se descifran para comprobar la clave

Resultado = tuple[str, str, str]


# --------------------------------------------------------------------------- comprobaciones
def _base_datos(db) -> list[Resultado]:
    try:
        db.execute(text("SELECT 1"))
    except Exception as e:  # noqa: BLE001
        return [(GRAVE, "Base de datos", f"No responde: {str(e)[:200]}")]
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    cabeza = ScriptDirectory.from_config(cfg).get_current_head()
    actual = MigrationContext.configure(db.connection()).get_current_revision()
    if actual == cabeza:
        return [(OK, "Base de datos", f"Responde y está en la última versión ({actual})")]
    db.rollback()
    try:
        migraciones.migrar()
        return [(ARREGLADO, "Base de datos", f"Estaba en la versión {actual} y faltaba la {cabeza}: actualizada")]
    except Exception as e:  # noqa: BLE001
        return [(GRAVE, "Base de datos", f"Versión {actual}, falta la {cabeza} y la actualización falla: "
                                         f"{str(e)[:200]}. Hay que revisarlo antes de que alguien use esa parte.")]


def _carpeta_documentos() -> list[Resultado]:
    prueba = settings.docs_dir / ".prueba_mantenimiento"
    try:
        settings.docs_dir.mkdir(parents=True, exist_ok=True)
        prueba.write_bytes(b"ok")
        prueba.unlink()
    except OSError as e:
        return [(GRAVE, "Documentos", f"No se puede escribir en la carpeta de documentos ({e.strerror}): "
                                      "no se pueden subir facturas ni documentos")]
    return [(OK, "Documentos", "La carpeta de documentos admite escritura")]


def _ficheros(db) -> list[Resultado]:
    faltan, ilegibles, total = [], [], 0
    for nombre, modelo in CON_FICHERO.items():
        filas = db.execute(select(modelo.id, modelo.fichero).where(modelo.fichero.is_not(None))
                           .order_by(modelo.id.desc())).all()
        total += len(filas)
        perdidos = [i for i, f in filas if not (settings.docs_dir / f).is_file()]
        if perdidos:
            faltan.append(f"{nombre}: {len(perdidos)} (n.º {', '.join(map(str, sorted(perdidos)[:10]))}"
                          f"{'…' if len(perdidos) > 10 else ''})")
        for i, f in [x for x in filas if x[0] not in perdidos][:MUESTRA_DESCIFRADO]:
            try:
                documentos.leer(f)
            except (InvalidToken, OSError):
                ilegibles.append(f"{nombre} n.º {i}")
    res = []
    if faltan:
        res.append((GRAVE, "Documentos", "Faltan ficheros de documentos registrados en el PMS: " + "; ".join(faltan)
                    + ". Hay que recuperarlos de la copia de seguridad (documentos_*.tar.gz)."))
    if ilegibles:
        res.append((GRAVE, "Documentos", "No se pueden descifrar: " + ", ".join(ilegibles)
                    + ". Puede haber cambiado PMS_DOCS_KEY en el .env: no tocar nada y revisarlo."))
    if not res:
        res.append((OK, "Documentos", f"{total} documentos cifrados presentes y legibles"))
    return res


def _correo(db) -> list[Resultado]:
    if not avisos.configurado():
        return [(GRAVE, "Correo", "El correo no está configurado (PMS_SMTP_HOST): no salen los avisos ni este "
                                  "informe")]
    res = []
    if settings.smtp_host != "memoria":
        try:
            ctx = ssl.create_default_context()
            if settings.smtp_seguridad == "ssl":
                smtp = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=30, context=ctx)
            else:
                smtp = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30)
            with smtp:
                if settings.smtp_seguridad == "starttls":
                    smtp.starttls(context=ctx)
                if settings.smtp_user:
                    smtp.login(settings.smtp_user, settings.smtp_password or "")
        except Exception as e:  # noqa: BLE001
            res.append((GRAVE, "Correo", f"El servidor de correo rechaza la conexión ({str(e)[:150]}): no salen "
                                         "los avisos. Revisar usuario y contraseña SMTP en el .env."))
    fallos = db.scalar(select(func.count()).select_from(EmailLog).where(
        EmailLog.ok.is_(False), EmailLog.fecha >= datetime.now() - timedelta(days=1))) or 0
    if fallos:
        res.append((AVISO, "Correo", f"{fallos} aviso(s) por correo sin enviar en las últimas 24 h"))
    return res or [(OK, "Correo", "El servidor de correo acepta la conexión")]


def _cuelgues() -> list[Resultado]:
    carpeta = settings.docs_dir / "_diagnostico"
    hace = time.time() - 86400
    n = len([f for f in carpeta.glob("cuelgue_*.txt") if f.stat().st_mtime >= hace]) if carpeta.is_dir() else 0
    if n:
        return [(AVISO, "Estabilidad", f"El PMS se ha colgado {n} vez/veces en 24 h y se ha reiniciado solo. "
                                       "Diagnóstico en /data/documentos/_diagnostico.")]
    return [(OK, "Estabilidad", "Sin cuelgues en las últimas 24 h")]


def _usuarios(db) -> list[Resultado]:
    n = db.scalar(select(func.count()).select_from(User).where(User.activo.is_(True),
                                                                User.debe_cambiar_password.is_(True))) or 0
    if n:
        return [(AVISO, "Seguridad", f"{n} usuario(s) activo(s) siguen con la contraseña provisional: cualquiera "
                                     "que conozca su usuario puede entrar. Pedirles que la cambien o darlos de baja.")]
    return [(OK, "Seguridad", "Ningún usuario activo con contraseña provisional")]


def comprobar() -> list[Resultado]:
    res: list[Resultado] = []
    with SessionLocal() as db:
        res += _base_datos(db)
        res += _carpeta_documentos()
        res += _ficheros(db)
        res += _correo(db)
        res += _cuelgues()
        res += _usuarios(db)
    return res


# --------------------------------------------------------------------------- informe por correo
def leer_informe(lineas) -> list[Resultado]:
    res = []
    for ln in lineas:
        partes = ln.rstrip("\n").split("\t", 2)
        if len(partes) == 3 and partes[0] in ORDEN:
            res.append((partes[0], partes[1], partes[2]))
    return sorted(res, key=lambda r: ORDEN[r[0]])


def enviar_informe(res: list[Resultado], tipo: str, servidor: str = "") -> str:
    """Envía el informe a PMS_MANTENIMIENTO_EMAIL. Devuelve el asunto."""
    graves = [r for r in res if r[0] == GRAVE]
    arreglados = [r for r in res if r[0] == ARREGLADO]
    avs = [r for r in res if r[0] == AVISO]
    fecha = f"{avisos.hoy():%d/%m/%Y}"
    urgente = tipo == "urgente" and bool(graves)
    if urgente:
        asunto = f"URGENTE · INVERPMS: {len(graves)} fallo(s) grave(s) en el mantenimiento del {fecha}"
        intro = ("El mantenimiento automático de las 06:00 ha encontrado fallos que no ha podido resolver solo. "
                 "Necesitan su intervención.")
    elif tipo == "semanal":
        asunto = f"INVERPMS · Mantenimiento semanal {fecha}: " + (
            "todo correcto" if not (avs or arreglados) else f"{len(avs)} aviso(s), {len(arreglados)} arreglado(s)")
        intro = "Resumen del mantenimiento automático de hoy. El sistema se revisa todos los días a las 06:00."
    else:
        asunto = (f"INVERPMS · Mantenimiento {fecha}: {len(arreglados)} arreglado(s) automáticamente, "
                  f"{len(avs)} aviso(s)")
        intro = "El mantenimiento automático de las 06:00 ha corregido o detectado lo siguiente. No es urgente."
    revisar = [r for r in res if r[0] != OK]
    oks = [r for r in res if r[0] == OK]
    texto = "\n".join([intro, ""] + [f"[{e}] {a}: {m}" for e, a, m in revisar]
                      + ["", f"Correcto ({len(oks)}):"] + [f"  - {a}: {m}" for _, a, m in oks]
                      + (["", f"Servidor: {servidor}"] if servidor else []))
    filas = "".join(
        f'<tr><td style="padding:5px 8px;border-bottom:1px solid #eee8dc;white-space:nowrap">'
        f'<b style="color:{COLOR[e]}">{e}</b></td><td style="padding:5px 8px;border-bottom:1px solid #eee8dc;'
        f'white-space:nowrap">{escape(a)}</td><td style="padding:5px 8px;border-bottom:1px solid #eee8dc">'
        f'{escape(m)}</td></tr>' for e, a, m in revisar)
    cuerpo = (f"<p>{escape(intro)}</p>"
              + (f'<table style="border-collapse:collapse;width:100%;font-size:13px">{filas}</table>' if filas else "")
              + f'<p style="margin-top:16px"><b>Correcto ({len(oks)}):</b></p><ul style="font-size:13px;color:#555">'
              + "".join(f"<li>{escape(a)}: {escape(m)}</li>" for _, a, m in oks) + "</ul>"
              + (f'<p style="color:#8d877b;font-size:12px">Servidor: {escape(servidor)}</p>' if servidor else ""))
    titulo = "Fallos graves: se necesita su intervención" if urgente else "Mantenimiento diario"
    avisos.enviar(settings.mantenimiento_email, asunto, texto, avisos._html(titulo, cuerpo), urgente=urgente)
    with SessionLocal() as db:
        db.add(EmailLog(clave=f"mantenimiento:{avisos.hoy()}:{tipo}", tipo="mantenimiento",
                        destinatario=settings.mantenimiento_email, asunto=asunto[:200], ok=True))
        db.commit()
    return asunto


def main(argv: list[str]) -> int:
    orden = argv[1] if len(argv) > 1 else "comprobar"
    if orden == "comprobar":
        try:
            res = comprobar()
        except Exception as e:  # noqa: BLE001 — que el informe salga aunque falle una comprobación
            res = [(GRAVE, "PMS", f"Las comprobaciones internas fallan: {str(e)[:200]}")]
        for e, a, m in res:
            print(f"{e}\t{a}\t{m.replace(chr(10), ' ')}")
        return 0
    if orden == "correo":
        tipo = argv[2] if len(argv) > 2 else "avisos"
        servidor = argv[3] if len(argv) > 3 else ""
        try:
            print(enviar_informe(leer_informe(sys.stdin), tipo, servidor))
        except Exception as e:  # noqa: BLE001
            print(f"No se pudo enviar el correo: {e}", file=sys.stderr)
            return 1
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
