"""Documentación legal de cada activo (Administración → Documentación legal): checklist de lo obligatorio según la
modalidad (apartamentos turísticos o alquiler residencial, Comunidad y Ayuntamiento de Madrid), los documentos
escaneados en PDF, su vencimiento y el recordatorio semanal de lo que falta.

El catálogo es orientativo y se revisa con la gestoría o el asesor: cada punto se puede marcar «no aplica» con el
motivo, y cada activo puede añadir puntos propios."""
from datetime import date, timedelta
from html import escape

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Asset, LegalItem

AT, LAU = "apartamentos_turisticos", "alquiler_residencial"
AMBAS = (AT, LAU)
GRUPOS = {
    "titularidad": "Titularidad y fiscalidad",
    "licencias": "Licencias, registros y declaraciones",
    "instalaciones": "Edificio e instalaciones",
    "seguros": "Seguros y contratos",
    "funcionamiento": "Funcionamiento y cumplimiento",
}
DIAS_AVISO = 60  # «por vencer» con esta antelación

# (clave, grupo, título, normativa / qué se guarda, modalidades, meses de validez o None, opcional)
CATALOGO: list[tuple[str, str, str, str, tuple[str, ...], int | None, bool]] = [
    ("escrituras", "titularidad", "Escritura de propiedad y nota simple registral",
     "Título de propiedad y nota simple actualizada del Registro de la Propiedad.", AMBAS, None, False),
    ("catastro", "titularidad", "Referencia y certificación catastral", "Sede Electrónica del Catastro.", AMBAS,
     None, False),
    ("ibi", "titularidad", "Recibo del IBI del último ejercicio", "Ayuntamiento de Madrid (renovar cada año).",
     AMBAS, 12, False),
    ("iae", "titularidad", "Alta censal (036) e IAE de la actividad de alojamiento",
     "Agencia Tributaria: epígrafe de la actividad de alojamiento turístico.", (AT,), None, False),
    ("contrato_gestion", "titularidad", "Contrato de cesión o gestión con la propiedad",
     "Si quien explota el activo no es la sociedad propietaria (p. ej. INVERSIETE gestiona y COMERCIAL DEL CAMPO "
     "es propietaria).", AMBAS, None, False),

    ("lpo", "licencias", "Licencia de primera ocupación / funcionamiento",
     "Ayuntamiento de Madrid. En la Comunidad de Madrid sustituye a la cédula de habitabilidad (Decreto 111/2018).",
     AMBAS, None, False),
    ("licencia_actividad", "licencias", "Licencia o declaración responsable municipal de la actividad de hospedaje",
     "Ayuntamiento de Madrid: uso de servicios terciarios de hospedaje (Plan Especial de Hospedaje).", (AT,), None,
     False),
    ("dr_turismo", "licencias", "Declaración responsable de inicio de actividad turística",
     "Decreto 79/2014 de apartamentos turísticos y viviendas de uso turístico de la Comunidad de Madrid.", (AT,),
     None, False),
    ("ret", "licencias", "Inscripción en el Registro de Empresas Turísticas (nº de registro)",
     "Comunidad de Madrid (p. ej. AM 265). Resolución o justificante de la inscripción.", (AT,), None, False),
    ("plano_tecnico", "licencias", "Planos de las unidades firmados por técnico competente",
     "Decreto 79/2014 (el visado colegial lo anuló el TSJ de Madrid; el plano firmado sí se exige).", (AT,), None,
     False),
    ("ses", "licencias", "Alta del establecimiento en SES.HOSPEDAJES",
     "Ministerio del Interior, RD 933/2021: registro de partes de viajeros.", (AT,), None, False),
    ("nra", "licencias", "Número de registro único de arrendamientos (si se obtuvo)",
     "RD 1312/2024. El Tribunal Supremo anuló el registro único (STS 620/2026, 19-5-2026): solo se conserva el "
     "justificante si se llegó a obtener.", (AT,), None, True),
    ("fianzas", "licencias", "Depósito de las fianzas de los contratos en la Comunidad de Madrid",
     "Ley 29/1994 (LAU) y Decreto 181/1996: justificante de depósito de cada fianza.", (LAU,), None, False),

    ("cee", "instalaciones", "Certificado de eficiencia energética registrado y etiqueta",
     "RD 390/2021. Uno por vivienda o apartamento, inscrito en el registro de la Comunidad de Madrid; validez 10 años.",
     AMBAS, 120, False),
    ("iee", "instalaciones", "Informe de Evaluación del Edificio (IEE / ITE)",
     "Ayuntamiento de Madrid: edificios de más de 30 años, cada 10 años.", AMBAS, 120, False),
    ("electricidad", "instalaciones", "Certificado de la instalación eléctrica (boletín) e inspecciones OCA",
     "REBT (RD 842/2002). Las zonas comunes de pública concurrencia con inspección periódica cada 5 años.", AMBAS,
     60, False),
    ("gas", "instalaciones", "Certificado de la instalación de gas y última revisión periódica",
     "RD 919/2006: revisión cada 5 años. «No aplica» si no hay gas.", AMBAS, 60, False),
    ("rite", "instalaciones", "Instalaciones térmicas (RITE): certificado y contrato de mantenimiento",
     "RD 1027/2007: calefacción, ACS y climatización.", AMBAS, 12, False),
    ("pci", "instalaciones", "Protección contra incendios: contrato de mantenimiento y actas de revisión",
     "RD 513/2017: revisión anual por empresa mantenedora e inspección periódica.", AMBAS, 12, False),
    ("ascensor", "instalaciones", "Ascensores: contrato de mantenimiento y última inspección periódica",
     "RD 355/2024 (ITC AEM 1): inspección por OCA. «No aplica» si no hay ascensor.", AMBAS, 24, False),
    ("legionela", "instalaciones", "Prevención de la legionela: plan y registros del agua",
     "RD 487/2022: plan de prevención y control de las instalaciones de agua (ACS colectiva).", (AT,), 12, False),

    ("seguro_edificio", "seguros", "Seguro del edificio (multirriesgo)", "Póliza y recibo del año en curso.", AMBAS,
     12, False),
    ("seguro_rc", "seguros", "Seguro de responsabilidad civil de la actividad",
     "Póliza y recibo del año en curso (para la actividad turística, exigido por el Decreto 79/2014).", AMBAS, 12,
     False),
    ("comunidad", "seguros", "Comunidad de propietarios: estatutos y certificado de estar al corriente",
     "«No aplica» si el edificio es de un solo propietario.", AMBAS, None, False),
    ("contratos_alquiler", "seguros", "Contratos de arrendamiento firmados con entrega del CEE",
     "Ley 29/1994 (LAU) y RD 390/2021: cada contrato con su certificado energético (expedientes de alquiler).",
     (LAU,), None, False),

    ("hojas_reclamaciones", "funcionamiento", "Hojas de reclamaciones y cartel anunciador",
     "Comunidad de Madrid (Ley 11/1998 y su normativa de desarrollo): a disposición del cliente y cartel visible.",
     (AT,), None, False),
    ("placa", "funcionamiento", "Placa distintivo de apartamento turístico en la entrada",
     "Decreto 79/2014: foto de la placa colocada.", (AT,), None, False),
    ("precios", "funcionamiento", "Precios, servicios y normas de régimen interior a la vista del cliente",
     "Decreto 79/2014 y normativa de consumo.", (AT,), None, False),
    ("autoproteccion", "funcionamiento", "Plan de autoprotección o medidas de emergencia y planos de evacuación",
     "RD 393/2007 y Código Técnico de la Edificación, según el aforo.", (AT,), None, False),
    ("ddd", "funcionamiento", "Control de plagas (DDD): contrato y certificados de tratamiento",
     "Empresa inscrita en el ROESB; certificado de cada tratamiento.", (AT,), 12, False),
    ("prl", "funcionamiento", "Prevención de riesgos laborales y coordinación de actividades (CAE)",
     "Ley 31/1995 y RD 171/2004: evaluación de riesgos, servicio de prevención y documentación de subcontratas.",
     (AT,), 12, False),
    ("rgpd", "funcionamiento", "Protección de datos: registro de actividades y contratos de encargado",
     "RGPD y LOPDGDD: registro de actividades de tratamiento, cláusulas informativas y contratos (art. 28).",
     AMBAS, None, False),
]
POR_CLAVE = {c[0]: c for c in CATALOGO}


def aplicables(modalidad: str) -> list[tuple]:
    return [c for c in CATALOGO if modalidad in c[4]]


def _sumar_meses(f: date, meses: int) -> date:
    m = f.month - 1 + meses
    y, m = f.year + m // 12, m % 12 + 1
    dias = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return date(y, m, min(f.day, dias[m - 1]))


def vencimiento_por_defecto(clave: str, fecha_documento: date | None) -> date | None:
    c = POR_CLAVE.get(clave)
    return _sumar_meses(fecha_documento, c[5]) if c and c[5] and fecha_documento else None


def estado(it: LegalItem | None, hoy: date) -> str:
    """falta | aportado | por_vencer | caducado | no_aplica."""
    if it is None:
        return "falta"
    if it.no_aplica:
        return "no_aplica"
    if not it.ficheros:
        return "falta"
    if it.vencimiento and it.vencimiento < hoy:
        return "caducado"
    if it.vencimiento and it.vencimiento <= hoy + timedelta(days=DIAS_AVISO):
        return "por_vencer"
    return "aportado"


ESTADOS = {"falta": "Falta", "aportado": "Aportado", "por_vencer": "Por vencer", "caducado": "Caducado",
           "no_aplica": "No aplica"}
PENDIENTES = ("falta", "caducado")  # lo que se reclama cada semana


def checklist(db: Session, a: Asset, hoy: date | None = None) -> list[dict]:
    hoy = hoy or date.today()
    filas = {x.clave: x for x in db.scalars(select(LegalItem).where(LegalItem.asset_id == a.id))}
    out = []
    for clave, grupo, titulo, norma, _, meses, opcional in aplicables(a.modalidad):
        out.append(_fila(filas.get(clave), clave, grupo, titulo, norma, meses, opcional, hoy))
    for clave, it in sorted(filas.items()):
        if clave.startswith("extra-"):
            out.append(_fila(it, clave, "propios", it.titulo or "Documento", "Punto propio del activo.", None,
                             False, hoy))
    return out


def _fila(it: LegalItem | None, clave, grupo, titulo, norma, meses, opcional, hoy) -> dict:
    e = estado(it, hoy)
    if opcional and e == "falta":
        e = "opcional"
    return {"clave": clave, "grupo": grupo, "grupo_nombre": GRUPOS.get(grupo, "Puntos propios del activo"),
            "titulo": titulo, "norma": norma, "meses": meses, "opcional": opcional, "estado": e,
            "estado_nombre": ESTADOS.get(e, "Opcional"), "id": it.id if it else None,
            "no_aplica": bool(it and it.no_aplica), "motivo": it.motivo if it else None,
            "fecha_documento": it.fecha_documento.isoformat() if it and it.fecha_documento else None,
            "vencimiento": it.vencimiento.isoformat() if it and it.vencimiento else None,
            "notas": it.notas if it else None,
            "ficheros": [{"id": f.id, "nombre": f.nombre, "tamano": f.tamano, "subido": f.subido.isoformat()}
                         for f in (it.ficheros if it else [])]}


def resumen(filas: list[dict]) -> dict:
    cuenta = {k: sum(1 for x in filas if x["estado"] == k) for k in (*ESTADOS, "opcional")}
    exigibles = [x for x in filas if x["estado"] not in ("no_aplica", "opcional")]
    hechos = sum(1 for x in exigibles if x["estado"] in ("aportado", "por_vencer"))
    return {**cuenta, "exigibles": len(exigibles), "completos": hechos,
            "porcentaje": round(100 * hechos / len(exigibles)) if exigibles else 100,
            "pendientes": cuenta["falta"] + cuenta["caducado"]}


# --------------------------------------------------------------------------- PDF del checklist
def pdf_checklist(db: Session, a: Asset, filas: list[dict]) -> bytes:
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, Spacer

    from .partes_trabajo import _doc_pdf, _esc, _estilos, _tabla
    r = resumen(filas)
    titulo = f"Documentación legal · {a.nombre}"
    out, doc, ancho, el = _doc_pdf(titulo, a, a.company)
    p, h = _estilos()
    el += [Paragraph(titulo, h),
           Paragraph(f"{date.today():%d/%m/%Y} · {r['completos']} de {r['exigibles']} documentos ({r['porcentaje']} %) · "
                     f"faltan {r['falta']} · caducados {r['caducado']} · por vencer {r['por_vencer']}", p),
           Spacer(1, 3 * mm)]
    datos = [["", "Documento", "Normativa / observaciones", "Fecha", "Vence", "Estado"]]
    for x in filas:
        marca_ = {"aportado": "OK", "por_vencer": "!", "caducado": "X", "falta": "[ ]", "no_aplica": "-",
                  "opcional": "( )"}.get(x["estado"], "")
        obs = _esc(x["norma"]) + (f"<br/><i>No aplica: {_esc(x['motivo'])}</i>" if x["no_aplica"] and x["motivo"]
                                  else "") + (f"<br/>{_esc(x['notas'])}" if x["notas"] else "")
        datos.append([marca_, Paragraph(f"<b>{_esc(x['titulo'])}</b><br/>{_esc(x['grupo_nombre'])}", p),
                      Paragraph(obs, p),
                      _f(x["fecha_documento"]), _f(x["vencimiento"]), x["estado_nombre"]])
    el.append(_tabla(datos, [10 * mm, 78 * mm, ancho - 164 * mm, 22 * mm, 22 * mm, 32 * mm]))
    doc.build(el)
    return out.getvalue()


def _f(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


# --------------------------------------------------------------------------- recordatorio semanal
def recordatorio_semanal(db: Session, dia: date) -> int:
    """Los lunes: a Recepción 1 de cada activo, lo que le falta a su activo; a la dirección (sin la presidencia),
    el resumen de todos los activos. Hasta que esté completo. No se repite en la misma semana."""
    from . import avisos
    from .ausencias import recepcion_1, usuarios_con
    from .models import EmailLog, User
    from .security import Scope
    if dia.weekday() != 0:
        return 0
    semana = f"{dia.isocalendar()[0]}-S{dia.isocalendar()[1]:02d}"
    por_activo = []
    for a in db.scalars(select(Asset).where(Asset.activo).order_by(Asset.codigo)):
        filas = [x for x in checklist(db, a, dia) if x["estado"] in PENDIENTES]
        if filas:
            por_activo.append((a, filas))
    if not por_activo:
        return 0
    envios: dict[int, tuple[User, list]] = {}
    for a, filas in por_activo:
        r1 = recepcion_1(db, a)
        if r1 is not None:
            envios.setdefault(r1.id, (r1, []))[1].append((a, filas))
    direccion = {u.id: u for a, _ in por_activo for u in usuarios_con(db, a.id, "legal.ver")
                 if not u.no_asignable and Scope(u, db).is_group_level("legal.ver")}
    for u in direccion.values():
        envios[u.id] = (u, por_activo)  # la dirección recibe el general
    enviados = 0
    for u, lista in envios.values():
        if not u.email or not avisos.quiere(u, "documentacion_legal"):
            continue
        clave = f"documentacion_legal:{semana}"
        if db.scalar(select(EmailLog.id).where(EmailLog.clave == clave, EmailLog.user_id == u.id, EmailLog.ok)):
            continue
        total = sum(len(f) for _, f in lista)
        asunto = f"Documentación legal pendiente: {total} documento(s) en {len(lista)} activo(s)"
        texto = "\n\n".join(f"{a.nombre.upper()}\n" + "\n".join(f"- {x['titulo']} ({x['estado_nombre'].lower()})"
                                                            for x in f) for a, f in lista)
        texto += "\n\nAporte los documentos en INVERPMS → Administración → Documentación legal."
        cuerpo = "".join(f'<h3 style="color:#13294b;margin:18px 0 6px">{escape(a.nombre)} ({len(f)})</h3>'
                         + avisos._tabla(["Documento", "Estado"], [[x["titulo"], x["estado_nombre"]] for x in f])
                         for a, f in lista)
        cuerpo += "<p>Aporte los documentos en <b>Administración → Documentación legal</b>.</p>"
        enviados += avisos._enviar_registrado(db, u, u.email, clave, "documentacion_legal", asunto, texto,
                                             avisos._html("Documentación legal pendiente", cuerpo))
    db.commit()
    return enviados
