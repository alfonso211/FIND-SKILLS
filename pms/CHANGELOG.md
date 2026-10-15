# CHANGELOG · INVERPMS

Registro técnico de versiones. El resumen para los usuarios está en `app/manual/novedades.md` (se muestra en el PMS).

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
- Pruebas reescritas para el flujo nuevo (+1: personal propio cierra desde su enlace).

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
