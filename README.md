# PMS Grupo INVERSIETE

Sistema de gestión de activos (Property Management System) común para todo el grupo
**INVERSIETE SA** y sus sociedades (COMERCIAL DEL CAMPO, EDIFICIOS CAMERANOS, ETHOSA).
Hay una sola plataforma, pero cada usuario solo ve y gestiona lo que su rol y su ámbito le permiten.

## Activos cargados de inicio

| Código | Activo | Modalidad | Gestora | Propietaria | Unidades |
|---|---|---|---|---|---|
| BAB35 | C/ Babilonia 35, Madrid | Alquiler residencial (LAU) | COMERCIAL DEL CAMPO S.A. | COMERCIAL DEL CAMPO S.A. | 20 viviendas (trasteros como anejos) + 33 plazas de garaje (ST-1, ST-2, ST-3) |
| SFL | Suite Florida (C/ Campezo 2, reg. AM 265) | Apartamentos turísticos | INVERSIETE SA | COMERCIAL DEL CAMPO S.A. | 325 en 4 portales (P1: 90, P2: 75, P3: 75, P4: 85). Código `P{portal}-{planta}{letra}`, p.ej. P1-1A |
| SAE | Suite Aeropuerto (C/ Campezo 8, reg. AM 259) | Apartamentos turísticos | INVERSIETE SA | COMERCIAL DEL CAMPO S.A. | 300 en 2 bloques (A: 147, B: 153): 268 de 1 dormitorio, 27 de 2 dormitorios y 5 estudios |

Las unidades se cargan desde `pms/app/data/unidades_iniciales.json`, que se generó a partir de estos documentos:
- **Babilonia 35:** listado de cuotas de comunidad de octubre de 2026. Se cargan solo las viviendas y los garajes,
  con superficie, coeficiente y cuota ordinaria. Los trasteros figuran como anejos de cada vivienda. Las cuotas
  cuadran con el listado (1.950,20 € en viviendas y 629,64 € en garajes).
- **Suite Florida:** listado del 2 de octubre de 2026. La tipología está pendiente de recibir.
- **Suite Aeropuerto:** listado del 2 de octubre de 2026. Las unidades sin anotación son apartamentos de 1 dormitorio,
  ESTUDIO son estudios y DOBLE son apartamentos de 2 dormitorios.

Cada activo distingue:
- **Sociedad gestora**: la que lo explota. Determina los accesos por sociedad y a qué sociedad pertenecen
  inquilinos y huéspedes.
- **Sociedad propietaria**: la titular del inmueble. Si no se indica, se toma la gestora.

Para añadir activos nuevos: *Activos → Nuevo activo* (se eligen la gestora, la propietaria y la modalidad).

## Módulos

- **Panel de control**: ocupación del día, llegadas y salidas, contratos vigentes, renta mensual,
  deuda vencida, producción del mes y OT abiertas o urgentes por activo.
- **Apartamentos turísticos**: reservas con control de solapes y de capacidad, búsqueda de disponibilidad,
  check-in (exige los datos del parte de viajeros, RD 933/2021), check-out y paso de la unidad a
  *pendiente de limpieza*. Incluye planning por unidad y día, y ficha de huéspedes.
- **Contrato de alojamiento (MOD-ALOJ-001)**: botón *Contrato* en cada reserva de Suite Florida y Suite Aeropuerto.
  - Rellena el Word original (`pms/app/plantillas/`) con los datos de la reserva, del huésped y del apartamento.
  - Se completa todo desde el ordenador al hacer la reserva: casillas ☒ (motivo y acreditación, varias), garaje
    («No incluido» si no hay) y opción de solo guardar para imprimir a la llegada. Antes de imprimir avisa de lo
    que falte, para que el cliente solo tenga que firmar (se puede forzar con huecos para rellenar a mano).
  - Cada impresión queda en el historial de la reserva para reimprimirla.
  - De la tarjeta de garantía solo se guardan titular, últimos 4 dígitos y caducidad.
  - El representante, su DNI y el correo de la empresa se configuran en la ficha del activo.
- **Escaneo de documentos de identidad** (DNI, NIE/TIE, pasaportes y otros documentos con zona MRZ), en la ficha
  del cliente y en el contrato:
  - Lee nombre, apellidos, número, nº de soporte, nacionalidad, fecha de nacimiento, sexo y caducidad de la zona
    de lectura mecánica, validada con dígitos de control. En el DNI propone además el domicilio del reverso.
  - Avisa si el documento está caducado.
  - Rellena el contrato y completa la ficha. El nombre tecleado con tildes no se sustituye.
  - **Escáner primero:** en *Nueva reserva*, *Nuevo huésped/inquilino* y *Nuevo contrato* el escáner es lo primero.
    Al elegir el fichero o capturar con la cámara, el documento se lee solo. El cliente se crea con sus datos y
    la copia queda adjunta. Si el equipo tiene cámara (webcam, tablet o móvil), se abre automáticamente; se puede
    desactivar. Las copias escaneadas que no llegan a adjuntarse se borran a las 24 h.
  - Guarda una copia cifrada en la ficha del cliente y registra quién la consulta.
  - Todo se procesa en el propio servidor: las imágenes no salen a servicios externos.
- **Alquiler residencial**: contratos LAU (fianza, garantía adicional, día de pago, índice IRAV/IPC),
  emisión mensual de recibos prorrateados, cobros parciales o totales, anulación y actualización de renta.
- **Mantenimiento**:
  - Órdenes de trabajo correctivas, preventivas, normativas y de mejora, por gremio o instalación y con
    prioridad. Una OT puede bloquear la unidad (la saca de venta) hasta su cierre.
  - **Circuito de cierre**:
    1. Abren la OT Recepción, Limpieza o Mantenimiento.
    2. Mantenimiento ejecuta el trabajo y lo confirma con la solución y el coste.
    3. Limpieza revisa la unidad y la confirma, o la rechaza y vuelve a Mantenimiento.
    4. Recepción la cierra. Solo puede hacerlo con las dos confirmaciones.

    Al cerrar, la unidad queda disponible. Cada paso queda registrado con usuario y fecha.
    Las OT preventivas y normativas de zonas comunes (sin unidad) no pasan por Limpieza: Mantenimiento confirma
    y Recepción cierra.
  - Planes preventivos periódicos que generan sus OT automáticamente.
  - Plantilla normativa cargable por activo: RITE, RIPCI (RD 513/2017), legionela (RD 487/2022),
    ascensores (RD 355/2024), REBT ITC-BT-05 y buenas prácticas. Es orientativa: hay que ajustar
    las periodicidades a cada instalación.
- **Administración**: usuarios, roles editables, sociedades y registro de auditoría de todas las operaciones.

## Control de accesos

Cada usuario recibe uno o varios **roles**, y cada rol se asigna con un **ámbito**:

| Ámbito | Alcance |
|---|---|
| Todo el grupo | Todas las sociedades y activos |
| Sociedad | Todos los activos que gestiona esa sociedad, también los que se den de alta en el futuro |
| Activo | Solo ese activo (p.ej. recepción de Suite Florida) |

Roles iniciales, todos editables en *Administración → Roles y permisos*: Dirección Grupo, Dirección Sociedad,
Gestor Alquiler Residencial, Recepción, Gobernanta / Limpieza, Técnico Mantenimiento, Administración / Finanzas
y Consulta.

### Usuarios iniciales

Todos entran por primera vez con la contraseña provisional **`00000000`**. El sistema obliga a cambiarla antes de
poder hacer nada más: mínimo 10 caracteres y distinta de la provisional. Tras 5 intentos fallidos el acceso
queda bloqueado 15 minutos.

| Puesto | Usuario (email) | Rol | Ámbito |
|---|---|---|---|
| Presidente | jr@inversiete.es | Dirección Grupo | Todo el grupo |
| Director General | barbara@inversiete.es | Dirección Grupo | Todo el grupo |
| Director Técnico | alfonso@inversiete.es | Dirección Grupo | Todo el grupo |
| Recepción 1 Suite Florida | juancarlos@apartamentossuitesflorida.es | Recepción | Suite Florida |
| Recepción 2 Suite Florida | info@apartamentossuitesflorida.es | Recepción | Suite Florida |
| Recepción 1 Suite Aeropuerto | jaime@apartamentossuitesaeropuerto.es | Recepción | Suite Aeropuerto |
| Recepción 2 Suite Aeropuerto | info@apartamentossuitesaeropuerto.es | Recepción | Suite Aeropuerto |

Están pendientes de titular la recepción 3, los 2 puestos de limpieza y los 2 de mantenimiento de cada Suite.
Se dan de alta desde *Administración → Usuarios* con los roles Recepción, Gobernanta / Limpieza o
Técnico Mantenimiento, limitados al activo correspondiente.

Los emails y nombres se pueden cambiar desde *Administración → Usuarios*. El personal con ámbito de un activo
solo ve los huéspedes e inquilinos vinculados a ese activo.

## Puesta en marcha

**Producción (servidor Arsys):** seguir [`deploy/INSTALACION.md`](deploy/INSTALACION.md). Usa Docker, PostgreSQL,
HTTPS automático y copias diarias.

**Desarrollo local:**

```bash
cd pms
pip install -r requirements-dev.txt
PMS_ADMIN_PASSWORD='ClaveInicialSegura' uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Abrir `http://localhost:8000` y entrar con `admin@inversiete.com` y la contraseña indicada. Si no se indica
`PMS_ADMIN_PASSWORD`, la contraseña se genera y se muestra una única vez en la consola.

Variables de entorno:

| Variable | Uso | Por defecto |
|---|---|---|
| `PMS_DATABASE_URL` | Base de datos (SQLAlchemy). En producción, PostgreSQL | `sqlite:///pms/pms.db` |
| `PMS_SECRET_KEY` | Clave de firma de sesiones | se genera en `pms/.secret_key` |
| `PMS_ADMIN_EMAIL` / `PMS_ADMIN_PASSWORD` | Superadministrador inicial | `admin@inversiete.com` / aleatoria |
| `PMS_TOKEN_HOURS` | Duración de la sesión | 12 |

La documentación de la API está en `http://localhost:8000/docs`.

Tests: `cd pms && python -m pytest`. Contra PostgreSQL: `PMS_TEST_DATABASE_URL=postgresql+psycopg://usuario:clave@host/bd python -m pytest`

## Cambios en la base de datos (migraciones)

El esquema se actualiza solo al arrancar el PMS (`pms/app/migraciones.py`, con Alembic). Las actualizaciones
conservan los datos. Para el desarrollo:

1. Modificar `pms/app/models.py`.
2. Generar la migración: `cd pms && alembic revision --autogenerate -m "descripción" --rev-id 0002`.
3. Revisar el fichero generado en `pms/migrations/versions/`.

El test `test_modelos_sin_migracion_pendiente` falla si se cambia un modelo sin crear su migración.

## Estructura técnica

- Backend: Python, FastAPI y SQLAlchemy. Autenticación con JWT y contraseñas en bcrypt.
- Frontend: aplicación web ligera sin dependencias (`pms/static`), adaptada a móvil y tablet.
- Modelo: `Sociedad → Activo (modalidad) → Unidad`. Para añadir una modalidad nueva (oficinas, locales,
  parking, hotel…) basta con declararla en `MODALIDADES` (`pms/app/models.py`) e indicar qué módulos usa.

## Próximos pasos propuestos

1. Definir los rangos de acceso definitivos por puesto y ajustar los roles.
2. Recibir las tipologías de Suite Florida y las superficies y capacidades de los apartamentos turísticos.
3. Envío del parte de viajeros a SES.HOSPEDAJES (Ministerio del Interior).
4. Conexión con channel manager (Booking, Airbnb, Expedia) y tarifas por temporada.
5. Remesas SEPA de recibos y exportación contable.
6. Adjuntos (contratos firmados, fotos de averías, certificados OCA) y app móvil para técnicos.
7. Despliegue en servidor con PostgreSQL, HTTPS y copias de seguridad.
