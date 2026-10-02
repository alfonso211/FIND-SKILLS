"""Relleno de los contratos de alojamiento (MOD-ALOJ-001) sobre la plantilla Word original.

Cada hueco de la plantilla es una secuencia de puntos suspensivos («……»). Los párrafos se localizan por su
etiqueta y los huecos se rellenan en orden, conservando el formato del documento. Un hueco sin dato se deja
con sus puntos para completarlo a mano.
"""
import io
import re
from datetime import date
from pathlib import Path

import docx

PLANTILLAS = Path(__file__).parent / "plantillas"
HUECO = re.compile(r"…+")
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
         "noviembre", "diciembre"]

MOTIVOS = {
    "turismo": "turismo / ocio",
    "laboral": "desplazamiento laboral temporal",
    "medico": "tratamiento médico o acompañamiento",
    "estudios": "estudios de duración limitada",
    "obras": "obras o siniestro en su vivienda habitual",
    "transito": "tránsito aeroportuario",
    "otro": "otro:",
}
ACREDITACIONES = {
    "empadronamiento": "empadronamiento",
    "dni": "DNI o equivalente",
    "alquiler": "contrato de alquiler / escritura",
    "suministro": "factura de suministro (últimos 3 meses)",
    "residencia_fiscal": "certificado de residencia fiscal",
    "otro": "otro:",
}

# (inicio del texto del párrafo, campos de sus huecos en orden). El orden de la lista importa:
# "P.p. Fdo." va antes que "Fdo." para no confundir la firma de la empresa con la del cliente.
CAMPOS = [
    ("Localizador nº", ["localizador", "firma_dia", "firma_mes", "firma_anio"]),
    ("LA EMPRESA:", ["registro_turistico", "representante", "representante_dni", "email_empresa"]),
    ("EL CLIENTE:", ["cliente_nombre", "cliente_nacionalidad", "cliente_documento", "cliente_domicilio",
                     "cliente_cp", "cliente_municipio", "cliente_pais", "cliente_email", "cliente_movil"]),
    ("Apartamento:", ["portal", "planta", "numero"]),
    ("Capacidad máxima:", ["capacidad"]),
    ("Dormitorios:", ["dormitorios"]),
    ("Garaje:", ["garaje_sotano", "garaje_plaza"]),
    ("Entrada:", ["entrada_dia", "entrada_mes", "entrada_anio"]),
    ("Salida:", ["salida_dia", "salida_mes", "salida_anio"]),
    ("Nº de noches:", ["noches"]),
    ("Precio total:", ["precio_total"]),
    ("Fianza:", ["fianza"]),
    ("Tarjeta de garantía:", ["tarjeta_titular", "tarjeta_terminacion", "tarjeta_cad_mes", "tarjeta_cad_anio"]),
    ("Ocupantes autorizados", ["ocupantes"]),
    ("Motivo de la estancia:", ["motivo_otro"]),
    ("Acreditación del domicilio habitual", ["acreditacion_otro"]),
    ("P.p. Fdo.:", ["representante"]),
    ("Fdo.:", ["cliente_nombre"]),
    ("DNI / Pasaporte / NIE:", ["cliente_documento"]),
]
CASILLAS = {"Motivo de la estancia:": ("motivo", MOTIVOS),
            "Acreditación del domicilio habitual": ("acreditacion", ACREDITACIONES)}


def plantilla(codigo_activo: str) -> Path | None:
    p = PLANTILLAS / f"contrato_alojamiento_{codigo_activo}.docx"
    return p if p.exists() else None


def _parrafos(doc):
    yield from doc.paragraphs
    for t in doc.tables:
        for fila in t.rows:
            vistas = set()  # guarda los elementos (no su id(), que puede reutilizarse)
            for celda in fila.cells:
                if celda._tc in vistas:  # celdas combinadas aparecen repetidas
                    continue
                vistas.add(celda._tc)
                yield from celda.paragraphs


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return str(v).strip()


NO_APLICA = "\x00"  # marca interna: hueco que no procede (se elimina en lugar de dejar puntos)


def rellenar(ruta: Path, datos: dict) -> tuple[bytes, list[str]]:
    """Devuelve el .docx relleno y la lista de huecos que han quedado sin dato.
    `datos["no_aplica"]`: campos que no proceden (p.ej. «otro» sin marcar): se quitan del texto.
    `datos["sin_garaje"]`: la línea de garaje se imprime como «No incluido»."""
    doc = docx.Document(str(ruta))
    pendientes: list[str] = []
    no_aplica = set(datos.get("no_aplica") or ())
    for p in _parrafos(doc):
        texto = p.text.strip()
        spec = next(((ini, campos) for ini, campos in CAMPOS if texto.startswith(ini)), None)
        if not spec:
            continue
        ini, campos = spec
        if ini == "Garaje:" and datos.get("sin_garaje"):
            for run in p.runs[1:]:
                if "…" in run.text:
                    run.text = " No incluido"
            continue
        cola = list(campos)
        for run in p.runs:
            t = run.text
            if ini in CASILLAS:
                t = _marcar(t, *CASILLAS[ini], datos)
            if "…" in t:
                def sustituir(m):
                    if not cola:
                        return m.group(0)
                    campo = cola.pop(0)
                    if campo in no_aplica:
                        return NO_APLICA
                    valor = _fmt(datos.get(campo))
                    if not valor:
                        pendientes.append(campo)
                        return m.group(0)
                    return valor
                t = HUECO.sub(sustituir, t).replace(": " + NO_APLICA, "").replace(NO_APLICA, "")
            if t != run.text:
                run.text = t
        if ini == "Apartamento:" and datos.get("etiqueta_bloque"):
            for run in p.runs:
                if " Portal " in f" {run.text}":
                    run.text = run.text.replace("Portal", datos["etiqueta_bloque"], 1)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), pendientes


def _marcar(texto: str, campo: str, opciones: dict, datos: dict) -> str:
    elegidos = datos.get(campo) or []
    if isinstance(elegidos, str):  # contratos guardados antes de admitir varias casillas
        elegidos = [elegidos]
    for elegido in elegidos:
        if elegido in opciones:
            texto = texto.replace(f"☐ {opciones[elegido]}", f"☒ {opciones[elegido]}", 1)
    return texto


def fecha_es(d: date) -> dict:
    return {"dia": d.day, "mes": MESES[d.month - 1], "anio": d.year}


# Nombre legible de cada hueco, para avisar de lo que falta antes de imprimir
ETIQUETAS = {
    "localizador": "Localizador", "firma_dia": "Fecha de firma", "firma_mes": "Fecha de firma",
    "firma_anio": "Fecha de firma", "registro_turistico": "Nº de registro turístico (ficha del activo)",
    "representante": "Representante de la empresa (ficha del activo)",
    "representante_dni": "DNI del representante (ficha del activo)",
    "email_empresa": "Correo de notificaciones (ficha del activo)",
    "cliente_nombre": "Nombre del cliente", "cliente_nacionalidad": "Nacionalidad",
    "cliente_documento": "DNI / Pasaporte / NIE", "cliente_domicilio": "Dirección del domicilio",
    "cliente_cp": "Código postal", "cliente_municipio": "Municipio", "cliente_pais": "País",
    "cliente_email": "Correo del cliente", "cliente_movil": "Móvil del cliente",
    "portal": "Portal / bloque de la unidad", "planta": "Planta de la unidad", "numero": "Número de la unidad",
    "capacidad": "Capacidad máxima", "dormitorios": "Dormitorios", "garaje_sotano": "Garaje: sótano",
    "garaje_plaza": "Garaje: plaza", "noches": "Noches", "precio_total": "Precio total", "fianza": "Fianza",
    "tarjeta_titular": "Tarjeta: titular", "tarjeta_terminacion": "Tarjeta: últimos 4 dígitos",
    "tarjeta_cad_mes": "Tarjeta: caducidad", "tarjeta_cad_anio": "Tarjeta: caducidad",
    "ocupantes": "Ocupantes autorizados", "motivo_otro": "Motivo: otro (detalle)",
    "acreditacion_otro": "Acreditación: otro (detalle)",
}


def faltan(pendientes: list[str]) -> list[str]:
    vistos: list[str] = []
    for c in pendientes:
        e = ETIQUETAS.get(c, c)
        if e not in vistos:
            vistos.append(e)
    return vistos
