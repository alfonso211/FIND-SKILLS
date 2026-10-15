# CHANGELOG · INVERPMS

Registro técnico de versiones. El resumen para los usuarios está en `app/manual/novedades.md` (se muestra en el PMS).

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
