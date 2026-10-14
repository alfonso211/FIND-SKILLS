"""Corrección de las horas guardadas en UTC (antes de la versión 1.49 el contenedor no tenía la zona de Madrid).

Hasta que se instaló la zona horaria en el servidor, el programa guardaba la hora UTC: en verano 2 horas menos y en
invierno 1 hora menos que la hora real de Madrid. Este programa pasa esas horas a hora de Madrid, solo en los registros
anteriores al momento en que el servidor empezó a ir en hora (`--hasta`).

    python -m app.corregir_hora --hasta "2026-10-13 14:51"            → solo enseña lo que cambiaría (no toca nada)
    python -m app.corregir_hora --hasta "2026-10-13 14:51" --aplicar  → lo corrige (una sola vez)

No se tocan los fichajes corregidos o anotados a mano (ya tienen la hora buena) ni los partes ya validados (se reabren y se
validan de nuevo para que salgan con la hora corregida). Hacer antes la copia de seguridad (backup.sh).
"""
import argparse
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .database import SessionLocal
from .models import CleaningTask, EmailLog, TimeEntry, WorkEntry, WorkOrder, WorkReport

MADRID = ZoneInfo("Europe/Madrid")
MARCA = "correccion_hora_utc"
# (modelo, columnas, condición extra, descripción)
TABLAS = [
    (TimeEntry, ("entrada", "salida"), lambda m: m.editado_en.is_(None) & (m.origen != "manual"),
     "Fichajes (registro de jornada)"),
    (WorkEntry, ("creada",), None, "Actuaciones anotadas en los partes de trabajo"),
    (CleaningTask, ("hecha",), None, "Limpiezas hechas"),
    (WorkOrder, ("conf_mto_fecha", "conf_limpieza_fecha"), None, "Órdenes de trabajo: confirmaciones"),
]


def a_madrid(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc).astimezone(MADRID).replace(tzinfo=None)


def revisar(db, hasta: datetime, aplicar: bool) -> dict:
    out = {}
    for modelo, cols, extra, nombre in TABLAS:
        q = select(modelo)
        if extra is not None:
            q = q.where(extra(modelo))
        n, ejemplos = 0, []
        for obj in db.scalars(q):
            cambiado = False
            for c in cols:
                v = getattr(obj, c)
                if v is not None and v < hasta:
                    nuevo = a_madrid(v)
                    if len(ejemplos) < 3:
                        ejemplos.append(f"{modelo.__tablename__} {obj.id} · {c}: {v:%d/%m/%Y %H:%M} → {nuevo:%d/%m/%Y %H:%M}")
                    if aplicar:
                        setattr(obj, c, nuevo)
                    cambiado = True
            n += cambiado
        out[nombre] = {"registros": n, "ejemplos": ejemplos}
    out["Fichajes corregidos o anotados a mano (no se tocan)"] = {"registros": len(list(db.scalars(
        select(TimeEntry.id).where(TimeEntry.editado_en.is_not(None) | (TimeEntry.origen == "manual"),
                                   TimeEntry.entrada < hasta)))), "ejemplos": []}
    out["Partes de trabajo validados antes (reabrir y validar de nuevo)"] = {"registros": len(list(db.scalars(
        select(WorkReport.id).where(WorkReport.estado == "validado", WorkReport.validado_en < hasta)))), "ejemplos": []}
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--hasta", required=True, help="Fecha y hora (de Madrid) desde la que el servidor ya va en hora")
    p.add_argument("--aplicar", action="store_true", help="Corregir (sin esto solo se enseña)")
    a = p.parse_args(argv)
    hasta = datetime.strptime(a.hasta, "%Y-%m-%d %H:%M")
    with SessionLocal() as db:
        if db.scalar(select(EmailLog.id).where(EmailLog.clave == MARCA)):
            print("La corrección ya se aplicó una vez: no se repite.")
            return 1
        res = revisar(db, hasta, a.aplicar)
        for nombre, x in res.items():
            print(f"{nombre}: {x['registros']}")
            for e in x["ejemplos"]:
                print(f"    {e}")
        if a.aplicar:
            db.add(EmailLog(clave=MARCA, tipo="sistema", asunto=f"Horas UTC pasadas a Madrid (hasta {a.hasta})"))
            db.commit()
            print("Corrección aplicada.")
        else:
            print("No se ha cambiado nada. Para corregir, repita con --aplicar.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
