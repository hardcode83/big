# Proposal: properties-crud

## Why

`properties` no tiene **ninguna vía de escritura**. No hay router (`backend/app/properties/` es el único módulo de dominio sin paquete `api/`), no hay permiso en `app/auth/domain/policy.py:13-43`, y el repositorio no sabe insertar: `SqlAlchemyPropertyRepository.save()` (`app/properties/infrastructure/repositories.py:109-120`) persiste **una sola columna**, `current_operational_state`, y su propio docstring veta ensancharlo (`app/properties/domain/repositories.py:83-93`). Medido: `PropertyModel(...)` se instancia en 20 sitios y **los 20 son tests**; cero en `app/`, en `alembic/versions/`, en `scripts/` y en targets del `Makefile`.

La consecuencia es que el recorrido básico del producto está roto en su tercer paso. `POST /api/v1/reservations` está implementado y probado, y hoy devuelve **404 en todas las peticiones** (`PropertyNotFoundError`, `app/reservations/application/use_cases.py:177`), lo que deja el criterio `reservations.md:42-43` permanentemente insatisfacible. El import CSV resuelve la propiedad por `internal_code` (`app/integrations/application/use_cases.py:369-372`) y `pms_sync` por `pms_external_id`: las tres vías de entrada de reservas están muertas a la vez. Y `AdvancePropertyStatesUseCase`, que el beat de Celery invoca cada ciclo (`app/scheduler/tasks.py:86-113`), avanza estados sobre una tabla vacía.

**El PRD no está en silencio: el roadmap se dejó una capability que el PRD especifica.** `docs/AutoHostAI_PRD_v5_Claude.md:1938-1943` (§23) lista `GET`, `POST /api/v1/properties`, `GET` y `PATCH /api/v1/properties/{id}`. Lo que falta es el paso en §26 (orden de desarrollo), que da por hecho que las filas llegan con el seed de §27 — es decir, el plan deja el recorrido básico detrás del endurecimiento de release. No inventamos superficie: cerramos un hueco de planificación.

Esta entrada nace del análisis registrado en `sdd/roadmap.md`, y `application/`+`api/`+puertos estaban **pre-autorizados** para este momento: `domain-foundation-core.md:12` y `:14` los difieren «al change que primero necesite persistirlas», y `steering/backend-architecture.md:140` lo repite. No se revoca ningún principio.

## What changes

Tras este change, `properties` tendrá capa `api/` con los cuatro endpoints de PRD §23, un puerto de repositorio con inserción y actualización reales, dos permisos nuevos en el catálogo de `policy.py` con su reparto por rol, rastro de `AuditLog` para el alta y la modificación, y tests de aislamiento por tenant propios. La contraseña de wifi deja de poder acabar en claro en una columna cuyo nombre promete lo contrario. `current_operational_state` sigue siendo intocable desde la API. Con ello, `POST /api/v1/reservations`, el import CSV y `pms_sync` pasan a ser alcanzables por primera vez.

## Requirements

### R1 — Lectura de propiedades

**Como** manager o propietaria, **quiero** listar y consultar las propiedades de mi tenant, **para** poder operarlas y referenciarlas al crear reservas.

Criterios de aceptación:

1. WHEN se solicita `GET /api/v1/properties`, THE SYSTEM SHALL devolver únicamente las propiedades del tenant del token, paginadas con `page`/`per_page` y el envelope `{data, total, page, per_page, total_pages}` de PRD §23.
2. THE SYSTEM SHALL acotar `per_page` a 100 y `page` a 100.000, respondiendo `422` fuera de esos rangos, por el mismo motivo que `user-management.md:58-60`: `page` se convierte en un `OFFSET` de SQL y un valor sin cota produce un error de driver en vez de una respuesta del envelope.
3. THE SYSTEM SHALL ordenar el listado por `name` ascendente con el `id` como segundo criterio, de modo que paginar no muestre una fila dos veces ni omita otra.
4. WHEN el listado recibe un filtro por `status` o por `current_operational_state`, THE SYSTEM SHALL aplicarlo con AND.
5. WHEN se solicita `GET /api/v1/properties/{id}` con un `id` del tenant del token, THE SYSTEM SHALL devolver la propiedad completa salvo los campos que R5 excluye.
6. WHEN un usuario referencia por `id` una propiedad que **existe** pero pertenece a otro tenant, THE SYSTEM SHALL responder `404` y no `403`, con un cuerpo indistinguible del de un `id` inventado.
7. THE SYSTEM SHALL decidir la autorización **antes** de consultar el recurso, de modo que un rol sin permiso reciba la misma respuesta para un `id` real y para uno inventado.

### R2 — Alta de una propiedad

**Como** manager, **quiero** crear una propiedad desde la API, **para** no depender de SQL a mano ni de un deploy con seed.

Criterios de aceptación:

1. WHEN se envía `POST /api/v1/properties` con un cuerpo válido, THE SYSTEM SHALL crear la propiedad en el tenant del token y responder `201` con el recurso creado.
2. THE SYSTEM SHALL derivar el `tenant_id` del token y no SHALL aceptarlo en el cuerpo, la query ni la ruta; los esquemas de petición usan `extra="forbid"`, así que un `tenant_id` inyectado se rechaza con `422` (`auth-tenancy.md:272-273`).
3. THE SYSTEM SHALL exigir `name` e `internal_code`, y SHALL aceptar como opcionales el resto de campos que PRD §7.4 declara nullable o con defecto, tomando como mínimo demostrable el juego de PRD §27 (`name`, `internal_code`, `address_line1`, `city`, `province`, `max_guests`, `bedrooms`, `bathrooms`, `default_check_in_time`, `default_check_out_time`).
4. THE SYSTEM SHALL acotar la longitud de cada campo de texto al ancho de su columna, y **declarar una cota explícita para las cuatro columnas sin longitud** (`access_notes`, `cleaning_notes`, `emergency_notes` y `wifi_password_encrypted` son `sa.String()` sin límite, migración `4a5faad7796b:99-102`), porque ahí no hay ancho de base de datos del que heredarla.
5. IF el `internal_code` ya existe en el tenant, THEN THE SYSTEM SHALL responder `409` con código `CONFLICT`, apoyándose en la violación del índice `uq_properties_tenant_id_internal_code` traducida **por nombre de constraint** y no en una comprobación previa: dos altas simultáneas pasarían las dos la comprobación y una acabaría en `500` (mismo razonamiento que `user-management.md:46-49`).
6. THE SYSTEM SHALL re-lanzar cualquier otro `IntegrityError`, porque un `409` por una violación distinta sería una mentira que el cliente no puede accionar.
7. IF el cuerpo declara un `pms_external_id` que otra propiedad del tenant ya usa, THEN THE SYSTEM SHALL rechazarlo, porque `reservations.md:128-130` exige que el sync **falle** ante esa ambigüedad en vez de adjudicar la reserva a una vivienda cualquiera, y esta vía de escritura es la que puede crearla. La columna **no** tiene constraint de unicidad, solo índice (`app/properties/domain/repositories.py:41-49`), así que el mecanismo —índice único nuevo en migración frente a comprobación en aplicación— se decide en `design.md` sabiendo que la segunda es susceptible a carrera.
8. THE SYSTEM SHALL respetar los defectos de DDL existentes en vez de re-declararlos en Python, conforme a `domain-foundation-core.md:29`.

### R3 — Modificación y desactivación

**Como** manager, **quiero** corregir los datos de una propiedad y poder retirarla de la operación, **para** mantener el inventario al día sin borrar historial.

Criterios de aceptación:

1. WHEN se envía `PATCH /api/v1/properties/{id}`, THE SYSTEM SHALL aplicar únicamente los campos presentes en el cuerpo y devolver el recurso actualizado.
2. THE SYSTEM SHALL rechazar en `PATCH` los campos de identidad (`id`, `tenant_id`, `created_at`) y `current_operational_state` (ver R4).
3. WHEN un `PATCH` no cambia nada —cuerpo vacío o campos con el valor que ya tenían— THE SYSTEM SHALL no escribir ni fila ni `AuditLog`: `audit_logs` es evidencia de cambios, no de peticiones (`user-management.md:119-121`).
4. THE SYSTEM SHALL modelar la retirada de una propiedad como `status = INACTIVE` vía `PATCH`, y no SHALL exponer ningún `DELETE`. El PRD §23 no lista `DELETE` para propiedades, `domain-foundation-core.md:30` establece que «el PRD modela el borrado vía `status`, nunca `DELETE` real», y el borrado físico es además imposible: `property_state_transitions.property_id` es FK con `ondelete="RESTRICT"` (`models.py:90-92`), y lo mismo hacen `cleaning_tasks`, `incidents` y `access_records` (`domain-foundation-ops.md:31,46`).
5. IF una propiedad `INACTIVE` se referencia al crear una reserva, THEN THE SYSTEM SHALL decidir en `design.md` si se rechaza, dejándolo escrito: hoy ningún criterio lo cubre y el comportamiento por omisión sería aceptarla.

### R4 — La frontera de `PropertyStateMachine` no se cruza

**Como** responsable del sistema, **quiero** que ninguna vía de la API pueda cambiar el estado operacional, **para** que la máquina de estados siga siendo la única autoridad y toda transición deje su rastro.

Criterios de aceptación:

1. THE SYSTEM SHALL rechazar `current_operational_state` en el cuerpo de `POST` y de `PATCH`, dejando que la columna tome su defecto de DDL (`VACANT_READY`) en el alta.
2. THE SYSTEM SHALL NOT añadir al puerto de repositorio ningún método que escriba `current_operational_state`, ni ensanchar `save()` para que persista «lo que la entidad lleve»: `celery-jobs.md:66-68` prohíbe escribir esa columna «por ninguna otra vía» que la máquina, `steering/backend.md:24` lo repite, `security.md:35` exige que todo escritor persista su fila de `property_state_transitions` en la misma transacción, y el propio docstring del puerto lo veta.
3. THE SYSTEM SHALL añadir la inserción como un método propio y estrecho (`add`), siguiendo el patrón que `set_pms_provider` estableció — «dos métodos nombrados que escriben una columna cada uno mantienen la regla intacta; uno que escribe lo que sea no» (`app/properties/domain/repositories.py:95-110`).
4. THE SYSTEM SHALL incluir un test que demuestre que crear una propiedad **no** escribe ninguna fila en `property_state_transitions` ni ningún `TimelineEvent`: crear no es transitar, no existe tipo `PROPERTY_CREATED` en `app/timeline/domain/enums.py:17-62`, y PRD §3.1:101 ata el evento a la *transición*.

### R5 — Secretos que no pueden viajar por la API

**Como** responsable de seguridad, **quiero** que abrir esta capa `api/` no cree la superficie de fuga que su ausencia venía previniendo, **para** que ninguna credencial ni contraseña salga en una respuesta ni se persista en claro.

Criterios de aceptación:

1. THE SYSTEM SHALL NOT serializar en ninguna respuesta de esta capacidad las credenciales de PMS, ni enmascaradas, y SHALL mantener `pms_credentials` como superficie exclusiva de CLI. La regla 3(a) de `steering/security.md` lo exige, y `app/integrations/cli/pms_credentials.py:1-8` justificaba el comando precisamente en que «`properties/` deliberadamente no tiene capa `api/`»: al crearla, esa protección pasa de estructural a obligación explícita del router.
2. THE SYSTEM SHALL NOT persistir una contraseña de wifi en texto plano. La regla 3 de `steering/security.md:15` nombra `wifi_password` **primero** en su enumeración y dice «Nunca en texto plano», y la exención vigente de `domain-foundation-core.md:31` se justifica **únicamente** en que «nada las lee ni las escribe todavía» — este change sería su primer escritor, lo que retira esa justificación.
3. THE SYSTEM SHALL resolver esa obligación por una de dos vías, decidida en `design.md`: cifrar el valor con la primitiva Fernet que ya existe y es real (`app/core/crypto.py`), siguiendo el patrón `EncryptedSecret` de `pms-provider-resolution.md:59-67` (sin atributo del que leer texto plano, y descifrado en **una** llamada explícita, nunca como efecto colateral de un `SELECT`); o dejar `wifi_password` fuera del payload en este change y registrar por qué. **Enmascararla no es una salida**: `security.md:84-86` es explícito en que la regla 4 no concede forma enmascarada al wifi.
4. WHERE se opte por cifrar, THE SYSTEM SHALL migrar la columna y SHALL NOT devolver el valor en ninguna respuesta de lectura.
5. THE SYSTEM SHALL tratar `access_notes`, `cleaning_notes` y `emergency_notes` como texto libre en el rastro de auditoría (ver R7.4), porque son el análogo en este dominio de los campos que `reservations.md:239-246` señala.

### R6 — Autorización por rol

**Como** responsable del sistema, **quiero** que cada endpoint declare su permiso y que el reparto por rol sea explícito, **para** que la superficie nueva no quede sin RBAC.

Criterios de aceptación:

1. THE SYSTEM SHALL añadir a `app/auth/domain/policy.py` los permisos que estos endpoints declaran —previsiblemente `READ_PROPERTIES` y `MANAGE_PROPERTIES`— sin permisos especulativos, conforme a `auth-tenancy.md:141-148`.
2. THE SYSTEM SHALL declarar el permiso exigido en cada ruta mediante la dependencia `require(permission)`.
3. WHEN un usuario autenticado invoca un endpoint cuyo permiso su rol no tiene, THE SYSTEM SHALL responder `403` con `{"error": {"code": "FORBIDDEN", ...}}`.
4. WHERE el rol es `PROPERTY_MANAGER`, THE SYSTEM SHALL permitir lectura y mutación, porque PRD §6:314 le da «acceder a todos los datos operativos».
5. WHERE el rol es `TENANT_OWNER`, THE SYSTEM SHALL permitir la lectura, porque PRD §6:297 le da «ver sus propiedades y reservas»; **si además se le permite mutar, la razón se argumenta en `design.md`**, porque PRD §6 no nombra ninguna capacidad de crear o editar propiedades para ningún rol y por tanto el reparto no se puede citar, hay que justificarlo.
6. WHERE el rol es `CLEANER`, `TECHNICIAN` o `SUPER_ADMIN`, THE SYSTEM SHALL denegar con `403` los cuatro endpoints, por el mismo razonamiento con el que lo hacen `reservations` y `user-management`.
7. THE SYSTEM SHALL hacer crecer en el diff el snapshot de rutas protegidas de `backend/tests/test_route_authorization.py:256-278`, que es un snapshot a propósito para que toda ruta nueva aparezca.
8. THE SYSTEM SHALL demostrar con tests, por endpoint y para cada uno de los cinco roles, el código concreto esperado — no `!= 403`, que pasaría igual si un rol permitido devolviera `500`.

### R7 — Rastro de auditoría y aislamiento por tenant

**Como** responsable de seguridad, **quiero** que cada escritura quede auditada y probada como aislada, **para** cumplir las reglas 1 y 9 sobre una tabla que hasta ahora nadie escribía.

Criterios de aceptación:

1. THE SYSTEM SHALL filtrar `tenant_id` explícitamente en cada consulta y comprobarlo en cada escritura, **porque el filtro global de sesión no cubre los `INSERT`** (`auth-tenancy.md:174-182`, `user-management.md:227-228`).
2. WHEN se crea o modifica una propiedad, THE SYSTEM SHALL registrar un `AuditLog` con acciones nuevas y nombradas, añadiendo `ENTITY_PROPERTY` y sus acciones a `ENTITY_TYPES`/`ACTIONS` y sus campos auditables a `AUDITABLE_FIELDS` (`app/audit/domain/actions.py:16-48`). La regla 9 lista «estados de propiedad» y no el alta, así que esto se acoge al precedente de `user-management.md:174-178`, que auditó `TenantConfig` sin que la regla lo nombrara.
3. THE SYSTEM SHALL construir todo diff a través de un `ChangeSet` **ligado al `entity_type`** de la propiedad, que solo admite sus campos declarados como auditables.
4. THE SYSTEM SHALL registrar los campos de texto libre y todo valor de la regla 3 solo como que cambiaron (`{"changed": true}`), sin que el valor sobreviva ni enmascarado (regla 11 de `steering/security.md`).
5. WHILE se escribe una mutación, THE SYSTEM SHALL persistir el cambio y su `AuditLog` en una única transacción, construyendo el `AuditLog` **después** del `flush` en el alta, de modo que un `409` no deje rastro de una creación que no ocurrió.
6. THE SYSTEM SHALL incluir tests que, para cada uno de los cinco roles, demuestren que un usuario del tenant A no lee ni modifica propiedades del tenant B a través de esta superficie (regla 1, obligatoria en cada módulo nuevo).
7. THE SYSTEM SHALL incluir un test de integración contra Postgres real que viole `uq_properties_tenant_id_internal_code` de verdad, no solo el camino feliz (`domain-foundation-core.md:44`).
8. THE SYSTEM SHALL regenerar `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts`, y SHALL hacer crecer los contadores de la guarda de modelos de respuesta de `api-contract.md:97-99`, porque una guarda que reporta éxito sobre una lista vacía es peor que no tenerla. Sin ambas regeneraciones, los workflows `api-contract` y `frontend-api-contract` salen en rojo.
9. THE SYSTEM SHALL registrar los códigos de error del nuevo router en `app/core/error_codes.py` como octavo sitio emisor, sin inventar códigos fuera de los once existentes (`api-contract.md:48-62`).

## Out of scope

- **`GET /api/v1/properties/{id}/state` y `GET /api/v1/properties/{id}/dashboard`** (PRD §23:1942-1943) — el agregado es de `dashboard-web` (PRD §26.15); el de estado se decide allí para no fijar su forma desde aquí.
- **`DELETE /api/v1/properties/{id}`** — no está en PRD §23 y el borrado físico es imposible por las FK `RESTRICT`. La retirada se modela con `status` (R3.4).
- **El seed de PRD §27** — es `seed-data-demo`, que declara `needs: properties-crud` precisamente para no convertirse en un segundo escritor de `properties`.
- **Cifrar `guests.document_number_encrypted`** — misma exención de `domain-foundation-core.md:31` pero otra entidad y otro dominio; llega con quien le dé un escritor.
- **UI de propiedades** — PRD §24:2041-2042 lista `/properties` y `/properties/[id]` sin página de creación ni formulario; el frontend es de `dashboard-web` y `field-apps`.
- **Ensanchar `save()` o tocar `PropertyStateMachine`** — R4 lo prohíbe explícitamente.
- **Endpoints de credenciales de PMS** — `pms_credentials` sigue siendo solo de CLI (R5.1).
- **Métodos de mutación en la entidad `Property`** — hoy es un `@dataclass` sin métodos (`app/properties/domain/entities.py:13-41`). Si el `PATCH` debe pasar por métodos que sostengan invariantes, como exige `user-management.md:87-91` para `User`, es decisión de `design.md` conforme al criterio de `steering/backend-architecture.md:133-136`: la ceremonia se justifica por la invariante que protege, no por el dominio en que vive.

## Affected specs

- `sdd/specs/properties-crud.md` — *(no existe aún — se creará al archivar)*
- `sdd/specs/domain-foundation-core.md` — sus `:12` y `:14` dejan de diferir `application/`/`api/`/puertos para `Property`, y la exención de `wifi_password_encrypted` de `:31` cambia de estado al aparecer su primer escritor.
- `sdd/specs/reservations.md` — su criterio `:42-43` pasa de insatisfacible a satisfacible; conviene registrar que las tres vías de entrada quedan alcanzables.
- `sdd/specs/api-contract.md` — nuevo `_MAPPING`, contadores de rutas y de operaciones con seguridad, contrato regenerado.
- `sdd/specs/auth-tenancy.md` — el catálogo de permisos de `:141-148` crece con los de propiedades.
- `sdd/specs/frontend-api-contract-consumer.md` — tipos generados regenerados.
- `sdd/specs/pms-provider-resolution.md` — solo si R5.3 opta por cifrar y reutiliza el patrón `EncryptedSecret`.
