# Design: reservations

## Context

El agregado ya está modelado y migrado: `backend/app/reservations/domain/entities.py`
(dataclass `Reservation` con la invariante `check_out_date > check_in_date`),
`backend/app/reservations/domain/enums.py` y
`backend/app/reservations/infrastructure/models.py` (`ReservationModel`, con
`UniqueConstraint(tenant_id, external_pms_id)` y los tres índices de PRD §7.7), en
la migración `4a5faad7796b_baseline_domain_foundation_core`. Lo que no existe es
ninguna capa `application/`, `infrastructure/repositories.py` ni `api/` en el
módulo: `backend/app/main.py` monta un único router, el de `auth`.

El módulo `auth` es la referencia de forma a copiar: puertos en `domain/`, casos de
uso en `application/use_cases.py`, adaptadores SQLAlchemy en
`infrastructure/repositories.py`, router fino en `api/router.py` con
`require(Permission.X)` (`backend/app/auth/api/dependencies.py`) y el envelope de
error de PRD §23 en `backend/app/core/errors.py`. El aislamiento por tenant tiene
dos mecanismos ya construidos en `backend/app/core/db.py`: el `tenant_id` explícito
en cada método de repositorio (mecanismo autoritativo, design D6 de `auth-tenancy`)
y el listener `_scope_statement_to_tenant` como red (que **no** cubre INSERTs ni
SQL crudo — así está documentado en el propio fichero).

`timeline` es dominio puro (`backend/app/timeline/domain/services.py`:
`TimelineEventFactory.create`, que valida y exige `id` y `created_at` explícitos) y
**nadie persiste todavía un `TimelineEvent`**. Este change es el primero que lo
hace.

## Decisions

### D1 — Dos módulos: `reservations` (agregado) e `integrations` (PMS + CSV)

**Chosen:** el agregado, su repositorio y sus endpoints `/api/v1/reservations` viven
en `backend/app/reservations/`; el puerto `PMSAdapter`, el `MockPMSAdapter`, el
parser CSV y los casos de uso de ingesta viven en `backend/app/integrations/`, que
expone `POST /api/v1/integrations/pms/import-csv`. `integrations` es uno de los
dominios que `steering/architecture.md` ya lista, y la ruta del endpoint del PRD
§16 lo confirma; así el agregado no se acopla a la forma de ingesta y la ingesta
depende del puerto del repositorio, no al revés.

Rejected: todo dentro de `reservations/` — mete el adapter de un sistema externo en
el módulo del agregado y deja la ruta `/integrations/...` colgando de un router que
no le corresponde.

### D2 — La persistencia del timeline es un puerto nuevo del módulo `timeline`

**Chosen:** `TimelineEventRepository` (Protocol) en
`backend/app/timeline/domain/repositories.py` con un único método `add`, y
`SqlAlchemyTimelineEventRepository` en
`backend/app/timeline/infrastructure/repositories.py`. Los eventos se construyen
**siempre** con `TimelineEventFactory.create` (R2.7), así que la validación de
dominio ya existente sigue siendo el único sitio donde se valida un evento. El
dominio de `timeline` no cambia: sigue sin importar SQLAlchemy.

Rejected: escribir `timeline_events` desde el repositorio de reservas — un
repositorio por agregado raíz es regla de `steering/backend-architecture.md`.
Rejected: un `TimelineService` de aplicación que orqueste eventos de todos los
módulos — no hay dos consumidores todavía; se introduciría una abstracción sin
segundo caso.

### D3 — Un `UnitOfWork` compartido en `core`, sin tocar `auth`

**Chosen:** `backend/app/core/unit_of_work.py` con el `UnitOfWork` (Protocol) y
`SqlAlchemyUnitOfWork`, que usan los casos de uso nuevos. `auth` se queda con su
`backend/app/auth/infrastructure/unit_of_work.py` intacto.

Rejected: importar el de `auth` desde `reservations` — acopla dos módulos de
dominio por un detalle de infraestructura. Rejected: promover el de `auth` a `core`
y actualizar sus imports — es refactor de un módulo ya archivado, fuera del alcance
de esta entrada. **Deuda registrada**: quedan dos clases idénticas de 8 líneas; la
consolidación es del próximo change que toque `auth`.

### D4 — Atomicidad: reserva y evento en la misma transacción, commit en el caso de uso

**Chosen:** cada caso de uso recibe repositorios + `UnitOfWork` y hace un único
`commit()` al final (R2.6). `get_db_session` ya garantiza rollback si la petición
revienta. El evento se añade a la misma `AsyncSession`, así que un fallo al escribir
el evento deja la reserva sin cambiar sin necesidad de compensaciones.

Rejected: commit por repositorio — rompe la atomicidad que pide R2.6.

### D5 — `tenant_id` explícito en cada método de repositorio

**Chosen:** se replica el design D6 de `auth-tenancy`: la firma de cada método lleva
`tenant_id` y la query lo filtra explícitamente; además `add()` rechaza una entidad
con `tenant_id` distinto al del contexto, porque el listener de `core/db.py` **no
guarda los INSERTs** (límite 3 documentado allí). El listener sigue siendo la red,
no el mecanismo.

Rejected: confiar solo en `bind_session_to_tenant` — deja los INSERTs y el mapa de
identidad sin cubrir, por escrito.

### D6 — Referencia cross-tenant → `404`, nunca `403`

**Chosen:** los repositorios devuelven `None` para una fila de otro tenant y el caso
de uso lanza `NotFoundError` (`app/core/errors.py`, ya mapeado a 404 con el envelope
de PRD §23).

**Desviación explícita de una decisión aprobada.** El design D15 de `auth-tenancy`
**rechazó por nombre** asignar sus R4.3/R4.4 a `reservations`: *"Rejected: asignarlos
a `reservations` … `user-management` va antes en el orden del roadmap y ya recibe
identificadores de recurso, así que el hueco se cierra antes"*. Esa premisa ya no se
cumple: el orden real de ejecución ha puesto `reservations` primero, así que **este**
es de hecho el primer módulo con endpoints que reciben identificadores de recurso
tenant-scoped. No se reescribe la historia — D15 decidió lo contrario y su motivo era
razonable cuando se escribió.

Consecuencias documentales, que son parte del alcance de este change y no un efecto
colateral:

- `sdd/specs/auth-tenancy.md` §*Alcance declarado* afirma hoy que esos criterios "son
  criterios de aceptación bloqueantes de `user-management`, la primera capacidad con
  endpoints que reciben identificadores tenant-scoped". Al archivar hay que corregir
  la parte factual (la primera capacidad es `reservations`), **sin** liberar a
  `user-management`: cada módulo demuestra la matriz de **sus** endpoints, así que sus
  criterios siguen siendo bloqueantes para los suyos.
- El bullet de `user-management` en `sdd/roadmap.md` repite la misma afirmación y hay
  que ajustarlo igual.

Lo que este change cierra es **su propia** R5.1/R5.7 sobre sus seis endpoints, no los
requisitos de otro change.

Rejected: `403` — confirma la existencia del recurso a quien no debería saberlo.
Rejected: presentar D6 como si D15 ya lo hubiera asignado aquí — es falso y dejaría
tres documentos vigentes contradiciéndose.

### D7 — Dos permisos nuevos, matriz derivada de PRD §6

**Chosen:** `Permission.READ_RESERVATIONS` y `Permission.MANAGE_RESERVATIONS` en
`backend/app/auth/domain/policy.py`, con el mapa:

| Rol | Listar/consultar | Crear/editar/cancelar | Importar CSV |
|---|---|---|---|
| `PROPERTY_MANAGER` | sí | sí | sí |
| `TENANT_OWNER` | sí | no (`403`) | no (`403`) |
| `CLEANER` | no | no | no |
| `TECHNICIAN` | no | no | no |
| `SUPER_ADMIN` | no | no | no |

PRD §6 dice literalmente que `PROPERTY_MANAGER` "gestiona reservas (crear, editar,
cancelar)" y que `TENANT_OWNER` "ve sus propiedades y reservas" — de ahí la
separación lectura/gestión. `CLEANER` y `TECHNICIAN` solo ven sus propias tareas y
tickets. `SUPER_ADMIN` queda denegado porque sus capacidades en PRD §6 son globales
(tenants, configuración, integraciones), no operativas de un tenant, y la
visibilidad cross-tenant está explícitamente diferida a la entrada
`saas-cross-tenant`: darle acceso aquí sería adelantar esa decisión. Importar usa
`MANAGE_RESERVATIONS`, no un permiso propio, porque es la misma capacidad de
negocio por otra vía.

Rejected: un solo permiso `MANAGE_RESERVATIONS` para todo — convertiría a la
propietaria en gestora, contra PRD §6.

### D8 — Vinculación de `Guest` por email normalizado, con desempate determinista

**Chosen:** al ingerir una reserva con datos de huésped se busca en el tenant un
`Guest` cuyo email normalizado (`strip` + `lower`) coincida; si hay varios se toma
el de `created_at` más antiguo (`id` como segundo criterio, para que el resultado no
dependa del plan de ejecución); si no hay ninguno se crea. Sin email pero con
nombre, se crea siempre uno nuevo. `guests.email` **no** es único —el índice de PRD
§7.6 es `INDEX(tenant_id, email)`, y ADR 0005 hizo único el email de `User`, no el
de `Guest`— así que el desempate hay que decidirlo, no asumirlo. Ningún campo de
documento (`document_number_encrypted`, `date_of_birth`, `nationality`) se toca: ese
flujo es de `access-notifications`/`guest-portal`.

Rejected: exigir email — el CSV de un canal puede no traerlo. Rejected: crear
siempre un `Guest` nuevo — duplica la misma persona en cada importación.

### D9 — Idempotencia por `(tenant_id, external_pms_id)`, apoyada en la constraint

**Chosen:** la ingesta (PMS y CSV) busca por `(tenant_id, external_pms_id)`; si
existe actualiza y **no** emite `RESERVATION_IMPORTED`; si no, inserta y lo emite.
La `UniqueConstraint` que ya está en la tabla es la autoridad ante una carrera: el
`IntegrityError` se traduce a `DuplicateExternalReservationError`, que la ingesta convierte en
una fila "omitida" con su motivo en el informe. Una reserva sin `external_pms_id` (creada a
mano) nunca entra en esta ruta.

**Hoy ese duplicado no produce ningún `409` por HTTP**, y conviene decirlo con precisión porque
este párrafo se ha corregido dos veces:

- `POST /reservations` no puede producirlo, porque el endpoint manual **no acepta**
  `external_pms_id` — es la clave de idempotencia de la ingesta, y un valor escrito a mano haría
  que la siguiente sincronización creyera que ya importó esa reserva. (Descubierto al escribir el
  test de API de la sección 4: la tabla de endpoints de este design listaba un `409` que el
  endpoint no puede producir.)
- Las vías de ingesta tampoco, porque `ReservationIngestor` **captura** la excepción y la reporta
  como fila omitida: es justo lo que R3.4/R4.2 piden. (Señalado por el panel de arquitectura a
  escala de feature.)

El mapeo `DuplicateExternalReservationError → 409` se mantiene en
`app/reservations/api/errors.py` a propósito: el error de dominio existe y un endpoint futuro que
acepte `external_pms_id` —o la recepción de webhooks— lo necesitará, y sin mapeo saldría como
`500`. Es un mapeo correcto de un error alcanzable en el dominio, no código muerto que finge una
respuesta que hoy nadie da.

Rejected: `ON CONFLICT DO UPDATE` — hace invisible la distinción creada/actualizada
que el informe de R4.1 tiene que reportar.

### D10 — La sincronización con el PMS se dispara por CLI, no por un endpoint nuevo

**Chosen:** `SyncReservationsFromPmsUseCase` se expone como comando de consola en
`backend/app/integrations/cli/pms_sync.py`, copiando la forma de
`backend/app/cli/bootstrap.py` (que ya existe y hace exactamente esto para el seed).
PRD §23 no define ningún endpoint de sync, y el disparador natural —Celery beat—
pertenece a `celery-jobs`. Cuando esa entrada llegue, programará este mismo caso de
uso sin tocar nada más.

Rejected: inventar `POST /api/v1/integrations/pms/sync` — endpoint no especificado,
y superficie pública nueva que habría que autorizar y documentar sin que el PRD la
pida.

### D11 — Contrato del CSV y sus límites

**Chosen:** `multipart/form-data`, un fichero, UTF-8 (con BOM tolerado), delimitador
`,`. Columnas requeridas: `property_internal_code`, `channel`, `check_in_date`,
`check_out_date`, `adults`. Opcionales: `external_pms_id`, `external_channel_id`,
`guest_name`, `guest_email`, `guest_phone`, `children`, `check_in_time`,
`check_out_time`, `gross_amount`, `ota_commission`, `currency`, `status`,
`special_requests`. La propiedad se referencia por `internal_code` (REDES11), no por
UUID, porque un CSV lo rellena una persona. Límites por configuración:
`csv_import_max_bytes` (default 10 MB, regla 6 de `steering/security.md`) y
`csv_import_max_rows` (default 1000) → `413`. Se valida el content-type declarado y
se rechaza `422` si faltan columnas requeridas. El informe devuelve
`{created, updated, skipped, errors: [{row, reason}]}` y **nunca** aborta por una
fila mala (R4.2).

Rejected: `property_id` UUID en el CSV — inutilizable a mano. Rejected: abortar todo
el fichero al primer error — contradice R4.2.

### D12 — Paginación y envelope según PRD §23

**Chosen:** `?page=1&per_page=20` con respuesta
`{data, total, page, per_page, total_pages}`, `per_page` acotado (máximo 100) y
orden estable por `check_in_date DESC, id`. Los filtros de R1.1 (`property_id`,
`status`, `date_from`, `date_to`) se combinan con AND; el rango se interpreta sobre
solape de estancia (`check_in_date <= date_to AND check_out_date >= date_from`), que
es lo que operativamente se pregunta ("qué reservas caen en estas fechas").

Rejected: cursor pagination — PRD §23 fija page/per_page.

### D13 — Este change no invoca la máquina de estados

**Chosen:** ninguna mutación de reserva dispara una transición de
`PropertyOperationalState`. `steering/architecture.md` exige que las transiciones
ocurran solo dentro de `PropertyStateMachine`, y las que dependen de una reserva son
dependientes del reloj (`AWAITING_CHECKIN`, `OCCUPIED_ESTIMATED`,
`CHECKOUT_WINDOW_REACHED`): pertenecen a `celery-jobs` (PRD §26.8). Persistir la
reserva y su `TimelineEvent` es todo lo que corresponde aquí.

Rejected: transicionar al crear una reserva — introduce lógica de reloj en un
endpoint y duplica lo que `celery-jobs` va a hacer bien.

### D14 — `AuditLog` de reservas: deuda con dueño, no desviación silenciosa

**Chosen:** este change **no** escribe `AuditLog`, porque la entidad (PRD §7.25) no
existe: pertenece a `domain-foundation-financial`, entrada del roadmap anterior a
esta y todavía sin empezar. La regla 9 de `steering/security.md` pide `AuditLog`
para `Reservation`, así que esto es una desviación **temporal y con dueño
explícito**, no una decisión de diseño: el rastro que sí queda es el `TimelineEvent`
de cada mutación (R2), que es inmutable y consultable. Se resuelve con el mismo
criterio que el proyecto ya aplicó a `user-management`, cuya entrada del roadmap
dice literalmente "Depende de `domain-foundation-financial` por la entidad
`AuditLog`" — es la convención establecida del repo para este caso, no un juicio
nuevo.

**Lo que hay que hacer cuando `domain-foundation-financial` pase**: añadir la escritura de
`AuditLog` en los **seis** casos de uso mutadores del change — los cuatro de `reservations`
(create/update/cancel más el propio agregado) y los dos de `integrations`
(`SyncReservationsFromPmsUseCase` e `ImportReservationsFromCsvUseCase`), que también crean
`Reservation` y `Guest`. Los dos últimos los añadió el panel de seguridad a escala de feature:
la nota original decía "cuatro" y habría dejado las reservas importadas como las únicas sin
registro de auditoría. Queda
anotado en la spec al archivar.

Rejected: crear la tabla `audit_logs` aquí — le roba la entidad a la entrada que la
posee y la duplicaría en dos migraciones. Rejected: no dejar rastro — incumpliría el
principio 1 de `steering/product.md`.

### D15 — Actor del evento: `SYSTEM` para el PMS, `USER` para el CSV

**Chosen:** la sincronización con el PMS emite `RESERVATION_IMPORTED` con
`actor_type` `SYSTEM` (no hay persona: la dispara un comando o, más adelante, el
scheduler); la importación CSV lo emite con `actor_type` `USER` y el
`actor_user_id` de quien subió el fichero, porque sí hay una persona identificada
detrás. `TimelineEventFactory` obliga a esa coherencia (rechaza `actor_user_id` en
eventos no-`USER` y lo exige en los `USER`), así que la decisión es también lo único
que el dominio acepta. El `proposal.md` se corrigió en este mismo change: su R2
original marcaba las dos vías como `SYSTEM`.

Rejected: `SYSTEM` para el CSV — perdería quién importó qué, que es justo lo que un
timeline auditable tiene que responder.

### D16 — La resolución de `Property` es un puerto nuevo del módulo `properties`

**Chosen:** `PropertyRepository` (Protocol) en
`backend/app/properties/domain/repositories.py` con
`get(tenant_id, property_id)`, `find_by_internal_code(tenant_id, internal_code)` y
`find_by_pms_external_id(tenant_id, pms_external_id)`, más
`SqlAlchemyPropertyRepository` en
`backend/app/properties/infrastructure/repositories.py`. Sin él, tres criterios no
tienen mecanismo: R1.4 (`property_id` inexistente en el tenant → `404`), R3.4 (reserva
del PMS que apunta a una propiedad desconocida → se omite y se informa) y R4 (el CSV
referencia la propiedad por `internal_code`, D11). El módulo `properties` hoy solo
tiene `domain/` e `infrastructure/models.py`, y `Property` ya lleva `internal_code` y
`pms_external_id` — el dato está, faltaba quién lo lee.

Las tres vías de resolución quedan así: por `id` en la API, por `internal_code` en el
CSV y por `pms_external_id` en la sincronización con el PMS. Las tres son
tenant-scoped y devuelven `None` fuera del tenant, que es lo que hace que R1.4 dé
`404` por D6 y que R3.4 pueda contar la fila como error sin abortar.

Rejected: leer `properties` desde el repositorio de reservas — un repositorio por
agregado raíz es regla de `steering/backend-architecture.md`. Rejected: pasar el
`property_id` sin comprobarlo y dejar que la FK falle — daría un `500`/`409` opaco
donde R1.4 pide `404`, y en la ingesta abortaría el lote en vez de informar la fila.
Rejected: resolver por `internal_code` también en la API — el identificador público de
un recurso en PRD §23 es su UUID.

### D17 — Las lecturas de `GuestRepository` devuelven una proyección sin documento

**Chosen:** `get`/`find_by_email` devuelven `GuestSummary` (frozen dataclass en
`backend/app/guests/domain/value_objects.py`) con `id`, `full_name`, `email`, `phone`,
`preferred_language`, `document_status` y `legal_registration_status` — y **nada** de
`document_number_encrypted`, `document_expiry_date`, `date_of_birth` ni `nationality`.
`add` sigue tomando la entidad `Guest` completa, porque las vías de ingesta crean
huéspedes sin datos de documento.

Lo levantó el panel de seguridad de la sección 1: el puerto afirmaba que dejar los
documentos fuera de su superficie los hacía inalcanzables, pero devolvía la entidad
entera, así que un `model_validate(guest)` en cualquier serializador futuro habría
filtrado el ciphertext. Con la proyección, R1.8 ("sin exponer ningún dato de documento") y
la regla 4 de `steering/security.md` ("número de documento jamás en listados, solo
`document_status`") pasan a ser estructurales en vez de depender de que cada autor de un
response model se acuerde.

Rejected: devolver la entidad y confiar en el schema de salida — deja la garantía en
manos de cada serializador nuevo. Rejected: enmascarar el número en la entidad — sigue
llevando el dato a una capa que no lo necesita.

### D18 — El tenant de las **referencias** de un evento de timeline lo garantiza quien llama

**Chosen:** `TimelineEventRepository.add(tenant_id, event)` comprueba el `tenant_id` del
propio evento, y documenta como **precondición** que `property_id`, `reservation_id`,
`actor_user_id` y `guest_id` ya se hayan resuelto dentro de ese tenant. Las FKs de `timeline_events`
son globales (no compuestas con `tenant_id`), así que la base de datos aceptaría un evento
del tenant A anclado a una propiedad del tenant B, y el adaptador no puede detectarlo sin
una query propia.

En este change la precondición se cumple estructuralmente en todas las vías: la propiedad
sale siempre de `PropertyRepository.get/find_by_internal_code/find_by_pms_external_id`
(D16, todas tenant-scoped) y la reserva de `ReservationRepository`, y el CSV referencia la
propiedad por `internal_code`, nunca por UUID (D11).

**`guest_id` es la excepción y necesita comprobación activa**, no argumento estructural: es
un UUID que el cliente envía en el cuerpo de `POST` y de `PATCH`, y la FK
`reservations.guest_id → guests.id` es global. Por eso los casos de uso de creación y
actualización lo resuelven con `GuestRepository.get(tenant_id, guest_id)` y responden `404`
(`GuestNotFoundError`) si no resuelve dentro del tenant — indistinguible de "no existe",
igual que R5.1 exige para la reserva. Lo señaló el panel de seguridad de la sección 2 al
ver que la lista original de esta precondición no lo incluía.

**Deuda registrada**: la FK compuesta `(tenant_id, property_id)` que convertiría esto en
imposible en lugar de solo incorrecto exige migración y toca tablas de
`domain-foundation-core`/`-ops`; pertenece a un change de esquema, no a este. Lo levantó
el panel de seguridad de la sección 1 (severidad baja).

Rejected: validar con una query por evento — un viaje extra a la base de datos en cada
mutación para cubrir un caso que hoy ningún camino puede producir. Rejected: no
documentarlo — sería exactamente el hueco silencioso que el panel señaló.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Reservas — dominio | `backend/app/reservations/domain/repositories.py` (nuevo), `exceptions.py` (nuevo), `entities.py` | Puerto `ReservationRepository`; excepciones de dominio; métodos de mutación en la entidad (`update_details`, `cancel`) que protegen las invariantes en vez de setters sueltos |
| Reservas — aplicación | `backend/app/reservations/application/use_cases.py` (nuevo) | `ListReservationsUseCase`, `GetReservationUseCase`, `CreateReservationUseCase`, `UpdateReservationUseCase`, `CancelReservationUseCase` |
| Reservas — infraestructura | `backend/app/reservations/infrastructure/repositories.py` (nuevo) | `SqlAlchemyReservationRepository` (traduce modelo ↔ entidad, `tenant_id` explícito) |
| Reservas — API | `backend/app/reservations/api/{router,schemas,dependencies}.py` (nuevos) | Los cinco endpoints de PRD §23 con `require(...)`, paginación y envelope |
| Timeline | `backend/app/timeline/domain/repositories.py` (nuevo), `backend/app/timeline/infrastructure/repositories.py` (nuevo) | Puerto `TimelineEventRepository` + adaptador SQLAlchemy (primera persistencia de eventos) |
| Huéspedes | `backend/app/guests/domain/repositories.py` (nuevo), `backend/app/guests/infrastructure/repositories.py` (nuevo) | Puerto `GuestRepository` (lectura por `id` para R1.8 y búsqueda por email normalizado para D8) + adaptador |
| Propiedades | `backend/app/properties/domain/repositories.py` (nuevo), `backend/app/properties/infrastructure/repositories.py` (nuevo) | Puerto `PropertyRepository` y adaptador: resolución tenant-scoped por `id`, `internal_code` y `pms_external_id` (D16, R1.4/R3.4/R4) |
| Integraciones | `backend/app/integrations/**` (módulo nuevo: `domain/{ports,dtos}.py`, `application/{ingest,use_cases}.py`, `infrastructure/{mock_pms,csv_parser}.py`, `api/{router,schemas,dependencies,errors}.py`, `cli/pms_sync.py`) | Puertos `PMSAdapter` y `ReservationCsvParser`, `ReservationDTO`, `MockPMSAdapter` (`EXTERNAL_DEPENDENCY`), `ReservationIngestor` (la **única** ruta de upsert, compartida por el sync y el CSV), parser CSV, endpoint de importación y comando de sync |
| Core | `backend/app/core/{unit_of_work,tenancy,http_limits}.py` (nuevos), `backend/app/core/config.py`, `backend/app/main.py` | `UnitOfWork` compartido; `CrossTenantWriteError` único; `MaxBodySizeMiddleware`; dos settings de límites del CSV; montaje de los dos routers nuevos y sus handlers de error |
| Auth | `backend/app/auth/domain/policy.py` | Dos permisos nuevos y su matriz de roles |
| Tests | `backend/tests/reservations/**`, `backend/tests/integrations/**`, `backend/tests/timeline/**` (nuevos) | Dominio puro, casos de uso con fakes, integración contra Postgres, matriz RBAC × rol y aislamiento cross-tenant |
| Documentación | `.env.example`, `README.md`, `docs/reservations.md` (nuevo) | Las dos variables nuevas y la capability, según `steering/documentation.md` |

## Data & interfaces

**Esquema**: sin migración. `reservations`, `guests` y `timeline_events` ya existen
en `4a5faad7796b` y `a1a72da30f8e`; este change solo escribe en ellas. Si al
implementar apareciera cualquier necesidad de DDL, es señal de que algo se salió del
alcance.

**API** (todas bajo `/api/v1`, Bearer JWT, envelope de error de PRD §23):

```
GET    /reservations?page&per_page&property_id&status&date_from&date_to  → 200 {data,total,page,per_page,total_pages}
POST   /reservations                                                     → 201 | 422 | 404 (propiedad)
GET    /reservations/{id}                                                → 200 | 404
PATCH  /reservations/{id}                                                → 200 | 422 | 404
DELETE /reservations/{id}                                                → 204 (idempotente)
POST   /integrations/pms/import-csv   (multipart/form-data)              → 200 {created,updated,skipped,errors[]} | 413 | 422
```

**Puertos nuevos** (todos `Protocol` en `domain/`). `tenant_id` es parámetro de **todos**
los métodos, escrituras incluidas, siguiendo `app/auth/domain/ports.py`: así una instancia
de repositorio no puede discrepar de su llamante sobre cuál es el tenant actuante — lo
levantó el panel de seguridad de la sección 1, que encontró dos fuentes de verdad del
tenant en la misma clase.

```python
class ReservationRepository(Protocol):
    async def get(self, tenant_id: UUID, reservation_id: UUID) -> Reservation | None: ...
    async def find_by_external_pms_id(self, tenant_id: UUID, external_pms_id: str) -> Reservation | None: ...
    async def list(self, tenant_id: UUID, filters: ReservationFilters, *, page: int, per_page: int) -> Page: ...
    async def add(self, tenant_id: UUID, reservation: Reservation) -> None: ...  # DuplicateExternalReservationError
    async def save(self, tenant_id: UUID, reservation: Reservation) -> None: ...

class TimelineEventRepository(Protocol):
    async def add(self, tenant_id: UUID, event: TimelineEvent) -> None: ...      # precondición: D18

class GuestRepository(Protocol):
    async def get(self, tenant_id: UUID, guest_id: UUID) -> GuestSummary | None: ...       # R1.8, D17
    async def find_by_email(self, tenant_id: UUID, email: str) -> GuestSummary | None: ... # D8, D17
    async def add(self, tenant_id: UUID, guest: Guest) -> None: ...

class PropertyRepository(Protocol):                                                 # D16
    async def get(self, tenant_id: UUID, property_id: UUID) -> Property | None: ...
    async def find_by_internal_code(self, tenant_id: UUID, internal_code: str) -> Property | None: ...
    async def find_by_pms_external_id(self, tenant_id: UUID, pms_external_id: str) -> Property | None: ...
    # ↑ AmbiguousPropertyExternalIdError (error de dominio) si dos propiedades comparten el id externo

class PMSAdapter(Protocol):
    async def list_reservations(self, since: datetime, property_external_id: str | None = None) -> list[ReservationDTO]: ...
    async def get_reservation(self, external_id: str) -> ReservationDTO | None: ...
```

`Page` (`items`, `total`) y `ReservationFilters` son value objects del dominio de reservas;
`GuestSummary` lo es del de huéspedes (D17). Los tres viven en `domain/`, de modo que
`application/` los maneja sin tocar infraestructura.

**`CrossTenantWriteError`** vive en `backend/app/core/tenancy.py`, por el mismo criterio
que D3 aplica al `UnitOfWork`: no tiene un dominio dueño, y una clase por módulo —que es
como empezó— hace que un `except` escrito contra la de `guests` no capture la de
`reservations`. Es un `RuntimeError`, no un `AppError`: llegar ahí significa que un caso de
uso confundió dos tenants, o sea un error de programación que debe salir como 500 y
arreglarse, nunca manejarse.

**Config nueva** (`.env.example` + `core/config.py`): `CSV_IMPORT_MAX_BYTES`
(default `10485760`) y `CSV_IMPORT_MAX_ROWS` (default `1000`). Ninguna es un secreto.

**Eventos de timeline emitidos**: `RESERVATION_CREATED_MANUAL`,
`RESERVATION_UPDATED`, `RESERVATION_CANCELLED`, `RESERVATION_IMPORTED` — los cuatro
ya existen en `TimelineEventType`.

## Risks & mitigations

- **El puerto `PMSAdapter` se define con dos métodos de los ocho de PRD §16.**
  Riesgo de que el adapter real no encaje. Mitigación: los dos métodos se copian
  literalmente de la firma del PRD (nombres y DTO incluidos) y los demás llegan con
  el módulo que los consuma — Interface Segregation, regla explícita de
  `steering/backend-architecture.md`.
- **`MockPMSAdapter` demasiado amable.** Si el mock nunca falla, el contrato queda
  sin probar (regla L de SOLID en el steering). Mitigación: el mock puede devolver
  filas con propiedad inexistente y fechas inválidas, y hay test de que la
  sincronización las reporta como error sin abortar (R3.4).
- **Importación CSV como vector de carga.** La primera versión ponía la cota de bytes *dentro*
  del endpoint, y el panel de seguridad **midió** que eso llega tarde: FastAPI parsea el
  `multipart` antes de resolver dependencias, así que una petición **sin token** ya había dejado
  60 MiB en el disco del contenedor antes del 401. Mitigación real: `MaxBodySizeMiddleware`
  (`app/core/http_limits.py`), que rechaza por `Content-Length` antes de leer nada y además
  cuenta el cuerpo mientras llega; la cota de filas y la de longitud por columna viven en el
  parser, de modo que una celda hostil es una fila reportada y no un 500 que se lleva el
  fichero entero (regla 6 de `steering/security.md`).
- **Primera escritura de `timeline_events`.** Si el evento falla, la reserva no debe
  quedar escrita. Mitigación: D4 (una transacción, un commit) más test explícito que
  fuerza el fallo del repositorio de timeline y comprueba que la reserva no existe.
- **`AuditLog` ausente** (D14): deuda con dueño y con acción concreta anotada; el
  `TimelineEvent` cubre la trazabilidad operativa mientras tanto.
- **La API sigue sin salida a internet** — se verifica con tests y túnel SSH; es
  `api-ingress-routing` quien lo cambia. No afecta a este alcance.

## Open questions

Ninguna. Las dos que este change podría haber dejado abiertas se resolvieron con
fuentes ya aprobadas y quedan registradas como decisiones: el alcance del
`webhook handling` (proposal, *Out of scope* — entidad `WebhookEvent` propiedad de
`domain-foundation-financial` y job de `celery-jobs`) y la ausencia de `AuditLog`
(D14 — convención que el roadmap ya fijó para `user-management`). Ambas dejan deuda
con dueño identificado, no una decisión pendiente de nadie.
