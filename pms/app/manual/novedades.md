# Novedades

## 2026-10-14 · Versión 1.56 · Pantallas más rápidas con muchas reservas
- **Todos**: con decenas de miles de reservas y miles de órdenes de trabajo, las pantallas de uso diario cargan mucho más rápido: órdenes de trabajo unas 10 veces más rápido, reservas 7 veces, llegadas y salidas de hoy 9 veces, planning 4 veces y plano del edificio 3 veces.
- Nada cambia en el manejo: los mismos datos, en menos tiempo.

## 2026-10-14 · Versión 1.55 · Acceso a apartamentos con cliente en las OT
- **Llave de recepción**: se anota quién autoriza el acceso y cómo (en persona, teléfono, WhatsApp o correo), quién lo registra y cuándo. El técnico ve que hay permiso, sin los datos del cliente.
- **El permiso vale para esa estancia**: si entra otro cliente con la OT abierta, se avisa para volver a pedirlo (botón **Acceso**).
- **Check-in**: si el apartamento tiene OT abiertas, se pregunta al cliente cómo se entra en ese momento.
- **Llegadas próximas**: al abrir una OT en un apartamento libre al que llega un cliente en 7 días, se avisa y se propone hacerla el día antes.

## 2026-10-14 · Versión 1.54 · Control del preventivo y de las inspecciones OCA
- **Mantenimiento · Plan preventivo**: nuevo cuadro de control con totales y semáforo por plan (vencido, plazo de subsanación vencido, deficiencias, próximo, al día). Mantenimiento e inspecciones OCA juntos o por separado.
- **Registrar revisión**: lista de comprobación por instalación, resultado (también los de la OCA), nº de acta o informe, próxima revisión del documento (se contrasta con la periodicidad del plan) y documentos de la empresa.
- **Cada deficiencia genera su orden de trabajo**, con prioridad según la gravedad y fecha hasta el plazo de subsanación. La OT preventiva del plan queda cerrada con la revisión.
- **Historial** de cada plan con sus documentos (se pueden añadir después) y el estado de las OT de las deficiencias. **Excel** con el registro completo.
- La plantilla normativa añade las **inspecciones OCA** (BT, ascensores, PCI, térmica, centro de transformación y gas).
- **Aviso cada lunes** al director técnico con lo que está en rojo o naranja y las OCA de los próximos 60 días.

## 2026-10-14 · Versión 1.53 · Dotación al importar reservas desde Excel
- **Recepción · importar reservas**: la dotación estándar es obligatoria, igual que al reservar a mano. Las reservas de un tipo de apartamento sin ella no se importan; la vista previa lo avisa con el botón **Fijar dotación habitual**.
- **Dotación extraordinaria en el Excel**: columna nueva **Dotación extraordinaria** («Cuna de viaje x1; Toallas de baño x2»). Se ve en la vista previa y queda en la reserva. Si no se indica, la estándar.
- **Asignación automática**: si el Excel no dice el apartamento, se eligen antes los que ya tienen fijada la dotación estándar.

## 2026-10-14 · Versión 1.52 · Protección del acceso
- **Todos · intentos de acceso**: 5 contraseñas mal seguidas bloquean ese usuario 15 minutos (como hasta ahora). Además, 20 intentos fallidos desde la misma conexión la bloquean 15 minutos, aunque se prueben usuarios distintos.
- **Enlaces públicos** (técnico, fichaje, revisión de salida, ofertas, aprobaciones): una conexión que prueba muchos enlaces no válidos se bloquea 15 minutos. El resto de enlaces y del programa siguen funcionando.
- **Dirección · aviso y desbloqueo**: cada bloqueo llega por correo al director técnico. En **Usuarios** aparecen los bloqueos activos con el botón **Desbloquear** (por ejemplo, si alguien del equipo se equivocó de contraseña).
- **Protección del navegador**: el programa solo ejecuta su propio código. Un texto malicioso guardado en una ficha no puede ejecutar nada ni enviar datos fuera.

## 2026-10-14 · Versión 1.51 · Hora de Madrid, partes de trabajo editables y dotación obligatoria
- **Todos · hora**: el programa trabaja siempre en hora de Madrid. Corregido el día que proponía el navegador entre las 00:00 y las 02:00 (salía el anterior) y la fecha de salida que a veces salía igual a la de entrada. Aviso si el reloj del ordenador va desfasado.
- **Partes de trabajo · Editar**: cada línea se puede corregir (hora, trabajo, lugar, quién y horas) con el motivo, mientras el parte esté abierto. Al anotar una actuación se indica la hora a la que se hizo.
- **Órdenes de trabajo · acceso con cliente alojado**: al abrirla se marca si el cliente autoriza la llave de recepción o hay que contactarle (su teléfono sale solo). Lo ve el técnico.
- **Recepción · dotación al reservar**: es obligatorio tener fijada la dotación estándar del tipo de apartamento (se fija en la misma reserva, una sola vez). La dotación extraordinaria se añade al reservar; si no se indica, se entrega la estándar.

## 2026-10-15 · Versión 1.50 · Caja por turno, fianza al llegar, plazos de OT, informe diario y gestión
- **Recepción**:
  - **Caja y cierres de turno**: arqueo de lo cobrado por cada recepcionista (efectivo, tarjeta, Bizum…). Si no cuadra se indica el motivo y la Dirección recibe un aviso.
  - **Cobrar fianza** al llegar: cuenta en la caja y es la que se devuelve, aunque no se guarde el contrato.
  - **Saldo pendiente**: al dar la salida, aviso si el cliente debe algo.
  - **Mensaje la víspera** de la llegada al cliente: documentos para el registro de viajeros, hora de entrada y fianza.
- **Mantenimiento**:
  - **Plazo de respuesta**: urgente 4 h, alta 24 h. Fuera de plazo, aviso al director técnico.
  - **Preventivo automático**: las OT de las revisiones que vencen en 7 días se generan solas.
  - **Enlace del técnico revocable**: deja de valer al reasignar la orden o con **Revocar enlace**.
  - **CAE/PRL de subcontratas**: con la documentación vencida no se les asignan órdenes.
- **Dirección**:
  - **Informe diario** a primera hora: ocupación, ADR, RevPAR, cobros pendientes, fianzas por transferir, OT urgentes y descuadres.
  - **Seguridad**: cambiar la contraseña o desactivar un usuario cierra sus sesiones abiertas.
  - **Vacaciones**: los colaboradores reciben el calendario sin los saldos de la plantilla.
- **Gestión**:
  - La ampliación de una reserva ya no llega como salida.
  - Avisos nuevos de fianzas, caja, cierre de incidencias e indicadores. Se activan cuando gestión los reciba.

## 2026-10-15 · Versión 1.49 · Botón «Gestión» solo para la Dirección y aviso de pedidos de reposición
- **Todos · botón «Gestión»**: solo lo ven el administrador, Alfonso y Bárbara.
- **Dirección · pedidos de reposición sin autorizar**: si Recepción 1 no autoriza un pedido de reposición en 3 días, llega un aviso cada día laborable.
- **Recepción · correcciones de la revisión general**:
  - No se puede hacer el check-in si en el apartamento sigue alojado otro cliente (estancia vencida).
  - «Editar» ya no cambia el estado de una reserva: para anular, dar la salida o el check-in están sus botones.
  - El importe de una reserva no puede bajar de lo ya facturado.
  - La lista negra reconoce el documento escrito con puntos, guiones o espacios.
  - Un pago a cuenta ya no da por cobrados los extras pendientes.
  - Al dar la salida no se puede devolver más que la fianza menos las roturas.
- **Personal**: si alguien olvidó fichar la salida otro día, el fichaje de hoy empieza una entrada nueva y el día olvidado queda para corregirlo.
- **Mantenimiento**: una OT urgente abierta desde «Hecha con incidencia» avisa al momento, como las demás.

## 2026-10-15 · Versión 1.48 · Pasarela con INVERGESTION (gestión)
- **Recepción · salida sin OT automática**: el check-out ya no abre la OT de revisión de salida. En el parte de limpieza, **Hecha con incidencia** abre la OT cuando hay algo que reparar (y llega a gestión). Las OT por roturas y el pedido de reposición al dar la salida siguen igual.
- **Recepción · apartamentos cerrados desde gestión**: una avería grave registrada en gestión bloquea el apartamento en el PMS y lo reabre al cerrarla. Las reservas no se cancelan: llega un correo con las que hay que reubicar.
- **Todos · botón «Gestión»**: arriba y en la ficha del apartamento, abre INVERGESTION en otra pestaña.
- **Dirección · Pasarela con gestión**: avisos a gestión con reintentos, comisión por canal y liquidación mensual.

## 2026-10-15 · Versión 1.47 · Pedido de reposición automático y recordatorio de cobro
- **Recepción · pedido de reposición**: lo que falta o se rompe de menaje y ropa de cama y baño se suma solo al pedido de reposición del activo. Recepción 1 lo autoriza y elige el proveedor.
- **Recepción · recordatorio de cobro**:
  - Las facturas de roturas que superan la fianza se recuerdan solas al cliente a los 3, 10 y 17 días.
  - También se recuerdan a mano con **Recordar cobro**, por correo con la factura y por WhatsApp.

## 2026-10-15 · Versión 1.46 · Revisión en el móvil, OT por roturas, factura del exceso e informe de roturas
- **Limpieza · revisión de salida en el móvil**: un enlace por apartamento, sin usuario. Limpieza marca lo que falta o está roto y Recepción lo ve cargado al dar la salida. Recepción 1 recibe un aviso por correo.
- **Recepción · OT por roturas**: lo roto que hay que reponer o reparar abre una orden de trabajo a mantenimiento al dar la salida.
- **Recepción y Dirección · exceso sobre la fianza**: se factura al cliente sin IVA, por ser una indemnización, y queda pendiente de cobro.
- **Dirección · informe de roturas**: por artículo y por apartamento, con Excel.

## 2026-10-15 · Versión 1.45 · Hoja de revisión de salida, precios de reposición y dotación por apartamento
- **Recepción y limpieza · hoja de revisión de salida**: PDF por apartamento con su dotación y casillas OK / Falta / Roto. En el parte de limpieza salen todas las del día.
- **Recepción · roturas en la fianza**: al dar la salida se eligen los artículos rotos o que faltan y se descuentan solos de la fianza a su precio de reposición. El detalle llega a la Dirección y a la gestoría.
- **Recepción · precios de reposición**: orientativos y editables por activo.
- **Recepción · dotación propia de un apartamento** (terraza, VIP…), que manda sobre la de su tipo.

## 2026-10-15 · Versión 1.44 · Fianzas, expediente del cliente, lista negra, dotación y ampliación de reserva
- **Recepción · salida con fianza**: al hacer el check-out sale la **devolución de fianza** con el cliente, el importe y la forma (transferencia, efectivo o tarjeta).
  - Por transferencia, IBAN y fecha se envían por **correo y WhatsApp** a Bárbara y a Alfonso.
  - Queda en el registro de envíos y va a la gestoría en la exportación a **INVERGESTION** (FIANZAS_*.csv).
- **Recepción · expediente del cliente**: en la ficha, **Expediente completo** con estancias, contratos, facturas, fianzas, alquileres y documentos.
- **Recepción · lista negra**: Recepción 1, Recepción 2 y Dirección anotan el motivo. Si el cliente vuelve a reservar, sale el aviso.
- **Recepción · dotación**:
  - Lista estándar 3 llaves para fijar la **dotación habitual** de cada tipo de apartamento, sin escribir.
  - **Dotación especial** por reserva y **Otra dotación** para artículos nuevos.
  - La casilla **Dotación habitual** del contrato imprime o envía el **Anexo I**.
- **Todos · ampliación de reserva**: los apartamentos turísticos no renuevan. En pantallas, avisos, informes y manuales ahora pone **ampliación de reserva**. El botón que solo cambia la fecha se llama **Corregir salida**.

## 2026-10-14 · Versión 1.43 · Calendario de vacaciones solo en días laborables
- **Todos**: el calendario de vacaciones agrupado solo se envía en **días laborables**, sin fines de semana ni festivos de Madrid, de 8:00 a 20:00. Lo que cambie el fin de semana llega el lunes a primera hora.

## 2026-10-14 · Versión 1.42 · Calendario de vacaciones agrupado
- **Todos**: el calendario de vacaciones ya no llega con cada cambio. Los cambios se agrupan y se envían **juntos en un solo correo cada 3 horas**, solo entre las 8:00 y las 20:00.
- **Dirección y Director Técnico**: en *Vacaciones y ausencias* se ven los cambios pendientes de enviar, con el botón **Enviar calendario ahora**.

## 2026-10-14 · Versión 1.41 · Personal: nuevas reglas y empezar de cero
- **Recepción 1 de cada activo**: ahora se asigna en *Activos → Editar → Recepción 1*. Antes se deducía del nombre del usuario y podía tomar a Recepción 1 por Recepción 2.
- **Fichas del personal**:
  - El personal propio de las sociedades lo da de alta solo el **Director Técnico**.
  - **Recepción 1 y Recepción 2** solo dan de alta personal de **subcontratas**, indicando la empresa.
  - Cada usuario del PMS solo puede estar en **una** ficha.
- **Vacaciones y ausencias**: cada persona las solicita **con su usuario y sobre su propia ficha**. Ya no se registran ausencias de otras personas.
- **Saldo de vacaciones**: en cada ficha se ven los días **disfrutados**, los **solicitados** pendientes de disfrutar y los **pendientes de solicitar**. Por defecto son 30 días naturales, o los que indique la ficha.
- **Vacaciones en la ficha** (Director Técnico): registra los periodos ya disfrutados y los ya acordados para cuadrar el saldo.
- **Calendario de vacaciones**:
  - Se genera en cada cambio (solicitud, autorización, desestimación, anulación o registro) y se envía por correo a **todos los usuarios, colaboradores incluidos**.
  - Tiene dos hojas con el año completo (disfrutadas, solicitadas, festivos de Madrid, hoy y el tramo modificado) y una de saldos, solapes y días pendientes.
  - También se descarga en *Vacaciones y ausencias → Calendario de vacaciones (PDF)*.
- **Recordatorio semanal**: cada lunes, a quien le quedan días sin solicitar, para que los pida antes del 31 de diciembre.
- **Comprobar personal** (Director Técnico):
  - Lista los errores: activos sin Recepción 1, nombres que no cuadran, usuarios en varias fichas y solicitudes que van a quien no debe aprobarlas, que se corrigen con un clic.
  - Genera las fichas desde los usuarios.
  - **Borra todo el personal** para empezar de nuevo.

## 2026-10-13 · Versión 1.40 · CAPEX: inversiones y reformas (fase 1)
- **Dirección Técnica**: nuevo menú **Inversiones (CAPEX)**. Cada proyecto lleva sus mediciones y su presupuesto base (PEM, gastos generales, beneficio industrial, PBL e IVA) y se compara con el presupuesto objetivo.
- **Presupuesto en minutos**: importar un **BC3** (Presto, Arquímedes…), añadir partidas desde una **base de precios** pública o cargar una **plantilla «CAPEX tipo»** (reforma de baño, panelado de puertas…) con sus planos y pliegos.
- **Licitación ciega**: cada contratista recibe por correo un enlace personal y un Excel protegido, **sin los precios base**. Puede ofertar en la web o devolver el Excel. Se registra cuándo abre el enlace y descarga la documentación.
- **Comparativo** con mapa de calor (bajas anormales y excesos) y PDF. **Adjudicación** de la obra completa o por capítulos a distintas contratas.
- **Más de 30.000 € sin IVA**: la adjudicación queda bloqueada hasta que la **Dirección General** la aprueba o la rechaza con los botones del correo, sin entrar en el PMS. Queda la fecha y la hora de la decisión.

## 2026-10-13 · Versión 1.39 · Gestión del personal
- **Acceso**: el grupo **Personal** sube al segundo lugar del menú: Vacaciones y ausencias, Fichas del personal, Registro de jornada y Mi jornada.
- **Dirección**: con **Todos los activos**, las ausencias de todos los activos en una sola pantalla, con resumen y Excel.
- **Resolver solicitudes desde el ordenador**: arriba, en *Vacaciones y ausencias*, cada solicitud pendiente (de cualquier mes) tiene **Autorizar**, **Desestimar** (con motivo) y **Anular** (si tiene un error o no procede, con el motivo). Se envía un correo al trabajador y a Recepción; si el trabajador no tiene correo, sale el WhatsApp ya escrito.
- **Saldo de vacaciones**: cada ficha muestra los días que le quedan. Si una solicitud lo supera, aviso en rojo.
- **Ficha del empleado** (Recepción 1 y dirección): DNI, puesto, contrato, jornada, alta y baja, y **documentos** con vencimiento (contrato, reconocimiento médico, formación…).
- **Registro de jornada**: el personal propio ficha entrada y salida desde **Mi jornada** o con su **enlace** en el móvil. Correcciones con motivo, informe PDF para firmar y Excel para la asesoría.
- **Panel de control**: nueva tarjeta **Personal hoy**.

## 2026-10-13 · Versión 1.38 · Órdenes de trabajo desde el portal del colaborador
- **Colaboradores (subcontratas)**: en su portal, botón **Gestionar** en cada orden abierta. Abre la misma pantalla que el enlace de WhatsApp (llegada, trabajos, material, estado al finalizar y firma), sin depender del mensaje. Nueva columna **Último resultado**.

## 2026-10-13 · Versión 1.37 · Órdenes de trabajo en el móvil del técnico
- **Recepción y dirección**: botón **Asignar** (personal propio o subcontrata). **Enviar** manda por WhatsApp o correo el mensaje «Tiene una nueva orden de trabajo OT-xxxxx en … Acceda aquí para gestionarla» con un enlace seguro.
- **Técnicos (propios y subcontratas)**: desde el enlace, sin usuario, indican llegada y salida, trabajos, material, fotos y el **estado al finalizar** (resuelta, pendiente de material, otra visita con fecha, derivar a subcontrata u otro), y **firman** en la pantalla.
- **Avisos**: el resultado suena en el PMS y llega por correo. Las órdenes en pausa se recuerdan cada día hasta que alguien actúa. «Derivar a subcontrata» sale en rojo.
- **Cierre**: **Conformidad y cierre** registra la conformidad de la propiedad. El parte PDF lleva la intervención, la firma del técnico y la conformidad.

## 2026-10-13 · Versión 1.36 · Partes de estado
- **Mantenimiento y limpieza**: ya no abren órdenes de trabajo. Al revisar una vivienda o zona común registran un **parte de estado** desde el móvil, en 4 pasos y con foto obligatoria: ubicación (o código QR), estancia, elemento, y deficiencia con su gravedad.
- **Recepción**: el parte le llega por correo y al Panel de control hasta resolverlo. Con **Generar OT** la orden sale rellena con sus fotos; también puede **descartarlo**. Al cerrar la OT, el parte queda resuelto.
- **Crítico**: la vivienda queda fuera de servicio hasta que se cierra su orden de trabajo.
- **Dirección**: nuevo **Panel técnico** con el Pareto de fallos, el tiempo medio de reparación y las intervenciones por unidad y mes. Hoja de **códigos QR** para las puertas.

## 2026-10-13 · Versión 1.35 · Lector de documentos (MRZ)
- **Recepción**: en el escaneo del documento hay un cuadro nuevo, **Lector de documentos**, para usar un lector MRZ conectado al ordenador. Al pasar el DNI, la TIE o el pasaporte, la ficha se rellena sola y validada en un segundo, sin fotos ni reflejos. Con la casilla «En este equipo hay lector», el cuadro queda listo nada más abrir la ficha.

## 2026-10-09 · Versión 1.34 · Botón Volver y borrar usuarios
- **Todos**: nuevo botón **← Volver** arriba, junto al título de la pantalla. Vuelve a la pantalla anterior o cierra la ventana abierta.
- **Director Técnico y administrador**: botón **Borrar** en *Administración → Usuarios* (solo estas dos cuentas). Si la persona ya había trabajado en el PMS, su nombre se conserva solo en el historial.

## 2026-10-09 · Versión 1.33 · Menos reinicios del PMS
- **Todos**: si el PMS se queda parado unos minutos y vuelve a responder solo, ya no se reinicia encima (era un corte más). Queda un diagnóstico detallado para localizar la causa, y el mantenimiento diario lo avisa como «PMS parado» en vez de «cuelgue».

## 2026-10-09 · Versión 1.32 · Justificante de pago obligatorio
- **Cuenta de gastos**: para marcar una factura como pagada hay que adjuntar antes el **justificante de pago** (botón **Pagado**). Queda guardado y enlazado a la factura (botón **Justificante**).

## 2026-10-08 · Versión 1.31 · Cobros de alquiler de otro programa
- **Alquiler residencial**: nuevo **Cobros de otro programa**. Se suben las facturas en PDF (o un ZIP), se indica de qué mes a qué mes se repite la renta y el PMS abre las fichas de los inquilinos y registra cada mensualidad como ingreso cobrado (producción del activo). Documento por inquilino y Excel de ingresos.

## 2026-10-08 · Versión 1.30 · Documentación legal de los activos
- **Dirección y recepción**: nuevo **Administración → Documentación legal**, con el checklist de lo obligatorio en cada activo (apartamentos turísticos o alquiler residencial), escaneo a PDF, vencimientos, **No aplica**, documentos propios, impresión del checklist y envío por correo.
- **Cada lunes**: recordatorio por correo a Recepción 1 (su activo) y a la dirección (todos los activos) de lo que falta o ha caducado, hasta completarlo.

## 2026-10-08 · Versión 1.29 · Ausencias: aprueba cualquiera de la dirección
- **Dirección**: las ausencias que aprueba dirección se avisan por correo al **Director General y al Director Técnico**, y **basta con que apruebe uno**. La presidencia no recibe estos avisos ni aprueba.
- **Todos**: en el **Panel de control** aparece «Ausencias que esperan su decisión» con el botón **Revisar**, aunque no llegue el correo.
- **Recepción 2**: su solicitud se avisa también a dirección desde el primer momento; la pueden aprobar en cuanto Recepción 1 da el visto bueno.

## 2026-10-08 · Versión 1.28 · Población y provincia por el código postal
- **Todos**: al escribir el **código postal** en una ficha, la **población** y la **provincia** se rellenan solas (datos del INE). Si el código es de varias poblaciones, se ofrecen para elegir; lo escrito a mano se respeta.

## 2026-10-08 · Versión 1.27 · Portal del colaborador
- **Subcontratas**: nuevo acceso **Colaborador**. Cada colaborador entra solo en su portal: sus OT, sus trabajos en los partes validados, los envíos a su personal y su personal. Sube facturas, albaranes y documentación de personal y legal / CAE.
- **Recepción**: en **Documentos recibidos**, filtro **De colaboradores: por revisar** con **Aceptar** y **Rechazar**. La documentación de personal solo la ven Recepción 1 y dirección.
- **Dirección**: el colaborador se da de alta en *Administración → Usuarios* (campo **Colaborador externo de** y rol **Colaborador**).

## 2026-10-08 · Versión 1.26 · Vacaciones y ausencias del personal
- **Todos**: nuevo menú **Personal → Vacaciones y ausencias** para pedir vacaciones, días libres, bajas, permisos y faltas, con un **cuadrante del mes** de quién falta.
- **Mantenimiento**: su solicitud se avisa a todos y solo la autoriza el **director técnico**.
- **Recepción 1**: registra y aprueba las ausencias de limpieza, conserjería y personal de subcontratas por administración (nuevas áreas en **Personal → Fichas del personal**), y da el **visto bueno** a las de Recepción 2, que después aprueba **dirección**.

## 2026-10-08 · Versión 1.25 · Parte de trabajo diario
- **Mantenimiento y limpieza**: nuevo **Mantenimiento → Parte de trabajo diario**. Las OT terminadas y las limpiezas hechas entran solas; lo que se hace sin parte (zonas comunes, trabajos sin OT) se añade con **Anotar actuación**.
- **Recepción 1 y 2**: **validan** cada parte; solo entonces se descarga en **PDF** y **Excel** y queda archivado en Documentos. **Informe quincenal** con los trabajos totales, descargable y archivable.

## 2026-10-08 · Versión 1.24 · Pedidos de material
- **Todos (recepción, mantenimiento, limpieza)**: nuevo apartado **Mantenimiento → Pedidos de material**. El buscador sugiere los productos del catálogo según se escribe; si un producto no está, se crea en el momento y, si no se indica referencia, el PMS pone una automática (PMS-000001…). Se ve el **coste estimado** con los últimos precios.
- **Recepción 1**: autoriza los pedidos de recepción 2, mantenimiento y limpieza; los suyos y los de dirección no necesitan autorización. Se envían al proveedor en **PDF** por correo o WhatsApp.
- **Dirección**: **catálogo de productos** compartido con **INVERGESTION** en los dos sentidos (importar su fichero y enviarle las altas y los pedidos con precio).

## 2026-10-08 · Versión 1.23 · Localizador automático
- **Recepción**: cada reserva tiene su **localizador** aunque no se escriba: **SF0000000001**, SF0000000002… en Suite Florida y **SA0000000001**… en Suite Aeropuerto. Las reservas que no lo tenían ya lo tienen. El de un canal (Booking…) se respeta si se escribe.

## 2026-10-08 · Versión 1.22 · Anular con un botón y fichas que solo coinciden en el nombre
- **Recepción y dirección**: **Anular** reservas, contratos y alquileres de garaje desde su ficha, con el motivo. Si hay facturas, primero la rectificativa; si hay cobros, se da de baja.
- **Recepción**: en las fichas repetidas (mismo nombre), **No es la misma persona** quita el aviso sin unirlas. También desde la propia ficha del cliente.

## 2026-10-08 · Versión 1.21 · Tarifas estándar en la reserva
- **Recepción**: al reservar o ampliar la reserva, el **precio a pagar** sale solo según el tipo de apartamento y las noches (1-6, 7-13 con -10 %, 14-29 con -19 % y 30 noches a precio cerrado), **en naranja**. Se puede cambiar, pero siempre hay que marcar **«Acepto el precio»** para continuar.

## 2026-10-08 · Versión 1.20 · Sin reinicios falsos
- **Todos**: corregido un fallo del vigilante que reiniciaba el PMS unos segundos después de volver a usarlo tras un rato sin uso (salía como «cuelgue» en el mantenimiento). Podía notarse como un corte breve al entrar.

## 2026-10-08 · Versión 1.19 · Otras webs del servidor y ficheros cambiados a mano
- **Dirección**: las webs que comparten servidor con el PMS (como INVERGESTION) se configuran en su propio fichero de `deploy/sitios/`, que las actualizaciones no tocan. Ya no hay que modificar el `Caddyfile`.
- **Dirección**: si hay ficheros del programa cambiados a mano en el servidor, el mantenimiento diario restaura solos los cambios de permisos; si el contenido cambió, guarda una copia y avisa de qué ficheros son, sin tocarlos.

## 2026-10-07 · Versión 1.18 · SYADE: enlace también por nombre del cliente
- **Dirección**: si el cliente no tiene DNI/NIF en el PMS, la facturación de SYADE se enlaza por su **nombre y apellidos** (sin importar tildes, mayúsculas ni el orden; en empresas, «S.L.» o «SL» da igual). Si hay dos fichas con el mismo nombre, no se enlaza con ninguna. En la ficha se indica cómo se enlazó cada línea.

## 2026-10-07 · Versión 1.17 · Importes de SYADE en la ficha del cliente
- **Dirección**: la facturación importada de SYADE se enlaza por **DNI/NIF** con los clientes del PMS. En la **ficha del cliente** se ven sus facturas, abonos, producción y fianzas del programa anterior. Solo es control de producción: no son facturas del PMS.

## 2026-10-07 · Versión 1.16 · Guía de emergencia
- **Dirección**: nueva **guía de emergencia** para recuperar el sistema si se cae, se pierde el servidor o hay un virus (`deploy/RECUPERACION.md`, también en PDF). Incluye el **kit de emergencia** que hay que guardar fuera del servidor y un simulacro trimestral.

## 2026-10-07 · Versión 1.15 · Órdenes de trabajo a personal propio o subcontrata
- **Mantenimiento**: en la OT, «Asignado a» es **Personal propio** o **Subcontrata** (de Proveedores). La orden se envía a quien la hace: al personal propio por WhatsApp; a la subcontrata por correo (con el PDF) y/o WhatsApp (con enlace al PDF), según se elija. Siempre con **copia al personal de mantenimiento propio**.

## 2026-10-07 · Versión 1.14 · Panel: cada casilla abre su listado
- **Todos**: en la situación de cada activo del panel, **cada casilla lleva a su listado** (llegadas y salidas, contratos, facturas, recibos, órdenes de trabajo, unidades…). El plano se abre con el botón **«🗺️ Ver plano del edificio»** o pulsando en una zona en blanco de la tarjeta.

## 2026-10-07 · Versión 1.13 · Factura de servicios aparte y parte de limpieza ajustable
- **Recepción**: los servicios (extras, limpieza contratada…) se facturan siempre en una **factura aparte** de la estancia. Al emitirlas se pueden **imprimir o enviar las dos** al cliente por correo o WhatsApp.
- **Recepción**: antes de imprimir o enviar el parte de limpieza se puede **ordenar**, marcar **urgente**, añadir notas o **pasar una limpieza a otro día**.
- **Recepción y limpieza**: **orden de limpieza urgente** durante el día, que se imprime o se envía al momento.

## 2026-10-07 · Versión 1.12 · Limpieza de salida solo tras el check-out
- **Recepción y limpieza**: la limpieza por salida entra en el parte **cuando recepción hace el check-out**. Ya no se prevé por la fecha de salida, porque el cliente puede ampliar la reserva.

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
- **Dirección**: el informe incluye producción por tipo de estancia (menos de 1 semana, 1 semana, 2 semanas, 1 mes, ampliaciones de reserva), servicios, gastos por proveedor con CAPEX/OPEX, **resultado con semáforo** (rojo, naranja, verde) y el **resumen mensual** del año anterior y del año en curso.
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
- **Recepción**: **facturar sin cobrar** en reservas y ampliaciones de reserva; aviso diario de **facturas pendientes de cobro** y botones **Cobrada / Deshacer cobro**.
- **Todos**: las **facturas emitidas** llevan fecha del **último día del mes** de emisión.
- **Dirección y recepción**: las **facturas recibidas** guardan su **vencimiento**; las vencidas sin pagar se marcan en rojo.
- **Dirección**: **expediente del contrato de vivienda** (Babilonia 35), **importación de SYADE** y **exportación a INVERGESTION**.
