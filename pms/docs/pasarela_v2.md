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
