"""Croquis por planta de los activos turísticos (plano interactivo).

Cada plano es una cuadrícula de filas x columnas, igual que el croquis del PMS anterior. Cada celda es:
- un apartamento ("u": su número, que se busca en las unidades del activo sin el prefijo de bloque: 432 -> B-432),
- una zona común ("zc"), en amarillo, para avisar incidencias de ese lado del edificio,
- o decoración: ascensor, escalera, piscina, jardín, patio, acceso, terraza o rótulo.

Para añadir el plano de otro activo (Suite Florida) basta con escribir su función y registrarla en PLANOS.
"""

# Suite Aeropuerto (C/ Campezo 8): 17 columnas x 11 filas, igual en todas las plantas salvo la 1ª y la 2ª.
# Mitad superior = bloque A (escalera roja), mitad inferior = bloque B (escalera verde).
COLUMNAS_SAE, FILAS_SAE = 17, 11

ZONAS_SAE = [  # (fila, columna, código, nombre): esquinas de los pasillos, a cada lado del edificio
    (2, 1, "A-PISCINA", "Bloque A · lado piscina"),
    (2, 17, "A-JARDIN", "Bloque A · lado jardín"),
    (10, 1, "B-PISCINA", "Bloque B · lado piscina"),
    (10, 17, "B-JARDIN", "Bloque B · lado jardín"),
]


def _sae_decoracion(p: str) -> dict[tuple[int, int], dict]:
    d: dict[tuple[int, int], dict] = {}

    def pon(f, c, t, texto=None):
        d[(f, c)] = {"t": t, **({"texto": texto} if texto else {})}

    for f in (1, 11):  # núcleos de ascensores y escalera en los extremos
        pon(f, 10, "asc"), pon(f, 11, "esc"), pon(f, 12, "asc")
    pon(1, 13, "asc")
    for f in (3, 9):
        pon(f, 8, "asc"), pon(f, 10, "asc")
    pon(3, 9, "escA"), pon(4, 9, "escA"), pon(8, 9, "escB"), pon(9, 9, "escB")
    pon(5, 9, "lbl", "A"), pon(6, 9, "lbl", f"{p}º"), pon(7, 9, "lbl", "B")
    for f in (4, 8):
        for c in (1, 2, 3, 4, 5, 13, 14, 15, 16, 17):
            pon(f, c, "pat")
    for f in (5, 6, 7):
        for c in (1, 2, 3, 4):
            pon(f, c, "pis")
        pon(f, 5, "pat"), pon(f, 12, "pat")
    pon(5, 6, "esc"), pon(7, 6, "esc"), pon(6, 6, "pat"), pon(6, 7, "pat"), pon(6, 8, "pat")
    for c in (13, 14, 15, 16):
        pon(5, c, "jar"), pon(7, c, "jar")
    pon(5, 17, "pat"), pon(7, 17, "pat")
    for c in (13, 14, 15, 16, 17):
        pon(6, c, "acc")
    return d


def _sae_planta(p: int) -> list[dict]:
    """Celdas de una planta. Posiciones según los croquis del PMS anterior."""
    n = lambda x: f"{p}{x:02d}"  # noqa: E731  número de apartamento: planta + 2 cifras
    u: dict[tuple[int, int], str] = {}
    if p == 1:
        for i, c in enumerate(range(1, 10)):  # fila superior: 135..127
            u[(1, c)] = str(135 - i)
        for i, c in enumerate(range(14, 18)):  # 151..148
            u[(1, c)] = str(151 - i)
        for i, c in enumerate(range(1, 7)):  # 136..141
            u[(3, c)] = str(136 + i)
        for i, c in enumerate(range(12, 18)):  # 142..147
            u[(3, c)] = str(142 + i)
        for i, c in enumerate(range(1, 7)):  # 117..112
            u[(9, c)] = str(117 - i)
        for i, c in enumerate(range(12, 18)):  # 111..106
            u[(9, c)] = str(111 - i)
        for i, c in enumerate(range(1, 7)):  # 118..123
            u[(11, c)] = str(118 + i)
        for i, c in enumerate(range(13, 18)):  # 101..105
            u[(11, c)] = str(101 + i)
    elif p == 2:
        for i, c in enumerate(range(1, 10)):  # 240..232
            u[(1, c)] = str(240 - i)
        for i, c in enumerate(range(14, 18)):  # 260..257
            u[(1, c)] = str(260 - i)
        for i, c in enumerate(range(1, 8)):  # 241..247
            u[(3, c)] = str(241 + i)
        for i, c in enumerate(range(11, 18)):  # 250..256
            u[(3, c)] = str(250 + i)
        u.update({(5, 8): "248", (5, 10): "249", (6, 10): "214", (7, 8): "215", (7, 10): "213"})
        for i, c in enumerate(range(1, 8)):  # 222..216
            u[(9, c)] = str(222 - i)
        for i, c in enumerate(range(11, 18)):  # 212..206
            u[(9, c)] = str(212 - i)
        for i, c in enumerate(range(1, 10)):  # 223..231
            u[(11, c)] = str(223 + i)
        for i, c in enumerate(range(13, 18)):  # 201..205
            u[(11, c)] = str(201 + i)
    else:  # plantas 3ª, 4ª y 5ª: misma distribución
        for i, c in enumerate(range(1, 10)):  # x42..x34
            u[(1, c)] = n(42 - i)
        for i, c in enumerate(range(14, 18)):  # x64..x61
            u[(1, c)] = n(64 - i)
        for i, c in enumerate(range(1, 8)):  # x43..x49
            u[(3, c)] = n(43 + i)
        for i, c in enumerate(range(11, 18)):  # x54..x60
            u[(3, c)] = n(54 + i)
        u.update({(4, 8): n(50), (5, 8): n(51), (7, 8): n(16), (8, 8): n(17),
                  (4, 10): n(53), (5, 10): n(52), (6, 10): n(15), (7, 10): n(14), (8, 10): n(13)})
        for i, c in enumerate(range(1, 8)):  # x24..x18
            u[(9, c)] = n(24 - i)
        for i, c in enumerate(range(11, 18)):  # x12..x06
            u[(9, c)] = n(12 - i)
        for i, c in enumerate(range(1, 10)):  # x25..x33
            u[(11, c)] = n(25 + i)
        for i, c in enumerate(range(13, 18)):  # x01..x05
            u[(11, c)] = n(1 + i)

    celdas = _sae_decoracion(str(p))
    if p == 2:  # terrazas de la 2ª planta
        for fc in ((4, 6), (4, 7), (4, 11), (4, 12), (5, 7), (5, 11), (6, 11), (7, 7), (7, 11),
                   (8, 6), (8, 7), (8, 11), (8, 12)):
            celdas[fc] = {"t": "ter", "texto": "Ter"}
    for fc, num in u.items():
        celdas[fc] = {"t": "u", "num": num}
    for f, c, codigo, nombre in ZONAS_SAE:
        celdas[(f, c)] = {"t": "zc", "zona": f"P{p}-{codigo}", "nombre": f"Planta {p}ª · {nombre}"}
    return [{"f": f, "c": c, **v} for (f, c), v in sorted(celdas.items())]


def _sae() -> dict:
    return {"columnas": COLUMNAS_SAE, "filas": FILAS_SAE,
            "plantas": [{"planta": str(p), "etiqueta": f"{p}ª planta", "celdas": _sae_planta(p)} for p in range(1, 6)]}


PLANOS = {"SAE": _sae()}


def plano(codigo_activo: str) -> dict | None:
    return PLANOS.get(codigo_activo)


def zonas(codigo_activo: str) -> dict[str, str]:
    """Código -> nombre de las zonas comunes del plano del activo."""
    p = plano(codigo_activo)
    if not p:
        return {}
    return {c["zona"]: c["nombre"] for pl in p["plantas"] for c in pl["celdas"] if c["t"] == "zc"}


def numero(codigo_unidad: str) -> str:
    """Número del apartamento sin el prefijo de bloque (B-432 -> 432)."""
    return codigo_unidad.split("-")[-1]
