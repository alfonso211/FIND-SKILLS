"""Control del preventivo y de las inspecciones OCA.

Cada plan (revisión de una empresa mantenedora o inspección reglamentaria por un organismo de control) lleva su
historial de revisiones: fecha, resultado, próxima fecha que indica el documento, puntos comprobados, deficiencias y
los documentos de la empresa (informe, acta, certificado). Al registrar una revisión:

- la próxima fecha del plan pasa a ser la del documento (si no la indica, la fecha de la revisión + la periodicidad);
- si no coincide con la periodicidad del plan, se avisa para contrastarlo (puede estar mal el plan o el documento);
- cada deficiencia genera su orden de trabajo, con prioridad según la gravedad y plazo hasta la fecha de subsanación;
- la OT preventiva abierta del plan queda cerrada con el resultado.

El semáforo de cada plan junta todo: vencido, próximo, deficiencias sin subsanar, plazo de subsanación vencido,
revisión sin documento o próxima fecha que no cuadra.
"""
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PreventivePlan, PreventiveRevision, RevisionAttachment, Supplier, User, WorkOrder

TIPOS_PLAN = {"mantenimiento": "Mantenimiento preventivo", "oca": "Inspección OCA (organismo de control)"}
# resultado -> (texto, hay deficiencias)
RESULTADOS = {
    "correcto": ("Correcto", False),
    "deficiencias": ("Con deficiencias", True),
    "favorable": ("Favorable", False),
    "favorable_leves": ("Favorable con defectos leves", True),
    "desfavorable": ("Desfavorable / condicionada (defectos graves)", True),
    "negativa": ("Negativa (defectos muy graves: instalación fuera de servicio)", True),
}
RESULTADOS_TIPO = {"mantenimiento": ("correcto", "deficiencias"),
                   "oca": ("favorable", "favorable_leves", "desfavorable", "negativa")}
GRAVEDADES = {"leve": "Leve", "grave": "Grave", "muy_grave": "Muy grave"}
PRIORIDAD = {"leve": "media", "grave": "alta", "muy_grave": "urgente"}
PLAZO_DIAS = {"leve": 60, "grave": 30, "muy_grave": 2}  # si el documento no fija plazo de subsanación
ESTADOS_PUNTO = ("ok", "deficiencia", "na")
AVISO_DIAS = 30  # «próximo»: vence dentro de este plazo
DESFASE_DIAS = 31  # diferencia admitida entre la próxima fecha del documento y la periodicidad del plan

CHECKLIST_OCA = [
    "Acta o certificado de inspección recibido y firmado",
    "Número de acta y organismo de control anotados",
    "Resultado y defectos anotados",
    "Plazo de subsanación anotado (si hay defectos)",
    "Etiqueta o placa de inspección colocada en la instalación",
]
CHECKLIST = {
    "pci": ["Extintores: presión, precinto, etiqueta y accesibilidad", "Bocas de incendio (BIE): presión y manguera",
            "Detección y alarma: centralita, detectores y pulsadores", "Alumbrado de emergencia: encendido y autonomía",
            "Señalización de evacuación visible", "Puertas cortafuegos: cierre y retenedores",
            "Registro de la revisión firmado por la mantenedora habilitada"],
    "climatizacion": ["Filtros limpios o sustituidos", "Baterías y bandejas de condensados limpias",
                      "Sin fugas de refrigerante", "Temperaturas y presiones de trabajo correctas",
                      "Libro de mantenimiento RITE actualizado"],
    "acs": ["Temperatura del acumulador ≥ 60 °C", "Temperatura de retorno ≥ 50 °C",
            "Puntos terminales ≥ 50 °C tras 1 minuto", "Purga de acumuladores realizada",
            "Registro del control anotado (RD 487/2022)"],
    "ascensores": ["Visita de la conservadora realizada", "Paracaídas, frenos y limitador de velocidad",
                   "Puertas de piso y de cabina", "Alarma y comunicación bidireccional", "Libro del ascensor firmado"],
    "electricidad": ["Cuadros: apriete y ausencia de calentamientos", "Prueba de diferenciales",
                     "Toma de tierra", "Termografía sin puntos calientes", "Alumbrado de zonas comunes"],
    "fontaneria": ["Grupo de presión: presiones y arranques", "Sin fugas en bombas y valvulería",
                   "Vaso de expansión", "Válvulas de corte operativas"],
    "cubiertas": ["Canalones y bajantes limpios", "Impermeabilización sin daños", "Sumideros libres"],
    "plagas": ["Tratamiento aplicado según plan", "Certificado de tratamiento DDD", "Puntos de cebo revisados"],
}
CHECKLIST_GENERAL = ["Trabajo realizado según el plan", "Informe o parte de la empresa recibido"]


def checklist_de(plan: PreventivePlan) -> list[str]:
    """Puntos a comprobar en la revisión: los fijados en el plan o los de su instalación."""
    if plan.checklist:
        return [str(x) for x in plan.checklist if str(x).strip()]
    if plan.tipo == "oca":
        return CHECKLIST_OCA
    return CHECKLIST.get(plan.categoria, CHECKLIST_GENERAL)


def ultima(db: Session, plan_id: int) -> PreventiveRevision | None:
    return db.scalar(select(PreventiveRevision).where(PreventiveRevision.plan_id == plan_id)
                     .order_by(PreventiveRevision.fecha.desc(), PreventiveRevision.id.desc()).limit(1))


def proxima_calculada(plan: PreventivePlan, fecha: date) -> date:
    return fecha + timedelta(days=plan.periodicidad_dias)


def desfase(plan: PreventivePlan, fecha: date, proxima: date | None) -> str | None:
    """Aviso si la próxima fecha del documento no cuadra con la periodicidad del plan."""
    if not proxima:
        return None
    calc = proxima_calculada(plan, fecha)
    if abs((proxima - calc).days) <= DESFASE_DIAS:
        return None
    return (f"El documento indica la próxima revisión el {proxima:%d/%m/%Y}, pero según la periodicidad del plan "
            f"(cada {plan.periodicidad_dias} días) tocaría el {calc:%d/%m/%Y}. Compruebe cuál es la buena.")


# --------------------------------------------------------------------------- semáforo
ESTADOS = {  # estado -> (texto, color, orden)
    "subsanacion_vencida": ("Plazo de subsanación vencido", "rojo", 0),
    "vencido": ("Vencido", "rojo", 1),
    "deficiencias": ("Deficiencias sin subsanar", "naranja", 2),
    "proximo": ("Próximo", "ambar", 3),
    "al_dia": ("Al día", "verde", 4),
    "inactivo": ("Inactivo", "gris", 5),
}


def estado(db: Session, p: PreventivePlan, hoy: date, abiertas: set[str]) -> dict:
    """Estado del plan para el control: semáforo, última revisión, deficiencias abiertas y avisos."""
    r = ultima(db, p.id)
    avisos: list[str] = []
    pendientes, vencida = [], False
    if r:
        for d in r.deficiencias or []:
            w = db.get(WorkOrder, d.get("ot_id")) if d.get("ot_id") else None
            if w and w.estado in abiertas:
                pendientes.append({"descripcion": d.get("descripcion"), "gravedad": d.get("gravedad"), "ot_id": w.id,
                                   "estado": w.estado})
        if pendientes and r.plazo_subsanacion and r.plazo_subsanacion < hoy:
            vencida = True
        n_docs = db.scalar(select(RevisionAttachment.id).where(RevisionAttachment.revision_id == r.id).limit(1))
        if not n_docs:
            avisos.append("La última revisión no tiene el documento de la empresa")
        if aviso := desfase(p, r.fecha, r.proxima):
            avisos.append(aviso)
        if r.resultado == "negativa" and pendientes:
            avisos.append("Inspección negativa: la instalación no puede usarse hasta subsanar")
    elif p.activo:
        avisos.append("Sin ninguna revisión registrada")
    # con la OT preventiva ya generada (el plan ya avanzó su próxima fecha), vence lo que diga esa OT
    ot = preventiva_abierta(db, p.id, abiertas)
    vence = min(p.proxima_fecha, ot.fecha_prevista) if ot and ot.fecha_prevista else p.proxima_fecha
    if not p.activo:
        clave = "inactivo"
    elif vencida:
        clave = "subsanacion_vencida"
    elif vence < hoy:
        clave = "vencido"
    elif pendientes:
        clave = "deficiencias"
    elif vence <= hoy + timedelta(days=AVISO_DIAS):
        clave = "proximo"
    else:
        clave = "al_dia"
    texto, color, orden = ESTADOS[clave]
    return {"estado": clave, "estado_nombre": texto, "color": color, "orden": orden, "vence": vence.isoformat(),
            "dias": (vence - hoy).days, "ot_preventiva": ot.id if ot else None, "avisos": avisos,
            "deficiencias_abiertas": pendientes, "ultima": revision_out(db, r, breve=True) if r else None}


def preventiva_abierta(db: Session, plan_id: int, abiertas) -> WorkOrder | None:
    """La OT preventiva del plan pendiente de hacer (no las OT de las deficiencias, que también llevan el plan)."""
    return db.scalar(select(WorkOrder).where(WorkOrder.plan_id == plan_id, WorkOrder.tipo == "preventivo",
                                             WorkOrder.estado.in_(abiertas)).order_by(WorkOrder.id).limit(1))


def revision_out(db: Session, r: PreventiveRevision, breve: bool = False) -> dict:
    d = r.to_dict()
    d["resultado_nombre"] = RESULTADOS.get(r.resultado, (r.resultado,))[0]
    d["con_deficiencias"] = RESULTADOS.get(r.resultado, ("", False))[1]
    docs = list(db.scalars(select(RevisionAttachment).where(RevisionAttachment.revision_id == r.id)
                           .order_by(RevisionAttachment.id)))
    d["documentos"] = [{"id": a.id, "nombre": a.nombre, "mime": a.mime, "tamano": a.tamano} for a in docs]
    if not breve:
        d["usuario"] = db.scalar(select(User.nombre).where(User.id == r.user_id)) if r.user_id else None
        for x in d.get("deficiencias") or []:
            w = db.get(WorkOrder, x.get("ot_id")) if x.get("ot_id") else None
            x["ot_estado"] = w.estado if w else None
    return d


# --------------------------------------------------------------------------- registrar una revisión
def registrar(db: Session, p: PreventivePlan, user: User, datos: dict) -> tuple[PreventiveRevision, list[WorkOrder]]:
    """Guarda la revisión, genera las OT de las deficiencias, cierra la OT preventiva abierta y fija la próxima
    fecha del plan. `datos` ya validado (schemas.RevisionIn)."""
    from .routers.mantenimiento import ABIERTAS
    fecha: date = datos["fecha"]
    if fecha > date.today():
        raise ValueError("La fecha de la revisión no puede ser futura")
    if datos["resultado"] not in RESULTADOS_TIPO[p.tipo]:
        raise ValueError(f"Resultado no válido para {TIPOS_PLAN[p.tipo].lower()}")
    con_def = RESULTADOS[datos["resultado"]][1]
    puntos = [{"punto": str(x.get("punto") or "")[:200], "estado": x.get("estado") if x.get("estado") in ESTADOS_PUNTO
               else "ok", "nota": (str(x.get("nota") or "").strip()[:300] or None)} for x in datos.get("checklist") or []]
    deficiencias = [{"descripcion": str(d.get("descripcion") or "").strip()[:300],
                     "gravedad": d.get("gravedad") if d.get("gravedad") in GRAVEDADES else "leve"}
                    for d in datos.get("deficiencias") or [] if str(d.get("descripcion") or "").strip()]
    # un punto marcado como deficiencia y no descrito aparte: también es una deficiencia
    descritas = {d["descripcion"].lower() for d in deficiencias}
    for x in puntos:
        if x["estado"] == "deficiencia":
            texto = x["punto"] + (f": {x['nota']}" if x["nota"] else "")
            if texto.lower() not in descritas and x["punto"].lower() not in descritas:
                deficiencias.append({"descripcion": texto[:300], "gravedad": "leve"})
    if con_def and not deficiencias:
        raise ValueError("Indique al menos una deficiencia (o marque el punto con deficiencia en la lista)")
    if not con_def and deficiencias:
        raise ValueError("Hay deficiencias anotadas: el resultado no puede ser «correcto» ni «favorable»")
    proveedor = db.get(Supplier, datos["proveedor_id"]) if datos.get("proveedor_id") else None
    empresa = (datos.get("empresa") or "").strip() or (proveedor.nombre if proveedor else None) or p.proveedor
    plazo = datos.get("plazo_subsanacion")
    if deficiencias and not plazo:
        peor = max((d["gravedad"] for d in deficiencias), key=list(GRAVEDADES).index)
        plazo = fecha + timedelta(days=PLAZO_DIAS[peor])
    preventiva = preventiva_abierta(db, p.id, ABIERTAS)
    r = PreventiveRevision(plan_id=p.id, asset_id=p.asset_id, fecha=fecha,
                           fecha_prevista=preventiva.fecha_prevista if preventiva and preventiva.fecha_prevista
                           else p.proxima_fecha,
                           proxima=datos.get("proxima") or proxima_calculada(p, fecha), resultado=datos["resultado"],
                           empresa=empresa, proveedor_id=proveedor.id if proveedor else p.proveedor_id,
                           tecnico=(datos.get("tecnico") or "").strip() or None,
                           numero=(datos.get("numero") or "").strip() or None, plazo_subsanacion=plazo,
                           checklist=puntos or None, observaciones=(datos.get("observaciones") or "").strip() or None,
                           user_id=user.id)
    db.add(r)
    db.flush()
    ots = []
    ref = f"{'Acta' if p.tipo == 'oca' else 'Revisión'} {r.numero or f'REV-{r.id}'} del {fecha:%d/%m/%Y}"
    for d in deficiencias:
        w = WorkOrder(asset_id=p.asset_id, plan_id=p.id, tipo="normativo" if p.tipo == "oca" else "correctivo",
                      categoria=p.categoria, prioridad=PRIORIDAD[d["gravedad"]],
                      titulo=f"Subsanar: {d['descripcion']}"[:200],
                      descripcion=(f"{p.titulo}\n{ref}{f' · {empresa}' if empresa else ''}\nDeficiencia {GRAVEDADES[d['gravedad']].lower()}: "
                                   f"{d['descripcion']}\nPlazo de subsanación: {plazo:%d/%m/%Y}"),
                      fecha_prevista=plazo, abierta_por=user.id,
                      proveedor=None if p.tipo == "oca" else p.proveedor)
        db.add(w)
        db.flush()
        d["ot_id"] = w.id
        ots.append(w)
    r.deficiencias = deficiencias or None
    if preventiva:  # la OT preventiva de este plan queda hecha con la revisión
        ahora = datetime.now()
        preventiva.conf_mto_fecha = preventiva.conf_mto_fecha or ahora
        preventiva.conf_mto_por = preventiva.conf_mto_por or user.id
        preventiva.estado, preventiva.fecha_cierre, preventiva.cerrada_por = "cerrada", date.today(), user.id
        preventiva.conformidad_en = ahora
        preventiva.solucion = (f"{preventiva.solucion or ''}\n{ref}: {RESULTADOS[r.resultado][0]}"
                               + (f" · {len(ots)} deficiencia(s) con su OT" if ots else "")).strip()
        r.work_order_id = preventiva.id
    p.proxima_fecha = r.proxima
    return r, ots


# --------------------------------------------------------------------------- aviso semanal al director técnico
def aviso_semanal(db: Session, hoy: date, forzar: bool = False) -> int:
    """Los lunes: planes vencidos, deficiencias sin subsanar (y plazos vencidos) e inspecciones OCA de los próximos
    60 días. Solo si hay algo que contar; una vez por semana."""
    from . import avisos
    from .config import settings
    from .models import Asset, EmailLog
    from .routers.mantenimiento import ABIERTAS
    if hoy.weekday() != 0 and not forzar:
        return 0
    clave = f"preventivo_semanal:{hoy.isoformat()}"
    if db.scalar(select(EmailLog.id).where(EmailLog.clave == clave)):
        return 0
    filas = []
    for p in db.scalars(select(PreventivePlan).where(PreventivePlan.activo).order_by(PreventivePlan.proxima_fecha)):
        e = estado(db, p, hoy, ABIERTAS)
        oca_cerca = p.tipo == "oca" and e["dias"] <= 60
        if e["color"] in ("rojo", "naranja") or oca_cerca:
            activo = db.scalar(select(Asset.nombre).where(Asset.id == p.asset_id))
            detalle = "; ".join(f"{d['descripcion']} (OT-{d['ot_id']:05d})" for d in e["deficiencias_abiertas"])
            filas.append((e["orden"], [activo, f"{'OCA · ' if p.tipo == 'oca' else ''}{p.titulo}", e["estado_nombre"],
                                       f"{date.fromisoformat(e['vence']):%d/%m/%Y}", detalle or " · ".join(e["avisos"])]))
    if not filas:
        return 0
    filas = [f for _, f in sorted(filas, key=lambda x: x[0])]
    asunto = f"PMS · Control de preventivo y OCA · {len(filas)} planes a revisar"
    texto = asunto + "\n\n" + "\n".join(" | ".join(str(c) for c in f) for f in filas)
    html = avisos._html("Control de preventivo y OCA", avisos._tabla(
        ["Activo", "Plan", "Estado", "Vence", "Detalle"], filas))
    n = 0
    for dest in {settings.mantenimiento_email}:
        u = db.scalar(select(User).where(User.email == dest))
        n += avisos._enviar_registrado(db, u, dest, clave, "preventivo", asunto, texto, html)
    db.commit()
    return n
