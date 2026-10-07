# Novedades

## 2026-10-07 · Versión 1.15 · Órdenes de trabajo a personal propio o subcontrata
- **Mantenimiento**: en la OT, «Asignado a» es **Personal propio** o **Subcontrata** (de Proveedores). La orden se envía a quien la hace: al personal propio por WhatsApp; a la subcontrata por correo (con el PDF) y/o WhatsApp (con enlace al PDF), según se elija. Siempre con **copia al personal de mantenimiento propio**.

## 2026-10-07 · Versión 1.14 · Panel: cada casilla abre su listado
- **Todos**: en la situación de cada activo del panel, **cada casilla lleva a su listado** (llegadas y salidas, contratos, facturas, recibos, órdenes de trabajo, unidades…). El plano se abre con el botón **«🗺️ Ver plano del edificio»** o pulsando en una zona en blanco de la tarjeta.

## 2026-10-07 · Versión 1.13 · Factura de servicios aparte y parte de limpieza ajustable
- **Recepción**: los servicios (extras, limpieza contratada…) se facturan siempre en una **factura aparte** de la estancia. Al emitirlas se pueden **imprimir o enviar las dos** al cliente por correo o WhatsApp.
- **Recepción**: antes de imprimir o enviar el parte de limpieza se puede **ordenar**, marcar **urgente**, añadir notas o **pasar una limpieza a otro día**.
- **Recepción y limpieza**: **orden de limpieza urgente** durante el día, que se imprime o se envía al momento.

## 2026-10-07 · Versión 1.12 · Limpieza de salida solo tras el check-out
- **Recepción y limpieza**: la limpieza por salida entra en el parte **cuando recepción hace el check-out**. Ya no se prevé por la fecha de salida, porque el cliente puede renovar.

## 2026-10-07 · Versión 1.11 · Parte de limpieza y revisión de salida
- **Recepción**: en la reserva se añaden los **servicios extra** (plaza extra, toallas… del catálogo o escritos) y la **limpieza contratada** con su día y periodicidad; todo pasa a la **factura de la estancia** («Facturar extras» si se pide después).
- **Recepción y limpieza**: nuevo **Parte de limpieza** diario con las salidas (y si hay llegada, «antes del…»), las limpiezas contratadas y las extra. Se imprime en PDF o se envía por WhatsApp o correo, y el Excel queda en Documentos recibidos. Recepción valida cada limpieza con **Hecha**; lo no validado pasa al día siguiente.
- **Mantenimiento**: con cada check-out se abre sola una **OT de revisión de salida** del apartamento.

## 2026-10-07 · Versión 1.10 · Babilonia 35 en carpetas
- **Dirección**: en el **Plano de apartamentos** y en el panel, Babilonia 35 aparece como **carpetas por planta** (y por sótano) con el logotipo de Comercial del Campo; dentro, sus viviendas o plazas.
- **Dirección**: la primera vez que se abre una vivienda se indica su **situación** (alquilada, vacía, en reforma, en obra…). Si está alquilada, se pide **completar el contrato** cada día hasta que esté completo, sin impedir trabajar en la vivienda.
- **Dirección**: desde la vivienda se suben sus **facturas recibidas** (ya imputadas a ella) y se abren **incidencias**; en su ficha se ven contratos, facturas e incidencias.

## 2026-10-07 · Versión 1.9 · Mantenimiento diario automático
- **Dirección**: cada día a las **06:00** el sistema revisa el servidor y el PMS (contenedores, acceso web, certificado, disco, copias de seguridad, base de datos, documentos, correo y seguridad) y **arregla solo** lo que puede.
- **Dirección**: si hay un fallo grave que necesita intervención, llega un **correo URGENTE** con lo que falla y qué hacer; lo arreglado y los avisos nuevos llegan en un correo normal, y los lunes un resumen semanal.

## 2026-10-07 · Versión 1.8 · Exportación a INVERGESTION con los PDF
- **Dirección**: la exportación a INVERGESTION sale en **un solo ZIP** con los CSV, un **manifest.json** y los **PDF** en las carpetas pdf/emitidas y pdf/recibidas, para que INVERGESTION adjunte cada PDF a su factura.
- **Dirección**: el nº de las facturas emitidas va como **SF-00001-2026** (igual que el nombre de su PDF), también en las rectificativas; el país siempre en código (ES) y las líneas del concepto separadas con «|».
- **Dirección**: si a alguna factura le falta su PDF, la exportación **no se genera** y avisa de cuál.

## 2026-10-07 · Versión 1.7 · Informe mensual a la presidencia
- **Recepción 1**: el primer día laborable de cada mes recibe el aviso para preparar el **informe a la presidencia** del mes anterior (**Facturación e informes → Informe a presidencia**).
- **Recepción 1**: el informe se **revisa en pantalla**, se marca como comprobado y se envía en **PDF** por **correo** o **WhatsApp**; el **Excel** queda guardado en los documentos del activo.
- **Dirección**: el informe incluye producción por tipo de estancia (menos de 1 semana, 1 semana, 2 semanas, 1 mes, renovaciones), servicios, gastos por proveedor con CAPEX/OPEX, **resultado con semáforo** (rojo, naranja, verde) y el **resumen mensual** del año anterior y del año en curso.
- **Dirección**: en la ficha de cada activo se puede indicar quién envía el informe, los correos y el WhatsApp de destino.

## 2026-10-07 · Versión 1.6 · Menú sin desplazamiento
- **Todos**: el **menú de la izquierda** cabe entero en la pantalla. Si no caben todos los grupos, los que no está usando se pliegan (▸) y se abren con un clic en su título.

## 2026-10-07 · Versión 1.5 · Pantallas de un vistazo
- **Todos**: **panel de control** reordenado: el **plano por plantas arriba** (con botones para elegir el edificio) y la situación de cada activo en una franja; la **agenda**, reducida, a la **derecha** con los avisos.
- **Todos**: las pantallas caben en el monitor sin bajar: las listas se desplazan dentro de su recuadro, con la **cabecera fija** y los **botones de cada fila siempre visibles**.
- **Todos**: menú más compacto; en tableta se abre con **☰** para dejar todo el ancho a la pantalla de trabajo.
- **Todos**: las ventanas de datos (formularios) nunca son más altas que la pantalla: el botón **Guardar** queda siempre a la vista.

## 2026-10-07 · Versión 1.4 · Lector de facturas y duplicados
- **Todos**: los formularios ya no montan unas casillas sobre otras; todo queda legible.
- **Todos**: clientes, proveedores, sociedades y activos tienen **código postal, población, provincia y país**.
- **Recepción y dirección**: **lector de facturas**: al subir el PDF o la foto rellena los datos solo; lo dudoso sale **en amarillo** para revisarlo.
- **Recepción y dirección**: cada gasto indica si es **OPEX** (gasto corriente) o **CAPEX** (inversión).
- **Recepción y dirección**: **facturas duplicadas**: mismo proveedor y nº, no se registra; si solo se parece, el programa pregunta antes de guardar.

## 2026-10-06 · Versión 1.3 · Retenciones y pagos retenidos
- **Recepción y dirección**: las facturas recibidas admiten **retención de IRPF** (profesionales 15 %, inicio de actividad 7 %, arrendamientos 19 %, módulos 1 %) u **otra retención** con su %. Se descuenta de lo que hay que pagar y se envía a INVERGESTION.
- **Recepción y dirección**: nueva opción **«Retener el pago»** (no pagar de momento) con **motivo** y **fecha de revisión**.
- **Dirección y administración**: aviso por **correo al momento**, en el **resumen diario** y en el **Panel** de las facturas con el pago retenido. Se liberan con **Liberar pago**.

## 2026-10-06 · Versión 1.2 · Forma de pago de las facturas recibidas
- **Recepción y dirección**: al registrar una factura recibida es **obligatorio** indicar si se paga por **Transferencia** o si está **Cargada en cuenta (domiciliación)**.
- **Recepción y dirección**: en **Cuenta de gastos** se ve la forma de pago de cada factura; las antiguas sin ella muestran **«falta forma de pago»** (complétela con **Editar**).
- **Dirección**: la exportación a INVERGESTION envía TRANSFERENCIA o DOMICILIACION, y **Comprobar** avisa de las facturas sin forma de pago.

## 2026-10-06 · Versión 1.1 · Exportación a INVERGESTION
- **Recepción y dirección**: al subir una factura recibida, la **fecha de la factura** ya no se rellena con la de hoy: hay que poner la **impresa en la factura** (es la que cuenta para el trimestre del IVA). No admite fechas futuras.
- **Dirección**: en la exportación a INVERGESTION, las facturas subidas como **foto** salen ahora en **PDF**, con el nombre exacto de la columna archivo_pdf.
- **Dirección**: **Comprobar** avisa de las facturas recibidas con fecha igual al día de registro, para revisarlas antes de enviar.

## 2026-10-06 · Versión 1.0 · Primer manual
- **Todos**: nuevo apartado **Manual de uso** en el menú, con el manual de cada puesto y las novedades de cada actualización (también en PDF).
- **Todos**: si el programa se bloquea, **se recupera solo** en 1-3 minutos; si está muy ocupado, pide **reintentar** en lugar de quedarse parado.
- **Recepción**: el **lector de documentos** es más rápido y fiable (DNI, NIE/TIE y pasaporte; webcam y móvil). Muestra los segundos que lleva leyendo.
- **Recepción**: **facturar sin cobrar** en reservas y renovaciones; aviso diario de **facturas pendientes de cobro** y botones **Cobrada / Deshacer cobro**.
- **Todos**: las **facturas emitidas** llevan fecha del **último día del mes** de emisión.
- **Dirección y recepción**: las **facturas recibidas** guardan su **vencimiento**; las vencidas sin pagar se marcan en rojo.
- **Dirección**: **expediente del contrato de vivienda** (Babilonia 35), **importación de SYADE** y **exportación a INVERGESTION**.
