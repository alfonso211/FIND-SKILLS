"""Versión 1.59: cambio de la clave de los documentos cifrados (PMS_DOCS_KEY) sin perder ninguno."""
from cryptography.fernet import Fernet

from app import documentos, rotar_documentos
from app.config import settings


def test_lee_con_las_dos_y_vuelve_a_cifrar(tmp_path, monkeypatch):
    antigua, nueva = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "docs_dir", tmp_path)
    monkeypatch.setattr(settings, "docs_key", antigua)
    monkeypatch.setattr(settings, "docs_key_anterior", None)
    viejos = [documentos.guardar(f"dni-{i}".encode()) for i in range(3)]
    (tmp_path / "_diagnostico").mkdir()  # lo que no es un documento no se toca
    (tmp_path / "roto.bin").write_bytes(b"no es un documento")

    # cambio de clave: el PMS lee los antiguos y guarda los nuevos con la clave nueva
    monkeypatch.setattr(settings, "docs_key", nueva)
    monkeypatch.setattr(settings, "docs_key_anterior", antigua)
    assert [documentos.leer(n) for n in viejos] == [b"dni-0", b"dni-1", b"dni-2"]
    nuevo = documentos.guardar(b"pasaporte")
    Fernet(nueva).decrypt((tmp_path / nuevo).read_bytes())

    r = rotar_documentos.rotar(tmp_path, nueva, antigua)  # solo cuenta
    assert (r["total"], r["ya_nuevos"], r["pendientes"], r["ilegibles"]) == (5, 1, 3, 1)
    r = rotar_documentos.rotar(tmp_path, nueva, antigua, aplicar=True)
    assert r["cifrados"] == 3 and r["ilegibles"] == 1
    r = rotar_documentos.rotar(tmp_path, nueva, antigua)  # repetirlo no cambia nada
    assert (r["ya_nuevos"], r["pendientes"]) == (4, 0)

    # sin la clave antigua, todo se sigue leyendo
    monkeypatch.setattr(settings, "docs_key_anterior", None)
    assert [documentos.leer(n) for n in viejos + [nuevo]] == [b"dni-0", b"dni-1", b"dni-2", b"pasaporte"]
    assert not list(tmp_path.glob("*.tmp"))


def test_sin_las_dos_claves_no_hace_nada(monkeypatch, capsys):
    monkeypatch.setattr(settings, "docs_key_anterior", None)
    assert rotar_documentos.main([]) == 2
    assert "PMS_DOCS_KEY_ANTERIOR" in capsys.readouterr().out
