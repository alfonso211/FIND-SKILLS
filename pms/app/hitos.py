"""Hitos normativos con fecha (Verifactu, factura electrónica…): se avisan a la dirección y administración en el
panel y en el resumen diario por correo, con antelación suficiente para programar y probar los cambios del PMS."""
from dataclasses import dataclass
from datetime import date, timedelta

PERMISO = "finanzas.ver"  # dirección y administración (a nivel de grupo o de sociedad)
DIAS_TRAS_FECHA = 30  # se siguen mostrando un mes después de la fecha


@dataclass(frozen=True)
class Hito:
    clave: str
    aviso: date  # desde cuándo se avisa
    fecha: date  # fecha límite
    titulo: str
    detalle: str


HITOS = [
    Hito("verifactu_boe", date(2026, 12, 1), date(2026, 12, 31),
         "Verifactu: confirmar en el BOE el aplazamiento a octubre de 2028",
         "Hacienda anunció el 05/10/2026 que Verifactu se aplaza a octubre de 2028, junto con la factura "
         "electrónica. Si a 31/12/2026 no se ha publicado la norma, la obligación de las sociedades empieza el "
         "01/01/2027 y hay que adaptar la facturación del PMS de inmediato."),
    Hito("verifactu_desarrollo", date(2027, 12, 1), date(2028, 1, 15),
         "Verifactu y factura electrónica: iniciar la adaptación del PMS",
         "Encargar la programación: registro de facturación encadenado, código QR en las facturas, envío a la AEAT "
         "y factura electrónica entre empresas. Comprobar antes la fecha definitiva y las especificaciones "
         "técnicas vigentes."),
    Hito("verifactu_pruebas", date(2028, 4, 15), date(2028, 5, 1),
         "Verifactu: pruebas en el entorno de pruebas de la AEAT",
         "Probar el envío de registros con el certificado electrónico de cada sociedad y formar a recepción y "
         "administración. Margen hasta la obligación: 5 meses."),
    Hito("verifactu_obligatorio", date(2028, 9, 1), date(2028, 10, 1),
         "Verifactu y factura electrónica obligatorios",
         "Desde esta fecha todas las facturas del PMS deben emitirse con Verifactu."),
]


def autorizado(scope) -> bool:
    comp = scope.company_level_ids(PERMISO)
    return comp is None or bool(comp)


def activos(dia: date) -> list[Hito]:
    return [h for h in HITOS if h.aviso <= dia <= h.fecha + timedelta(days=DIAS_TRAS_FECHA)]


def para(scope, dia: date) -> list[dict]:
    if not autorizado(scope):
        return []
    return [{"clave": h.clave, "titulo": h.titulo, "detalle": h.detalle, "fecha": h.fecha.isoformat(),
             "dias": (h.fecha - dia).days} for h in activos(dia)]


def para_correo(dia: date) -> list[Hito]:
    """En el resumen diario: el primer día, cada lunes y el día de la fecha límite (no todos los días)."""
    return [h for h in activos(dia) if dia in (h.aviso, h.fecha) or dia.weekday() == 0]
