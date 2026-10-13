"""Partes de estado (revisión de una vivienda o zona común por mantenimiento o limpieza).

Todo se elige de listas encadenadas, sin texto libre (salvo las observaciones), para poder sacar indicadores:
  A. tipología de la ubicación (T0 estudio, T1 1 dormitorio, T2 2 dormitorios, ZC zonas comunes)
  B. estancia, según la tipología
  C. familia y elemento, según la estancia
  D. deficiencia: técnica (D1, va a mantenimiento) u operativa (D2, va a limpieza)
El cruce elemento + deficiencia + gravedad propone el departamento, la prioridad de la orden de trabajo y las alertas
(motor de reglas). El parte llega a recepción, que genera la orden de trabajo y la encarga a quien considere, o lo
descarta. Un parte crítico deja la unidad fuera de servicio hasta que se cierra su orden de trabajo.
"""
import unicodedata

TIPOLOGIAS = {"T0": "Estudio", "T1": "Apartamento 1 dormitorio", "T2": "Apartamento 2 dormitorios",
              "ZC": "Zonas comunes"}

# Tabla B: estancias de cada tipología (clave -> nombre) y el tipo de estancia, que decide los elementos posibles
ESTANCIAS: dict[str, list[tuple[str, str, str]]] = {
    "T0": [("zona_diafana", "Zona diáfana", "diafana"), ("bano", "Baño", "humeda")],
    "T1": [("hall", "Hall", "paso"), ("salon", "Salón", "estar"), ("cocina", "Cocina", "cocina"),
           ("dormitorio", "Dormitorio", "dormitorio"), ("bano", "Baño", "humeda")],
    "T2": [("pasillo", "Pasillo", "paso"), ("salon", "Salón", "estar"), ("cocina", "Cocina", "cocina"),
           ("dormitorio_principal", "Dormitorio principal", "dormitorio"), ("bano_principal", "Baño principal", "humeda"),
           ("dormitorio_secundario", "Dormitorio secundario", "dormitorio"), ("aseo", "Aseo", "humeda")],
    "ZC": [("recepcion", "Recepción", "zc_recepcion"), ("pasillos", "Pasillos", "zc_paso"),
           ("escaleras", "Escaleras", "zc_paso"), ("cuarto_instalaciones", "Cuarto de instalaciones", "zc_instalaciones"),
           ("exteriores", "Exteriores", "zc_exterior")],
}

# Tabla C: familias y elementos (clave -> nombre). La categoría es la de la orden de trabajo (gremio).
FAMILIAS: dict[str, tuple[str, list[tuple[str, str, str]]]] = {
    "C1": ("Arquitectura y acabados", [
        ("paredes", "Paredes", "pintura"), ("techos", "Techos", "albanileria"), ("suelos", "Suelos", "albanileria"),
        ("puertas", "Puertas", "carpinteria"), ("ventanas", "Ventanas", "carpinteria"),
        ("rodapies", "Rodapiés", "carpinteria"), ("cerrajeria", "Cerrajería", "cerrajeria")]),
    "C2": ("Instalaciones (MEP)", [
        ("cuadro_electrico", "Cuadro eléctrico", "electricidad"), ("enchufes", "Enchufes / mecanismos", "electricidad"),
        ("luminarias", "Luminarias", "electricidad"), ("climatizacion", "Climatización / splits", "climatizacion"),
        ("rejillas", "Rejillas de ventilación", "climatizacion"), ("griferia", "Grifería", "fontaneria"),
        ("sanitarios", "Sanitarios", "fontaneria"), ("desagues", "Desagües", "fontaneria"),
        ("termos", "Termos / calderas", "acs")]),
    "C3": ("Equipamiento y electrodomésticos", [
        ("nevera", "Nevera", "electrodomesticos"), ("lavadora", "Lavadora", "electrodomesticos"),
        ("lavavajillas", "Lavavajillas", "electrodomesticos"), ("vitroceramica", "Vitrocerámica", "electrodomesticos"),
        ("campana", "Campana extractora", "electrodomesticos"), ("tv", "TV", "telecom"), ("router", "Router", "telecom")]),
    "C4": ("Mobiliario", [
        ("cama", "Cama", "carpinteria"), ("sofa", "Sofá", "general"), ("armarios", "Armarios", "carpinteria"),
        ("mesas", "Mesas", "carpinteria"), ("sillas", "Sillas", "carpinteria")]),
    "C5": ("Operaciones", [
        ("menaje", "Menaje de cocina", "limpieza"), ("lenceria", "Lencería (sábanas / toallas)", "limpieza"),
        ("amenities", "Amenities", "limpieza")]),
}

_C1 = [e for e, _, _ in FAMILIAS["C1"][1]]
_ELECTRICO = ["cuadro_electrico", "enchufes", "luminarias"]
# Elementos que puede tener cada tipo de estancia (el resto no se ofrece)
ELEMENTOS_ESTANCIA: dict[str, list[str]] = {
    "diafana": [e for _, (_, els) in FAMILIAS.items() for e, _, _ in els],  # cocina, salón y dormitorio en uno
    "humeda": _C1 + _ELECTRICO + ["rejillas", "griferia", "sanitarios", "desagues", "termos", "lavadora", "armarios",
                                  "lenceria", "amenities"],
    "cocina": _C1 + ["cuadro_electrico", "enchufes", "luminarias", "climatizacion", "rejillas", "griferia", "desagues",
                     "termos", "nevera", "lavadora", "lavavajillas", "vitroceramica", "campana", "router", "armarios",
                     "mesas", "sillas", "menaje"],
    "estar": _C1 + _ELECTRICO + ["climatizacion", "rejillas", "tv", "router", "sofa", "armarios", "mesas", "sillas"],
    "dormitorio": _C1 + ["enchufes", "luminarias", "climatizacion", "rejillas", "tv", "cama", "armarios", "mesas",
                         "sillas", "lenceria"],
    "paso": _C1 + _ELECTRICO + ["climatizacion", "rejillas", "termos", "router", "armarios"],
    "zc_recepcion": _C1 + _ELECTRICO + ["climatizacion", "rejillas", "tv", "router", "sofa", "armarios", "mesas",
                                        "sillas", "amenities"],
    "zc_paso": _C1 + _ELECTRICO + ["climatizacion", "rejillas"],
    "zc_instalaciones": ["paredes", "techos", "suelos", "puertas", "cerrajeria"] + [e for e, _, _ in FAMILIAS["C2"][1]],
    "zc_exterior": ["paredes", "suelos", "puertas", "ventanas", "cerrajeria", "enchufes", "luminarias", "climatizacion",
                    "griferia", "desagues"],
}

# Tabla D: deficiencias. D1 técnicas -> mantenimiento; D2 operativas -> limpieza / gobernanta
DEFICIENCIAS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "D1": ("Deficiencias técnicas", [
        ("rotura", "Rotura / desperfecto físico"), ("fuga", "Fuga / goteo"), ("atasco", "Atasco / obstrucción"),
        ("fallo_electrico", "Fallo eléctrico / sin corriente"), ("averia_electronica", "Avería electrónica (códigos de error)"),
        ("desgaste", "Desgaste estético")]),
    "D2": ("Deficiencias operativas", [
        ("limpieza_profunda", "Falta de limpieza profunda"), ("falta_dotacion", "Falta de dotación"),
        ("restos_huesped", "Restos de huéspedes anteriores"), ("malos_olores", "Malos olores")]),
}

GRAVEDADES = {"leve": "Leve: al backlog, no afecta a la estancia",
              "media": "Media: resolver antes de la próxima entrada de cliente",
              "critica": "Crítica (bloqueante): la unidad queda fuera de servicio"}
DEPARTAMENTOS = {"mantenimiento": "Mantenimiento", "limpieza": "Limpieza / gobernanta"}
ESTADOS = {"pendiente": "Pendiente de recepción", "ot_generada": "Orden de trabajo en curso",
           "resuelto": "Resuelto", "descartado": "Descartado"}
ABIERTOS = ("pendiente", "ot_generada")

ELEMENTOS = {e: (fam, nombre, cat) for fam, (_, els) in FAMILIAS.items() for e, nombre, cat in els}
DEF = {d: (clase, nombre) for clase, (_, ds) in DEFICIENCIAS.items() for d, nombre in ds}
_PRIORIDAD = {"leve": "baja", "media": "alta", "critica": "urgente"}
_ORDEN_PRIORIDAD = ["baja", "media", "alta", "urgente"]
_AGUA = {"griferia", "sanitarios", "desagues", "termos", "nevera", "lavadora", "lavavajillas", "climatizacion"}


def tipologia_unidad(dormitorios: int | None, tipologia: str | None) -> str | None:
    """T0 / T1 / T2 a partir de la ficha de la unidad; None si no se sabe (se pregunta en el parte)."""
    t = unicodedata.normalize("NFKD", tipologia or "").encode("ascii", "ignore").decode().lower()
    if "estudio" in t or dormitorios == 0:
        return "T0"
    if dormitorios == 1 or "1 dormitorio" in t:
        return "T1"
    if (dormitorios or 0) >= 2 or "2 dormitorios" in t:
        return "T2"
    return None


def estancia(tipologia: str, clave: str) -> tuple[str, str] | None:
    """(nombre, tipo de estancia) o None si la estancia no existe en esa tipología."""
    return next(((n, t) for c, n, t in ESTANCIAS.get(tipologia, []) if c == clave), None)


def elementos_de(tipo_estancia: str) -> list[dict]:
    """Familias con los elementos posibles en ese tipo de estancia (acordeón de la pantalla)."""
    permitidos = set(ELEMENTOS_ESTANCIA.get(tipo_estancia, ()))
    out = []
    for fam, (nombre, els) in FAMILIAS.items():
        vis = [{"clave": e, "nombre": n} for e, n, _ in els if e in permitidos]
        if vis:
            out.append({"clave": fam, "nombre": nombre, "elementos": vis})
    return out


def catalogo() -> dict:
    return {
        "tipologias": TIPOLOGIAS,
        "estancias": {t: [{"clave": c, "nombre": n, "elementos": elementos_de(tp)} for c, n, tp in ls]
                      for t, ls in ESTANCIAS.items()},
        "deficiencias": [{"clase": c, "nombre": n, "opciones": [{"clave": d, "nombre": dn} for d, dn in ds]}
                         for c, (n, ds) in DEFICIENCIAS.items()],
        "gravedades": GRAVEDADES, "departamentos": DEPARTAMENTOS, "estados": ESTADOS,
    }


def reglas(elemento: str, deficiencia: str, gravedad: str) -> dict:
    """Motor de reglas: departamento, prioridad y categoría de la orden de trabajo, y alertas del parte."""
    clase, _ = DEF[deficiencia]
    fam, nombre_el, categoria = ELEMENTOS[elemento]
    departamento = "mantenimiento" if clase == "D1" else "limpieza"
    prioridad = _PRIORIDAD[gravedad]
    alertas = []
    if deficiencia == "fuga":
        prioridad = "urgente"
        alertas.append("Fuga: posible daño a mobiliario, suelo o a la vivienda inferior. Cerrar la llave de paso si "
                       "es posible y revisar el entorno.")
    elif deficiencia == "fallo_electrico":
        prioridad = max(prioridad, "alta", key=_ORDEN_PRIORIDAD.index)
        if elemento == "cuadro_electrico":
            alertas.append("Fallo en el cuadro eléctrico: no rearmar varias veces seguidas; puede haber una derivación.")
    elif deficiencia == "atasco" and elemento in ("desagues", "sanitarios", "lavavajillas", "lavadora"):
        alertas.append("Atasco: revisar filtros y bomba de desagüe; no usar hasta su revisión.")
    if clase == "D2":
        categoria = "limpieza"
        if fam == "C3":
            alertas.append("Electrodoméstico: ciclo de limpieza en vacío y retirada de menaje sucio.")
    if clase == "D2" and gravedad == "critica":
        alertas.append("Crítico de limpieza: la unidad no se puede entregar hasta resolverlo.")
    if deficiencia == "fuga" and elemento not in _AGUA and fam != "C1":
        alertas.append("Revise de dónde procede el agua: el elemento indicado no lleva agua.")
    return {"clase": clase, "departamento": departamento, "prioridad": prioridad, "categoria": categoria,
            "familia": fam, "elemento_nombre": nombre_el, "alertas": alertas,
            "tipo_aviso": "Orden de trabajo técnica" if clase == "D1" else "Alerta operativa"}
