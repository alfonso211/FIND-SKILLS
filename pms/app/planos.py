"""Croquis por planta de los activos turísticos (plano interactivo).

Cada plano es una cuadrícula de filas x columnas, igual que el croquis del PMS anterior. Cada celda es:
- un apartamento ("u": su número, que se busca en las unidades del activo sin el prefijo de bloque: 432 -> B-432),
- una zona común ("zc"), en amarillo, para avisar incidencias de ese lado del edificio,
- o decoración: ascensor, escalera, piscina, jardín, patio, acceso, terraza o rótulo.

Para añadir el plano de otro activo (Suite Florida) basta con escribir su función y registrarla en PLANOS.
"""

import json
from pathlib import Path

# Suite Aeropuerto (C/ Campezo 8): 17 columnas x 11 filas, igual en todas las plantas salvo la 1ª y la 2ª.
# La entrada del edificio son las flechas (a la derecha del croquis). Entrando, el bloque A queda a la derecha
# (mitad superior, escalera roja) y el bloque B a la izquierda (mitad inferior, escalera verde).
COLUMNAS_SAE, FILAS_SAE = 17, 11

ZONAS_SAE = [  # (fila, columna, código, nombre): esquinas de los pasillos, a cada lado del edificio
    (2, 1, "A-PISCINA", "Bloque A (derecha) · lado piscina"),
    (2, 17, "A-ENTRADA", "Bloque A (derecha) · lado entrada"),
    (10, 1, "B-PISCINA", "Bloque B (izquierda) · lado piscina"),
    (10, 17, "B-ENTRADA", "Bloque B (izquierda) · lado entrada"),
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
        pon(6, c, "acc", "←")
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


# Garajes de Suite Aeropuerto según los croquis del PMS anterior: exterior (39 x 23) e interior, sótano -1
# (40 x 24). Flechas negras: entrada de vehículos; rojas: salida.
GARAJES_SAE = Path(__file__).parent / "data" / "planos_sae_garajes.json"
GARAJES_SAE_INFO = {  # clave del fichero: (prefijo del código, bloque, planta, etiqueta, columnas, filas)
    "EXT": ("EXT", "Garaje exterior", "0", "Garaje exterior", 39, 23),
    "S1": ("S1", "Sótano -1", "-1", "Garaje interior (sótano -1)", 40, 24),
}


def _sae_garaje(clave: str, plazas: dict[str, int]) -> dict:
    prefijo, _, planta, etiqueta, columnas, filas = GARAJES_SAE_INFO[clave]
    celdas: dict[tuple[int, int], dict] = {}

    def pon(f, c, t, texto=None):
        celdas[(f, c)] = {"t": t, **({"texto": texto} if texto else {})}

    zonas: list[tuple[int, int, str, str]] = []
    if clave == "EXT":
        for f in (1, 22):
            pon(f, 38, "entrada", "←"), pon(f, 39, "entrada", "←")
            pon(f + 1, 38, "salida", "→"), pon(f + 1, 39, "salida", "→")
        for f in (11, 12, 13):  # piscina
            for c in range(3, 11):
                pon(f, c, "pis")
        for f in (10, 14):
            for c in range(30, 36):
                pon(f, c, "arbol")
        pon(9, 2, "esc"), pon(15, 2, "esc")
        for f, negro in ((4, 5), (20, 19)):  # accesos a los bloques
            for c in range(26, 30):
                pon(f, c, "esc")
            pon(negro, 27, "negro"), pon(negro, 28, "negro")
        zonas = [(1, 37, "ACCESO-NORTE", "acceso de vehículos superior"),
                 (23, 37, "ACCESO-SUR", "acceso de vehículos inferior"),
                 (9, 3, "PEATONAL-1", "acceso peatonal (escalera superior)"),
                 (15, 3, "PEATONAL-2", "acceso peatonal (escalera inferior)")]
    else:
        pon(2, 33, "entrada", "↓"), pon(2, 35, "salida", "↑")
        for f in (2, 3, 4, 22, 23, 24):  # escaleras y ascensores de los extremos
            pon(f, 2, "esc")
        pon(5, 2, "asc"), pon(21, 2, "asc"), pon(5, 39, "asc"), pon(5, 40, "asc"), pon(21, 39, "asc"), pon(21, 40, "asc")
        for c in (39, 40):
            pon(2, c, "esc"), pon(24, c, "esc")
        for f in (2, 24):  # accesos peatonales al edificio
            pon(f, 24, "esc"), pon(f, 25, "negro"), pon(f, 26, "negro")
        for c in range(31, 41):  # muros
            pon(7, c, "muro")
        for f in range(8, 18):
            pon(f, 31, "muro")
        for c in [*range(15, 28), *range(30, 41)]:
            pon(18, c, "muro")
        pon(18, 28, "puerta"), pon(18, 29, "puerta")
        for f in range(19, 25):
            pon(f, 15, "muro")
        zonas = [(2, 34, "RAMPA", "rampa de entrada y salida"), (4, 3, "NO", "escalera noroeste"),
                 (4, 38, "NE", "escalera noreste"), (23, 3, "SO", "escalera suroeste"), (23, 38, "SE", "escalera sureste")]
    for rc, n in plazas.items():
        f, c = map(int, rc.split(","))
        celdas[(f, c)] = {"t": "u", "cod": f"{prefijo}-{n}", "num": str(n)}
    for f, c, codigo, nombre in zonas:
        celdas[(f, c)] = {"t": "zc", "zona": f"{prefijo}-{codigo}", "nombre": f"{etiqueta} · {nombre}"}
    return {"planta": planta, "etiqueta": etiqueta, "columnas": columnas, "filas": filas,
            "celdas": [{"f": f, "c": c, **v} for (f, c), v in sorted(celdas.items())]}


def _sae() -> dict:
    garajes = json.loads(GARAJES_SAE.read_text(encoding="utf-8"))
    return {"columnas": COLUMNAS_SAE, "filas": FILAS_SAE,
            "plantas": [_sae_garaje("EXT", garajes["EXT"]), _sae_garaje("S1", garajes["S1"])]
            + [{"planta": str(p), "etiqueta": f"{p}ª planta", "celdas": _sae_planta(p)} for p in range(1, 6)]}


def unidades_sae_garajes() -> list[dict]:
    """Plazas de garaje de Suite Aeropuerto (exterior y sótano -1) según los croquis."""
    garajes = json.loads(GARAJES_SAE.read_text(encoding="utf-8"))
    out = []
    for clave, (prefijo, bloque, planta, *_) in GARAJES_SAE_INFO.items():
        for n in sorted(garajes[clave].values()):
            out.append({"codigo": f"{prefijo}-{n}", "bloque": bloque, "planta": planta, "uso": "garaje"})
    return out


# --------------------------------------------------------------------------- Suite Florida (C/ Campezo 2)
# Plantas: 13 x 12 como el croquis anterior, más una columna exterior a cada lado para las zonas comunes, que
# van junto al número de portal de cada esquina. La entrada (flecha) está a la derecha: entrando, los portales
# 2 y 3 quedan a la derecha (arriba) y los portales 1 y 4 a la izquierda (abajo).
# Garajes: 30 x 26 como el croquis anterior, más las mismas columnas exteriores.
GARAJES_SFL = Path(__file__).parent / "data" / "planos_sfl_garajes.json"
DOS_DORMITORIOS_SFL = {1: "IJ", 2: "GHMNO", 3: "ABCHI", 4: "IJOPQ"}  # letras de 2 dormitorios por portal

# (fila, columna del croquis, portal, letra)
_APARTAMENTOS_SFL = (
    # portal 3 (arriba a la izquierda)
    [(1, c, 3, l) for c, l in zip(range(2, 7), "HGFED")] + [(2, 1, 3, "I")]
    + [(2, c, 3, l) for c, l in zip(range(3, 6), "ABC")]
    + [(f, 1, 3, l) for f, l in zip(range(3, 6), "JKL")] + [(f, 2, 3, l) for f, l in zip(range(3, 6), "ONM")]
    # portal 2 (arriba a la derecha)
    + [(1, c, 2, l) for c, l in zip(range(8, 13), "LKJIH")]
    + [(2, c, 2, l) for c, l in zip(range(9, 12), "MNO")] + [(2, 13, 2, "G")]
    + [(f, 12, 2, l) for f, l in zip(range(3, 6), "ABC")] + [(f, 13, 2, l) for f, l in zip(range(3, 6), "FED")]
    # portal 4 (abajo a la izquierda)
    + [(f, 1, 4, l) for f, l in zip(range(7, 11), "EFGH")] + [(f, 2, 4, l) for f, l in zip(range(7, 11), "DCBA")]
    + [(11, 1, 4, "I")] + [(11, c, 4, l) for c, l in zip(range(3, 6), "QPO")]
    + [(12, c, 4, l) for c, l in zip(range(2, 7), "JKLMN")]
    # portal 1 (abajo a la derecha)
    + [(f, 12, 1, l) for f, l in zip(range(7, 11), "OPQR")] + [(f, 13, 1, l) for f, l in zip(range(7, 11), "NMLK")]
    + [(11, c, 1, l) for c, l in zip(range(8, 12), "DCBA")] + [(11, 13, 1, "J")]
    + [(12, c, 1, l) for c, l in zip(range(8, 13), "EFGHI")]
)
_ESQUINAS_SFL = {3: ("arriba", "izquierda"), 2: ("arriba", "derecha"), 4: ("abajo", "izquierda"), 1: ("abajo", "derecha")}


def _sfl_esquinas(celdas: dict, filas: int, columnas: int, prefijo: str, nombre: str, negras: bool) -> None:
    """Número de portal en cada esquina y, en la columna exterior a su lado, la zona común del portal.
    `columnas` es el ancho del croquis original (sin las columnas exteriores)."""
    for portal, (v, h) in _ESQUINAS_SFL.items():
        f = 1 if v == "arriba" else filas
        c = 1 if h == "izquierda" else columnas
        celdas[(f, c + 1)] = {"t": "portal", "texto": str(portal)}
        celdas[(f, 1 if h == "izquierda" else columnas + 2)] = {
            "t": "zc", "zona": f"{prefijo}-PORTAL{portal}", "nombre": f"{nombre} · Portal {portal}"}
        if negras:  # bloque negro de 2 x 2 de los garajes
            f2 = f + 1 if v == "arriba" else f - 1
            c2 = c + 1 if h == "izquierda" else c - 1
            for fc in ((f, c2), (f2, c), (f2, c2)):
                celdas[(fc[0], fc[1] + 1)] = {"t": "negro"}


def _sfl_planta(p: int) -> dict:
    celdas: dict[tuple[int, int], dict] = {}
    pon = lambda f, c, t, texto=None: celdas.__setitem__((f, c + 1), {"t": t, **({"texto": texto} if texto else {})})  # noqa: E731
    for f, c in ((2, 2), (2, 12), (11, 2), (11, 12)):  # escalera y ascensor de cada portal
        pon(f, c, "esc")
    for f in (4, 5):
        for c in (4, 5):
            pon(f, c, "jar")
        for c in (9, 10):
            pon(f, c, "plaza")
    for f in (7, 8, 9):
        for c in (4, 5):
            pon(f, c, "pis")
    for f in (8, 9):
        for c in (8, 9, 10):
            pon(f, c, "tarima")
    pon(6, 7, "lbl", f"{p}º")
    pon(6, 13, "acc", "←")
    for f, c, portal, letra in _APARTAMENTOS_SFL:
        celdas[(f, c + 1)] = {"t": "u", "cod": f"P{portal}-{p}{letra}", "num": letra}
    _sfl_esquinas(celdas, 12, 13, f"P{p}", f"Planta {p}ª", negras=False)
    return {"planta": str(p), "etiqueta": f"{p}ª planta", "columnas": 15, "filas": 12,
            "celdas": [{"f": f, "c": c, **v} for (f, c), v in sorted(celdas.items())]}


def _sfl_garaje(nivel: int, plazas: dict[str, int]) -> dict:
    celdas: dict[tuple[int, int], dict] = {}
    pon = lambda f, c, t, texto=None: celdas.__setitem__((f, c + 1), {"t": t, **({"texto": texto} if texto else {})})  # noqa: E731
    for c in (4, 5, 26, 27):  # ascensores y escaleras de los portales
        pon(5, c, "asc"), pon(6, c, "esc"), pon(21, c, "esc"), pon(22, c, "asc")
    if nivel == 1:
        for f in range(15, 23):
            pon(f, 14, "rampa"), pon(f, 15, "rampa")
        for c in (1, 30):
            pon(15, c, "acc", "←"), pon(16, c, "acc", "→")
        for f in (3, 24):
            for c, t in ((8, "‹‹‹"), (11, "›››"), (20, "‹‹‹"), (23, "›››")):
                pon(f, c, "sentido", t)
    else:
        for f in range(15, 21):
            pon(f, 14, "rampa"), pon(f, 15, "rampa")
        pon(14, 14, "acc", "↓"), pon(14, 15, "acc", "↑")
    for rc, n in plazas.items():
        f, c = map(int, rc.split(","))
        celdas[(f, c + 1)] = {"t": "u", "cod": f"S{nivel}-{n}", "num": str(n)}
    _sfl_esquinas(celdas, 26, 30, f"S{nivel}", f"Sótano -{nivel}", negras=True)
    return {"planta": f"-{nivel}", "etiqueta": f"Sótano -{nivel}", "columnas": 32, "filas": 26,
            "celdas": [{"f": f, "c": c, **v} for (f, c), v in sorted(celdas.items())]}


def _sfl() -> dict:
    garajes = json.loads(GARAJES_SFL.read_text(encoding="utf-8"))
    return {"columnas": 15, "filas": 12,
            "plantas": [_sfl_garaje(2, garajes["S2"]), _sfl_garaje(1, garajes["S1"])]
            + [_sfl_planta(p) for p in range(1, 6)]}


def unidades_sfl() -> list[dict]:
    """Unidades de Suite Florida según el plano: apartamentos de 1 y 2 dormitorios y plazas de garaje."""
    out = []
    for p in range(1, 6):
        for _, _, portal, letra in sorted(_APARTAMENTOS_SFL, key=lambda x: (x[2], x[3])):
            dos = letra in DOS_DORMITORIOS_SFL[portal]
            out.append({"codigo": f"P{portal}-{p}{letra}", "bloque": f"Portal {portal}", "planta": str(p),
                        "uso": "apartamento", "dormitorios": 2 if dos else 1,
                        "tipologia": "Apartamento 2 dormitorios" if dos else "Apartamento 1 dormitorio"})
    garajes = json.loads(GARAJES_SFL.read_text(encoding="utf-8"))
    for nivel in (1, 2):
        for n in sorted(garajes[f"S{nivel}"].values()):
            out.append({"codigo": f"S{nivel}-{n}", "bloque": f"Sótano -{nivel}", "planta": f"-{nivel}", "uso": "garaje"})
    return out


# Babilonia 35: sin planos del edificio. Se muestra como carpetas, una por planta (y por sótano de garaje), con el
# logotipo de la sociedad propietaria; dentro, las viviendas o plazas de esa planta (ver routers/plano.py).
CARPETAS = {"tipo": "carpetas", "columnas": 0, "filas": 0, "plantas": []}
ORDEN_PLANTAS = ["Bajo", "1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "ST-1", "ST-2", "ST-3", "ST-4"]


def etiqueta_planta(p: str | None) -> str:
    if not p:
        return "Sin planta"
    if p.lower() in ("bajo", "baja", "bj"):
        return "Planta baja"
    if p.upper().startswith("ST-"):
        return f"Sótano -{p[3:]}"
    return f"Planta {p}ª" if p.isdigit() else f"Planta {p}"


def orden_planta(p: str | None) -> tuple[int, str]:
    return (ORDEN_PLANTAS.index(p), "") if p in ORDEN_PLANTAS else (len(ORDEN_PLANTAS), p or "")


PLANOS = {"SAE": _sae(), "SFL": _sfl(), "BAB35": CARPETAS}


def plano(codigo_activo: str) -> dict | None:
    return PLANOS.get(codigo_activo)


def zonas(codigo_activo: str) -> dict[str, str]:
    """Código -> nombre de las zonas comunes del plano del activo."""
    p = plano(codigo_activo)
    if not p:
        return {}
    return {c["zona"]: c["nombre"] for pl in p["plantas"] for c in pl.get("celdas", []) if c["t"] == "zc"}


def numero(codigo_unidad: str) -> str:
    """Número del apartamento o plaza sin el prefijo de bloque (B-432 -> 432, EXT-12 -> 12)."""
    return codigo_unidad.split("-")[-1]
