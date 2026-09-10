# Design: reservation-manual-guest-resolution

## Context

El alta manual vive en `backend/app/reservations/application/use_cases.py` y hoy valida un
`guest_id` existente antes de crear la reserva y registrar
`RESERVATION_CREATED_MANUAL`; el caso de uso termina con un único `UnitOfWork.commit()`.
`CreateReservationRequest` está en `backend/app/reservations/api/schemas.py` y la ruta POST
usa `MANAGE_RESERVATIONS` desde `backend/app/reservations/api/router.py`.

`GuestRepository` está definido en `backend/app/guests/domain/repositories.py` y su adapter en
`backend/app/guests/infrastructure/repositories.py`. `find_by_email` normaliza con
`normalize_email` y elige determinísticamente por `created_at, id`; `add` normaliza el email
pero no captura colisiones ni coordina el patrón find/create. La tabla `guests` solo tiene un
índice no único por `(tenant_id, email)` en
`backend/app/guests/infrastructure/models.py`.

El único writer de producción que actualmente aplica la política de resolver por email es
`ReservationIngestor._link_guest` en `backend/app/integrations/application/ingest.py`. El
portal puede crear un Guest sin email en `backend/app/guests/application/portal.py`, y los
scripts de seed pueden insertar Guests directamente; ninguno de esos caminos es un writer de
la política de resolución por email de este change.

## Decisions

### D1 — Resolver compartido en la capa de aplicación

**Chosen:** crear un servicio de aplicación `ResolveOrCreateGuest` bajo
`backend/app/guests/application/`, consumido por el alta manual y por los writers existentes
que aplican resolución por email. Recibe el tenant y una identidad ya validada, normaliza en la
frontera existente, busca por email y crea solo cuando no hay coincidencia. Al reutilizar un
Guest no actualiza sus datos.

Esto centraliza la política sin crear un endpoint ni un CRUD de Guests. La responsabilidad
específica de ingest —mapeo desde `ReservationDTO`, defaults de importación e informes—
permanece en `ingest.py`.

Rejected: duplicar `_link_guest` dentro de reservations — mantendría dos políticas y dos races.

### D2 — Port de exclusión transaccional y adapter PostgreSQL

**Chosen:** declarar un port estrecho en
`backend/app/guests/domain/ports.py`, por ejemplo `GuestEmailExclusion.acquire(tenant_id,
normalized_email)`, y hacer que `ResolveOrCreateGuest` lo invoque antes de
`find_by_email`. La implementación quedará en
`backend/app/guests/infrastructure/postgres_guest_email_exclusion.py` y recibirá la sesión
SQLAlchemy ya perteneciente a la UoW.

El adapter ejecutará `SELECT pg_advisory_xact_lock(:key)` sobre la conexión de la transacción.
El port no expondrá SQL, PostgreSQL, `AsyncSession` ni detalles de la clave. `domain/` y
`application/` dependerán solo del port, cumpliendo
`backend-architecture.md`.

Rejected: importar SQLAlchemy o ejecutar `pg_advisory_xact_lock` desde application — rompería
la separación hexagonal y haría imposible probar el resolver con un fake.

### D3 — Clave estable del advisory lock

**Chosen:** el adapter construirá el material canónico como:

```text
tenant_id en UUID canónico + "\0" + normalized_email
```

Aplicará SHA-256 con la librería estándar y convertirá los primeros 8 bytes en un entero
big-endian con signo de 64 bits para `pg_advisory_xact_lock(bigint)`. El algoritmo será una
función pura del adapter, documentada y cubierta por tests con vectores conocidos.

No se usará `hash()` de Python, el id del objeto, representación dependiente de proceso ni
truncado basado en el runtime. Dos transacciones con el mismo tenant y email producirán la
misma clave; distintos tenants producirán claves distintas salvo la colisión criptográfica
teórica del espacio de 64 bits.

Rejected: `hash()` de Python — su seed puede variar entre procesos.

Rejected: lock solo por email — permitiría bloquear innecesariamente entre tenants y no
expresaría el ámbito de identidad del dominio.

### D4 — Orden de resolución y duplicados históricos

**Chosen:** para un email no vacío, el resolver normaliza, adquiere el lock transaccional y
vuelve a ejecutar `find_by_email` dentro de la misma transacción antes de crear. Si ya existen
varios Guests históricos con ese email normalizado, conserva la selección determinista ya
definida por `SqlAlchemyGuestRepository`: menor `created_at` y después menor `id`.

El change no fusiona, elimina ni reasigna Guests históricos. El lock evita nuevos duplicados
creados por los call sites que adopten el resolver, pero no convierte el índice actual en una
garantía de base de datos.

Rejected: escoger el survivor por estado documental, número de reservas o heurística de nombre
— el dominio no define esas prioridades y podría seleccionar una identidad incorrecta.

### D5 — No actualizar Guests reutilizados

**Chosen:** el resolver devuelve el Guest existente como resultado de identidad y descarta los
valores de `full_name`, `phone`, `preferred_language` y demás campos recibidos para esa alta.
Solo el camino de creación construye y persiste un Guest nuevo con la identidad validada.

La edición de un Guest existente queda fuera del contrato y del scope; no se introduce una
operación de patch implícita.

### D6 — Contrato de request y errores

**Chosen:** ampliar `CreateReservationRequest` con un bloque `guest` opcional, manteniendo
`guest_id` opcional. La validación de modelo rechazará ambos campos juntos con el mecanismo de
validación Pydantic existente, que la API serializa como `422` en el envelope estándar.

El bloque `guest` tendrá `full_name` obligatorio, trim y longitud 1–300; `email` opcional con
trim/lowercase por `normalize_email`; `phone` opcional con `normalize_phone_e164`; y
`preferred_language` opcional restringido a `es|en`, con default `es`. Si no llega ninguno de
`guest_id`/`guest`, la reserva seguirá siendo guest-less. Si llega solo `guest_id`, se mantiene
el `404` actual para un Guest inexistente o de otro tenant.

La respuesta seguirá usando el `ReservationResponse` existente, incluyendo el `guest_id`
resuelto. Se actualizarán `backend/openapi.json` y el tipo generado del frontend conforme a
`steering/documentation.md`.

Rejected: endpoint separado de resolución — añade un round trip y no puede hacer Guest +
Reservation + evento atómicos a través de HTTP.

### D7 — Una UoW y un commit para el alta manual

**Chosen:** `CreateReservationUseCase` resolverá/creará el Guest antes de construir la
Reservation, añadirá la Reservation, registrará `RESERVATION_CREATED_MANUAL` y ejecutará el
único `commit()` al final. Guest, Reservation y evento compartirán la sesión y la UoW real.

Ante cualquier excepción, la dependencia de sesión existente hará rollback; el caso de uso no
deberá confirmar ninguna parte intermedia. Los tests de integración verificarán que falla la
reserva, falla el evento o falla el persistido del Guest no deja filas parciales.

Rejected: permitir que el resolver o un caso de uso anidado haga commit — rompería la atomicidad
y repetiría el fallo que `CallerOwnedUnitOfWork` evita en composiciones existentes.

### D9 — Aislamiento después de esperar por el lock

**Chosen:** mantener el isolation level por defecto de PostgreSQL/SQLAlchemy. La factoría real
en `backend/app/core/db.py` se crea como `create_async_engine(settings.database_url)` y
`async_sessionmaker(engine, expire_on_commit=False)`, sin `isolation_level` propio; PostgreSQL
opera por tanto con `READ COMMITTED`, salvo una configuración externa de la base de datos que
este change no modifica.

El adapter ejecutará el `pg_advisory_xact_lock` y, una vez que retorna, el resolver ejecutará
`find_by_email` como una sentencia posterior. En `READ COMMITTED` cada sentencia obtiene su
snapshot al comenzar: después de esperar al lock, el segundo `find_by_email` ve el Guest que la
primera transacción ya confirmó. No se debe convertir ese flujo en una única sentencia leída
antes del lock ni elevar la sesión a `REPEATABLE READ`, porque el snapshot anterior podría no
ver la fila recién confirmada y el race reaparecería como duplicado.

La prueba de integración usará dos sesiones reales: la segunda deberá bloquearse, continuar
tras el commit de la primera y devolver su mismo `guest_id`. También fijará que no se configura
un isolation level alternativo en el adapter.

Rejected: commits intermedios en ingest — romperían la UoW actual y permitirían persistir parte
del batch cuando otra fila o el registro de auditoría falla.

Rejected: `REPEATABLE READ` o snapshot compartido — no aporta la garantía necesaria al segundo
lookup y puede producir un snapshot obsoleto tras la espera.

### D8 — Integración con todos los writers relevantes

**Chosen:** revisar y adaptar todos los call sites productivos que usen la política de
resolución por email. El inventario actual es:

| Writer | Ubicación | Decisión |
|---|---|---|
| Ingesta PMS/CSV/demo | `backend/app/integrations/application/ingest.py::_link_guest` | Adoptar `ResolveOrCreateGuest`; conservar el mapeo y reporte propios de ingest |
| Alta manual | `backend/app/reservations/application/use_cases.py::CreateReservationUseCase` | Adoptar el resolver y compartir la UoW del alta |
| Guest Portal check-in | `backend/app/guests/application/portal.py::_create_guest` | No adopta la política de email: crea por reserva sin email y queda fuera de este change |
| Legal/documentos | `backend/app/guests/application/use_cases.py` | No crea Guests; solo lee o actualiza datos de un Guest existente |
| Seed CLI | `backend/app/cli/seed_demo.py` | Inserción controlada de datos demo, no resolución de identidad de negocio |

No se ampliará el inventario a crear funcionalidades nuevas. Si la implementación descubre un
writer productivo adicional que sí resuelve por email, deberá pasar por el mismo servicio antes
de marcar el change completo.

La granularidad transaccional de los writers conocidos queda fijada por el código actual:

- `ImportReservationsFromCsvUseCase.execute` pasa todas las filas parseadas a una sola llamada
  de `ReservationIngestor.ingest` y ejecuta `self._uow.commit()` una vez al final. El parser
  limita el fichero a `settings.csv_import_max_rows`, actualmente 1.000, en
  `backend/app/core/config.py`.
- `SyncReservationsFromPmsUseCase.execute` puede llamar al ingestor una vez por cada proveedor
  configurado y acumula sus filas en la misma sesión/UoW; su único `self._uow.commit()` se
  ejecuta después del bucle de proveedores y del registro de lecturas de credenciales.
  Las listas PMS no tienen en este caso de uso un límite de filas equivalente al CSV.
- `ReservationIngestor.ingest` recorre la lista recibida, pero no hace commit ni crea una UoW
  propia. La UoW pertenece al caso de uso exterior.

Por consecuencia, cada `pg_advisory_xact_lock` adquirido para un email se mantiene hasta el
commit de todo el batch que lo adquirió. Los emails distintos no se bloquean entre sí; una alta
manual del mismo email puede esperar al sync completo, no solo a la fila que lo encontró. Esto
es un riesgo de latencia potencial para un PMS batch grande, no una razón para introducir
commits intermedios: partir la UoW cambiaría la semántica actual de rollback y del informe.

Mitigación de menor blast-radius: adquirir el lock lo más tarde posible, inmediatamente antes
del segundo `find_by_email` y del `add`, no adquirirlo para emails ausentes y no hacer trabajo
de propiedad, reserva, timeline o reporting mientras se espera. El comportamiento seguro ante
contención es esperar a que termine la transacción propietaria; no se libera manualmente el
lock antes del commit, porque otro resolver podría no ver todavía el Guest no confirmado y
crear un duplicado. El design deberá añadir métricas/logging de tiempo de espera para hacer
visible esta contención sin alterar la UoW.

Rejected: modificar todo call site que simplemente pueda insertar un Guest — el portal sin
email y el seed no ejercen la política de identidad por email y ampliarles el alcance alteraría
otras capacidades.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Guest domain/application | `backend/app/guests/domain/ports.py`, `backend/app/guests/application/` | Port de exclusión y `ResolveOrCreateGuest`; política de normalización, selección determinista y no actualización de reutilizados |
| Guest infrastructure | `backend/app/guests/infrastructure/postgres_guest_email_exclusion.py`, `backend/app/guests/infrastructure/repositories.py` | Adapter PostgreSQL; wiring con la sesión existente; conservar `find_by_email` determinista |
| Reservations application/API | `backend/app/reservations/application/use_cases.py`, `backend/app/reservations/api/schemas.py`, `backend/app/reservations/api/router.py` | Request `guest`, exclusión mutua, resolución dentro de la UoW y errores 422 |
| Integrations | `backend/app/integrations/application/ingest.py` y wiring correspondiente | Sustituir `_link_guest` duplicado por el resolver, sin cambiar semántica específica de ingest |
| Tests | `backend/tests/guests/`, `backend/tests/reservations/`, `backend/tests/integrations/` | Normalización, no-update, tenant isolation, duplicados históricos, concurrencia, rollback y contrato |
| Contract artifacts | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerar tras cambiar el schema |
| Living specs | `sdd/specs/reservations.md`, `sdd/specs/domain-foundation-core.md` | Documentar el contrato y la garantía application-level sin UNIQUE |

## Data & interfaces

No se añade migración ni constraint de base de datos en este change. El índice actual
`ix_guests_tenant_id_email` permanece no único.

El port de exclusión es una operación transaccional sin estado persistido. El advisory lock se
libera automáticamente al terminar la transacción PostgreSQL.

Forma conceptual del request:

```json
{
  "guest_id": "uuid opcional",
  "guest": {
    "full_name": "Nombre obligatorio",
    "email": "email opcional",
    "phone": "teléfono opcional",
    "preferred_language": "es|en opcional"
  }
}
```

Las combinaciones válidas son solo `guest_id`, solo `guest` o ninguno. Ambos producen `422`.
El response continúa siendo la reserva existente con `guest_id` nullable.

## Risks & mitigations

- **No hay garantía DB absoluta:** un writer que evite el resolver puede crear duplicados.
  Mitigación: inventario de call sites, adapter compartido, tests y documentación; la UNIQUE
  queda como hardening posterior.
- **Duración del lock durante ingest:** `ReservationIngestor` no hace commits por fila. El CSV
  puede procesar hasta 1.000 filas y el sync PMS procesa las listas devueltas por cada proveedor
  dentro de la UoW exterior, cuyo commit ocurre al final del sync. Por ello, una alta manual con
  el mismo email puede esperar al batch completo; no se considera despreciable para batches PMS
  grandes. Mitigación: adquirir el lock justo antes del segundo `find_by_email`/`add`, omitirlo
  para email ausente, no hacer trabajo adicional mientras se espera y observar la duración de
  la espera. No se introducen commits intermedios, porque romperían la atomicidad y el rollback
  del batch actual.
- **Colisiones históricas:** el resolver puede seguir seleccionando un Guest entre varios.
  Mitigación: selección `created_at, id` compatible con el repositorio y no merge implícito.
- **Colisión de clave de 64 bits:** riesgo teórico del advisory lock. Mitigación: SHA-256,
  algoritmo documentado y clave tenant-scoped; la futura UNIQUE será la garantía definitiva.
- **Dependencia PostgreSQL:** queda confinada al adapter y el port puede sustituirse por un fake
  en unit tests.
- **Rollback incompleto:** un commit intermedio del resolver lo rompería. Mitigación: wiring
  con la UoW de `CreateReservationUseCase`, un único commit y tests de fallo.
- **Deriva OpenAPI:** cambiar el schema sin artefactos generados rompe CI. Mitigación:
  regenerar backend y frontend en el mismo cambio.
- **Datos recibidos sobre Guest existente:** podrían parecer una edición. Mitigación: criterio
  explícito de no actualización y test que compara todos los campos relevantes.
- **Aislamiento configurado externamente:** la garantía de visibilidad posterior al lock
  presupone `READ COMMITTED`, que es el valor efectivo de PostgreSQL cuando no se configura otro
  nivel. Mitigación: no fijar `REPEATABLE READ`, ejecutar el segundo lookup como sentencia
  posterior al lock y cubrir con dos sesiones reales que el segundo resolver devuelve el Guest
  confirmado por el primero.

## Open questions

No quedan decisiones funcionales abiertas para implementar el proposal. La política de UNIQUE y
la reconciliación de duplicados históricos están deliberadamente aplazadas al change separado
`guest-email-identity-hardening`.
