"""Tarifas estándar de los apartamentos turísticos según el número de noches (IVA incluido).

    Tipo                       1-6 noches   7-13 (-10 %)   14-29 (-19 %)   30 noches (precio de la estancia)
    Estudio                    50,00        45,00          40,50           950
    Apartamento 1 dormitorio   55,00        49,50          44,55           1.100
    Apartamento 2 dormitorios  75,00        67,50          60,75           1.400

Más de 30 noches: el precio de 30 noches proporcional a las noches (p. ej. 31 noches = 950 / 30 x 31).
Es el precio que propone el PMS al reservar; recepción puede cambiarlo y siempre debe aceptarlo.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

TIPOS = {
    "estudio": {"nombre": "Estudio", "noche": Decimal("50"), "mes": Decimal("950")},
    "1d": {"nombre": "Apartamento 1 dormitorio", "noche": Decimal("55"), "mes": Decimal("1100")},
    "2d": {"nombre": "Apartamento 2 dormitorios", "noche": Decimal("75"), "mes": Decimal("1400")},
}
# (desde, hasta, descuento sobre la tarifa base, texto)
TRAMOS = [(1, 6, Decimal("0"), "1 a 6 noches"), (7, 13, Decimal("0.10"), "7 a 13 noches (-10 %)"),
          (14, 29, Decimal("0.19"), "14 a 29 noches (-19 %)")]
NOCHES_MES = 30
_C = Decimal("0.01")


def tipo_de(dormitorios: int | None, tipologia: str | None = None, uso: str | None = None) -> str | None:
    """Estudio, 1 o 2 dormitorios (3 o más se tarifican como 2). Garajes y unidades sin dato: sin tarifa."""
    if uso == "garaje":
        return None
    if dormitorios is None and tipologia:
        t = tipologia.lower()
        dormitorios = 0 if "estudio" in t else 2 if "2 dorm" in t else 1 if "1 dorm" in t else None
    if dormitorios is None:
        return None
    return "estudio" if dormitorios <= 0 else "1d" if dormitorios == 1 else "2d"


def calcular(tipo: str | None, entrada: date, salida: date) -> dict | None:
    """{tipo, nombre, noches, tramo, por_noche, total} o None si la unidad no tiene tarifa estándar."""
    t = TIPOS.get(tipo or "")
    noches = (salida - entrada).days
    if not t or noches < 1:
        return None
    if noches >= NOCHES_MES:
        total = (t["mes"] * noches / NOCHES_MES).quantize(_C, ROUND_HALF_UP)
        tramo = f"{NOCHES_MES} noches: precio de la estancia" if noches == NOCHES_MES else \
            f"Más de {NOCHES_MES} noches: precio de {NOCHES_MES} noches proporcional"
        por_noche = (total / noches).quantize(_C, ROUND_HALF_UP)
    else:
        _, _, dto, tramo = next(x for x in TRAMOS if x[0] <= noches <= x[1])
        por_noche = (t["noche"] * (1 - dto)).quantize(_C, ROUND_HALF_UP)
        total = por_noche * noches
    return {"tipo": tipo, "nombre": t["nombre"], "noches": noches, "tramo": tramo,
            "por_noche": float(por_noche), "total": float(total)}


def de_unidad(u, entrada: date, salida: date) -> dict | None:
    return calcular(tipo_de(u.dormitorios, u.tipologia, u.uso), entrada, salida)
