"""Código postal -> población y provincia (Callejero del Censo Electoral del INE)."""
from app import registro_viajeros as rv


def test_por_cp():
    r = rv.por_cp("28022")
    assert [m["nombre"] for m in r["municipios"]] == ["Madrid"] and r["provincia"] == "Madrid"
    assert rv.por_cp("28232")["municipios"][0]["nombre"] == "Las Rozas de Madrid"  # «Rozas de Madrid, Las»
    assert rv.por_cp("35001")["provincia"] == "Las Palmas"
    compartido = rv.por_cp("29620")  # Málaga y Torremolinos
    assert {m["nombre"] for m in compartido["municipios"]} == {"Málaga", "Torremolinos"}
    assert compartido["provincia"] == "Málaga"
    assert rv.por_cp("99999") is None and rv.por_cp("2802") is None and rv.por_cp("abcde") is None
    assert rv.nombre_natural("Palmas de Gran Canaria, Las") == "Las Palmas de Gran Canaria"


def test_api_cp(client, admin):
    assert client.get("/api/codigos-postales/07001", headers=admin).json()["provincia"] == "Illes Balears"
    assert client.get("/api/codigos-postales/99999", headers=admin).status_code == 404
    assert client.get("/api/codigos-postales/28022").status_code == 401
