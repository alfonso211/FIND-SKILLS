"""Clientes separados por activo: cada recepción ve solo los clientes de su activo; la dirección los ve todos."""
from datetime import date, timedelta

from test_adjuntos_ot import _usuario

HOY = date.today()


def _unidad(client, h, asset_id, codigo):
    return next(u for u in client.get(f"/api/unidades?asset_id={asset_id}&q={codigo}", headers=h).json()
                if u["codigo"] == codigo)


def _reserva(client, h, unit_id, loc, **cliente):
    r = client.post("/api/turistico/reservas", headers=h, json={
        "unit_id": unit_id, "localizador": loc, "fecha_entrada": (HOY + timedelta(days=40)).isoformat(),
        "fecha_salida": (HOY + timedelta(days=42)).isoformat(), **cliente})
    return r


def test_recepciones_no_comparten_clientes(client, admin, ids):
    sae, sfl = ids["assets"]["SAE"]["id"], ids["assets"]["SFL"]["id"]
    rec_sae = _usuario(client, admin, ids, "recepcion.sae.clientes@inversiete.com", "Recepción", "SAE")
    rec_sfl = _usuario(client, admin, ids, "recepcion.sfl.clientes@inversiete.com", "Recepción", "SFL")
    datos = {"nombre": "Viajera", "apellidos": "Dos Suites", "documento_tipo": "DNI", "documento_num": "00000000T",
             "telefono": "699000111"}
    a = _reserva(client, rec_sae, _unidad(client, admin, sae, "A-246")["id"], "SEP-1", guest=datos)
    assert a.status_code == 201, a.text
    # la misma persona se aloja en Suite Florida: allí tiene su propia ficha
    b = _reserva(client, rec_sfl, _unidad(client, admin, sfl, "P1-1K")["id"], "SEP-2", guest=datos)
    assert b.status_code == 201, b.text
    ga, gb = a.json()["guest_id"], b.json()["guest_id"]
    assert ga != gb

    def nombres(h, **q):
        return [(c["id"], c["activo"]) for c in client.get("/api/terceros", headers=h,
                                                             params={"tipo": "huesped", "q": "Dos Suites", **q}).json()]
    assert nombres(rec_sae) == [(ga, "Suite Aeropuerto")]
    assert nombres(rec_sfl) == [(gb, "Suite Florida")]
    assert sorted(nombres(admin)) == sorted([(ga, "Suite Aeropuerto"), (gb, "Suite Florida")])  # la dirección, todos
    assert nombres(admin, asset_id=sfl) == [(gb, "Suite Florida")]
    # una recepción no abre ni usa la ficha de la otra
    assert client.get(f"/api/terceros/{ga}", headers=rec_sfl).status_code == 403
    assert client.put(f"/api/terceros/{ga}", headers=rec_sfl, json={**datos, "company_id": a.json()["guest_id"] and
                      client.get(f"/api/terceros/{ga}", headers=admin).json()["company_id"], "tipo": "huesped"}
                      ).status_code == 403
    robo = _reserva(client, rec_sfl, _unidad(client, admin, sfl, "P1-1L")["id"], "SEP-3", guest_id=ga)
    assert robo.status_code == 403
    # no son fichas repetidas (cada activo tiene la suya) ni se pueden unir
    assert not [g for g in client.get("/api/terceros/duplicados?tipo=huesped", headers=admin).json()
                if g["nombre"] == "Viajera Dos Suites"]
    assert client.post(f"/api/terceros/{ga}/fusionar", headers=admin, json={"ids": [gb]}).status_code == 400
    # la dirección reserva en Suite Florida con la ficha de Suite Aeropuerto: se usa la ficha propia de Florida
    c = _reserva(client, admin, _unidad(client, admin, sfl, "P1-1L")["id"], "SEP-4", guest_id=ga)
    assert c.status_code == 201 and c.json()["guest_id"] == gb
    # alta manual: la recepción da de alta en su activo, no en otro
    comp = client.get(f"/api/terceros/{ga}", headers=admin).json()["company_id"]
    alta = {"company_id": comp, "tipo": "huesped", "nombre": "Alta", "apellidos": "Manual"}
    assert client.post("/api/terceros", headers=rec_sfl, json={**alta, "asset_id": sae}).status_code == 403
    assert client.post("/api/terceros", headers=rec_sfl, json=alta).status_code == 400  # sin activo
    r = client.post("/api/terceros", headers=rec_sfl, json={**alta, "asset_id": sfl})
    assert r.status_code == 201 and r.json()["asset_id"] == sfl


def test_migracion_separa_clientes_de_dos_activos(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, text

    from app.migraciones import _config, migrar
    eng = create_engine(f"sqlite:///{tmp_path}/m.db")
    with eng.begin() as conn:
        command.upgrade(_config(conn), "0017")
    with eng.begin() as c:
        c.execute(text("insert into sociedades (id, nombre, activa) values (1, 'INVERSIETE S.A.', 1)"))
        for i, cod in ((1, "SAE"), (2, "SFL")):
            c.execute(text("insert into activos (id, company_id, codigo, nombre, modalidad, activo) values "
                           "(:i, 1, :c, :c, 'apartamentos_turisticos', 1)"), {"i": i, "c": cod})
            c.execute(text("insert into unidades (id, asset_id, codigo, uso, estado) values "
                           "(:i, :i, 'U', 'apartamento', 'disponible')"), {"i": i})
        c.execute(text("insert into terceros (id, company_id, tipo, nombre, documento_num) values "
                       "(1, 1, 'huesped', 'Compartido', '00000000T'), (2, 1, 'huesped', 'Solo SAE', null), "
                       "(3, 1, 'huesped', 'Sin reservas', null)"))
        for rid, unit, guest in ((1, 1, 1), (2, 2, 1), (3, 1, 2)):
            c.execute(text("insert into reservas (id, unit_id, guest_id, canal, fecha_entrada, fecha_salida, adultos, "
                           "ninos, importe_total, importe_pagado, estado, creada) values (:r, :u, :g, 'directo', "
                           "'2026-01-01', '2026-01-03', 1, 0, 0, 0, 'checkout', '2026-01-01')"),
                      {"r": rid, "u": unit, "g": guest})
            c.execute(text("insert into reserva_ocupantes (reservation_id, contact_id, titular, orden) values "
                           "(:r, :g, 1, 0)"), {"r": rid, "g": guest})
    migrar(eng)
    with eng.connect() as c:
        fichas = c.execute(text("select id, nombre, asset_id, documento_num from terceros order by id")).all()
        assert fichas[:3] == [(1, "Compartido", 1, "00000000T"), (2, "Solo SAE", 1, None), (3, "Sin reservas", None, None)]
        assert fichas[3][1:] == ("Compartido", 2, "00000000T")  # ficha propia en Suite Florida
        nueva = fichas[3][0]
        assert c.execute(text("select id, guest_id from reservas order by id")).all() == [(1, 1), (2, nueva), (3, 2)]
        assert c.execute(text("select reservation_id, contact_id from reserva_ocupantes order by reservation_id")
                         ).all() == [(1, 1), (2, nueva), (3, 2)]
