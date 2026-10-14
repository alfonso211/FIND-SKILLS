# Dirección y administración

## Informe diario de dirección
- Cada mañana, a la hora del resumen, llega un correo con los indicadores de cada activo turístico:
  - ocupación de hoy y de ayer;
  - ADR y RevPAR de ayer, sin IVA;
  - llegadas y salidas;
  - facturas pendientes de cobro y lo que deben los alojados;
  - fianzas por transferir;
  - OT urgentes y fuera de plazo;
  - descuadres de caja.
- Destinatarios: PMS_INFORME_DIRECCION (por defecto Bárbara y Alfonso). Los mismos datos van a gestión.
- **Caja y cierres de turno**: la Dirección ve los cierres de todos los recepcionistas de sus activos. Un descuadre llega por correo al momento.

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

## Devoluciones de fianza
- Cuando Recepción da la salida con fianza **por transferencia**, llega un **correo** con cliente, apartamento, importe, IBAN y fecha (y Recepción puede enviarlo también por **WhatsApp**). Hecha la transferencia, se marca en *Reservas → Devoluciones de fianza*.
- Lo que **supera la fianza** se factura al cliente sin IVA (indemnización por daños, art. 78.Tres.1º LIVA) y queda **pendiente de cobro** en Facturas emitidas.
- **Pedidos de reposición sin autorizar**: si un pedido de reposición lleva más de 3 días pendiente de Recepción 1, llega un correo cada día laborable con la lista hasta que se autorice.
- **Informe de roturas** (en *Reservas → Devoluciones de fianza*): qué se rompe o falta más, en qué apartamentos y su coste, con Excel.
- Todas las devoluciones van en la exportación a **INVERGESTION** (FIANZAS_*.csv) para la gestoría. Los avisos quedan en *Administración → Avisos* (registro de envíos).
- **Libro de fianzas** (*Reservas → Devoluciones de fianza → Libro de fianzas*, con permiso de finanzas):
  - **Saldo por activo**: lo que se custodia ahora (de clientes alojados y transferencias sin hacer) y las preautorizaciones de tarjeta, que no son dinero.
  - **Movimientos del periodo**: cobros, devoluciones y transferencias, cada uno con su asiento sugerido (560 fianzas, 570 caja, 572 bancos, 778 retenido) y si gestión ha recibido el aviso.
  - **Lo que no cuadra**: movimientos sin aviso, avisos que no llegan, devoluciones sin el cobro registrado y reservas con fianza cobrada sin devolver.
  - **Excel** con las tres partes.
- **Fianzas contabilizadas desde los avisos**: gestión las contabiliza con los avisos de fianza cuando en el `.env` del servidor estén `PMS_FIANZAS_ORIGEN=avisos` y `PMS_FIANZAS_AVISOS_DESDE=AAAA-MM-DD` (primer día). Desde entonces las devoluciones a partir de esa fecha salen en **CONTROL_FIANZAS_*.csv**, solo para cuadrar; las anteriores siguen en FIANZAS_*.csv, así que se puede activar en cualquier momento sin perder ninguna. Si falta algún aviso, el botón **Generar los avisos que faltan** del libro los crea sin duplicar.

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

## Partes de estado y panel técnico
- Mantenimiento y limpieza señalan las deficiencias con **partes de estado** (listas encadenadas, foto obligatoria, GPS) y recepción genera la orden de trabajo. Los **críticos** dejan la unidad fuera de servicio y le llegan también por correo.
- **Mantenimiento → Partes de estado → Panel técnico**: **Pareto** de los elementos que más fallan (en negrita, el 80 %), **tiempo medio de reparación** (del parte al cierre de la OT; global, por departamento y de los críticos) e **intervenciones técnicas por unidad y mes** para controlar el coste de cada vivienda.

## Órdenes de trabajo: técnico en el móvil y conformidad
- Recepción o dirección asignan la OT (personal propio o subcontrata) y la envían: el técnico recibe un **enlace firmado** (caduca a los 30 días) para gestionarla desde el móvil sin usuario, con llegada y salida, trabajos, material, estado al finalizar y **firma**.
- Los resultados llegan al momento (aviso sonoro en el PMS y correo); **derivar a subcontrata** va en rojo. Las OT en pausa (material, otra visita, otro) se recuerdan cada día hasta que alguien actúa.
- La OT solo queda **cerrada y archivable** con la **conformidad de la propiedad** (usuario y fecha de quien la da), que figura en el parte PDF junto a la firma del técnico.

## Pedidos de material y catálogo
- **Mantenimiento → Pedidos de material**: los de Dirección y Recepción 1 quedan autorizados; los demás los autoriza Recepción 1 (Dirección también puede). Se envían al proveedor en PDF y se marcan como recibidos.
- **Catálogo de productos**: referencia, artículo, familia, unidad, precio sin IVA, marca, referencia y nombre del proveedor.
  - **Importar de INVERGESTION**: el fichero INVERGESTION_PRODUCTOS_….zip. Da de alta lo nuevo y actualiza precio y datos de lo que ya existe; no borra nada y volver a cargarlo no duplica.
  - **Enviar a INVERGESTION**: descarga PRODUCTOS_PMS_<ACTIVO>_<fecha>.zip con las altas hechas en el PMS y los pedidos con precio, solo lo nuevo desde el último envío. «Fichero de prueba» lo descarga sin marcarlo como enviado.

## Gastos
- **Informe a presidencia** (mensual, por activo): producción por tipo de estancia y servicios, gastos por proveedor con CAPEX/OPEX, resultado con semáforo y resumen mensual del año anterior y del actual. Lo revisa y envía «Recepción 1» de cada activo (o quien se indique en la ficha del activo, junto con los correos y el WhatsApp de envío; si no se indican correos, va a la presidencia).
- **Documentos recibidos**: carpeta de facturas y cartas de cada activo. El **lector** rellena los datos de la factura y marca en amarillo lo dudoso; las facturas **duplicadas** (mismo proveedor y nº) no se registran.
- **OPEX / CAPEX**: cada gasto lo indica; la cuenta de gastos muestra el total de cada uno y el Excel lo incluye.
- **Cuenta de gastos**: con **fecha de factura, vencimiento y forma de pago** (transferencia o cargo en cuenta); las pendientes vencidas se marcan en rojo y las que no tienen forma de pago muestran «falta forma de pago». Exportable a Excel.
  - **Retención de IRPF**: cada factura guarda el tipo, el % y el importe retenido; la columna **A pagar** ya lo descuenta. Se exporta a INVERGESTION en la columna retencion.
  - **Pagos retenidos**: facturas que alguien ha marcado para **no pagar todavía**, con motivo y **fecha de revisión**. Le llega un correo al momento, salen en el **resumen diario** y en un aviso del **Panel**. No se pueden marcar pagadas hasta **Liberar pago** (lo hace quien paga o quien la retuvo); **Retener pago** permite cambiar la fecha de revisión.

## Administración
- **Usuarios** y **Roles y permisos**: alta de personas y qué puede hacer cada una en cada activo.
- Al **cambiar la contraseña**, al **restablecerla** o al **desactivar** un usuario, se cierran todas sus sesiones abiertas (otros ordenadores o móviles).
- Los **colaboradores** (subcontratas) reciben el calendario de vacaciones sin la hoja de saldos de la plantilla.
- **Borrar un usuario** (botón **Borrar** en Administración → Usuarios; solo lo tienen el Director Técnico y el administrador): deja de poder entrar y desaparece de la lista; su email queda libre. Si ya ha trabajado en el PMS, su nombre se conserva solo en el historial (partes, gastos, auditoría). Esas dos cuentas no se pueden borrar.
- **Sociedades**, **Avisos por correo** (servidor y resumen diario) y **Auditoría** (quién hizo qué y cuándo).

## Hora del programa
- El programa trabaja siempre en **hora de Madrid**, aunque el servidor esté en otra zona. Si el reloj del ordenador de alguien va desfasado más de 3 minutos, le sale un aviso al entrar; a la Dirección, además, si el servidor no está en hora de Madrid.
- Hasta la versión 1.49 el servidor no tenía la zona de Madrid y guardaba la hora UTC (2 horas menos en verano, 1 en invierno). Para corregir esas horas antiguas (fichajes, partes, limpiezas y OT) hay un programa que primero solo enseña lo que cambiaría: `python -m app.corregir_hora --hasta "AAAA-MM-DD HH:MM"`. Se aplica una sola vez, con copia previa.

## Control del preventivo y OCA
- **Mantenimiento → Plan preventivo**: semáforo de cada revisión e inspección OCA, con su último documento (informe, acta o certificado) y las deficiencias pendientes con su OT. Botón **Excel** para entregar el registro a la propiedad o a una inspección.
- Cada **lunes** llega por correo al director técnico lo vencido, las deficiencias sin subsanar y las inspecciones OCA de los próximos 60 días (solo si hay algo).
- La plantilla normativa incluye las inspecciones OCA habituales (BT, ascensores, PCI, eficiencia energética térmica, centro de transformación y gas). Las periodicidades son orientativas: revíselas con cada instalación.

## Seguridad y continuidad
- Copia de seguridad **antes de cada actualización** y copia diaria **fuera del servidor** (Google Drive).
- **Mantenimiento diario a las 06:00**: revisa servidor, copias, base de datos, documentos, correo y seguridad; arregla solo lo que puede y, si hay un fallo grave, envía un **correo URGENTE** al director técnico. Los lunes, resumen semanal.
- **Guía de emergencia** (`deploy/RECUPERACION.md`): qué hacer si el PMS no responde, si se borran datos, si se pierde el servidor o si hay un virus. Guarde impresa la guía y el **kit de emergencia** (contraseña del cifrado de las copias y `PMS_DOCS_KEY`) **fuera del servidor**.
- Si el programa se bloquea, **se reinicia solo** en 1-3 minutos y deja un informe con la causa.
- **Intentos de acceso**: 5 contraseñas mal bloquean ese usuario 15 minutos; 20 intentos fallidos desde la misma conexión (IP) la bloquean 15 minutos, aunque se prueben usuarios distintos. Los enlaces públicos (técnico, fichaje, revisión, ofertas, aprobaciones) se bloquean igual tras 30 enlaces no válidos desde la misma conexión.
- Cada bloqueo llega por **correo al director técnico** (`PMS_SEGURIDAD_AVISOS`). Si es un usuario real que existe, conviene confirmar que fue él; si no, cambiar su contraseña.
- **Administración → Usuarios** muestra arriba los **accesos bloqueados** con el botón **Desbloquear**. Úselo solo si sabe quién es (una oficina propia con varias personas equivocándose comparte la misma conexión).
- **Protección del navegador** (`PMS_CSP`): el programa solo ejecuta su propio código. Si alguna pantalla dejara de funcionar tras una actualización, se puede poner `PMS_CSP=informe` en el `.env` (solo anota, no bloquea) y avisar al soporte.

## Partes de trabajo e informe quincenal
- **Mantenimiento → Parte de trabajo diario**: parte de cada día de mantenimiento y limpieza (OT terminadas, limpiezas hechas y actuaciones anotadas). Recepción lo valida y queda archivado en PDF y Excel en **Documentos**.
- **Informe quincenal**: trabajos totales de la quincena por área, tipo y persona; se puede descargar o archivar. Permiso nuevo: **partes.validar** (dirección y recepción).

## Vacaciones y ausencias del personal
- **Personal → Vacaciones y ausencias**: dirección aprueba las de Recepción 1, Recepción 2 (después del visto bueno de Recepción 1) y oficinas. El aviso llega al Director General y al Director Técnico y **basta con que apruebe uno**; la presidencia no interviene. Las pendientes salen también en el **Panel de control**. Las de limpieza y conserjería las aprueba Recepción 1 (dirección también puede).
- Las de **mantenimiento** solo las autoriza el **director técnico**: rol **Dirección Técnica** (permiso «personal.autorizar_mto»), que se suma a su rol de dirección. Se asigna en Administración → Usuarios.
- **Resumen del año** y **Excel** con todas las ausencias y los días aprobados por persona.
- Con **Todos los activos** arriba, la pantalla muestra las ausencias de todos los activos (con el nombre de cada uno), y el resumen y el Excel también.
- Las solicitudes pendientes salen arriba, sean del mes que sean, con **Autorizar**, **Desestimar** (motivo obligatorio) y **Anular** (solicitud con un error o que no procede; motivo obligatorio). Cada decisión se comunica por correo al trabajador y a Recepción del activo; si el trabajador no tiene correo, se abre el WhatsApp con el mensaje escrito. Queda todo registrado: las anuladas no se borran, se ven con el filtro *Anuladas*.
- Si una solicitud de vacaciones **supera el saldo** de la persona, sale el aviso en rojo antes de aprobarla.

## Gestión del personal: ficha, saldo, documentos y jornada
- **Reglas**:
  - El **Director Técnico** da de alta al personal propio de las sociedades y enlaza su usuario del PMS (un usuario, una ficha).
  - Recepción solo da de alta subcontratas.
  - **Recepción 1** de cada activo se asigna en *Activos → Editar*.
- **Vacaciones** (botón en la ficha):
  - Muestra lo que corresponde, lo disfrutado, lo solicitado y lo pendiente de solicitar.
  - El Director Técnico registra los periodos ya disfrutados o ya acordados (quedan autorizados) y puede anularlos con motivo.
  - Los cambios se agrupan: cada 3 horas, en días laborables de 8 a 20 h, se genera el **calendario de vacaciones** en PDF con todos ellos y se envía a todos los usuarios y colaboradores. En *Vacaciones y ausencias* se ven los pendientes, con el botón **Enviar calendario ahora**.
- **Recordatorio**: cada lunes se avisa por correo a quien tiene días sin solicitar, con el plazo del 31 de diciembre.
- **Comprobar personal** (en *Fichas del personal*) tiene cuatro funciones:
  - Revisa activos sin Recepción 1, nombres que no cuadran, usuarios repetidos y solicitudes mal clasificadas (estas se corrigen con un clic).
  - **Generar las fichas desde los usuarios** crea las que falten, con el área y el activo según el rol.
  - **Borrar todo el personal** borra todas las fichas, sus fichajes, documentos y envíos. Solo pueden hacerlo las cuentas autorizadas y hay que escribir «BORRAR PERSONAL». Las ausencias de los usuarios se conservan.
- **Personal → Fichas del personal → Editar**: ficha del empleado (DNI, puesto, contrato, jornada semanal, alta y baja, días de vacaciones del convenio y su usuario del PMS). Solo la ven Recepción 1 de su activo y la dirección.
- **Saldo de vacaciones**: los días del convenio (30 naturales por defecto, o los que indique la ficha) prorrateados por la fecha de alta y de baja: disfrutadas, solicitadas y pendientes de solicitar. Se ve en la columna **Vacaciones**.
- **Docs.**: contrato, nóminas, reconocimiento médico, formación PRL… cifrados y con vencimiento. Los que vencen en 30 días salen en el panel y en el resumen diario de correo.
- **Registro de jornada** (art. 34.9 ET): el personal propio ficha desde **Mi jornada** (con usuario) o con su **Enlace** personal en el móvil. En **Personal → Registro de jornada**: horas del mes por persona, **Detalle**, **Corregir** (queda el original, quién y el motivo), **Registro manual**, **Informe PDF** para firmar y **Excel** para la asesoría. Se conserva 4 años.
- **Panel de control**: tarjeta **Personal hoy** con quién falta, quién está dentro, olvidos de fichar la salida y documentos que vencen.

## Colaboradores (subcontratas)
- **Alta**: en *Administración → Usuarios*, nuevo usuario con su correo, en **Colaborador externo de** elija su empresa (ficha de Proveedores) y dele el rol **Colaborador** en los activos donde trabaja. Un usuario por persona; desactívelo al terminar el contrato.
- El colaborador **solo entra en su portal**: el programa le bloquea cualquier otra pantalla. Ve las OT encargadas a su empresa o a su personal (y las gestiona con **Gestionar**, como con el enlace de WhatsApp: tiempos, trabajos, material, estado final y firma), sus líneas de los partes validados, lo que se ha enviado a su personal (OT, partes de limpieza) y la ficha de su personal.
- **Sube** facturas, albaranes, presupuestos, documentación de personal y legal / CAE. Quedan **pendientes de revisar** en Documentos recibidos y se avisa por correo a Recepción 1.
- Antes de dar acceso: contrato de **encargado del tratamiento** (art. 28 RGPD) con la subcontrata.

## Documentación legal de los activos
- **Administración → Documentación legal**: checklist de lo obligatorio en cada activo según sea de **apartamentos turísticos** (declaración responsable y Registro de Empresas Turísticas, licencias municipales, SES.HOSPEDAJES, hojas de reclamaciones, placa, seguros, PCI, RITE, ascensores, legionela, DDD, PRL…) o de **alquiler residencial** (CEE, depósito de fianzas, licencia de primera ocupación, IEE, instalaciones, seguros, contratos…).
- **Escanear / subir**: PDF o fotos (varias fotos se unen en un PDF). Con la fecha del documento, el vencimiento sale solo en los que caducan (seguros, revisiones, CEE…). Se avisa **60 días antes** («por vencer») y al caducar.
- **Datos**: fechas, notas y **No aplica** (con el motivo). **Documento propio**: añade un punto que no está en el catálogo.
- **Imprimir checklist** (PDF) y **Enviar** cada documento por correo.
- **Cada lunes**: correo a **Recepción 1** con lo que falta o ha caducado en su activo y a la **dirección** con el total de todos los activos, hasta que esté completo.
- El catálogo es orientativo (normativa de la Comunidad y del Ayuntamiento de Madrid a octubre de 2026): conviene revisarlo con la gestoría.

## Cobros de alquiler de otro programa
- **Alquiler residencial → Cobros de otro programa**: **Importar facturas (PDF o ZIP)** lee cada factura simplificada (inquilino, importe y mes). En la revisión se indica de qué mes a qué mes se repite la renta (por defecto, de enero al mes actual); avisa si alguna factura es de un mes distinto (inquilino nuevo).
- Al importar: se abre la **ficha del inquilino** si no existe (el piso y el contrato se completan después en **Contratos**) y se guarda **un ingreso cobrado por mes**, que cuenta en la producción del activo (panel, informes e informe a presidencia). Repetir la importación actualiza, no duplica.
- **Documento** de cada inquilino (PDF con sus mensualidades) y **Excel de ingresos** con todos los cobros para la contabilidad. **Borrar cobros** de un inquilino para corregirlo.

## Facturas pagadas: justificante obligatorio
- En la **Cuenta de gastos**, una factura solo se marca como pagada con el botón **Pagado**, que pide **adjuntar el justificante de pago** (transferencia, cargo en cuenta…) y la fecha. Sin justificante no se puede marcar. El justificante queda en **Documentos recibidos** («Justificante de pago») y se abre con el botón **Justificante**.

## Inversiones (CAPEX)
- **Inversiones (CAPEX) → Proyectos CAPEX → Nuevo proyecto**: activo, título, presupuesto objetivo y, si se quiere, una **plantilla «CAPEX tipo»** que carga capítulos, partidas y documentos base.
- **Presupuesto**: **Importar BC3** (con mediciones), **Añadir desde base de precios** o **Nuevo capítulo**. Cantidades y precios se escriben en la tabla y se guardan solos. Las partidas sin medir salen en amarillo. Arriba se ven el PEM, el PBL (con GG y BI), el total con IVA y la desviación sobre el objetivo.
- **Documentos**: planos (PDF, DWG, DXF), fotos del estado previo, pliegos y licencias. Los marcados «Va a licitación» se envían a los contratistas.
- **Licitación** → **Pedir ofertas**: se eligen los proveedores y el plazo. Cada uno recibe un enlace personal y un Excel protegido, **sin los precios base**. La tabla muestra si han abierto el enlace y si han enviado la oferta. Si alguien devuelve el Excel por correo, súbalo con **Subir su Excel**. Para terminar, **Cerrar recepción y comparar**.
- **Comparativo y adjudicación**: mapa de calor por partida y capítulo (azul = baja anormal, rojo = exceso; ★ = mejor oferta completa) y **PDF del comparativo**. Se adjudica todo a un contratista o cada capítulo a uno distinto.
- **Aprobación**: por encima de 30.000 € sin IVA, la adjudicación va por correo a la **Dirección General** con el comparativo y los botones **Aprobar** y **Rechazar**. La obra queda bloqueada hasta su decisión. Si la rechaza, el proyecto vuelve al comparativo.
- **Plantillas CAPEX tipo** y **Base de precios (BC3)**: se gestionan en sus pantallas. La forma más rápida de crear una plantilla es abrir un proyecto y pulsar **Guardar como plantilla**.

## Pasarela con INVERGESTION (gestión)
- **Administración → Pasarela con gestión**: estado de la conexión, avisos enviados a gestión (reservas, salidas, incidencias y liquidaciones) y los que no han llegado. Si gestión no responde, el PMS reintenta solo (1 min, 5 min, 30 min, 2 h y después cada 2 h) y avisa por correo; no se pierde nada. **Reintentar ahora** adelanta el reintento.
- **Comisión de cada canal** (% del bruto: Booking, Airbnb…) por activo. Con ella se calcula el neto de la **liquidación mensual** que recibe gestión; gestión la compara con los cobros del banco.
- **Liquidación mensual**: **Ver** la de un mes y **Mandar a gestión**. Si se marca **Mandar sola cada mes**, el día 2 se manda la del mes anterior. La cifra sale de las reservas del PMS: si no están todas metidas, saldrá corta. Gestión no sustituye una producción metida a mano sin enseñar antes las diferencias.
- **Botón «Gestión»**: solo lo ven el superadministrador y las cuentas de PMS_GESTION_USUARIOS (por defecto alfonso@inversiete.es y barbara@inversiete.es); a los demás no les aparece y el servidor les niega el pase.
- Claves: PMS_EVENTOS_SECRET y PMS_GESTION_SSO_SECRET en el .env del servidor, las mismas en gestión. Sin la segunda, el botón «Gestión» abre gestión y allí se entra con usuario y contraseña.
- El importador manual de ZIP (exportación a INVERGESTION) sigue disponible como respaldo.
- **Avisos nuevos (versión 1.50)**:
  - Tipos: fianza cobrada, devuelta y transferida; ampliación de reserva; cierre de caja; cierre de incidencias; indicadores del día.
  - Se guardan desde ya, pero no salen hasta poner PMS_GESTION_EVENTOS_V2=1 en el .env del servidor. Al activarlo se mandan todos los guardados.
  - El contrato para gestión está en `pms/docs/pasarela_v2.md`.
  - La ampliación de una reserva ya no llega a gestión como salida.
