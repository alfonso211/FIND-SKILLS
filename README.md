# PMS Grupo INVERSIETE

Sistema de gestión de activos (Property Management System) común para todo el grupo
**INVERSIETE SA** y sus sociedades (COMERCIAL DEL CAMPO, EDIFICIOS CAMERANOS, ETHOSA).
Hay una sola plataforma, pero cada usuario solo ve y gestiona lo que su rol y su ámbito le permiten.

## Activos cargados de inicio

| Código | Activo | Modalidad | Unidades |
|---|---|---|---|
| BAB35 | C/ Babilonia 35, Madrid | Alquiler residencial (LAU) | Se dan de alta desde *Unidades → Alta masiva* |
| SFL | Suite Florida | Apartamentos turísticos | 325 (SF-001 … SF-325) |
| SAE | Suite Aeropuerto | Apartamentos turísticos | 300 (SA-001 … SA-300) |

Para añadir activos nuevos: *Activos → Nuevo activo* (se elige la sociedad titular y la modalidad).

> **Pendiente de confirmar:** la sociedad titular de cada activo. De forma provisional los tres
> cuelgan de INVERSIETE SA. Se cambia desde *Activos → Editar*.

## Módulos

- **Panel de control**: ocupación del día, llegadas y salidas, contratos vigentes, renta mensual,
  deuda vencida, producción del mes y OT abiertas o urgentes por activo.
- **Apartamentos turísticos**: reservas con control de solapes y de capacidad, búsqueda de disponibilidad,
  check-in (exige los datos del parte de viajeros, RD 933/2021), check-out y paso de la unidad a
  *pendiente de limpieza*. Incluye planning por unidad y día, y ficha de huéspedes.
- **Alquiler residencial**: contratos LAU (fianza, garantía adicional, día de pago, índice IRAV/IPC),
  emisión mensual de recibos prorrateados, cobros parciales o totales, anulación y actualización de renta.
- **Mantenimiento**:
  - Órdenes de trabajo correctivas, preventivas, normativas y de mejora, por gremio o instalación y con
    prioridad. Una OT puede bloquear la unidad (la saca de venta) y la libera al cerrarse.
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
| Sociedad | Todos los activos de esa sociedad, también los que se den de alta en el futuro |
| Activo | Solo ese activo (p.ej. recepción de Suite Florida) |

Roles iniciales, todos editables en *Administración → Roles y permisos*: Dirección Grupo, Dirección Sociedad,
Gestor Alquiler Residencial, Recepción, Gobernanta / Limpieza, Técnico Mantenimiento, Administración / Finanzas
y Consulta. Los permisos concretos se ajustarán cuando se detallen los rangos de acceso.

## Puesta en marcha

```bash
cd pms
pip install -r requirements.txt
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

Tests: `cd pms && python -m pytest`

## Estructura técnica

- Backend: Python, FastAPI y SQLAlchemy. Autenticación con JWT y contraseñas en bcrypt.
- Frontend: aplicación web ligera sin dependencias (`pms/static`), adaptada a móvil y tablet.
- Modelo: `Sociedad → Activo (modalidad) → Unidad`. Para añadir una modalidad nueva (oficinas, locales,
  parking, hotel…) basta con declararla en `MODALIDADES` (`pms/app/models.py`) e indicar qué módulos usa.

## Próximos pasos propuestos

1. Definir los rangos de acceso definitivos por puesto y ajustar los roles.
2. Confirmar la sociedad titular de cada activo y el número de viviendas de Babilonia 35.
3. Envío del parte de viajeros a SES.HOSPEDAJES (Ministerio del Interior).
4. Conexión con channel manager (Booking, Airbnb, Expedia) y tarifas por temporada.
5. Remesas SEPA de recibos y exportación contable.
6. Adjuntos (contratos firmados, fotos de averías, certificados OCA) y app móvil para técnicos.
7. Despliegue en servidor con PostgreSQL, HTTPS y copias de seguridad.
