"""Mantenimiento diario: comprobaciones internas y correo urgente si hay un fallo grave."""
import io
from datetime import date

from app import avisos
from app import mantenimiento as mt
from app.config import settings
from app.database import SessionLocal
from app.models import ReceivedDocument


def _estado(res, area):
    return [r for r in res if r[1] == area]


def test_comprobaciones_internas(client, admin, ids):
    res = mt.comprobar()
    assert _estado(res, "Base de datos")[0][0] == mt.OK
    assert _estado(res, "Documentos")[0] == (mt.OK, "Documentos", "La carpeta de documentos admite escritura")
    assert _estado(res, "Estabilidad")[0][0] == mt.OK
    # un documento registrado cuyo fichero se ha perdido: GRAVE, con su número y sin datos personales
    r = client.post("/api/documentos-recibidos", headers=admin, data={
        "asset_id": str(ids["assets"]["SFL"]["id"]), "tipo": "carta", "fecha": date.today().isoformat(),
        "confirmar_duplicado": "true"},
        files=[("ficheros", ("m.pdf", b"%PDF-1.4 mantenimiento", "application/pdf"))])
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        d = db.query(ReceivedDocument).order_by(ReceivedDocument.id.desc()).first()
        fichero, did = d.fichero, d.id
    contenido = (settings.docs_dir / fichero).read_bytes()
    (settings.docs_dir / fichero).unlink()
    try:
        graves = [m for e, a, m in mt.comprobar() if e == mt.GRAVE and a == "Documentos"]
        assert graves and "documentos recibidos:" in graves[0] and f"{did})" in graves[0]
        # cifrado con otra clave: no se puede descifrar
        (settings.docs_dir / fichero).write_bytes(b"gAAAAAinvalido")
        graves = [m for e, a, m in mt.comprobar() if e == mt.GRAVE and a == "Documentos"]
        assert any(m.startswith("No se pueden descifrar") and f"n.º {did}" in m for m in graves)
    finally:
        (settings.docs_dir / fichero).write_bytes(contenido)
    assert not any(f"{did})" in m or "descifrar" in m for _, a, m in mt.comprobar() if a == "Documentos")


def test_salida_y_correo(capsys, client):
    assert mt.main(["m", "comprobar"]) == 0
    lineas = capsys.readouterr().out.splitlines()
    assert lineas and all(len(x.split("\t")) == 3 for x in lineas)

    informe = ("OK\tContenedores\tdb, app y caddy funcionando\n"
               "ARREGLADO\tDisco\tAl 85 %: limpiadas imágenes antiguas, ahora al 61 %\n"
               "AVISO\tSeguridad\tEl servidor necesita reiniciarse\n"
               "GRAVE\tCopias\tNo hay copia de seguridad de hoy y backup.sh falla\n"
               "línea que no es del informe\n")
    res = mt.leer_informe(io.StringIO(informe))
    assert [r[0] for r in res] == ["GRAVE", "ARREGLADO", "AVISO", "OK"]

    avisos.BANDEJA.clear()
    asunto = mt.enviar_informe(res, "urgente", "ubuntu")
    m = avisos.BANDEJA[-1]
    assert m["para"] == "alfonso@inversiete.es" and m["urgente"] is True
    assert asunto.startswith("URGENTE · INVERPMS: 1 fallo(s) grave(s)")
    assert "backup.sh falla" in m["texto"] and "Necesitan su intervención" in m["texto"]
    # sin fallos graves: correo normal, no urgente
    mt.enviar_informe(res[1:], "avisos")
    assert avisos.BANDEJA[-1]["urgente"] is False and "1 arreglado(s)" in avisos.BANDEJA[-1]["asunto"]
    mt.enviar_informe(res[-1:], "semanal")
    assert avisos.BANDEJA[-1]["asunto"].endswith("todo correcto")
