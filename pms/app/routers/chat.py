"""Avisos dentro del PMS (campana con sonido) y chat interno del equipo.

- Avisos: cada aviso «al momento» que el PMS manda por correo a un usuario queda también en su campana (y suena en
  el navegador). Se crean en avisos._enviar_registrado; aquí se leen y se marcan como vistos.
- Chat: «Todo el equipo» (todos los usuarios internos activos), conversaciones de dos personas y grupos. Quien crea un
  grupo elige a las personas y es quien puede añadir o quitar a otras más adelante; cualquiera puede salir. Solo ven
  los mensajes los miembros (tampoco la Dirección ve chats ajenos). Los colaboradores externos no tienen chat.
"""
import re
import unicodedata
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import adjuntos, avisos, documentos
from ..database import get_db
from ..models import ChatAdjunto, ChatConversacion, ChatMensaje, ChatMiembro, Notificacion, User
from ..security import current_user
from ..utils import bad_request

router = APIRouter(prefix="/api", tags=["chat y avisos"])

MAX_TEXTO = 4000
MAX_MIEMBROS = 100
MAX_ADJUNTOS = 5  # por mensaje (fotos o PDF de hasta 20 MB; las fotos se reducen y pierden la ubicación GPS)


def _interno(u: User | None) -> bool:
    return bool(u and u.activo and u.supplier_id is None)


# --------------------------------------------------------------------------- avisos (campana)
def _notif_out(n: Notificacion) -> dict:
    return {"id": n.id, "tipo": n.tipo, "titulo": n.titulo, "texto": n.texto, "vista": n.vista, "urgente": n.urgente,
            "creada": n.creada.isoformat(timespec="seconds"), "leida": n.leida is not None}


@router.get("/notificaciones")
def mis_notificaciones(user: User = Depends(current_user), db: Session = Depends(get_db)):
    filas = db.scalars(select(Notificacion).where(Notificacion.user_id == user.id)
                       .order_by(Notificacion.id.desc()).limit(50))
    return [_notif_out(n) for n in filas]


@router.post("/notificaciones/leidas")
def marcar_leidas(user: User = Depends(current_user), db: Session = Depends(get_db)):
    ahora = datetime.now()
    n = 0
    for x in db.scalars(select(Notificacion).where(Notificacion.user_id == user.id, Notificacion.leida.is_(None))):
        x.leida, n = ahora, n + 1
    db.commit()
    return {"leidas": n}


@router.get("/notificaciones/estado")
def estado(desde: int | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Lo que consulta el navegador cada pocos segundos: avisos nuevos (para que suenen) y mensajes sin leer. La
    primera consulta va sin `desde` (solo da la referencia `ultima`); las siguientes, con la `ultima` recibida."""
    nuevas = [_notif_out(n) for n in db.scalars(select(Notificacion).where(
        Notificacion.user_id == user.id, Notificacion.id > desde).order_by(Notificacion.id).limit(20))] if desde is not None else []
    sin_leer = db.scalar(select(func.count()).select_from(Notificacion).where(
        Notificacion.user_id == user.id, Notificacion.leida.is_(None))) or 0
    ultima = db.scalar(select(func.max(Notificacion.id)).where(Notificacion.user_id == user.id)) or 0
    chat = _resumen_chat(db, user) if _interno(user) else {"no_leidos": 0, "ultimo": 0, "nuevos": []}
    return {"ultima": ultima, "nuevas": nuevas, "sin_leer": sin_leer, "chat": chat}


# --------------------------------------------------------------------------- chat
def _todos(db: Session) -> ChatConversacion:
    c = db.scalar(select(ChatConversacion).where(ChatConversacion.tipo == "todos").limit(1))
    if c is None:
        c = ChatConversacion(tipo="todos", titulo="Todo el equipo")
        db.add(c)
        db.flush()
    return c


def _miembro(db: Session, c: ChatConversacion, user: User, crear: bool = False) -> ChatMiembro | None:
    m = db.scalar(select(ChatMiembro).where(ChatMiembro.conversacion_id == c.id, ChatMiembro.user_id == user.id))
    if m is None and c.tipo == "todos" and crear:  # todo el equipo: la fila de lectura se crea al entrar
        m = ChatMiembro(conversacion_id=c.id, user_id=user.id, leido_hasta=0)
        db.add(m)
        db.flush()
    return m


def _puede_ver(db: Session, c: ChatConversacion, user: User) -> bool:
    if c.tipo == "todos":
        return _interno(user)
    m = _miembro(db, c, user)
    return bool(m and m.activo)


def _conversacion(db: Session, cid: int, user: User) -> ChatConversacion:
    if not _interno(user):
        raise HTTPException(403, "El chat es solo para el personal del grupo")
    c = db.get(ChatConversacion, cid)
    if c is None or not _puede_ver(db, c, user):
        raise HTTPException(404, "Conversación no encontrada")
    return c


def _mis_conversaciones(db: Session, user: User) -> list[ChatConversacion]:
    ids = set(db.scalars(select(ChatMiembro.conversacion_id).where(ChatMiembro.user_id == user.id,
                                                                   ChatMiembro.activo.is_(True))))
    ids.add(_todos(db).id)
    return list(db.scalars(select(ChatConversacion).where(ChatConversacion.id.in_(ids))
                           .order_by(ChatConversacion.ultimo.desc())))


def _no_leidos(db: Session, c: ChatConversacion, user: User) -> tuple[int, int]:
    m = _miembro(db, c, user)
    desde = m.leido_hasta if m else 0
    if c.tipo == "todos" and m is None:  # nunca lo ha abierto: cuenta desde que se le dio de alta como mucho
        desde = 0
    q = select(func.count(), func.max(ChatMensaje.id)).where(
        ChatMensaje.conversacion_id == c.id, ChatMensaje.id > desde, ChatMensaje.user_id.is_distinct_from(user.id),
        ChatMensaje.sistema.is_(False), ChatMensaje.borrado.is_(False))
    n, ultimo = db.execute(q).one()
    return n or 0, ultimo or 0


def _resumen_chat(db: Session, user: User) -> dict:
    total, ultimo, nuevos = 0, 0, []
    for c in _mis_conversaciones(db, user):
        n, u = _no_leidos(db, c, user)
        if n:
            total += n
            nuevos.append({"id": c.id, "titulo": _titulo(db, c, user), "no_leidos": n, "ultimo": u})
        ultimo = max(ultimo, u)
    db.commit()  # «Todo el equipo» se crea la primera vez
    return {"no_leidos": total, "ultimo": ultimo, "nuevos": nuevos}


def _activos(db: Session, c: ChatConversacion) -> list[User]:
    if c.tipo == "todos":
        return list(db.scalars(select(User).where(User.activo.is_(True), User.supplier_id.is_(None))
                               .order_by(User.nombre)))
    return list(db.scalars(select(User).join(ChatMiembro, ChatMiembro.user_id == User.id).where(
        ChatMiembro.conversacion_id == c.id, ChatMiembro.activo.is_(True)).order_by(User.nombre)))


def _titulo(db: Session, c: ChatConversacion, user: User) -> str:
    if c.titulo:
        return c.titulo
    otros = [u.nombre for u in _activos(db, c) if u.id != user.id]
    return ", ".join(otros[:4]) + (f" y {len(otros) - 4} más" if len(otros) > 4 else "") or "Solo usted"


def _conv_out(db: Session, c: ChatConversacion, user: User) -> dict:
    n, _ = _no_leidos(db, c, user)
    ult = db.scalar(select(ChatMensaje).where(ChatMensaje.conversacion_id == c.id, ChatMensaje.borrado.is_(False))
                    .order_by(ChatMensaje.id.desc()).limit(1))
    autor = db.get(User, ult.user_id) if ult and ult.user_id else None
    miembros = _activos(db, c)
    return {"id": c.id, "tipo": c.tipo, "titulo": _titulo(db, c, user), "creador_id": c.creador_id,
            "es_creador": c.creador_id == user.id, "no_leidos": n, "ultimo": c.ultimo.isoformat(timespec="seconds"),
            "vista_previa": (f"{autor.nombre.split()[0]}: " if autor and not ult.sistema else "") + ult.texto[:80]
            if ult else "", "miembros": [{"id": u.id, "nombre": u.nombre} for u in miembros]}


def _msg_out(m: ChatMensaje, nombres: dict, adj: dict | None = None) -> dict:
    return {"id": m.id, "user_id": m.user_id, "autor": nombres.get(m.user_id, ""), "sistema": m.sistema,
            "texto": "Mensaje eliminado" if m.borrado else m.texto, "borrado": m.borrado,
            "creado": m.creado.isoformat(timespec="seconds"), "menciones": [] if m.borrado else (m.menciones or []),
            "adjuntos": [] if m.borrado else [{"id": a.id, "nombre": a.nombre, "mime": a.mime, "tamano": a.tamano}
                                             for a in (adj or {}).get(m.id, [])]}


def _adjuntos_de(db: Session, ids: list[int]) -> dict[int, list[ChatAdjunto]]:
    out: dict[int, list[ChatAdjunto]] = {}
    for a in db.scalars(select(ChatAdjunto).where(ChatAdjunto.mensaje_id.in_(ids or [-1])).order_by(ChatAdjunto.id)):
        out.setdefault(a.mensaje_id, []).append(a)
    return out


def _plano(t: str) -> str:
    """Sin tildes ni mayúsculas, para reconocer «@josé» como «@Jose»."""
    return "".join(x for x in unicodedata.normalize("NFD", t or "") if unicodedata.category(x) != "Mn").casefold()


def _menciones(db: Session, c: ChatConversacion, autor: User, texto: str) -> list[User]:
    """Personas de la conversación citadas con @nombre (el nombre completo, como lo propone el chat)."""
    plano = _plano(texto)
    if "@" not in plano:
        return []
    out = []
    for u in sorted(_activos(db, c), key=lambda x: -len(x.nombre or "")):  # «@Ana María» antes que «@Ana»
        if u.id == autor.id or not u.nombre:
            continue
        if re.search(r"@" + re.escape(_plano(u.nombre)) + r"(?![\w])", plano):
            out.append(u)
    return out


def _avisar_menciones(db: Session, c: ChatConversacion, autor: User, msg: ChatMensaje) -> None:
    citados = _menciones(db, c, autor, msg.texto)
    msg.menciones = [u.id for u in citados] or None
    titulo = f"{autor.nombre} le menciona en «{_titulo(db, c, autor) if c.tipo != 'directo' else 'conversación privada'}»"
    for u in citados:  # a la campana (suena); el chat solo se ve en el PMS, no se manda por correo
        avisos.notificar(db, u, None, "chat_mencion", titulo[:200], msg.texto[:600] or "(adjunto)", vista=f"chat:{c.id}")


def _sistema(db: Session, c: ChatConversacion, texto: str) -> None:
    db.add(ChatMensaje(conversacion_id=c.id, user_id=None, texto=texto, sistema=True))
    c.ultimo = datetime.now()


@router.get("/chat/usuarios")
def personas(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not _interno(user):
        raise HTTPException(403, "El chat es solo para el personal del grupo")
    return [{"id": u.id, "nombre": u.nombre, "email": u.email} for u in db.scalars(
        select(User).where(User.activo.is_(True), User.supplier_id.is_(None), User.id != user.id).order_by(User.nombre))]


@router.get("/chat/conversaciones")
def conversaciones(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not _interno(user):
        raise HTTPException(403, "El chat es solo para el personal del grupo")
    out = [_conv_out(db, c, user) for c in _mis_conversaciones(db, user)]
    db.commit()
    return out


class NuevaIn(BaseModel):
    miembros: list[int] = Field(min_length=1, max_length=MAX_MIEMBROS)
    titulo: str | None = Field(default=None, max_length=120)
    texto: str | None = Field(default=None, max_length=MAX_TEXTO)  # primer mensaje (opcional)


def _usuarios_validos(db: Session, ids: list[int], yo: User) -> list[User]:
    out = []
    for i in dict.fromkeys(ids):
        if i == yo.id:
            continue
        u = db.get(User, i)
        if not _interno(u):
            bad_request("Alguna de las personas elegidas no está activa o no tiene acceso al chat")
        out.append(u)
    if not out:
        bad_request("Elija al menos una persona")
    return out


@router.post("/chat/conversaciones", status_code=201)
def nueva(data: NuevaIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Con una sola persona y sin título: conversación directa (si ya existe, se reutiliza). Con varias o con
    título: grupo, que administra quien lo crea."""
    if not _interno(user):
        raise HTTPException(403, "El chat es solo para el personal del grupo")
    otros = _usuarios_validos(db, data.miembros, user)
    titulo = " ".join((data.titulo or "").split()) or None
    c = None
    if len(otros) == 1 and not titulo:
        par = {user.id, otros[0].id}
        for x in db.scalars(select(ChatConversacion).where(ChatConversacion.tipo == "directo")):
            ids = set(db.scalars(select(ChatMiembro.user_id).where(ChatMiembro.conversacion_id == x.id)))
            if ids == par:
                c = x
                break
        if c is None:
            c = ChatConversacion(tipo="directo", creador_id=user.id)
            db.add(c)
            db.flush()
            for u in (user, otros[0]):
                db.add(ChatMiembro(conversacion_id=c.id, user_id=u.id, anadido_por=user.id))
        else:  # quien había salido vuelve a la conversación directa
            for m in db.scalars(select(ChatMiembro).where(ChatMiembro.conversacion_id == c.id)):
                m.activo = True
    else:
        c = ChatConversacion(tipo="grupo", titulo=titulo, creador_id=user.id)
        db.add(c)
        db.flush()
        for u in [user, *otros]:
            db.add(ChatMiembro(conversacion_id=c.id, user_id=u.id, anadido_por=user.id))
        _sistema(db, c, f"{user.nombre} ha creado la conversación con {', '.join(u.nombre for u in otros)}")
    db.flush()
    if data.texto and data.texto.strip():
        _escribir(db, c, user, data.texto)
    db.commit()
    return _conv_out(db, c, user)


class MiembrosIn(BaseModel):
    miembros: list[int] = Field(min_length=1, max_length=MAX_MIEMBROS)


def _solo_creador(c: ChatConversacion, user: User) -> None:
    if c.tipo != "grupo":
        bad_request("Solo se pueden añadir o quitar personas en los grupos. Para hablar con más gente, cree un grupo.")
    if c.creador_id != user.id:
        raise HTTPException(403, "Solo quien creó la conversación puede añadir o quitar personas")


@router.post("/chat/conversaciones/{cid}/miembros")
def anadir(cid: int, data: MiembrosIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _conversacion(db, cid, user)
    _solo_creador(c, user)
    candidatos = _usuarios_validos(db, data.miembros, user)
    if len(_activos(db, c)) + len(candidatos) > MAX_MIEMBROS:
        bad_request(f"Máximo {MAX_MIEMBROS} personas por conversación")
    nuevos = []
    for u in candidatos:
        m = db.scalar(select(ChatMiembro).where(ChatMiembro.conversacion_id == c.id, ChatMiembro.user_id == u.id))
        if m is None:
            db.add(ChatMiembro(conversacion_id=c.id, user_id=u.id, anadido_por=user.id))
        elif not m.activo:
            m.activo, m.anadido_por, m.anadido = True, user.id, datetime.now()
        else:
            continue
        nuevos.append(u.nombre)
    if nuevos:
        _sistema(db, c, f"{user.nombre} ha añadido a {', '.join(nuevos)}")
    db.commit()
    return _conv_out(db, c, user)


@router.delete("/chat/conversaciones/{cid}/miembros/{uid}")
def quitar(cid: int, uid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """El creador quita a alguien; cualquiera puede quitarse a sí mismo (salir)."""
    c = _conversacion(db, cid, user)
    if c.tipo == "todos":
        bad_request("De «Todo el equipo» no se sale: está todo el personal")
    if uid != user.id:
        _solo_creador(c, user)
    m = db.scalar(select(ChatMiembro).where(ChatMiembro.conversacion_id == c.id, ChatMiembro.user_id == uid,
                                            ChatMiembro.activo.is_(True)))
    if m is None:
        bad_request("Esa persona no está en la conversación")
    m.activo = False
    u = db.get(User, uid)
    if c.tipo == "grupo":
        _sistema(db, c, f"{u.nombre} ha salido de la conversación" if uid == user.id
                 else f"{user.nombre} ha quitado a {u.nombre}")
    db.commit()
    return {"ok": True}


class TituloIn(BaseModel):
    titulo: str = Field(min_length=1, max_length=120)


@router.put("/chat/conversaciones/{cid}")
def renombrar(cid: int, data: TituloIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _conversacion(db, cid, user)
    _solo_creador(c, user)
    c.titulo = " ".join(data.titulo.split())
    _sistema(db, c, f"{user.nombre} ha cambiado el nombre a «{c.titulo}»")
    db.commit()
    return _conv_out(db, c, user)


@router.get("/chat/conversaciones/{cid}/mensajes")
def mensajes(cid: int, despues: int = 0, antes: int | None = None, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    """Mensajes (los 100 últimos, o los posteriores a `despues`, o los anteriores a `antes`). Abrirlos los marca
    como leídos."""
    c = _conversacion(db, cid, user)
    q = select(ChatMensaje).where(ChatMensaje.conversacion_id == c.id)
    if antes:
        filas = list(db.scalars(q.where(ChatMensaje.id < antes).order_by(ChatMensaje.id.desc()).limit(100)))[::-1]
    elif despues:
        filas = list(db.scalars(q.where(ChatMensaje.id > despues).order_by(ChatMensaje.id).limit(200)))
    else:
        filas = list(db.scalars(q.order_by(ChatMensaje.id.desc()).limit(100)))[::-1]
    m = _miembro(db, c, user, crear=True)
    if filas and m and filas[-1].id > m.leido_hasta:
        m.leido_hasta = filas[-1].id
    nombres = dict(db.execute(select(User.id, User.nombre).where(
        User.id.in_({x.user_id for x in filas if x.user_id} or {-1}))).all())
    adj = _adjuntos_de(db, [x.id for x in filas])
    db.commit()
    return {"conversacion": _conv_out(db, c, user), "mensajes": [_msg_out(x, nombres, adj) for x in filas]}


class MensajeIn(BaseModel):
    texto: str = Field(min_length=1, max_length=MAX_TEXTO)


def _escribir(db: Session, c: ChatConversacion, user: User, texto: str, vacio: bool = False) -> ChatMensaje:
    texto = (texto or "").strip()
    if not texto and not vacio:
        bad_request("Escriba el mensaje")
    msg = ChatMensaje(conversacion_id=c.id, user_id=user.id, texto=texto)
    db.add(msg)
    db.flush()
    if texto:
        _avisar_menciones(db, c, user, msg)
    c.ultimo = msg.creado
    m = _miembro(db, c, user, crear=True)
    if m:
        m.leido_hasta = msg.id
    return msg


@router.post("/chat/conversaciones/{cid}/mensajes", status_code=201)
def escribir(cid: int, data: MensajeIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _conversacion(db, cid, user)
    msg = _escribir(db, c, user, data.texto)
    db.commit()
    return _msg_out(msg, {user.id: user.nombre})


@router.post("/chat/conversaciones/{cid}/adjuntos", status_code=201)
def adjuntar(cid: int, ficheros: list[UploadFile] = File(...), texto: str = Form(""), user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    """Fotos (JPG, PNG) o PDF en un mensaje, con un texto opcional. Se guardan cifrados."""
    c = _conversacion(db, cid, user)
    if not ficheros or len(ficheros) > MAX_ADJUNTOS:
        bad_request(f"Adjunte entre 1 y {MAX_ADJUNTOS} ficheros")
    if len(texto) > MAX_TEXTO:
        bad_request(f"El mensaje no puede pasar de {MAX_TEXTO} caracteres")
    partes = []
    for f in ficheros:
        try:
            partes.append(adjuntos.normalizar(f.file.read(adjuntos.TAM_MAX + 1), (f.filename or "fichero")[-150:]))
        except ValueError as e:
            bad_request(f"{f.filename}: {e}")
    msg = _escribir(db, c, user, texto, vacio=True)
    for datos, mime, nombre in partes:
        db.add(ChatAdjunto(mensaje_id=msg.id, nombre=nombre[:200], mime=mime, tamano=len(datos),
                           sha256=documentos.huella(datos), fichero=documentos.guardar(datos), user_id=user.id))
    db.flush()
    out = _msg_out(msg, {user.id: user.nombre}, _adjuntos_de(db, [msg.id]))
    db.commit()
    return out


@router.get("/chat/adjuntos/{aid}")
def ver_adjunto(aid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Solo los miembros de la conversación; los de un mensaje borrado ya no se sirven."""
    a = db.get(ChatAdjunto, aid)
    msg = db.get(ChatMensaje, a.mensaje_id) if a else None
    if msg is None or msg.borrado:
        raise HTTPException(404, "Adjunto no encontrado")
    _conversacion(db, msg.conversacion_id, user)
    nombre = re.sub(r'[^\w.\- ]', "_", a.nombre)[:150]
    return Response(documentos.leer(a.fichero), media_type=a.mime, headers={
        "Content-Disposition": f'inline; filename="{nombre}"', "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff"})


@router.delete("/chat/mensajes/{mid}")
def borrar(mid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Cada uno borra sus propios mensajes (queda «Mensaje eliminado»)."""
    msg = db.get(ChatMensaje, mid)
    if msg is None:
        raise HTTPException(404, "Mensaje no encontrado")
    _conversacion(db, msg.conversacion_id, user)
    if msg.user_id != user.id:
        raise HTTPException(403, "Solo puede borrar sus propios mensajes")
    msg.borrado = True
    for a in db.scalars(select(ChatAdjunto).where(ChatAdjunto.mensaje_id == msg.id)):
        documentos.borrar(a.fichero)  # el fichero cifrado se borra del disco
        db.delete(a)
    db.commit()
    return {"ok": True}
