"""Peticiones IA: asistente de INVERPMS para dirección y recepción.

Responde con los datos del PMS (siempre con los permisos del usuario que pregunta: cada recepción ve solo lo de su
activo), lee los documentos que se le adjuntan y los archiva en la carpeta del activo y en la cuenta de gastos, y
prepara tablas en Excel. Funciona con la API de Anthropic (clave en PMS_ANTHROPIC_API_KEY); el nombre del proveedor
no aparece en la interfaz.

El historial de la conversación lo guarda el navegador y se reenvía en cada petición tal cual lo devuelve la API
(solo se añade al final), como exige la API para conservar el razonamiento del modelo entre turnos.
"""
import base64
import json
import logging
from datetime import date, datetime
from io import BytesIO
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import documentos
from .config import settings
from .models import (CATEGORIAS_GASTO, TIPOS_DOCUMENTO, Asset, AuditLog, Expense, ReceivedDocument, Unit)
from .security import Scope, audit

log = logging.getLogger("pms.ia")

MAX_VUELTAS = 12  # llamadas a herramientas por petición
MAX_FILAS = 300  # filas que se devuelven al modelo por consulta
CLIENTE_PRUEBAS = None  # las pruebas automáticas sustituyen aquí el cliente de la API


def configurado() -> bool:
    return bool(settings.ia_api_key) or CLIENTE_PRUEBAS is not None


def _cliente():
    if CLIENTE_PRUEBAS is not None:
        return CLIENTE_PRUEBAS
    import anthropic
    return anthropic.Anthropic(api_key=settings.ia_api_key, timeout=600.0, max_retries=2)


# --------------------------------------------------------------------------- herramientas
CONSULTAS = ("activos", "panel", "reservas", "unidades", "clientes", "gastos", "documentos_recibidos",
             "ordenes_trabajo", "facturas", "alquileres_garaje", "contratos_alquiler")

HERRAMIENTAS = [
    {
        "name": "consultar",
        "description": (
            "Consulta datos del PMS con los permisos del usuario. Tipos: activos (lista de activos y sus id), panel "
            "(situación de hoy por activo: ocupación, llegadas, salidas, producción del mes, OT), reservas, unidades "
            "(apartamentos y plazas), clientes (huéspedes, inquilinos o clientes de garaje), gastos (cuenta de "
            "gastos), documentos_recibidos, ordenes_trabajo, facturas (emitidas), alquileres_garaje, "
            "contratos_alquiler (residencial). Devuelve como máximo 300 filas en JSON; afine con los filtros si hay "
            "más."),
        "input_schema": {
            "type": "object",
            "properties": {
                "tipo": {"type": "string", "enum": list(CONSULTAS)},
                "asset_id": {"type": "integer", "description": "Activo (id de la consulta «activos»)"},
                "desde": {"type": "string", "description": "Fecha inicial AAAA-MM-DD"},
                "hasta": {"type": "string", "description": "Fecha final AAAA-MM-DD"},
                "texto": {"type": "string", "description": "Texto a buscar (nombre, localizador, concepto…)"},
                "estado": {"type": "string", "description": "Estado (reservas: confirmada, checkin, checkout, "
                                                            "cancelada; OT: abiertas)"},
                "tipo_cliente": {"type": "string", "enum": ["huesped", "inquilino", "cliente_garaje"]},
            },
            "required": ["tipo"],
            "additionalProperties": False,
        },
    },
    {
        "name": "crear_excel",
        "description": (
            "Crea un fichero Excel descargable con una o varias hojas (tablas). Úselo siempre que el usuario pida "
            "una tabla, un listado o un informe en Excel. Los importes como números, las fechas como AAAA-MM-DD."),
        "input_schema": {
            "type": "object",
            "properties": {
                "titulo": {"type": "string", "description": "Nombre del fichero (sin extensión)"},
                "hojas": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "nombre": {"type": "string"},
                            "columnas": {"type": "array", "items": {"type": "string"}},
                            "filas": {"type": "array", "items": {"type": "array", "items": {}}},
                            "nota": {"type": "string", "description": "Texto bajo el título de la hoja"},
                        },
                        "required": ["nombre", "columnas", "filas"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["titulo", "hojas"],
            "additionalProperties": False,
        },
    },
    {
        "name": "archivar_documento",
        "description": (
            "Guarda un documento adjuntado en esta conversación en la carpeta de documentos recibidos del activo y, "
            "si es un gasto, lo anota en la cuenta de gastos. Use la referencia del adjunto que figura en el mensaje. "
            "Antes de archivar, muestre al usuario los datos que va a guardar y pida confirmación, salvo que ya le "
            "haya pedido expresamente que lo archive."),
        "input_schema": {
            "type": "object",
            "properties": {
                "adjunto": {"type": "string", "description": "Referencia del adjunto"},
                "asset_id": {"type": "integer"},
                "tipo": {"type": "string", "enum": list(TIPOS_DOCUMENTO)},
                "fecha": {"type": "string", "description": "Fecha del documento AAAA-MM-DD"},
                "emisor": {"type": "string"},
                "referencia": {"type": "string", "description": "Nº de factura o referencia"},
                "descripcion": {"type": "string"},
                "apartamento": {"type": "string", "description": "Código del apartamento si es de uno concreto"},
                "gasto": {
                    "type": "object",
                    "description": "Solo si es un gasto",
                    "properties": {
                        "categoria": {"type": "string", "enum": list(CATEGORIAS_GASTO)},
                        "concepto": {"type": "string"},
                        "total": {"type": "number", "description": "Importe total con IVA"},
                        "tipo_iva": {"type": "number", "enum": [0, 4, 5, 10, 21]},
                        "base": {"type": "number", "description": "Base imponible si hay varios tipos de IVA"},
                        "pagado": {"type": "boolean"},
                        "forma_pago": {"type": "string", "enum": ["efectivo", "tarjeta", "transferencia",
                                                                  "domiciliacion", "bizum", "plataforma"]},
                    },
                    "required": ["categoria", "concepto", "total", "tipo_iva"],
                    "additionalProperties": False,
                },
            },
            "required": ["adjunto", "asset_id", "tipo", "fecha"],
            "additionalProperties": False,
        },
    },
]


def _fecha(v: str | None) -> date | None:
    if not v:
        return None
    try:
        return date.fromisoformat(v[:10])
    except ValueError:
        raise ValueError(f"Fecha no válida: {v} (use AAAA-MM-DD)")


def _consultar(db: Session, scope: Scope, p: dict) -> Any:
    from .routers import (alquiler, estructura, facturas, garajes, gastos, mantenimiento, panel,  # noqa: I001
                          turistico)
    tipo, aid = p["tipo"], p.get("asset_id")
    desde, hasta, texto = _fecha(p.get("desde")), _fecha(p.get("hasta")), p.get("texto") or None
    if tipo == "activos":
        return estructura.list_assets(scope, db)
    if tipo == "panel":
        return panel.panel(scope, db)
    if tipo == "reservas":
        return turistico.list_reservations(aid, desde, hasta, p.get("estado"), texto, scope, db)
    if tipo == "unidades":
        return estructura.list_units(aid, None, texto, None, None, scope, db)
    if tipo == "clientes":
        return estructura.list_contacts(p.get("tipo_cliente") or "huesped", None, aid, texto, scope, db)
    if tipo == "gastos":
        return gastos.list_expenses(aid, desde, hasta, None, None, None, scope, db)
    if tipo == "documentos_recibidos":
        return gastos.list_documents(aid, None, desde, hasta, texto, scope, db)
    if tipo == "ordenes_trabajo":
        return mantenimiento.list_orders(aid, None, p.get("estado") == "abiertas", None, scope, db)
    if tipo == "facturas":
        filas = facturas.list_invoices(aid, desde.year if desde else None, None, texto, None, None, scope, db)
        return [f for f in filas if (not desde or f["fecha_expedicion"] >= desde.isoformat())
                and (not hasta or f["fecha_expedicion"] <= hasta.isoformat())]
    if tipo == "alquileres_garaje":
        return garajes.list_garage_leases(aid, p.get("estado"), texto, scope, db)
    if tipo == "contratos_alquiler":
        return alquiler.list_leases(aid, p.get("estado"), scope, db)
    raise ValueError(f"Consulta no válida: {tipo}")


def _recortar(datos: Any) -> str:
    if isinstance(datos, dict) and isinstance(datos.get("gastos"), list):
        filas, extra = datos["gastos"], {"totales": datos.get("totales")}
    elif isinstance(datos, list):
        filas, extra = datos, {}
    else:
        return json.dumps(datos, ensure_ascii=False, default=str)
    out = {"filas": filas[:MAX_FILAS], "total_filas": len(filas), **extra}
    if len(filas) > MAX_FILAS:
        out["aviso"] = f"Solo se muestran {MAX_FILAS} de {len(filas)} filas: afine los filtros"
    return json.dumps(out, ensure_ascii=False, default=str)


def _crear_excel(db: Session, scope: Scope, p: dict) -> tuple[str, dict]:
    from openpyxl import Workbook

    from .routers.informes import _hoja
    wb = Workbook()
    wb.remove(wb.active)
    usados = set()
    for h in p["hojas"][:20]:
        nombre = "".join(c for c in str(h.get("nombre") or "Hoja") if c not in "[]:*?/\\")[:31] or "Hoja"
        while nombre in usados:
            nombre = f"{nombre[:28]}_{len(usados)}"
        usados.add(nombre)
        filas = [[(_fecha(v) if isinstance(v, str) and len(v) == 10 and v[4] == "-" and v[7] == "-" else v)
                  for v in f] for f in (h.get("filas") or [])[:20000]]
        _hoja(wb, nombre, [str(c) for c in h["columnas"]], filas, nota=h.get("nota"))
    out = BytesIO()
    wb.properties.creator = "INVERPMS"
    wb.save(out)
    titulo = "".join(c for c in str(p.get("titulo") or "") if c.isalnum() or c in " _-").strip()[:80] or "informe"
    fichero = documentos.guardar(out.getvalue())
    audit(db, scope.user, "ia_excel", "ia", None, {"fichero": fichero, "nombre": f"{titulo}.xlsx"})
    db.commit()
    f = {"nombre": f"{titulo}.xlsx", "url": f"/api/ia/ficheros/{fichero}"}
    return json.dumps({"ok": True, "fichero": f["nombre"], "aviso": "El usuario ya ve el enlace de descarga"},
                      ensure_ascii=False), f


def adjunto_propio(db: Session, scope: Scope, fichero: str) -> dict:
    """Datos del adjunto si lo subió este usuario (se comprueba en el registro de auditoría)."""
    for d in db.scalars(select(AuditLog.detalle).where(AuditLog.user_id == scope.user.id,
                                                      AuditLog.accion == "ia_adjunto").order_by(AuditLog.id.desc())
                        .limit(500)):
        if d and d.get("fichero") == fichero:
            return d
    raise ValueError("Adjunto no encontrado en esta conversación")


def _archivar(db: Session, scope: Scope, p: dict) -> tuple[str, dict]:
    from .routers.gastos import ExpenseIn, _valores_gasto
    adj = adjunto_propio(db, scope, p["adjunto"])
    a = db.get(Asset, p["asset_id"])
    if a is None:
        raise ValueError("Activo no encontrado")
    if not scope.can_asset("documentos.editar", a.id):
        raise HTTPException(403, f"Sin permiso para archivar documentos en {a.nombre}")
    unidad = None
    if p.get("apartamento"):
        unidad = db.scalar(select(Unit).where(Unit.asset_id == a.id, Unit.codigo == p["apartamento"].strip()))
        if unidad is None:
            raise ValueError(f"El apartamento {p['apartamento']} no existe en {a.nombre}")
    datos = documentos.leer(adj["fichero"])
    fecha = _fecha(p["fecha"]) or date.today()
    x = ReceivedDocument(asset_id=a.id, unit_id=unidad.id if unidad else None, tipo=p["tipo"], fecha=fecha,
                         emisor=p.get("emisor") or None, referencia=p.get("referencia") or None,
                         descripcion=p.get("descripcion") or None, nombre=adj["nombre"],
                         fichero=documentos.guardar(datos), mime=adj["mime"], tamano=len(datos),
                         sha256=documentos.huella(datos), user_id=scope.user.id)
    db.add(x)
    db.flush()
    g = None
    if p.get("gasto"):
        gi = ExpenseIn(fecha=fecha, ambito="apartamento" if unidad else "general",
                       unit_id=unidad.id if unidad else None, proveedor=p.get("emisor"),
                       numero_factura=p.get("referencia"), **p["gasto"])
        g = Expense(asset_id=a.id, documento_id=x.id, user_id=scope.user.id, **_valores_gasto(db, a.id, gi))
        db.add(g)
        db.flush()
    audit(db, scope.user, "subir", "documento_recibido", x.id, {"tipo": x.tipo, "emisor": x.emisor,
                                                                 "gasto": g.id if g else None, "via": "ia"})
    db.commit()
    accion = {"texto": f"{TIPOS_DOCUMENTO[x.tipo]} archivada en {a.nombre}"
                       + (f" · gasto de {float(g.total):.2f} € anotado" if g else ""), "vista": "docrecibidos"}
    return json.dumps({"ok": True, "documento_id": x.id, "gasto_id": g.id if g else None,
                       "gasto_total": float(g.total) if g else None}, ensure_ascii=False), accion


def ejecutar(db: Session, scope: Scope, nombre: str, entrada: dict) -> tuple[str, bool, dict | None, dict | None]:
    """(resultado, es_error, fichero creado, acción realizada)."""
    try:
        if nombre == "consultar":
            if entrada.get("tipo") not in CONSULTAS:
                raise ValueError("Tipo de consulta no válido")
            return _recortar(_consultar(db, scope, entrada)), False, None, None
        if nombre == "crear_excel":
            if not isinstance(entrada.get("hojas"), list) or not entrada["hojas"]:
                raise ValueError("Indique al menos una hoja con columnas y filas")
            r, f = _crear_excel(db, scope, entrada)
            return r, False, f, None
        if nombre == "archivar_documento":
            r, a = _archivar(db, scope, entrada)
            return r, False, None, a
        return f"Herramienta desconocida: {nombre}", True, None, None
    except HTTPException as e:
        db.rollback()
        return f"Sin permiso o dato no válido: {e.detail}", True, None, None
    except (ValueError, KeyError, TypeError) as e:
        db.rollback()
        return f"Error: {e}", True, None, None


# --------------------------------------------------------------------------- conversación
def _sistema(db: Session, scope: Scope) -> str:
    activos = [f"{a['id']}: {a['nombre']} ({a['modalidad']})" for a in _consultar(db, scope, {"tipo": "activos"})]
    roles = ", ".join(sorted({a.role.nombre for a in scope.user.assignments})) or (
        "Superadministrador" if scope.user.is_superadmin else "—")
    return (
        "Eres el Asistente de INVERPMS, el programa de gestión del Grupo INVERSIETE (gestión de activos "
        "inmobiliarios: apartamentos turísticos, alquiler residencial y garajes). Atiendes las «Peticiones IA» de "
        "dirección y recepción. Preséntate solo como «Asistente de INVERPMS»; no menciones el modelo ni la "
        "empresa que hay detrás.\n\n"
        "Cómo trabajas:\n"
        "- Responde en español de España, profesional, claro y breve. Importes en euros con dos decimales.\n"
        "- Los datos salen siempre de la herramienta «consultar», con los permisos del usuario: no inventes cifras "
        "ni nombres. Si una consulta no devuelve nada o no hay permiso, dilo.\n"
        "- Si piden una tabla, un listado o un informe para descargar, crea el Excel con «crear_excel».\n"
        "- Si adjuntan un documento (factura, ticket, carta…), léelo, resume lo importante (emisor, fecha, nº, "
        "importes con IVA, a qué apartamento o zona se refiere) y propón dónde archivarlo y, si es un gasto, la "
        "categoría. Archívalo con «archivar_documento» cuando el usuario lo confirme o lo haya pedido.\n"
        "- La ocupación y la producción del edificio se calculan solo con apartamentos: las plazas de garaje van "
        "aparte y no computan.\n"
        "- No compartas datos personales de clientes salvo lo necesario para la petición.\n\n"
        f"Usuario: {scope.user.nombre} · perfil: {roles}.\n"
        f"Activos a los que tiene acceso (id: nombre): {'; '.join(activos) or 'ninguno'}.\n"
        f"Fecha de hoy: {date.today().isoformat()}."
    )


def _eco(contenido: list[dict]) -> list[dict]:
    """Bloques de la respuesta para reenviarlos en el historial. Si el modelo de respaldo tomó el relevo a mitad de
    respuesta, se omiten el razonamiento y las llamadas del tramo anterior al último bloque «fallback»."""
    corte = max((i for i, b in enumerate(contenido) if b.get("type") == "fallback"), default=-1)
    if corte < 0:
        return contenido
    previos = [b for b in contenido[:corte] if b.get("type") == "text"]
    return previos + contenido[corte:]


def mensaje_usuario(db: Session, scope: Scope, texto: str, adjuntos: list[str]) -> dict:
    partes: list[dict] = []
    for ref in adjuntos[:5]:
        try:
            adj = adjunto_propio(db, scope, ref)
        except ValueError:
            raise HTTPException(400, "Adjunto no encontrado: vuelva a adjuntarlo")
        datos = base64.standard_b64encode(documentos.leer(adj["fichero"])).decode()
        if adj["mime"] == "application/pdf":
            partes.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                          "data": datos}, "title": adj["nombre"]})
        else:
            partes.append({"type": "image", "source": {"type": "base64", "media_type": adj["mime"], "data": datos}})
        partes.append({"type": "text", "text": f"[Adjunto «{adj['nombre']}» · referencia para archivar: {ref}]"})
    partes.append({"type": "text", "text": texto.strip() or "Revisa el documento adjunto."})
    return {"role": "user", "content": partes}


def conversar(db: Session, scope: Scope, historial: list[dict], texto: str, adjuntos: list[str]) -> dict:
    if not configurado():
        raise HTTPException(503, "Las Peticiones IA no están configuradas en el servidor (falta la clave de la API)")
    mensajes = list(historial) + [mensaje_usuario(db, scope, texto, adjuntos)]
    sistema = _sistema(db, scope)
    cliente = _cliente()
    ficheros, acciones, respuesta = [], [], None
    for _ in range(MAX_VUELTAS):
        try:
            r = cliente.beta.messages.create(
                model=settings.ia_modelo, max_tokens=16000, system=sistema, tools=HERRAMIENTAS, messages=mensajes,
                output_config={"effort": settings.ia_esfuerzo}, cache_control={"type": "ephemeral"},
                betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        except Exception as e:  # noqa: BLE001 — se informa al usuario sin tumbar el PMS
            log.warning("Peticiones IA: error de la API: %s", e)
            raise HTTPException(502, f"El servicio de IA no ha respondido: {str(e)[:200]}")
        contenido = [b.to_dict() for b in r.content]
        respuesta = r
        if r.stop_reason == "refusal":
            mensajes.append({"role": "assistant", "content": [{"type": "text", "text": "No puedo ayudar con esa "
                                                                                        "petición."}]})
            break
        mensajes.append({"role": "assistant", "content": _eco(contenido)})
        llamadas = [b for b in r.content if b.type == "tool_use"]
        if r.stop_reason != "tool_use" or not llamadas:
            break
        resultados = []
        for b in llamadas:
            res, error, fichero, accion = ejecutar(db, scope, b.name, dict(b.input or {}))
            if fichero:
                ficheros.append(fichero)
            if accion:
                acciones.append(accion)
            resultados.append({"type": "tool_result", "tool_use_id": b.id, "content": res,
                               **({"is_error": True} if error else {})})
        mensajes.append({"role": "user", "content": resultados})
    else:
        mensajes.append({"role": "user", "content": [{"type": "text", "text": "(límite de pasos alcanzado)"}]})
    texto_resp = ""
    if respuesta is not None and respuesta.stop_reason == "refusal":
        texto_resp = "No puedo ayudar con esa petición."
    else:
        ult = next((m for m in reversed(mensajes) if m["role"] == "assistant"), None)
        texto_resp = "\n\n".join(b["text"] for b in (ult or {}).get("content", []) if b.get("type") == "text")
        if respuesta is not None and respuesta.stop_reason == "max_tokens":
            texto_resp += "\n\n(La respuesta se ha cortado por su extensión: pida que continúe.)"
    audit(db, scope.user, "ia_peticion", "ia", None, {
        "pregunta": texto[:300], "adjuntos": len(adjuntos), "ficheros": [f["nombre"] for f in ficheros],
        "acciones": [a["texto"] for a in acciones],
        "tokens": getattr(getattr(respuesta, "usage", None), "output_tokens", None)})
    db.commit()
    return {"historial": mensajes, "respuesta": texto_resp.strip() or "(sin respuesta)", "ficheros": ficheros,
            "acciones": acciones, "hora": datetime.now().isoformat(timespec="seconds")}
