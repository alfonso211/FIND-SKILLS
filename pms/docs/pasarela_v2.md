# Pasarela PMS → gestión · contrato v2 (versión 1.50 del PMS)

El PMS es el origen de la operativa diaria (reservas, cobros, fianzas, caja y mantenimiento). Gestión recibe lo que
necesita para contabilidad, tesorería y control. Este documento fija los avisos nuevos.

## Lo que no cambia

- Mismo punto de entrada: `POST {PMS_GESTION_URL}/api/pms/eventos`.
- Misma firma: cabeceras `X-PMS-Fecha` y `X-PMS-Firma`, HMAC-SHA256 con `PMS_EVENTOS_SECRET` sobre `fecha + "." + cuerpo`.
- Mismo cuerpo: `{id_evento, tipo, emitido, datos}`.
- Mismos reintentos: 1 min, 5 min, 30 min, 2 h y después cada 2 h. Gestión descarta los repetidos por `id_evento`.
- Gestión responde 2xx cuando ha guardado el aviso. Un tipo que todavía no trate también debe responder 2xx (y
  guardarlo); si no, el PMS lo reintenta.
- Los avisos de la fase 4 no cambian: `reserva.creada`, `reserva.modificada`, `reserva.cancelada`, `checkout`,
  `incidencia.reportada` y `liquidacion.periodo`.

## Activación

Los avisos nuevos se guardan en la cola desde ya, pero el PMS **no los manda** hasta que en su servidor se ponga
`PMS_GESTION_EVENTOS_V2=1` en `.env` y se reinicie el contenedor. Entonces salen todos los guardados, por orden.
Antes de activarlo, gestión debe tener desplegada la recepción de estos tipos.

## Datos comunes de reserva

Los avisos de reserva y de fianza llevan los campos de `_datos_reserva` (fase 4):

`reserva_id, localizador, activo, activo_pms, unidad_pms_id, unidad_codigo, uso, canal, entrada, salida, adultos,
ninos, importe_total, importe_pagado, estado`

No se envían nombres de clientes, documentos de identidad, IBAN ni números de tarjeta.

## Avisos nuevos

### 1. `reserva.ampliada` (corrige la fase 4)

Cuando empieza la ampliación de una estancia, la reserva anterior se cierra sin que el cliente salga. Hasta ahora
llegaba a gestión como `checkout`. Ahora llega como `reserva.ampliada`.

- Datos: los comunes de la reserva que se cierra, con `estado = "checkout"`.
- `fecha_fin_tramo`: fecha en que termina este tramo.
- `continua_en`: los datos comunes de la reserva que sigue (la ampliación), que ya está con el cliente dentro.

Gestión **no** debe tratarlo como una salida: no hay limpieza de salida, no se devuelve la fianza y el apartamento
sigue ocupado.

### 2. `fianza.cobrada`

Recepción cobra la fianza al llegar el cliente.

- Datos: los comunes de la reserva.
- `fianza` (€).
- `forma`: `efectivo`, `tarjeta`, `preautorizacion`, `bizum` o `transferencia`.
- `fecha` (ISO).

### 3. `fianza.devolucion`

Se registra la devolución de la fianza al dar la salida.

- Datos: los comunes de la reserva.
- `devolucion_id`.
- `fianza`, `devuelto`, `retenido` (€).
- `cargos`: lista de `{articulo, cantidad, precio, importe, ot_id}` por roturas y faltas descontadas.
- `cargos_total` (€).
- `forma`: `transferencia`, `efectivo`, `tarjeta` o `no_procede`.
- `estado`: `pendiente` (falta hacer la transferencia) o `devuelta`.
- `fecha`: la de la devolución; si es por transferencia, la prevista.
- `cobro`: `{forma, fecha}` del cobro al llegar, o `null`.
- `factura_exceso`: `{codigo, total}` o `null`. Es la factura al cliente de lo que superó la fianza: no sujeta a
  IVA (indemnización) y pendiente de cobro.

Para tesorería, el importe `retenido` es un ingreso del activo, y la factura del exceso es un cobro pendiente.

### 4. `fianza.transferida`

La Dirección marca hecha la transferencia de una devolución.

- Datos: los comunes de la reserva.
- `devolucion_id`, `fianza`, `devuelto`.
- `fecha`: la de la transferencia.

### Contabilidad de las fianzas desde los avisos (versión 1.58 del PMS)

Desde la 1.58, los tres avisos `fianza.*` llevan además estos campos. No se quita ni se cambia ninguno de los
anteriores.

- `empresa`: `{nombre, cif}` de la sociedad que explota el activo.
- `origen_contable`: `avisos` o `csv`. Indica de dónde contabiliza gestión las fianzas.
- `contabilizar`: `true` si gestión debe contabilizar este aviso. Es `false` con `origen_contable` = `csv` o si el
  movimiento es anterior a la fecha de corte.
- `cobro_registrado`: `false` si la fianza no se anotó al cobrarla (solo constaba en el contrato). Hay que revisarla.
- `asiento`: lista de `{cuenta, nombre, debe, haber}` con el asiento sugerido (Plan General Contable). Lista vacía si
  el movimiento no mueve dinero.
- `saldo_activo`: fianzas en custodia del activo después del movimiento (€). Incluye las de los clientes alojados y
  las devoluciones por transferencia aún sin hacer.
- `preautorizado_activo`: preautorizaciones de tarjeta abiertas del activo (€). No es dinero.
- `generado_desde_libro`: `true` solo en los avisos creados después desde el libro de fianzas (ver más abajo).

**Cuentas sugeridas**: 560 Fianzas recibidas a corto plazo, 570 Caja, 572 Bancos y 778 Ingresos excepcionales
(fianza retenida). Gestión puede usar sus propias cuentas; el importe y el reparto son los mismos.

| Movimiento | Asiento sugerido |
|---|---|
| `fianza.cobrada` (efectivo) | 570 al debe / 560 al haber |
| `fianza.cobrada` (tarjeta, Bizum, transferencia) | 572 al debe / 560 al haber |
| `fianza.cobrada` (preautorización) | sin asiento: no hay dinero hasta la salida |
| `fianza.devolucion`, parte retenida | 560 al debe / 778 al haber |
| `fianza.devolucion`, devuelto en efectivo o tarjeta | 560 al debe / 570 o 572 al haber |
| `fianza.devolucion`, devuelto por transferencia | sin asiento todavía: sigue en la 560 |
| `fianza.transferida` | 560 al debe / 572 al haber |
| Preautorización con retención | 572 al debe / 778 al haber, solo por lo retenido |

Así, el saldo de la 560 de cada activo en gestión debe coincidir con `saldo_activo` del último aviso.

**Activación y fecha de corte.** En el `.env` del servidor del PMS:

1. `PMS_FIANZAS_ORIGEN=avisos`.
2. `PMS_FIANZAS_AVISOS_DESDE=AAAA-MM-DD`: el primer día que gestión contabiliza desde los avisos. Lo anterior ya
   está contabilizado con los CSV.

Desde ese momento, las devoluciones **a partir de la fecha de corte** van en `CONTROL_FIANZAS_*.csv` y las
**anteriores** siguen en `FIANZAS_*.csv` (se contabilizan con el CSV, como hasta ahora). Una exportación que abarque el
corte puede llevar los dos ficheros. Si una devolución por transferencia se registró antes del corte y la
transferencia se hizo después, va en `FIANZAS_*.csv` como pendiente y la transferencia se contabiliza con su aviso
`fianza.transferida`. El fichero de control tiene las mismas columnas, pero **no se contabiliza**: sirve para cuadrar. El `manifest.json` indica
`"fianzas_origen": "avisos"` y, en ese fichero, `"contabilizar": false`. Con el nombre nuevo, un importador que busque
`FIANZAS_*` no lo recoge, y una fianza no se apunta dos veces.

**Avisos que faltan.** El libro de fianzas del PMS (*Reservas → Devoluciones de fianza → Libro de fianzas*) compara
cada movimiento con su aviso. La Dirección puede generar los que falten desde la fecha de corte. Esos avisos llevan
un `id_evento` fijo (`pms-{tipo}-r{reserva_id}`) y `generado_desde_libro: true`, así que no se duplican. En ellos,
`saldo_activo` es el del día en que se generan.

### 5. `caja.cierre`

Cada recepcionista cierra su turno con el arqueo.

- `cierre_id`, `activo`, `activo_pms`, `recepcionista`.
- `desde`, `hasta`.
- `totales`: `{forma: importe}`. Las formas son `efectivo`, `tarjeta`, `bizum`, `transferencia`, `plataforma`,
  `preautorizacion` y `sin_forma`. Incluyen los cobros, las fianzas cobradas y, en negativo, las fianzas devueltas
  en efectivo o tarjeta.
- `efectivo_esperado`, `efectivo_contado`, `fondo`.
- `diferencia`: contado − fondo − esperado.
- `nota`: obligatoria si hay diferencia.
- `movimientos`: número de movimientos del turno.

Una diferencia distinta de 0 ya se ha avisado por correo a la Dirección. En gestión se puede llevar a una cuenta de
descuadres de caja.

### 6. `incidencia.cerrada`

Se cierra o cancela en el PMS una orden de trabajo correctiva o de mejora (las mismas que llegaron como
`incidencia.reportada`).

- `ot_pms_id`.
- `estado`: `cerrada` o `cancelada`.
- `fecha_cierre`, `solucion`.
- `coste_real` (o `null`).
- `asignado_a`.

Gestión cierra su incidencia espejo. Si no la conoce (por ejemplo, una orden anterior a la fase 4), la ignora y
responde 2xx. El coste real va al gasto del activo, si gestión lo lleva.

### 7. `kpi.diario`

A primera hora de cada día, uno por activo turístico. El `id_evento` es fijo: `pms-kpi-{activo}-{fecha}`.

- `activo`, `activo_pms`, `nombre`, `fecha`.
- Ocupación:
  - `unidades`, `ocupadas_hoy`.
  - `ocupacion`, `ocupacion_ayer` (%).
- Ingresos de ayer, sin IVA y repartidos por noches:
  - `adr_ayer`, `revpar_ayer`, `ingreso_ayer`.
- Movimiento del día: `llegadas_hoy`, `salidas_hoy`.
- Pendiente de cobro:
  - `facturas_pendientes`, `facturas_pendientes_importe`.
  - `deuda_alojados`: lo pendiente de los clientes que están dentro.
- Fianzas: `fianzas_por_transferir`, `fianzas_por_transferir_importe`.
- Mantenimiento: `ot_urgentes_abiertas`, `ot_fuera_de_plazo`.
- Caja: `descuadres_caja_ayer`, lista de `{diferencia, nota}`.

Sirve para el cuadro de mando de gestión, sin recalcular nada allí.

## Qué tiene que hacer gestión

1. Aceptar (2xx) y guardar los 7 tipos nuevos.
2. `reserva.ampliada`: no tratarlo como salida.
3. Fianzas: **decidido (14/10/2026), se contabilizan desde los avisos `fianza.*`** con el asiento sugerido. Hay que
   contabilizar solo los avisos con `contabilizar: true` y dejar de importar el CSV de fianzas. Cuando gestión esté
   lista, Alfonso pone `PMS_FIANZAS_ORIGEN=avisos` y la fecha de corte en el `.env` del PMS. Hasta entonces sigue el
   CSV `FIANZAS_*.csv`.
4. `incidencia.cerrada`: cerrar la incidencia espejo.
5. `kpi.diario` y `caja.cierre`: guardarlos para el cuadro de mando y el control de caja.
6. Cuando esté desplegado, avisar a Alfonso para que ponga `PMS_GESTION_EVENTOS_V2=1` en el `.env` del PMS.

## Fusión: facturas, pagos, proveedores y catálogo

Contrato «fusion1», fijado el 14/10/2026 por Alfonso y construido así en los dos programas. Las instrucciones
originales están copiadas en `pms/docs/fusion/` (`INSTRUCCION_FUSION_PMS_GESTION.txt`, apartados 1 y 1 bis, e
`INSTRUCCION_PMS_FUSION_FACTURAS.txt`). Si el contrato cambia, hay que cambiarlo en los dos programas y en esas copias.

**Decisiones**:
- Gestión manda siempre en los datos contables.
- Viajan solos, en los dos sentidos:
  - facturas recibidas con sus PDF;
  - pagos y cobros con su justificante;
  - facturas emitidas con su PDF;
  - proveedores y catálogo de productos y precios.
- Las fianzas **no**: siguen con sus avisos `fianza.*` (ver arriba).

### Activación

1. En el `.env` del servidor del PMS: `PMS_GESTION_SYNC_FACTURAS=1` (por defecto `0`: no se manda ni se aplica nada de
   la fusión). Gestión tiene su propio interruptor, `INVG_SYNC_FACTURAS`.
2. Por activo, en *Administración → Pasarela con gestión*: casilla **«Sincronizar facturas»**. Solo viaja lo de los
   activos marcados. Al marcarlo no se manda lo anterior: la carga inicial es el botón «Emparejar facturas» de gestión.
3. Proveedores y productos no son de un activo: viajan si al menos un activo tiene la casilla.

### Transporte

| Sentido | Ruta | Firma |
|---|---|---|
| PMS → gestión, avisos | `POST http://invergestion:8000/api/pms/eventos` (cola `gestion_cola`, mismos reintentos y aviso por correo, cabecera `X-INVG: 1`) | `X-PMS-Fecha` + `X-PMS-Firma` = HMAC-SHA256(`PMS_EVENTOS_SECRET`, fecha + "." + cuerpo) |
| Gestión → PMS, avisos | `POST http://pms-app-1:8000/api/gestion/eventos` | la misma que `/api/gestion/bloqueo` (que no cambia) |
| Gestión descarga un documento del PMS | `GET http://pms-app-1:8000/api/gestion/documento/{doc_id}` | HMAC(fecha + "." + doc_id) |
| El PMS descarga un documento de gestión | `GET http://invergestion:8000/api/pms/documento/{doc_id}` | HMAC(fecha + "." + doc_id) |
| Carga inicial | `GET http://pms-app-1:8000/api/gestion/fusion/inventario?activo=…&desde=AAAA-MM-DD` | HMAC(fecha + "." + "activo=…&desde=…") |
| Botón «PMS» de gestión | `GET https://pms.inversiete.es/sso/gestion?pase=…&firma=…` | hex HMAC-SHA256(`PMS_GESTION_SSO_SECRET`, pase) |

- Las rutas de documentos e inventario solo responden desde la red interna: rechazan con 403 cualquier petición con
  `X-Forwarded-For`, que es lo que añade Caddy a lo que llega de internet.
- Ventana de la firma: 5 minutos.

### Cabecera de todos los avisos

```json
{"id_evento": "único, [A-Za-z0-9._:-], máx. 120", "tipo": "…", "version": "fusion1", "emitido": "ISO UTC",
 "origen": "PMS" | "GESTION", "id_evento_causa": null | "id del aviso que lo provocó",
 "activo": "SFLORIDA | SAEROPUERTO | BABILONIA35… o null en proveedores y productos",
 "sociedad": "INV | CDC | EC | ETH o null", "datos": {…}, "documentos": [{…}]}
```

**Respuesta del receptor**:
- `200 {"ok": true}`, también si el `id_evento` ya se recibió: no se repite nada.
- En las altas, el PMS devuelve su identificador: `{"ok": true, "pms_id": "…"}`. Gestión devuelve el suyo como
  `{"ok": true, "resultado": {"id": "…"}}`, y el PMS lo guarda como enlace.
- Un tipo desconocido se guarda «sin_tratar» y se responde 200.
- Un aviso que todavía no se puede aplicar (por ejemplo, el pago de una factura que aún no ha llegado) se responde
  **400**. El emisor lo reintenta con su calendario normal.

**Documento** (cada elemento de `documentos[]`):

```json
{"doc_id": "…", "nombre": "…", "tipo_mime": "application/pdf|image/jpeg|image/png", "tamano": bytes,
 "sha256": "hex", "categoria": "FACTURA|JUSTIFICANTE|ALBARAN|OTRO"}
```

- Al descargarlo se responde el fichero con la cabecera `X-Sha256`.
- Si la sha256 no cuadra, el documento no se adjunta y queda **«A revisar»**.
- Los `doc_id` del PMS son `rd-N` (documento de la carpeta del activo) y `fd-N` (copia del PDF de una factura emitida,
  siempre la misma, para que su sha256 no cambie).
- El PMS descifra con `PMS_DOCS_KEY` dentro del propio PMS: la clave nunca sale.

### Avisos

| Tipo | Sentido | En el PMS |
|---|---|---|
| `factura_recibida.creada` / `.actualizada` | los dos | apunte de la Cuenta de gastos |
| `factura_recibida.anulacion_pedida` | los dos | «Pedir anulación»: el PMS nunca anula por su cuenta |
| `factura_recibida.anulada` | gestión → PMS | el apunte sale de la Cuenta de gastos (los documentos quedan en la carpeta y la auditoría guarda sus datos) |
| `factura_emitida.emitida` / `.rectificada` | PMS → gestión | factura del PMS, con su serie y número |
| `factura_emitida.emitida` | gestión → PMS | se guarda como facturación externa «INVERGESTION», fuera de la numeración y de la cadena de huellas del PMS |
| `documento.adjuntado` | los dos | documento de más de una factura, pago o cobro ya sincronizado |
| `pago.registrado` / `pago.anulado` | los dos | pago de la factura recibida, con justificante |
| `cobro.registrado` / `cobro.anulado` | los dos | cobro de la factura emitida |
| `proveedor.alta` / `.actualizado` | los dos | fichero de proveedores (por NIF) |
| `producto.alta` / `.actualizado` | los dos | catálogo (por referencia) |
| `precio.pedido` | PMS → gestión | línea con precio de un pedido autorizado |

**Identificadores del PMS (`pms_id`)**:
- `gasto-N`: factura recibida.
- `pago-N`: su pago (mismo N).
- `factura-N`: factura emitida.
- `cobro-N`: su cobro (mismo N).
- `externa-N`: emitida que vino de gestión.
- `proveedor-N` y `producto-N`.

Los nombres de `datos` de cada tipo son los del apartado 1 bis (los del CSV v1.1 del importador). Lo que no se
tenga va `null`.

### Reglas

- **Gestión manda.** Lo que llega de gestión se aplica siempre, aunque pise un dato del PMS. No genera avisos de
  vuelta: sin eco. Un aviso con `origen: "PMS"` que vuelve al PMS se guarda como «eco» y no se aplica.
- **Idempotente.** El mismo `id_evento` recibido 5 veces deja un solo cambio. Lo recibido se guarda en
  `fusion_entradas` y la auditoría.
- **Identidad, sin duplicar**:
  - Recibida: `pms_id` ↔ id de gestión; si no lo hay, NIF del proveedor + número + fecha de factura.
  - Emitida: su `pms_id`.
  - Pago o cobro: `pms_id` ↔ `PAG-`/`COB-`.
  - Proveedor: NIF.
  - Producto: referencia.

  Si se encuentra el gemelo (por ejemplo, entró por ZIP), se enlaza y no se crea otro.
- **Solo lectura.** Una factura recibida, un pago o un proveedor que ya está en gestión no cambia sus datos contables
  en el PMS. La pantalla los marca «Gestionada en INVERGESTION» y ofrece:
  - «Abrir en gestión»: el `/sso/pms` de siempre con `destino` = recibida|emitida|pago|proveedor e `id` = id de gestión.
  - «Adjuntar documento».
  - «Pedir corrección»: manda `factura_recibida.actualizada` con los datos corregidos, sin cambiar nada en el PMS.
  - «Pedir anulación».

  Datos contables de la recibida: proveedor, número, fechas, base, IVA, retención, total, forma de pago y OPEX/CAPEX.
  El concepto, la categoría, a qué apartamento se imputa y las notas sí se cambian en el PMS. Una factura del PMS
  que aún no ha llegado a gestión se edita con normalidad.
- **Avisos agrupados.** Los avisos del PMS toman los datos y documentos del registro al mandarse por primera vez.
  Un gasto registrado y completado enseguida (por ejemplo, con un segundo PDF) sale en un solo aviso con todo. En
  los reintentos se manda siempre lo mismo.
- Las facturas emitidas del PMS no se modifican nunca desde gestión (un cambio se hace con rectificativa). Un aviso
  de gestión sobre una de ellas solo guarda el enlace.

### Carga inicial

`GET /api/gestion/fusion/inventario?activo=…&desde=AAAA-MM-DD` contesta, sin documentos:

```json
{"recibidas": [datos…], "emitidas": [datos…], "pagos": [datos… con "tipo": "PAGO"|"COBRO"],
 "proveedores": [datos…], "productos": [datos…]}
```

Gestión solo simula hasta que Alfonso dice desde qué fecha se aplica.

### Botón «PMS» de gestión (SSO inverso)

- `pase` = base64url de un JSON con `email`, `nombre`, `usuario`, `destino` (inicio|recibida|emitida|pago|proveedor),
  `id`, `activo`, `emitido` (ISO UTC) y `nonce` (16 a 128 caracteres).
- Vale 60 segundos y una sola vez.
- El PMS busca al usuario por email (activo) y le abre su sesión normal: los permisos son los suyos en el PMS.
- Lleva a la pantalla del destino: Cuenta de gastos, Facturas o Proveedores.


## Calendario común (15/10/2026 · versión 1.66 del PMS)

Una sola agenda para los dos programas. Mismo transporte, firma, ventana de 5 minutos, idempotencia por `id_evento` y
cabecera que la fusión (contrato «fusion1»). Código: `app/calendario_comun.py`. La parte de gestión está en su
`app/calendario.py`.

### Tipos
`calendario.creada` · `calendario.actualizada` · `calendario.cancelada`. Respuesta 200 `{"ok": true}` al aceptarlo
(también si se ignora por versión: `{"ok": true, "ignorado": "version"}`). 400 si faltan uid, versión o tipo.

### Datos (`datos`)
`uid` (estable: `INVG-…` nace en gestión, `PMS-AG-<id>` cita de la Agenda, `PMS-LIM-<id>` limpieza), `version` (≥ 1,
+1 en cada cambio), `tipo` (CITA, TAREA, OT, PREVENTIVO, BLOQUEO, LIMPIEZA, VENCIMIENTO_PAGO, VENCIMIENTO_COBRO,
FISCAL, CONTRATO, SEGURO, AVAL), `subtipo`, `titulo`, `descripcion`, `lugar`, `inicio`/`fin` (hora de Madrid sin
zona: `AAAA-MM-DD` o `AAAA-MM-DDTHH:MM`; en día completo `fin` es el último día incluido), `todo_el_dia`, `activo`,
`unidad`, `sociedad`, `responsables`, `invitados` (correos; inversiete.es = inversiete.com), `estado` (PENDIENTE,
HECHA, CANCELADA), `recordatorio`, `repeticion` (diaria, laborables, semanal, mensual, anual), `repetir_hasta`,
`importe` (solo vencimientos y fiscal), `prioridad`, `origen`, `origen_col`, `origen_id`, `editable_en` (GESTION,
PMS, AMBOS), `solo_lectura`, `roles`, `url_gestion`.

### Reglas en el PMS
- Gestión → PMS: se guarda por uid; versión ≤ la guardada se ignora. Gestión manda: si el PMS tenía un cambio, queda
  en el historial de la entrada y su aviso pendiente se descarta. `cancelada` no borra (Outlook la quita).
- PMS → gestión: citas y tareas compartidas o públicas (tarea → TAREA; reunión, evento y recordatorio → CITA con
  subtipo), limpiezas programadas (LIMPIEZA, `editable_en` PMS) y cambios sobre citas de gestión con `editable_en`
  AMBOS (versión + 1). Nunca vencimientos, fiscal ni entradas de solo lectura. Sin eco. Cola con los reintentos de la
  fusión, en orden por uid (no sale un aviso mientras otro anterior de la misma entrada siga pendiente).
- Casilla de la superadministración, apagada al desplegar: apagada, lo recibido queda «sin tratar» y no sale nada. Al
  encenderla (1.67) se aplican primero, en orden de llegada, los avisos `calendario.*` «sin tratar» (la versión evita
  duplicados) y después se preparan las citas compartidas y las limpiezas de los últimos 60 días.
- Historial (1.67): solo con choque, es decir, cuando el PMS tiene un cambio que gestión aún no ha recibido. Si un aviso
  de gestión no trae `fin`, el PMS conserva el que tenía.
- Visibilidad: lo financiero y lo que gestión limita a `["superadmin","administracion","direccion"]` solo la
  superadministración y los roles Dirección Grupo, Dirección Sociedad y Administración / Finanzas, cada uno solo lo de
  sus sociedades (`sociedad`; si falta, el activo de la entrada). Citas y tareas: responsables, invitados y la
  dirección de su ámbito. Mantenimiento: por el activo del usuario.

### Outlook del PMS
`GET /cal/<clave>.ics` (clave `token_urlsafe(32)`, en la base solo su sha256). RFC 5545; UID `uid@pms.inversiete.es`;
SEQUENCE = versión; canceladas 60 días con STATUS:CANCELLED; VALARM el día antes a las 9:00 en vencimientos y fiscal
(`-PT15H` en día completo) y el recordatorio en las citas. Importes ocultos salvo «Mostrar importes» (administración y
dirección). Auditoría de cada acceso con la IP; más de 60 peticiones en una hora: 429 hasta la hora siguiente y aviso.


## Activos y unidades: maestros (15/10/2026 · versión 1.71 del PMS)

Activos y unidades iguales en los dos programas. Mismo transporte, firma, idempotencia por `id_evento` y cabecera
«fusion1». Contrato exacto: punto 8 de `docs/fusion/INSTRUCCION_PMS_MAESTROS_ACTIVOS.txt`. Código: `app/maestros.py`.

- **Reparto**: el PMS manda en lo operativo (alta y baja, código, bloque, uso, tipología, planta, superficie_m2,
  dormitorios, capacidad, estado, situación, renta_base, tarifa_base_noche, anejos y los datos del activo). Gestión
  manda en lo patrimonial y fiscal (propietaria, referencia y valores catastrales, uso catastral, IBI y TRUA).
- **PMS → gestión**: `maestro.unidad` (accion creada | actualizada | baja, `version` que sube en cada cambio
  operativo), `maestro.activo` y `maestro.cuadre` (03:30, por activo `por_uso` y `huella`).
- **Huella** (1.73): cada línea «pms_id|codigo|uso|situacion» sale de los mismos datos que viajan en
  `maestro.unidad`; gestión debe rehacerla con su campo `situacion` (situación de la vivienda: alquilada, vacia…),
  no con `estado` (ocupada, disponible, bloqueada). Si no hay situación, el hueco va vacío.
- **Gestión → PMS**: `maestro.catastro` (unidad por `pms_id`, activo por `activo_pms`; versión por ficha) y
  `maestro.pedir` (`pms_ids`: «todos» o lista). Lo operativo que mande gestión se ignora y se anota en auditoría.
- **Activos**: solo SFL, SAE y BAB35 (los que gestión conoce); los demás no salen.
- **Baja** (solo superadministración, sin reservas pendientes ni contrato vigente): no borra; la unidad queda con fecha de baja, fuera de servicio y fuera de las listas, del `por_uso` y de la
  huella. Gestión la marca BAJA.
- **Casilla** de la superadministración, apagada al desplegar. Encendido: primero la del PMS y después la de gestión.
