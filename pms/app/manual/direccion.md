# Dirección y administración

## Panel de control
- Por cada activo: **ocupación**, **producción del mes** (facturado sin IVA ni garajes; incluye lo importado de SYADE), renta, **deuda vencida** y OT abiertas.
- Avisos: **facturas pendientes de cobro**, estancias vencidas e **hitos normativos** (Verifactu, factura electrónica…).

## Informes Excel
- **Ocupación**, **Producción**, **Morosidad**, **Costes de mantenimiento** y **Facturas pendientes de cobro** (con días pendientes y quién comprobó cada cobro).
- **Encuesta del INE** de apartamentos turísticos.
- **Programa anterior (SYADE)**: importar los listados de facturación y ver el resumen mensual. Las facturas se enlazan solas con los clientes que ya están en el PMS: por **DNI/NIF** y, si el cliente no lo tiene, por **nombre y apellidos** (solo si hay una única ficha con ese nombre; con dos fichas iguales no se enlaza), y sus importes (producción, total y fianzas) aparecen en la **ficha del cliente**. Es solo control de producción: la facturación válida para Hacienda empieza el 1 de enero de 2027.
- **Exportar a INVERGESTION**: facturas emitidas y recibidas en **un solo ZIP** (CSV, manifest.json y los PDF en pdf/emitidas y pdf/recibidas). **Envío semanal** con «Semana pasada»; pulse **Comprobar** antes de descargar. Si a alguna factura le falta su PDF, el paquete **no se genera** y se indica cuál (vuelva a subir ese documento).
  - **Comprobar** avisa de las facturas recibidas cuya fecha coincide con el día en que se registraron: revise que sea la de la factura.
  - Todos los documentos van en **PDF** (las fotos se convierten) con el nombre exacto de la columna archivo_pdf.

## Facturación
- **Facturas emitidas**: listado con filtros (pendientes de cobro, cobradas), PDF y **libro de facturas** para la gestoría.
- **Fecha de factura: último día del mes** de emisión (criterio de la gestoría).
- **Rectificar**: anula una factura con una rectificativa (no se borran facturas).
- **Servicios**: catálogo de servicios facturables (limpieza extra, parking…).

## Alquiler residencial (Babilonia 35)
- **Plano de apartamentos → C/ Babilonia 35**: una **carpeta por planta** (y por sótano de garaje) con el logotipo de Comercial del Campo. Al abrir una carpeta se ven sus viviendas, con un color por situación.
- La **primera vez** que se abre una vivienda se pide su **situación**: alquilada, vacía, reservada, en reforma menor, en obra mayor, ocupada sin título, en venta, uso propio / cedida u otra (indicando cuál). Si no se indica, se vuelve a pedir cada vez. Se cambia después con el botón **Situación** de la vivienda.
- Si está **alquilada**, se pide **crear o completar el contrato** con la lista de lo que falta. Con «Completar más tarde» no vuelve a salir ese día; al día siguiente, sí, hasta que el contrato esté completo. Mientras tanto se puede trabajar en la vivienda: **facturas recibidas**, **incidencias** y partes de trabajo.
- **Contratos → Expediente**: checklist de la hoja de control, datos del contrato, **contrato Word** relleno, inventario, **cobros con recibo**, carpeta de documentos y tareas en la agenda.
- **Unidades → Ficha alquiler**: certificado energético, registro, IBI y tasa, llaves, contadores e inventario.
- **Sociedades → Datos para contratos**: registro mercantil, representante, IBAN y contactos.
- **Recibos y cobros**: recibos mensuales de renta y su cobro.

- **Anular un contrato** hecho por error o que no sigue adelante: **Anular** en el contrato (o en **Editar** → **Anular contrato**), con su motivo. Con recibos cobrados no se anula: se rescinde o se da por finalizado. Con facturas, primero la rectificativa.

## Gastos
- **Informe a presidencia** (mensual, por activo): producción por tipo de estancia y servicios, gastos por proveedor con CAPEX/OPEX, resultado con semáforo y resumen mensual del año anterior y del actual. Lo revisa y envía «Recepción 1» de cada activo (o quien se indique en la ficha del activo, junto con los correos y el WhatsApp de envío; si no se indican correos, va a la presidencia).
- **Documentos recibidos**: carpeta de facturas y cartas de cada activo. El **lector** rellena los datos de la factura y marca en amarillo lo dudoso; las facturas **duplicadas** (mismo proveedor y nº) no se registran.
- **OPEX / CAPEX**: cada gasto lo indica; la cuenta de gastos muestra el total de cada uno y el Excel lo incluye.
- **Cuenta de gastos**: con **fecha de factura, vencimiento y forma de pago** (transferencia o cargo en cuenta); las pendientes vencidas se marcan en rojo y las que no tienen forma de pago muestran «falta forma de pago». Exportable a Excel.
  - **Retención de IRPF**: cada factura guarda el tipo, el % y el importe retenido; la columna **A pagar** ya lo descuenta. Se exporta a INVERGESTION en la columna retencion.
  - **Pagos retenidos**: facturas que alguien ha marcado para **no pagar todavía**, con motivo y **fecha de revisión**. Le llega un correo al momento, salen en el **resumen diario** y en un aviso del **Panel**. No se pueden marcar pagadas hasta **Liberar pago** (lo hace quien paga o quien la retuvo); **Retener pago** permite cambiar la fecha de revisión.

## Administración
- **Usuarios** y **Roles y permisos**: alta de personas y qué puede hacer cada una en cada activo.
- **Sociedades**, **Avisos por correo** (servidor y resumen diario) y **Auditoría** (quién hizo qué y cuándo).

## Seguridad y continuidad
- Copia de seguridad **antes de cada actualización** y copia diaria **fuera del servidor** (Google Drive).
- **Mantenimiento diario a las 06:00**: revisa servidor, copias, base de datos, documentos, correo y seguridad; arregla solo lo que puede y, si hay un fallo grave, envía un **correo URGENTE** al director técnico. Los lunes, resumen semanal.
- **Guía de emergencia** (`deploy/RECUPERACION.md`): qué hacer si el PMS no responde, si se borran datos, si se pierde el servidor o si hay un virus. Guarde impresa la guía y el **kit de emergencia** (contraseña del cifrado de las copias y `PMS_DOCS_KEY`) **fuera del servidor**.
- Si el programa se bloquea, **se reinicia solo** en 1-3 minutos y deja un informe con la causa.
