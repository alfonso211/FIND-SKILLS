"""Lectura de ficheros FIEBDC-3 (.bc3): bases de precios de construcción y presupuestos con mediciones.

Registros que se usan (separados por «~», campos por «|», subcampos por «\\»):
  ~V  propiedad y versión; el campo 4 indica el juego de caracteres (ANSI, 850, 437)
  ~C  concepto: código, unidad, resumen, precio, fecha, tipo. «##» = raíz, «#» = capítulo
  ~D  descomposición: padre | hijo \\ factor \\ rendimiento \\ hijo \\ …
  ~T  texto largo del concepto
  ~M  mediciones: padre \\ hijo | posición | medición total | …

Las partidas son los conceptos que cuelgan directamente de un capítulo; sus descompuestos (mano de obra,
materiales, maquinaria) no se importan como partidas, pero sirven para calcular el precio si no lo trae."""
from dataclasses import dataclass, field

CODIFICACIONES = {"ANSI": "cp1252", "850": "cp850", "437": "cp437", "UTF-8": "utf-8", "UTF8": "utf-8"}


@dataclass
class Concepto:
    codigo: str
    unidad: str = ""
    resumen: str = ""
    precio: float | None = None
    tipo: str = ""
    capitulo: bool = False
    raiz: bool = False
    texto: str = ""


@dataclass
class Bc3:
    conceptos: dict[str, Concepto] = field(default_factory=dict)
    hijos: dict[str, list[tuple[str, float, float]]] = field(default_factory=dict)  # padre -> (hijo, factor, rend.)
    mediciones: dict[tuple[str, str], float] = field(default_factory=dict)
    propiedad: str = ""


def _num(t: str) -> float | None:
    t = (t or "").strip()
    if not t:
        return None
    try:
        return float(t.replace(",", "."))
    except ValueError:
        return None


def _limpia(codigo: str) -> tuple[str, bool, bool]:
    c = codigo.strip()
    raiz = c.endswith("##")
    cap = c.endswith("#")
    return c.rstrip("#"), cap and not raiz, raiz


def _texto(datos: bytes) -> str:
    cabecera = datos[:400].decode("latin-1", "replace").lstrip("\ufeff").lstrip("ï»¿")
    cod = "cp1252"
    if cabecera.startswith("~V"):
        campos = cabecera.split("~", 2)[1].split("|")  # ["V", propiedad, versión, programa, cabecera, juego…]
        if len(campos) > 5:
            cod = CODIFICACIONES.get(campos[5].strip().upper(), cod)
    for c in (cod, "utf-8", "cp1252"):
        try:
            return datos.decode(c)
        except UnicodeDecodeError:
            continue
    return datos.decode("latin-1", "replace")


def leer(datos: bytes) -> Bc3:
    if not datos.lstrip()[:1] == b"~":
        raise ValueError("No es un fichero FIEBDC-3 (.bc3)")
    out = Bc3()
    for reg in _texto(datos).split("~")[1:]:
        reg = reg.rstrip("\r\n")
        if len(reg) < 2 or reg[1] != "|":
            continue
        tipo, campos = reg[0], reg[2:].split("|")
        if tipo == "V":
            out.propiedad = campos[0].strip() if campos else ""
        elif tipo == "C" and campos:
            for cod in campos[0].split("\\"):
                if not cod.strip():
                    continue
                c, cap, raiz = _limpia(cod)
                precio = _num((campos[3] if len(campos) > 3 else "").split("\\")[0])
                out.conceptos[c] = Concepto(
                    codigo=c, unidad=(campos[1] if len(campos) > 1 else "").strip(),
                    resumen=(campos[2] if len(campos) > 2 else "").strip(), precio=precio,
                    tipo=(campos[5] if len(campos) > 5 else "").strip(), capitulo=cap, raiz=raiz,
                    texto=out.conceptos[c].texto if c in out.conceptos else "")
                break  # el primer código es el principal
        elif tipo == "D" and len(campos) > 1:
            padre = _limpia(campos[0])[0]
            sub = campos[1].split("\\")
            lista = []
            for i in range(0, len(sub) - 2, 3):
                if sub[i].strip():
                    lista.append((_limpia(sub[i])[0], _num(sub[i + 1]) or 1.0, _num(sub[i + 2]) or 0.0))
            out.hijos[padre] = lista
        elif tipo == "T" and len(campos) > 1:
            c = _limpia(campos[0])[0]
            out.conceptos.setdefault(c, Concepto(codigo=c)).texto = campos[1].strip()
        elif tipo == "M" and len(campos) > 2:
            ph = campos[0].split("\\")
            if len(ph) == 2:
                total = _num(campos[2])
                if total is not None:
                    out.mediciones[(_limpia(ph[0])[0], _limpia(ph[1])[0])] = total
    if not out.conceptos:
        raise ValueError("El fichero no contiene conceptos (~C)")
    return out


def precio(b: Bc3, codigo: str, _prof: int = 0) -> float:
    """Precio del concepto; si no lo trae, la suma de su descomposición."""
    c = b.conceptos.get(codigo)
    if c is not None and c.precio is not None and c.precio != 0:
        return c.precio
    if _prof > 12 or codigo not in b.hijos:
        return (c.precio or 0.0) if c else 0.0
    return round(sum(f * r * precio(b, h, _prof + 1) for h, f, r in b.hijos[codigo]), 4)


def _raices(b: Bc3) -> list[str]:
    r = [c.codigo for c in b.conceptos.values() if c.raiz]
    if r:
        return r
    con_padre = {h for lst in b.hijos.values() for h, _, _ in lst}
    return [c.codigo for c in b.conceptos.values() if c.capitulo and c.codigo not in con_padre]


def partidas_base(b: Bc3) -> list[dict]:
    """Partidas de una base de precios con la ruta de capítulos («Demoliciones › Tabiquería»)."""
    vistos, out = set(), []

    def recorre(cod: str, ruta: list[str], prof: int) -> None:
        if prof > 10:
            return
        for h, _, _ in b.hijos.get(cod, []):
            c = b.conceptos.get(h)
            if c is None:
                continue
            if c.capitulo:
                recorre(h, [*ruta, c.resumen or h], prof + 1)
            elif h not in vistos:
                vistos.add(h)
                out.append({"codigo": h, "unidad": c.unidad, "resumen": c.resumen or h, "texto": c.texto,
                            "precio": round(precio(b, h), 2), "capitulo": " › ".join(ruta)})

    for r in _raices(b):
        recorre(r, [], 0)
    if not out:  # bases sin árbol de capítulos: los conceptos con unidad que tienen descomposición o tipo 0
        for c in b.conceptos.values():
            if not c.capitulo and not c.raiz and c.unidad and (c.codigo in b.hijos or c.tipo in ("", "0")):
                out.append({"codigo": c.codigo, "unidad": c.unidad, "resumen": c.resumen or c.codigo,
                            "texto": c.texto, "precio": round(precio(b, c.codigo), 2), "capitulo": ""})
    return out


def presupuesto(b: Bc3) -> list[dict]:
    """Partidas de un presupuesto con su medición, agrupadas por los capítulos de primer nivel (los subcapítulos
    se integran en su capítulo)."""
    out = []
    raices = _raices(b)
    caps = []
    for r in raices:
        caps += [h for h, _, _ in b.hijos.get(r, []) if b.conceptos.get(h) and b.conceptos[h].capitulo]
    if not caps:
        caps = raices

    def recorre(cap: str, cod: str, nombre: str, mult: float, prof: int) -> None:
        if prof > 10:
            return
        for h, f, rend in b.hijos.get(cod, []):
            c = b.conceptos.get(h)
            if c is None:
                continue
            if c.capitulo:
                recorre(cap, h, nombre, mult * (rend or 1), prof + 1)
                continue
            cantidad = b.mediciones.get((cod, h), rend) * mult
            out.append({"capitulo": cap, "capitulo_nombre": nombre, "codigo": h, "unidad": c.unidad,
                        "descripcion": (c.resumen + (f"\n{c.texto}" if c.texto and c.texto != c.resumen else ""))
                        or h, "cantidad": round(cantidad, 3), "precio": round(precio(b, h), 2)})

    for n, cap in enumerate(caps, 1):
        c = b.conceptos[cap]
        recorre(cap if len(cap) <= 20 else f"{n:02d}", cap, c.resumen or cap, 1.0, 0)
    return out
