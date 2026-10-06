from app.mrz import digito, interpretar
from docs_sinteticos import mrz_dni, mrz_pasaporte

# Ejemplos oficiales de la norma ICAO 9303
ICAO_TD3 = ["P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<", "L898902C36UTO7408122F1204159ZE184226B<<<<<10"]
ICAO_TD1 = ["I<UTOD231458907<<<<<<<<<<<<<<<", "7408122F1204159UTO<<<<<<<<<<<6", "ERIKSSON<<ANNA<MARIA<<<<<<<<<<"]


def test_digito_control():
    assert digito("L898902C3") == "6" and digito("740812") == "2" and digito("120415") == "9"


def test_icao():
    p = interpretar(ICAO_TD3)
    assert p["mrz_valido"] and p["documento_tipo"] == "PAS" and p["documento_num"] == "L898902C3"
    assert (p["nombre"], p["apellidos"], p["sexo"]) == ("Anna Maria", "Eriksson", "F")
    assert str(p["fecha_nacimiento"]) == "1974-08-12"
    assert interpretar(ICAO_TD1)["mrz_valido"]


def test_dni_y_nie():
    d = interpretar(mrz_dni())
    assert d["mrz_valido"] and d["documento_tipo"] == "DNI"
    assert (d["documento_num"], d["num_soporte"], d["nacionalidad"]) == ("99999999R", "BAA000589", "España")
    n = interpretar(mrz_dni(tipo="IR", soporte="E01234567", dni="X1234567L"))
    assert n["mrz_valido"] and (n["documento_tipo"], n["documento_num"]) == ("NIE", "X1234567L")


def test_corrige_errores_de_ocr():
    l1, l2 = ICAO_TD3
    malas = [l1, l2.replace("0", "O").replace("1204159", "12O4159")]  # O por 0
    r = interpretar(malas)
    assert r["mrz_valido"] and r["documento_num"] == "L898902C3"
    # línea del nombre recortada por el OCR
    a, b, c = mrz_dni(apellidos="LI", nombre="WEI")
    assert interpretar([a, b, c.rstrip("<")])["nombre"] == "Wei"


def test_digito_erroneo_se_detecta():
    l1, l2 = mrz_pasaporte()
    assert interpretar([l1, l2[:-1] + str((int(l2[-1]) + 1) % 10)])["mrz_valido"] is False


def test_texto_sin_mrz():
    assert interpretar(["REINO DE ESPAÑA", "DOCUMENTO NACIONAL DE IDENTIDAD"]) is None


def test_cifra_dudosa_se_corrige_con_el_digito_global():
    l1, l2 = mrz_pasaporte()  # nacimiento 850315, su dígito de control en la posición 19
    mala = l2[:19] + str((int(l2[19]) + 6) % 10) + l2[20:]  # el OCR lee el dígito de control mal (0 → 6)
    r = interpretar([l1, mala])
    assert r["mrz_valido"] and r["corregido"] and r["fecha_nacimiento"].isoformat() == "1985-03-15"
    a, b, c = mrz_dni()
    r = interpretar([a, b[:2] + "6" + b[3:], c])  # 800101 leído 806101: fecha imposible de cuadrar sin corregir
    assert r["mrz_valido"] and r["fecha_nacimiento"].isoformat() == "1980-01-01"


def test_primera_letra_del_codigo():
    a, b, c = mrz_dni(tipo="IR", soporte="E01234567", dni="X1234567L")
    r = interpretar(["T" + a[1:], b, c])  # «I» leída como «T»
    assert (r["documento_tipo"], r["documento_num"]) == ("NIE", "X1234567L")
