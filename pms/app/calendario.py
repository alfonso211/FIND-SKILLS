"""Días laborables (lunes a viernes sin festivos nacionales ni de la Comunidad de Madrid, donde están los activos)."""
from datetime import date, timedelta


def pascua(anio: int) -> date:
    """Domingo de Pascua (algoritmo anónimo gregoriano)."""
    a, b, c = anio % 19, anio // 100, anio % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    lv = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lv) // 451
    mes = (h + lv - 7 * m + 114) // 31
    dia = (h + lv - 7 * m + 114) % 31 + 1
    return date(anio, mes, dia)


def festivos(anio: int) -> set[date]:
    p = pascua(anio)
    fijos = [(1, 1), (1, 6), (5, 1), (5, 2), (8, 15), (10, 12), (11, 1), (12, 6), (12, 8), (12, 25)]
    return {date(anio, m, d) for m, d in fijos} | {p - timedelta(days=3), p - timedelta(days=2)}  # Jueves y Viernes Santo


def laborable(d: date) -> bool:
    return d.weekday() < 5 and d not in festivos(d.year)


def primer_laborable(anio: int, mes: int) -> date:
    d = date(anio, mes, 1)
    while not laborable(d):
        d += timedelta(days=1)
    return d
