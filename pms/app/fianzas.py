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
    """Fianza anotada en el contrato de la reserva (0 si no hay)."""
    try:
        return round(float((r.datos_contrato or {}).get("fianza") or 0), 2)
    except (TypeError, ValueError):
        return 0.0


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
