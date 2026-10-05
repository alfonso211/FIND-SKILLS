"""Fichero de proveedores del grupo y ficha única del cliente (apartamentos que tiene, fichas repetidas)."""
from datetime import date, timedelta

from app import nif

HOY = date.today()


def test_nif():
    assert nif.tipo("12345678Z") == "DNI" and nif.tipo("12345678A") is None
    assert nif.tipo("X1234567L") == "NIE" and nif.tipo("B-1234567-4") == "CIF" and nif.tipo("B12345675") is None
    assert nif.nombre_clave("María  López", None) == nif.nombre_clave("MARIA", "LOPEZ") == "MARIA LOPEZ"
    assert nif.telefono_clave("+34 611 22 33 44") == nif.telefono_clave("611223344") == "611223344"


def test_proveedores(client, admin):
    p = client.post("/api/proveedores", headers=admin, json={
        "nombre": "Fontanería  Hermanos Gil S.L.", "tipo_persona": "empresa", "nif": "b-12345674", "pais": "España",
        "direccion": "C/ Mayor 1", "cp": "28001", "municipio": "Madrid", "email": "averias@gil.example",
        "telefono": "912345678", "actividad": "Fontanería", "notas": "Urgencias 24 h"})
    assert p.status_code == 201, p.text
    p = p.json()
    assert p["nif"] == "B12345674" and p["nombre"] == "Fontanería Hermanos Gil S.L." and p["activo"]
    # no se repite: mismo NIF o mismo nombre
    dup = client.post("/api/proveedores", headers=admin, json={"nombre": "Otro nombre", "nif": "B12345674"})
    assert dup.status_code == 400 and "Fontanería Hermanos Gil" in dup.json()["detail"]
    assert client.post("/api/proveedores", headers=admin, json={
        "nombre": "FONTANERIA HERMANOS GIL S.L."}).status_code == 400
    # NIF comprobado; autónomo con DNI; un extranjero no se comprueba
    assert client.post("/api/proveedores", headers=admin, json={"nombre": "Mal", "nif": "B12345675"}).status_code == 400
    assert client.post("/api/proveedores", headers=admin, json={
        "nombre": "Juan Pintor", "nif": "12345678Z"}).status_code == 400  # empresa con DNI
    a = client.post("/api/proveedores", headers=admin, json={
        "nombre": "Juan Pintor", "tipo_persona": "autonomo", "nif": "12345678Z", "actividad": "Pintura"})
    assert a.status_code == 201, a.text
    assert client.post("/api/proveedores", headers=admin, json={
        "nombre": "Lift Services Ltd", "nif": "GB123456789", "pais": "Reino Unido"}).status_code == 201
    assert [x["nombre"] for x in client.get("/api/proveedores?q=pintura", headers=admin).json()] == ["Juan Pintor"]
    r = client.put(f"/api/proveedores/{a.json()['id']}", headers=admin, json={**a.json(), "activo": False})
    assert r.status_code == 200 and not r.json()["activo"]
    assert "Juan Pintor" not in [x["nombre"] for x in client.get("/api/proveedores?solo_activos=true",
                                                                  headers=admin).json()]
    assert client.delete(f"/api/proveedores/{a.json()['id']}", headers=admin).json()["ok"]
    # ya no hay proveedores como terceros de una sociedad
    assert client.get("/api/terceros?tipo=proveedor", headers=admin).status_code == 400


def _reserva(client, h, unit_id, loc, guest=None, guest_id=None, dias=(0, 5)):
    body = {"unit_id": unit_id, "localizador": loc, "fecha_entrada": (HOY + timedelta(days=dias[0])).isoformat(),
            "fecha_salida": (HOY + timedelta(days=dias[1])).isoformat()}
    body.update({"guest_id": guest_id} if guest_id else {"guest": guest})
    r = client.post("/api/turistico/reservas", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_cliente_con_varios_apartamentos(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    u = {x["codigo"]: x["id"] for x in client.get(f"/api/unidades?asset_id={sae}", headers=admin).json()}
    # el mismo cliente reserva tres apartamentos: con el mismo teléfono no se duplica su ficha
    r1 = _reserva(client, admin, u["A-240"], "VAR-1", {"nombre": "Construcciones", "apellidos": "Ébano SL",
                                                       "telefono": "655 111 222"})
    r2 = _reserva(client, admin, u["A-241"], "VAR-2", {"nombre": "CONSTRUCCIONES", "apellidos": "EBANO SL",
                                                       "telefono": "+34655111222"})
    r3 = _reserva(client, admin, u["A-242"], "VAR-3", guest_id=r1["guest_id"])
    assert r1["guest_id"] == r2["guest_id"] == r3["guest_id"]
    # mismo nombre sin teléfono ni correo: no se puede saber si es el mismo; se crea otra ficha (se revisa luego)
    r4 = _reserva(client, admin, u["A-243"], "VAR-4", {"nombre": "Construcciones", "apellidos": "Ebano SL"})
    assert r4["guest_id"] != r1["guest_id"]

    ficha = client.get(f"/api/terceros/{r1['guest_id']}", headers=admin).json()
    assert ficha["n_apartamentos"] == 3 and [x["codigo"] for x in ficha["unidades"]] == ["A-240", "A-241", "A-242"]
    lista = [c for c in client.get("/api/terceros?tipo=huesped&q=Ebano", headers=admin).json()]
    assert len(lista) == 2 and {c["n_apartamentos"] for c in lista} == {3, 1}

    # fichas repetidas: se detectan y se unen en una
    dup = [g for g in client.get("/api/terceros/duplicados?tipo=huesped", headers=admin).json()
           if g["nombre"].upper().startswith("CONSTRUCCIONES")]
    assert len(dup) == 1 and dup[0]["principal"] == r1["guest_id"] and not dup[0]["documentos_distintos"]
    m = client.post(f"/api/terceros/{r1['guest_id']}/fusionar", headers=admin, json={"ids": [r4["guest_id"]]})
    assert m.status_code == 200, m.text
    assert m.json()["n_apartamentos"] == 4 and nif.telefono_clave(m.json()["telefono"]) == "655111222"
    assert client.get(f"/api/terceros/{r4['guest_id']}", headers=admin).status_code == 404
    assert len(client.get("/api/terceros?tipo=huesped&q=Ebano", headers=admin).json()) == 1
    res = client.get(f"/api/turistico/reservas?asset_id={sae}&q=VAR-4", headers=admin).json()[0]
    assert res["guest_id"] == r1["guest_id"]


def test_no_se_unen_personas_distintas(client, admin, ids):
    sae = ids["assets"]["SAE"]["id"]
    u = {x["codigo"]: x["id"] for x in client.get(f"/api/unidades?asset_id={sae}", headers=admin).json()}
    a = _reserva(client, admin, u["A-244"], "HOM-1", {"nombre": "Pedro", "apellidos": "Homónimo Uno",
                                                      "documento_num": "12345678Z", "telefono": "600999888"})
    b = _reserva(client, admin, u["A-245"], "HOM-2", {"nombre": "Pedro", "apellidos": "Homónimo Uno",
                                                      "documento_num": "X1234567L", "telefono": "600999888"})
    assert a["guest_id"] != b["guest_id"]  # mismo nombre y teléfono pero documento distinto
    r = client.post(f"/api/terceros/{a['guest_id']}/fusionar", headers=admin, json={"ids": [b["guest_id"]]})
    assert r.status_code == 400 and "personas distintas" in r.json()["detail"]
    g = [x for x in client.get("/api/terceros/duplicados?tipo=huesped", headers=admin).json()
         if x["nombre"] == "Pedro Homónimo Uno"]
    assert g and g[0]["documentos_distintos"]
    # alta manual con un documento que ya tiene ficha
    guest = client.get(f"/api/terceros/{a['guest_id']}", headers=admin).json()
    dup = client.post("/api/terceros", headers=admin, json={"company_id": guest["company_id"], "tipo": "huesped",
                                                            "asset_id": guest["asset_id"], "nombre": "Otro",
                                                            "documento_num": "12345678z"})
    assert dup.status_code == 400 and "Ya existe" in dup.json()["detail"]


def test_migracion_proveedores(tmp_path):
    """Los proveedores que había como terceros de una sociedad pasan al fichero del grupo."""
    from alembic import command
    from sqlalchemy import create_engine, text

    from app.migraciones import _config, migrar
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    with eng.begin() as conn:
        command.upgrade(_config(conn), "0016")
    with eng.begin() as c:
        c.execute(text("insert into sociedades (id, nombre, activa) values (1, 'INVERSIETE S.A.', 1)"))
        for nombre, doc in (("Ascensores Norte SL", "B12345674"), ("Ascensores Norte SL", "B12345674"),
                            ("Pintor Pérez", None)):
            c.execute(text("insert into terceros (company_id, tipo, nombre, documento_num, telefono) "
                           "values (1, 'proveedor', :n, :d, '910000000')"), {"n": nombre, "d": doc})
        c.execute(text("insert into terceros (company_id, tipo, nombre) values (1, 'huesped', 'Cliente')"))
    migrar(eng)
    with eng.connect() as c:
        assert c.execute(text("select nombre, nif from proveedores order by nombre")).all() == [
            ("Ascensores Norte SL", "B12345674"), ("Pintor Pérez", None)]
        assert c.execute(text("select tipo from terceros")).scalars().all() == ["huesped"]
