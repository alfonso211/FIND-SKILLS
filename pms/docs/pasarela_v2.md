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
3. Para las fianzas, elegir una de estas dos opciones:
   - Contabilizarlas desde los avisos (`fianza.*`).
   - Seguir con el CSV `FIANZAS_*.csv` del paquete de exportación, que no cambia. En ese caso, los avisos sirven de
     control.
4. `incidencia.cerrada`: cerrar la incidencia espejo.
5. `kpi.diario` y `caja.cierre`: guardarlos para el cuadro de mando y el control de caja.
6. Cuando esté desplegado, avisar a Alfonso para que ponga `PMS_GESTION_EVENTOS_V2=1` en el `.env` del PMS.
