# CHANGELOG · INVERPMS

Registro técnico de versiones. El resumen para los usuarios está en `app/manual/novedades.md` (se muestra en el PMS).

## 1.74 · 16/10/2026 · Contrato turístico, «¿Dónde nos conoció?», empadronados y OT
- Migración **0065**: `ordenes_trabajo.exige_foto_antes = false` en las OT sin parte de estado (solo datos).
- OT: `exige_foto_antes` solo si la OT se crea desde un parte de estado (`parte_estado_id`) y es correctiva o de
  mejora; recepción y dirección la abren sin foto. Tipo nuevo `revision` («apto. en revisión»).
- Contrato de alojamiento (`AccommodationContractIn`): `conocio` (claves de `contratos.CONOCIO`), `conocio_otro`,
  `cliente_antiguo`, `cliente_antiguo_desde` (en el JSON `datos`; sin migración). `bloqueos_contrato()` impide imprimir
  o firmar aunque se pida «permitir huecos»: sin motivo (o «otro» sin detalle), sin «¿Dónde nos conoció?» (o «Otro»
  sin detalle), domicilio en la calle de un activo turístico sin cliente antiguo con fecha (no futura). «Solo
  guardar» guarda y devuelve lo que falta. Los cuatro campos pasan a la siguiente reserva del mismo cliente.
- `app/empadronados.py`: `calle()` (sin tipo de vía, número, piso ni puerta), `misma_calle()` (y mismo municipio si
  consta), `datos()` (alojados ahora: titular y ocupantes) y `excel()`. `GET /api/turistico/empadronados.xlsx`
  (reservas.ver, por los activos del usuario; queda en auditoría). Tarjeta en *Informes*.
- Informe diario de dirección: `automatismos.donde_nos_conocio()` (contratos del mes, una vez por reserva, último
  contrato) en el correo. **No** se añade a `kpi.diario`: el contrato «fusion1» no cambia.
- Pruebas: `tests/test_contrato_ot_174.py` (datos ZZ-PRUEBA-174).

## 1.73 · 16/10/2026 · Huella del cuadre con lo enviado en maestro.unidad
- Sin migración. No cambia el contrato «fusion1» ni el valor de la huella.
- `maestros.huella()` arma cada línea con `datos_unidad()` (la misma función que construye maestro.unidad) mediante
  `linea_huella()`: pms_id, codigo, uso y situacion valen siempre lo mismo en el cuadre y en lo enviado.
- Aclaración para gestión: «ocupada / disponible / bloqueada» viaja en `estado`; `situacion` es la situación de la
  vivienda (alquilada, vacia, reservada…) y va vacía si no se ha indicado. La huella usa `situacion`, como dice el punto 8.
- Prueba `tests/test_maestros_huella.py`: gestión rehace la huella con lo recibido en maestro.pedir y coincide con la
  del cuadre, también después de cambiar la situación (datos ZZ-PRUEBA-MAEH, se borran al terminar).

## 1.72 · 15/10/2026 · Campana y revisión general
- Sin migración.
- Avisos: `_enviar_registrado(..., vista=)`; los de un registro concreto llevan `ordenes?id=`, `estado?id=` y
  `gastos?id=` (OT urgente, resultado del técnico, parte de estado, pago retenido). `VISTA_AVISO` completa: ot_plazo,
  seguridad (usuarios), sistema (gestion), informe_direccion, personal. Prueba que cada tipo usado tiene una pantalla
  del menú (`tests/test_campana_172.py`).
- `GET /api/mantenimiento/ordenes`, `/api/partes-estado` y `/api/gastos` aceptan `id` (un solo registro, sin los demás
  filtros). Pantallas con `?id=`: aviso «🔔 … del aviso» y «Ver todo».
- Campana (app.js): `irAviso` dice si la pantalla no está en el menú del usuario; una sola consulta de avisos a la vez
  (evita sonar dos veces); comprobación al volver a la pestaña (`visibilitychange`); error de carga visible.
- `pickAsset`: si se cierra sin elegir, rechaza con mensaje (antes la pantalla quedaba en «Cargando…»); `go()` muestra
  un mensaje aunque el error no lo traiga (Cobros de otro programa sin activos residenciales).
- `/api/auth/me` devuelve `recepcion1`; el menú «Registro de jornada» sale a `personal.autorizar` o Recepción 1.
- Revisión con Playwright de todas las pantallas del menú con superadministración, Recepción, Técnico, Limpieza,
  Administración y Gestor residencial (1366 px y 412 px).

## 1.71 · 15/10/2026 · Activos y unidades sincronizados con gestión (maestros)
- Instrucción: `docs/fusion/INSTRUCCION_PMS_MAESTROS_ACTIVOS.txt` (manda su punto 8). Código: `app/maestros.py`.
- **Migración 0064**: `unidades.maestro_version` (entero, 1 para las existentes), `unidades.maestro_cambiado`,
  `unidades.baja` (fecha; la unidad no se borra) y `unidades.catastro` / `activos.catastro` (JSON de gestión). La
  casilla es el ajuste `maestros_sync` (sin fila = apagada).
- PMS → gestión (cola de la fusión, contrato «fusion1», origen PMS): `maestro.unidad` (`pms_id`, `accion` creada |
  actualizada | baja, `version`, `activo_pms`, `cambiado` y los 13 operativos; uso en minúsculas) en cada alta, cambio
  operativo o baja (la versión sube en `before_flush`, esté o no encendida la casilla); `maestro.activo` (`activo_pms`,
  nombre, modalidad, dirección, municipio, provincia, cp, nº registro turístico); `maestro.cuadre` desde las 03:30
  (Madrid) una vez al día, desde el hilo de la cola: por activo `por_uso` y `huella` sha256 de «pms_id|codigo|uso|
  situacion» por pms_id, sin las bajas.
- Gestión → PMS (`POST /api/gestion/eventos`): `maestro.catastro` (ámbito unidad o activo; guarda `ref_catastral` en su
  campo y lo demás, con `ibi_AAAA`/`trua_AAAA` tal cual, en `catastro`; versión ≤ la guardada se ignora);
  `maestro.pedir` (`pms_ids` «todos» o lista: vuelve a mandar esas unidades con `id_evento_causa`). `maestro.unidad` y
  `maestro.activo` que lleguen de gestión se ignoran (lo operativo es del PMS). Campos que no manda el emisor: se
  ignoran y quedan en auditoría (`campo_ignorado`). Sin eco.
- Casilla «Sincronizar activos y unidades con gestión» (`GET/PUT /api/maestros/config`, solo superadministración),
  apagada: no se encola nada, lo encolado espera y lo recibido queda «sin tratar». Al encender: se aplican los
  catastros sin tratar y se encolan todas las unidades y activos.
- Solo los activos que gestión conoce (`maestros.SINCRONIZADOS` = SFL, SAE, BAB35): los demás no generan
  `maestro.unidad` ni `maestro.activo`, no entran en la carga inicial ni en el cuadre, y su `maestro.pedir` queda
  «sin tratar».
- `POST /api/maestros/unidades/{id}/baja` (solo superadministración; motivo; no con reservas pendientes ni contrato
  vigente) y `/reactivar` (solo superadministración).
  `GET /api/unidades` oculta las bajas salvo `bajas=true`. La referencia catastral no se cambia en el PMS si hay
  catastro de gestión (400 «Se edita en gestión»).
- Pantallas: ficha de unidad y activo con el bloque «🔒 Catastro y propiedad · Se edita en gestión», columna Ref.
  catastral con candado, «Dar de baja» / «Reactivar», filtro de bajas y tarjeta de la casilla en Pasarela con gestión.
- Pruebas: `tests/test_maestros_171.py` (datos ZZ-PRUEBA-MAE, borrados al terminar).

## 1.70 · 15/10/2026 · Órdenes de trabajo simplificadas
- **Migración 0063** (sin tablas nuevas): `partes_estado.crear` sale de Recepción, Técnico Mantenimiento y Dirección
  Sociedad (solo limpieza); `limpieza.confirmar_ot` desaparece de todos los roles y del catálogo; Dirección Técnica
  recibe `mantenimiento.cerrar`; descripciones de roles al día; las OT en `trabajo_realizado` pasan a
  `pendiente_cierre`.
- `confirmar-mantenimiento` pide `llegada`, `salida` y, al personal propio, `firma` (PNG); exige al menos una foto
  `trabajo` y guarda la intervención (`intervenciones_ot`). Personal propio (asignación distinta de subcontrata):
  queda **cerrada** al momento (`cerrar_ot`). Subcontrata: `pendiente_cierre`.
- Enlace del técnico, «Resuelta»: exige foto de la reparación y hora de llegada; personal propio → cerrada,
  subcontrata → `pendiente_cierre`. `datos` devuelve `fotos_trabajo` y `cierra`.
- `cerrar` (mantenimiento.cerrar: recepción y Director Técnico): exige trabajo finalizado, tiempo > 0 y foto; para OT
  antiguas sin tiempo admite `llegada`/`salida`. Sin confirmación de limpieza (se quita `confirmar-limpieza`).
  `rechazar` solo con `mantenimiento.cerrar`.
- `POST /ordenes/{id}/reabrir` (motivo, 7 días desde el cierre): vuelve a `en_curso`, la unidad a mantenimiento y
  anula la limpieza pendiente de después de la reparación.
- Al cerrar o cancelar, un apartamento que quedaba libre pasa a `pendiente_limpieza` y se crea su limpieza extra del
  día (`clave` «ot:<id>:…»); al validarla (o al marcar la unidad limpia) queda disponible. Viviendas, garajes,
  trasteros y locales: disponibles.
- OT: `minutos` (suma llegada → salida de sus intervenciones), `fotos_trabajo`, `reabrible`.
- `POST /api/mantenimiento/peticiones` («Pedir OT», `mantenimiento.editar`): aviso `peticion_ot` en la campana de
  recepción del activo (urgente: también dirección), con la suscripción `partes_estado`.
- Parte diario: actuaciones con `horas` obligatorias (alta y corrección); las líneas de OT llevan sus horas (de las
  intervenciones); no se valida el de mantenimiento con líneas sin tiempo.
- Pantallas: «Trabajo realizado» con llegada, salida, fotos (obligatoria una) y firma táctil; «Cerrar», «Rechazar» y
  «Reabrir»; columna Tiempo/fotos en lugar de Limpieza; parte diario con aviso a mantenimiento y «Pedir OT».
- **Foto del «antes»** (migración 0063: `ordenes_trabajo.exige_foto_antes`, por defecto falso; las abiertas antes
  quedan exentas): se marca al crear OT `correctivo` o `mejora`. `exigir_finalizacion`, `confirmar-mantenimiento` y
  «Resuelta» del enlace exigen al menos una imagen `averia`. El enlace sube fotos con `?tipo=averia` (por defecto
  `trabajo`); `datos` devuelve `fotos_antes` y `exige_foto_antes`. OT: `falta_foto_antes`. Nueva OT: foto
  obligatoria en pantalla salvo si viene de un parte de estado (copia sus fotos como `averia`).
- **Aviso 48 h** (`avisos.recordatorio_ot_sin_cerrar`, en el resumen diario): OT de subcontrata en `pendiente_cierre`
  con `conf_mto_fecha` de hace más de 48 h, a los suscritos a `ot_tecnico` con `mantenimiento.cerrar` en el activo;
  una vez al día (clave `ot_sin_cerrar:<día>`). OT: `sin_cerrar_48h`.
- **Coste de mano de obra** (migración 0063: `personal_servicio.coste_hora`, campo de la ficha, solo para quien
  gestiona al empleado): informe `mantenimiento` con columnas Horas, Mano de obra propia y Coste total por OT y hojas
  nuevas «Horas por técnico» (OT + parte diario) y «Por apartamento». Las columnas de coste solo para el Director
  Técnico o `personal.autorizar` de grupo.
- Pruebas reescritas para el flujo nuevo (+1: personal propio cierra desde su enlace; +1: coste de mano de obra;
  foto del antes y aviso 48 h en `test_tecnico_ot`).

## 1.69 · 15/10/2026 · Móviles plegables (Galaxy Fold cerrado y abierto)
- Hasta 900 px de ancho (Fold cerrado ≈ 344-412 px, abierto ≈ 700-900 px) las tablas de lista se pintan como fichas
  (`table.t-tarjeta`): «nombre: valor» con `data-label`, botones de acción debajo y que pasan de línea; 1 columna
  cerrado y 2 abierto. Antes la columna de botones (fija a la derecha y sin saltos de línea) tapaba los datos: en
  *Órdenes de trabajo* no se veía ninguno.
- `table()` pone `data-label`; el resto de tablas con cabecera se etiquetan solas (`etiquetarTablas`). Siguen como
  tabla las que tienen casillas para rellenar, `colspan` o las clases `planning`, `inv`, `dot`, `check-rev`,
  `tabla-inf` y `no-tarjeta`; si no están en una caja con desplazamiento se meten en `.desliza` (se deslizan de lado
  sin ensanchar la página).
- En modo fichas las listas no se encajan a la altura de la pantalla (se desplaza la página, mejor en táctil); al
  abrir o cerrar el plegable se recalcula.
- Barra superior hasta 1100 px: título en una línea con «…» y la fila de activo/avisos/chat/usuario debajo; hasta
  600 px, «Volver» solo con la flecha, ventanas a todo el ancho y aviso inferior a lo ancho. Sin migración ni cambios
  en el servidor.

## 1.68 · 15/10/2026 · Chat con fotos, PDF y @menciones · reinicio nocturno del servidor
- **Migración 0062**: tabla `chat_adjuntos` (fichero cifrado fuera de la base de datos, como los de las OT) y columna
  `chat_mensajes.menciones`.
- Chat: `POST /api/chat/conversaciones/{id}/adjuntos` (hasta 5 fotos JPG/PNG o PDF de 20 MB; las fotos se reducen y
  pierden la ubicación GPS) y `GET /api/chat/adjuntos/{id}` (solo miembros; los de un mensaje borrado dejan de
  servirse y su fichero se borra del disco).
- Menciones: «@Nombre Apellido» (sin importar tildes ni mayúsculas) de una persona de la conversación deja un aviso en
  su campana (`chat_mencion`) que abre la conversación. Sin correo.
- Servidor: `deploy/actualizar_servidor.sh` (actualizaciones de seguridad y reinicio cada día a las 03:00 de Madrid,
  con copia previa y comprobación tras el arranque); `mantenimiento.sh` avisa si la noche falló. Ver
  `deploy/INSTALACION.md`, apartado 8 sexies. Se activa una sola vez con `--instalar`.
- 2 pruebas nuevas (`tests/test_chat_adjuntos_168.py`).

## 1.67 · 15/10/2026 · Calendario común: encendido después de gestión
- Al encender la casilla del PMS se aplican, en el orden en que llegaron, los avisos `calendario.*` que quedaron «sin
  tratar» (gestión encendió antes). La versión de cada entrada evita duplicados; uno que no se pueda aplicar sigue «sin
  tratar» con el motivo. Sin migración.
- Historial: solo se apunta «Sustituido por la versión de gestión» cuando hay choque (un cambio del PMS que gestión aún
  no ha recibido); un cambio de gestión posterior a uno ya entregado no deja historial.
- Citas de varios días: si gestión no manda `fin`, se conserva el que había; en las de día completo el último día se
  guarda como lo guarda la Agenda (00:00), sin cambiar su forma.
- 3 pruebas nuevas en `tests/test_calendario_comun_166.py`.

## 1.66 · 15/10/2026 · Calendario común PMS ↔ gestión
- **Migración 0061**: tablas `calendario_comun` (una fila por uid, con versión, historial y espejo de lo que manda el
  PMS), `calendario_enlaces` (enlace de Outlook por usuario; solo la sha256 de la clave) y `ajustes` (interruptores de
  la configuración).
- **Contrato «fusion1»**: tipos nuevos `calendario.creada`, `calendario.actualizada` y `calendario.cancelada`, por la
  misma ruta, firma y cola que la fusión (`POST /api/gestion/eventos` y `POST /api/pms/eventos`). Ver
  `docs/pasarela_v2.md`, apartado «Calendario común».
- **Gestión → PMS**: idempotente por id_evento y por versión; gestión manda (el cambio local queda en el historial y su
  aviso pendiente se descarta); `cancelada` marca CANCELADA y no borra; sin eco.
- **PMS → gestión**: citas y tareas compartidas o públicas de la Agenda (`PMS-AG-<id>`; las privadas no salen) y
  limpiezas programadas (`PMS-LIM-<id>`); cambios sobre citas de gestión editables en los dos (`AMBOS`). Nunca
  vencimientos, fiscal ni entradas de solo lectura. Cola con los reintentos de la fusión y en orden por uid.
- **Casilla** «Sincronizar el calendario con gestión» (solo superadministración, apagada al desplegar). Apagada: lo
  que llega se guarda «sin tratar» y no sale nada. Al encenderla se preparan las citas compartidas y las limpiezas
  de los últimos 60 días.
- **Visibilidad**: vencimientos, fiscal y lo que gestión marca solo para administración y dirección los ve solo la
  superadministración y los roles Dirección Grupo, Dirección Sociedad y Administración / Finanzas (no basta
  `finanzas.ver`: el Gestor Alquiler Residencial no los ve). Cada uno, solo los de sus sociedades (por `sociedad`; si la
  entrada no la indica, por el activo); la superadministración, todo. Lo mismo para «Mostrar importes» en Outlook.
  Recepción y técnicos nunca, ni en pantalla ni en Outlook.
- **Outlook**: `GET /cal/<clave>.ics` (RFC 5545: CRLF, plegado a 75 octetos, UID `uid@pms.inversiete.es`, SEQUENCE =
  versión, STATUS:CANCELLED 60 días, horas en UTC, VALUE=DATE con DTEND exclusivo, RRULE, VALARM). Clave de 32 bytes,
  cambiar el enlace deja el anterior en 404, auditoría de cada acceso con la IP y corte con 429 a partir de 61
  peticiones en la hora (con aviso por correo).
- **Pruebas**: `tests/test_calendario_comun_166.py` (8 pruebas contra un gestión simulado; datos ZZ-PRUEBA-CAL en
  2031 que se borran al terminar). `icalendar` solo en `requirements-dev.txt`.

## 1.65 · 15/10/2026 · Avisos con sonido y chat del equipo
- Migración 0060: `notificaciones`, `chat_conversaciones`, `chat_miembros`, `chat_mensajes`.
