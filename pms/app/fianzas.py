"""Devolución de la fianza al hacer la salida del apartamento.

La fianza se anota en los datos del contrato de alojamiento de la reserva. Al hacer la salida, Recepción 1 o
Recepción 2 indican cómo se devuelve (transferencia, efectivo o tarjeta), cuánto (si se retiene algo, el motivo) y,
si es por transferencia, el IBAN y la fecha. Las transferencias las hace la Dirección: se le envían los datos por
correo (queda en el registro de envíos) y se prepara el WhatsApp con el mismo texto. Todas las devoluciones entran
en la exportación a INVERGESTION (FIANZAS_*.csv) para la gestoría."""
import logging
from datetime import datetime
from html import escape
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import avisos
from .config import settings
from .firma_contrato import movil_whatsapp
from .models import FORMAS_DEVOLUCION, DepositRefund, EmailLog, Reservation, StaffMember, User

log = logging.getLogger("pms.fianzas")


def importe(r: Reservation) -> float:
    """Fianza de la reserva: la cobrada al llegar o, si no se registró el cobro, la anotada en el contrato (0 si no
    hay ninguna)."""
    for x in ((r.fianza_cobro or {}).get("importe"), (r.datos_contrato or {}).get("fianza")):
        try:
            if x not in (None, ""):
                return round(float(x), 2)
        except (TypeError, ValueError):
            continue
    return 0.0


FORMAS_COBRO = {"efectivo": "Efectivo", "tarjeta": "Tarjeta (cobro)", "preautorizacion": "Tarjeta (preautorización)",
                "bizum": "Bizum", "transferencia": "Transferencia"}


def registrar_cobro(r: Reservation, importe: float, forma: str, user: User, ref: str | None = None,
                    cuando: datetime | None = None) -> dict:
    """Fianza cobrada al llegar: importe, forma, fecha y quién (entra en la caja del turno y en la exportación)."""
    r.fianza_cobro = {"importe": round(float(importe), 2), "forma": forma, "fecha": (cuando or datetime.now())
                      .isoformat(timespec="seconds"), "user_id": user.id, "usuario": user.nombre, "ref": ref or None}
    datos = dict(r.datos_contrato or {})
    datos["fianza"] = r.fianza_cobro["importe"]  # el contrato que se imprima después ya la lleva
    r.datos_contrato = datos
    return r.fianza_cobro


def titular(r: Reservation) -> str:
    g = r.guest
    return f"{g.nombre} {g.apellidos or ''}".strip()


def _euros(x) -> str:
    return f"{float(x):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def iban_valido(iban: str | None) -> bool:
    """Comprobación del IBAN (dígitos de control, ISO 13616)."""
    s = "".join((iban or "").split()).upper()
    if not (15 <= len(s) <= 34) or not s[:2].isalpha() or not s[2:4].isdigit() or not s.isalnum():
        return False
    if s.startswith("ES") and len(s) != 24:
        return False
    n = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(n) % 97 == 1


def iban_legible(iban: str | None) -> str:
    s = "".join((iban or "").split()).upper()
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


def _lineas(d: DepositRefund, r: Reservation) -> list[tuple[str, str]]:
    filas = [("Cliente", d.titular), ("Activo", r.unit.asset.nombre), ("Apartamento", r.unit.codigo),
             ("Reserva", r.localizador or f"R-{r.id}"),
             ("Estancia", f"{r.fecha_entrada:%d/%m/%Y} – {r.fecha_salida:%d/%m/%Y}"),
             ("Fianza", _euros(d.fianza)), ("A devolver", _euros(d.importe))]
    if d.retenido_motivo:
        filas.append(("Se retiene", f"{_euros(float(d.fianza) - float(d.importe))} · {d.retenido_motivo}"))
    filas.append(("Forma", FORMAS_DEVOLUCION.get(d.forma, d.forma)))
    if d.forma == "transferencia":
        filas += [("IBAN", iban_legible(d.iban)), ("Fecha de la transferencia", f"{d.fecha:%d/%m/%Y}")]
    else:
        filas.append(("Fecha", f"{d.fecha:%d/%m/%Y}"))
    if d.nota:
        filas.append(("Nota", d.nota))
    return filas


def texto(d: DepositRefund, r: Reservation) -> str:
    return ("Devolución de fianza por transferencia\n"
            + "\n".join(f"{k}: {v}" for k, v in _lineas(d, r)))


def _telefono(db: Session, email: str) -> str | None:
    """Móvil del destinatario: el de su ficha del personal (si la tiene)."""
    tel = db.scalar(select(StaffMember.telefono).join(User, User.id == StaffMember.user_id)
                    .where(User.email == email, StaffMember.telefono.is_not(None)))
    if not tel:
        tel = db.scalar(select(StaffMember.telefono).where(StaffMember.email == email, StaffMember.telefono.is_not(None)))
    return movil_whatsapp(tel) if tel else None


def whatsapp(db: Session, d: DepositRefund, r: Reservation) -> list[dict]:
    """Enlaces de WhatsApp con los datos (uno por destinatario). Sin móvil en su ficha, el enlace deja elegir el
    contacto en WhatsApp."""
    t = quote(texto(d, r))
    out = []
    for e in settings.fianza_avisos:
        nombre = db.scalar(select(User.nombre).where(User.email == e)) or e
        movil = _telefono(db, e)
        out.append({"destinatario": nombre, "email": e, "movil": movil,
                    "url": f"https://wa.me/{movil or ''}?text={t}"})
    return out


def avisar(db: Session, d: DepositRefund, r: Reservation, autor: User | None) -> list[dict]:
    """Correo a la Dirección con los datos de la transferencia (queda en el registro de envíos) y enlaces de
    WhatsApp. Devuelve [{destinatario, ok, error}]."""
    filas = _lineas(d, r)
    asunto = f"Devolución de fianza por transferencia · {r.unit.asset.nombre} {r.unit.codigo} · {d.titular}"
    cuerpo = (f"<p>Recepción{(' (' + escape(autor.nombre) + ')') if autor else ''} ha hecho la salida del cliente y "
              f"la fianza se devuelve <b>por transferencia</b>. Datos para hacerla:</p>"
              + avisos._tabla(["Dato", "Valor"], [list(f) for f in filas]))
    out = []
    for e in settings.fianza_avisos:
        u = db.scalar(select(User).where(User.email == e))
        try:
            avisos.enviar(e, asunto, texto(d, r), avisos._html("Devolución de fianza por transferencia", cuerpo))
            ok, err = True, None
        except Exception as ex:  # noqa: BLE001 — un fallo de correo no impide la salida
            ok, err = False, str(ex)[:300]
            log.warning("Aviso de fianza %s a %s no enviado: %s", d.id, e, err)
        db.add(EmailLog(clave=f"fianza:{d.id}", tipo="fianza", user_id=u.id if u else None, destinatario=e,
                        asunto=asunto[:200], ok=ok, error=err))
        out.append({"destinatario": e, "ok": ok, "error": err})
    d.avisada = datetime.now()
    return out


def a_dict(d: DepositRefund) -> dict:
    x = d.to_dict()
    x["forma_texto"] = FORMAS_DEVOLUCION.get(d.forma, d.forma)
    x["retenido"] = round(float(d.fianza) - float(d.importe), 2)
    return x


# --------------------------------------------------------------------------- recordatorio de cobro del exceso
RECORDATORIOS_DIAS = (3, 10, 17)  # días desde la factura: como mucho tres recordatorios automáticos


def factura_exceso(db: Session, d: DepositRefund):
    from .models import Invoice
    return db.scalar(select(Invoice).where(Invoice.codigo == d.factura_exceso)) if d.factura_exceso else None


def _texto_recordatorio(d: DepositRefund, r: Reservation, f) -> str:
    return (f"Le recordamos que tiene pendiente de pago la factura {f.codigo}, de {_euros(f.total)}, por la reposición "
            f"de la dotación del apartamento {r.unit.codigo} de {r.unit.asset.nombre} que superó la fianza de su "
            f"estancia ({r.fecha_entrada:%d/%m/%Y} – {r.fecha_salida:%d/%m/%Y}). Puede abonarla por transferencia o en "
            f"la recepción, indicando el número de factura. Si ya la ha abonado, no tenga en cuenta este mensaje.")


def recordatorio_exceso(db: Session, d: DepositRefund, clave: str) -> dict:
    """Recordatorio al cliente de la factura del exceso pendiente: correo con la factura adjunta (si tiene correo) y
    WhatsApp preparado con el mismo texto y el enlace de descarga. Queda en el registro de envíos."""
    from .routers.facturas import _pdf, enlace
    r = db.get(Reservation, d.reservation_id)
    f = factura_exceso(db, d)
    if f is None or f.cobro != "pendiente":
        return {"ok": False, "error": "La factura del exceso no está pendiente de cobro"}
    texto = _texto_recordatorio(d, r, f)
    out: dict = {"ok": True, "factura": f.codigo}
    g = r.guest
    if g.email:
        asunto = f"Recordatorio de pago · factura {f.codigo} · {r.unit.asset.nombre}"
        try:
            avisos.enviar(g.email, asunto, f"Estimado/a cliente:\n\n{texto}\n\nAtentamente,\n{r.unit.asset.nombre}",
                          avisos._html("Recordatorio de pago", f"<p>Estimado/a cliente:</p><p>{escape(texto)}</p>"
                                                               f"<p>Atentamente,<br>{escape(r.unit.asset.nombre)}</p>"),
                          [(*_pdf(db, f), "application/pdf")])
            ok, err = True, None
        except Exception as ex:  # noqa: BLE001
            ok, err = False, str(ex)[:300]
        db.add(EmailLog(clave=clave, tipo="recordatorio_cobro", destinatario=g.email, asunto=asunto[:200], ok=ok,
                        error=err))
        out["email"] = {"destinatario": g.email, "ok": ok, "error": err}
    movil = movil_whatsapp(g.telefono) if g.telefono else None
    if movil:
        extra = f" Descargue su factura: {enlace(f.id)}" if settings.url else ""
        out["whatsapp"] = f"https://wa.me/{movil}?text={quote(texto + extra)}"
    return out


def recordatorios_exceso(db: Session, hoy=None) -> int:
    """Recordatorios automáticos de las facturas de exceso sin cobrar a los 3, 10 y 17 días (una vez cada uno)."""
    from datetime import date
    from .models import Invoice
    hoy = hoy or date.today()
    enviados = 0
    for d, f in db.execute(select(DepositRefund, Invoice).join(Invoice, Invoice.codigo == DepositRefund.factura_exceso)
                           .where(Invoice.cobro == "pendiente")):
        dias = (hoy - f.creada.date()).days
        for n, limite in enumerate(RECORDATORIOS_DIAS, 1):
            clave = f"recordatorio_exceso:{f.id}:{n}"
            if dias < limite or db.scalar(select(EmailLog.id).where(EmailLog.clave == clave)):
                continue
            if not db.get(Reservation, d.reservation_id).guest.email:
                break  # sin correo del cliente: solo el recordatorio manual por WhatsApp
            recordatorio_exceso(db, d, clave)
            enviados += 1
            break  # uno por día como mucho
    db.commit()
    return enviados
