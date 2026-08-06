# Reservas e ingesta desde el PMS

## Purpose

Esta capacidad gestiona el ciclo de vida de una reserva —alta manual, consulta, edición y
cancelación— y la trae desde el exterior por dos vías: sincronización con el PMS a través
de un adapter sustituible e importación manual por CSV. Es la primera capacidad de negocio
con API del producto y el dato del que cuelga la operación: la máquina de estados de la
propiedad resuelve su precedencia a partir de "reserva activa" y "próxima reserva", y
limpieza, accesos, mensajería y statements se disparan desde el ciclo de una reserva.

Es además el primer módulo que **persiste** `TimelineEvent`: hasta esta capacidad
`timeline-state-machine` construía eventos validados y nadie los escribía.

No incluye recepción de webhooks (necesita `WebhookEvent`, de `domain-foundation-financial`,
y su job de `celery-jobs`), ni frontend (`dashboard-web`), ni escritura de `AuditLog` (entidad
de `domain-foundation-financial`).

Las **transiciones de estado operacional dependientes del reloj** sí existen ya: las hace
`celery-jobs`, que lee estas reservas para decidir cuándo una propiedad entra en ventana de
check-in, se ocupa o queda pendiente de limpieza (ver `specs/celery-jobs.md`). Esta capacidad
no las dispara; aporta el dato del que cuelgan.

## Requirements

### Alta manual de una reserva

- WHEN se solicita `POST /api/v1/reservations` con datos válidos, THE SYSTEM SHALL crear la
  reserva, derivar `nights` como la diferencia entre `check_out_date` y `check_in_date` y
  `total_guests` como `adults + children`, y responder `201` con el recurso creado.
- THE SYSTEM SHALL derivar `nights` y `total_guests` dentro del agregado y no SHALL
  aceptarlos del cliente; un cuerpo que los incluya se rechaza.
- IF el `channel` solicitado no es `MANUAL` ni `DIRECT`, THEN THE SYSTEM SHALL responder
  `422`: los canales de OTA llegan por la ingesta, que aporta `external_pms_id`, y una
  reserva de Airbnb escrita a mano no lo tendría y la siguiente sincronización la
  importaría otra vez.
- THE SYSTEM SHALL rechazar en el alta manual cualquier `external_pms_id`, que es la clave
  de idempotencia de la ingesta.
- IF `check_out_date` no es posterior a `check_in_date`, o `adults` es menor que 1, o
  `children` es negativo, THEN THE SYSTEM SHALL responder `422` en el envelope de PRD §23
  sin escribir nada.
- IF la `property_id` indicada no existe en el tenant del token, THEN THE SYSTEM SHALL
  responder `404`.
- IF el `guest_id` indicado no existe en el tenant del token, THEN THE SYSTEM SHALL
  responder `404`.

### Consulta y listado

- WHEN se solicita `GET /api/v1/reservations`, THE SYSTEM SHALL devolver únicamente las
  reservas del tenant del token, paginadas con `page`/`per_page` y el envelope
  `{data, total, page, per_page, total_pages}` de PRD §23.
- THE SYSTEM SHALL acotar `per_page` a 100 y `page` a 100.000, y responder `422` fuera de
  esos rangos: `page` se convierte en un `OFFSET` de SQL y un valor sin cota desborda y
  produce un error de driver en vez de una respuesta del envelope.
- WHEN el listado recibe un rango de fechas, THE SYSTEM SHALL devolver las reservas cuya
  estancia **solapa** el rango, no solo aquellas cuya entrada cae dentro de él.
- IF `date_to` es anterior a `date_from`, THEN THE SYSTEM SHALL responder `422` en lugar de
  un resultado vacío.
- THE SYSTEM SHALL ordenar el listado por `check_in_date` descendente con el `id` como
  segundo criterio, de modo que paginar no muestre una fila dos veces ni omita otra.
- WHEN se solicita `GET /api/v1/reservations/{id}` de una reserva del tenant, THE SYSTEM
  SHALL devolverla con su huésped vinculado si existe.
- THE SYSTEM SHALL exponer del huésped solo identidad de contacto y `document_status`, y
  no SHALL exponer `document_number_encrypted`, `document_expiry_date`, `date_of_birth` ni
  `nationality` por ninguna de sus respuestas.

### Edición y cancelación

- WHEN se solicita `PATCH /api/v1/reservations/{id}`, THE SYSTEM SHALL aplicar solo los
  campos presentes en el cuerpo, revalidar las invariantes de fechas y ocupación sobre el
  **resultado** y recalcular `nights` y `total_guests` cuando sus campos de origen cambien.
- THE SYSTEM SHALL rechazar en `PATCH` los campos derivados (`nights`, `total_guests`), los
  de identidad (`tenant_id`, `property_id`, `external_pms_id`) y los que pertenecen a otras
  capacidades (`access_status`, `legal_registration_status`).
- WHEN se solicita `DELETE /api/v1/reservations/{id}`, THE SYSTEM SHALL pasar la reserva a
  `CANCELLED` conservando la fila y responder `204`.
- IF la reserva ya está en `CANCELLED`, THEN THE SYSTEM SHALL responder `204` sin registrar
  un segundo evento de cancelación.
- THE SYSTEM SHALL permitir editar una reserva cancelada, registrando la edición como tal.

### Timeline: evidencia de cada mutación, en la misma transacción

- WHEN una reserva se crea por API, THE SYSTEM SHALL persistir un `TimelineEvent`
  `RESERVATION_CREATED_MANUAL` con `actor_type` `USER` y el `actor_user_id` del token.
- WHEN una reserva se modifica por API, THE SYSTEM SHALL persistir un `RESERVATION_UPDATED`
  cuyo `metadata` registre los campos cambiados.
- WHEN una edición lleva la reserva a `CANCELLED`, THE SYSTEM SHALL persistir un
  `RESERVATION_CANCELLED`, igual que la cancelación por `DELETE`: una reserva no puede
  quedar cancelada sin que exista su evento de cancelación.
- WHEN una reserva se crea por sincronización con el PMS, THE SYSTEM SHALL persistir un
  `RESERVATION_IMPORTED` con `actor_type` `SYSTEM` y sin `actor_user_id`.
- WHEN una reserva se crea por importación CSV, THE SYSTEM SHALL persistir un
  `RESERVATION_IMPORTED` con `actor_type` `USER` y el `actor_user_id` de quien subió el
  fichero.
- WHILE se escribe una mutación, THE SYSTEM SHALL persistir la reserva y su evento en una
  única transacción, de modo que un fallo al escribir el evento deje la reserva sin cambiar.
- WHEN una edición no cambia nada —cuerpo vacío o campos con el valor que ya tenían— THE
  SYSTEM SHALL no escribir ni fila ni evento.
- THE SYSTEM SHALL registrar de los campos de texto libre (`internal_notes`,
  `special_requests`) únicamente que cambiaron, no su contenido: `timeline_events` es
  inmutable por norma y un código de acceso pegado en una nota quedaría en claro para
  siempre.
- THE SYSTEM SHALL construir todo evento a través de la fábrica de dominio del timeline, y
  SHALL rechazar con un error de dominio un `metadata` con valores que la columna `JSONB`
  no pueda almacenar, nombrando las claves ofensivas.

### Sincronización con el PMS

- THE SYSTEM SHALL declarar su dependencia del PMS como un puerto `PMSAdapter` en el
  dominio, con dos implementaciones: `MockPMSAdapter` (el defecto) y `ChannexAdapter`, que
  habla con la API real de Channex staging y se documenta en
  `sdd/specs/pms-channex-staging.md`. **Qué implementación se usa lo resuelve cada propiedad**,
  a través de la `PMSAdapterFactory` de `sdd/specs/pms-provider-resolution.md`.
- THE SYSTEM SHALL devolver de `list_reservations` un `PmsFetchResult` que lleva **juntos** los
  DTOs y las filas que no se pudieron mapear. Sustituye al `unmappable_rows: list[str]` que el
  puerto exponía como atributo de clase: aquel obligaba a toda implementación a ofrecerlo, era
  estado mutable en un puerto, y `vars()` no ve una anotación desnuda, así que el test de
  conformidad no lo comprobaba. El pliegue de esas filas al informe ocurre en el caso de uso.
- THE SYSTEM SHALL mapear cada elemento del proveedor **por separado**, y WHEN uno resulta
  imposible de mapear THE SYSTEM SHALL saltarlo reportándolo y conservar los demás, en vez de
  abortar la sincronización completa. El mapeo ocurre en el adapter, antes de que ninguna fila
  alcance el `try/except` por fila del `ReservationIngestor`, así que sin esto un solo payload
  malformado perdía todas las reservas buenas de la página.
- THE SYSTEM SHALL incluir en el informe del comando, como filas saltadas con su motivo, las
  que el adapter no pudo mapear — nunca en silencio.
- THE SYSTEM SHALL resolver la propiedad de cada reserva del PMS por su `pms_external_id`
  dentro del tenant.
- IF dos propiedades del tenant comparten `pms_external_id`, THEN THE SYSTEM SHALL fallar
  con un error de dominio en lugar de elegir una: son dos viviendas distintas y adjudicar
  la reserva a cualquiera de ellas ataría al huésped a la casa equivocada.
- WHEN se sincroniza una reserva cuyo `external_pms_id` ya existe en el tenant, THE SYSTEM
  SHALL actualizar la existente y no SHALL emitir `RESERVATION_IMPORTED`.
- WHEN se sincroniza dos veces el mismo conjunto sin cambios externos, THE SYSTEM SHALL
  dejar el mismo número de reservas y no añadir eventos en la segunda pasada.
- THE SYSTEM SHALL limitar lo que una vía de ingesta puede sobrescribir a los campos que el
  proveedor posee, y no SHALL permitirle tocar `internal_notes`, `payment_status`,
  `cleaning_required`, `access_status` ni `legal_registration_status`.
- THE SYSTEM SHALL derivar `net_amount` como `gross_amount` menos `ota_commission`, porque
  el DTO de PRD §16 no lo trae.
- WHEN una reserva aporta datos de huésped, THE SYSTEM SHALL vincularla a un `Guest` del
  tenant reutilizando el que coincida por email normalizado y creándolo si no existe.
- THE SYSTEM SHALL tratar un email en blanco como ausencia de email: no coincide con nadie
  y no se almacena, de modo que dos filas sin email son dos personas y no una.
- WHEN se ejecuta el comando `python -m app.integrations.cli.pms_sync <tenant> [días]
  [--provider {mock,channex,beds24}]`, THE SYSTEM SHALL sincronizar ese tenant e imprimir el
  informe, marcando la sesión con el tenant indicado porque un comando no atraviesa la
  verificación del token.
- WHEN no se pasa `--provider`, THE SYSTEM SHALL dejar que **cada propiedad resuelva el suyo**
  (`sdd/specs/pms-provider-resolution.md`), y una propiedad que no declara ninguno cae al
  proveedor por defecto, `MOCK` — de modo que el comportamiento de la suite y del arranque local
  sigue sin depender de configuración alguna.
- WHEN se pasa `--provider`, THE SYSTEM SHALL tratarlo como **override explícito de operador**
  sobre todas las propiedades del tenant, y SHALL anunciarlo por salida estándar diciendo que
  ignora el proveedor que cada una guarda. Es un flag de diagnóstico, no el mecanismo.
- IF `--provider channex` se selecciona sin `CHANNEX_API_KEY` en el entorno, THEN THE SYSTEM
  SHALL abortar nombrando la variable ausente y no SHALL caer al mock: un fallback silencioso
  informaría «created 0» y sería indistinguible de un PMS vacío.
- IF `--provider` recibe un valor desconocido, THEN THE SYSTEM SHALL rechazarlo con el uso del
  comando y código de salida 2, **sin imprimir el valor recibido** — un valor mal puesto puede
  ser una credencial pegada por error.
- IF el proveedor no puede responder, THEN THE SYSTEM SHALL salir con código 3, distinto del 2
  de un argumento inválido: un sync que no ocurrió no es un sync vacío.
- IF el tenant indicado al comando no existe, THEN THE SYSTEM SHALL fallar con código de
  salida 2 en lugar de informar un resultado vacío indistinguible de "el PMS no tenía
  datos".

> **La elección de proveedor es un flag del comando y no configuración global a propósito.**
> PRD §22 definía un `PMS_PROVIDER` global que [ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md)
> retiró en favor de resolución **por propiedad** con credenciales cifradas. Un flag de operador
> no puede filtrarse a la aplicación ni resucitar ese nombre. La `PMSAdapterFactory` definitiva
> pertenece a `pms-beds24-adapter`.
- THE SYSTEM SHALL terminar el comando con código 0 cuando haya filas omitidas: informarlas
  es el comportamiento correcto, no un fallo de la ejecución.

### Importación manual por CSV

- WHEN se solicita `POST /api/v1/integrations/pms/import-csv` con un fichero válido, THE
  SYSTEM SHALL importar las filas válidas y responder un informe con creadas, actualizadas,
  omitidas y errores.
- THE SYSTEM SHALL nombrar la propiedad por su `internal_code` y resolverla dentro del
  tenant, de modo que un CSV no pueda referenciar la propiedad de otro tenant.
- IF una fila es inválida —por cualquier motivo, sea de parseo o de dominio— THEN THE
  SYSTEM SHALL omitirla, continuar con el resto e incluir en el informe **su número de
  línea** y el motivo, contando la cabecera como línea 1.
- THE SYSTEM SHALL ordenar los errores del informe por número de línea.
- THE SYSTEM SHALL acotar el tamaño de un registro CSV, y una fila que lo supere SHALL
  omitirse como fila —no SHALL invalidar el fichero— tanto si es una línea física larga
  como si es un campo entrecomillado repartido en varias líneas.
- IF el fichero termina dentro de un valor entrecomillado sin cerrar, THEN THE SYSTEM SHALL
  reportar esa fila y conservar las anteriores.
- THE SYSTEM SHALL acotar por columna la longitud de los valores del CSV según el ancho de
  su columna en base de datos, y rechazar valores no finitos, fuera de rango o con bytes
  NUL como fila omitida: sin esas cotas el error llega de la base de datos y aborta la
  transacción entera, perdiendo también las filas buenas.
- THE SYSTEM SHALL validar `currency` **después** de normalizarlo, exigiendo tres letras
  ASCII, porque pasar a mayúsculas puede alargar la cadena.
- IF el cuerpo de la petición supera el límite configurado de bytes, THEN THE SYSTEM SHALL
  responder `413` **antes de leer el cuerpo**, rechazando por `Content-Length` cuando se
  declara y contando los bytes recibidos cuando no.
- IF el fichero supera el límite configurado de filas, THEN THE SYSTEM SHALL responder
  `413` sin importar ninguna fila y sin construir las filas que exceden el límite.
- IF el fichero no es UTF-8, está vacío, le faltan columnas requeridas o su content-type no
  es de CSV, THEN THE SYSTEM SHALL responder `422` describiendo el problema.
- WHEN una fila trae un `external_pms_id` ya presente en el tenant, THE SYSTEM SHALL
  aplicar la misma regla de idempotencia que la sincronización.

### Aislamiento por tenant y autorización

- THE SYSTEM SHALL derivar el `tenant_id` del token en todos los endpoints y no SHALL
  aceptarlo en el cuerpo, la query ni la ruta.
- WHEN un usuario referencia por `id` una reserva, propiedad o huésped que existe pero
  pertenece a otro tenant, THE SYSTEM SHALL responder `404` y no `403`, sin revelar que el
  recurso existe.
- THE SYSTEM SHALL decidir la autorización antes de consultar el recurso, de modo que un rol
  sin permiso reciba la misma respuesta para un `id` real y para uno inventado.
- WHERE el rol es `PROPERTY_MANAGER`, THE SYSTEM SHALL permitir listar, consultar, crear,
  editar, cancelar e importar.
- WHERE el rol es `TENANT_OWNER`, THE SYSTEM SHALL permitir listar y consultar, y SHALL
  denegar con `403` crear, editar, cancelar e importar.
- WHERE el rol es `CLEANER`, `TECHNICIAN` o `SUPER_ADMIN`, THE SYSTEM SHALL denegar con
  `403` todos los endpoints de esta capacidad. `SUPER_ADMIN` queda denegado porque sus
  capacidades en PRD §6 son globales, no operativas de un tenant, y la visibilidad
  cross-tenant está diferida a `saas-cross-tenant`.
- THE SYSTEM SHALL filtrar `tenant_id` explícitamente en cada consulta y comprobarlo en
  cada escritura, porque el filtro global de sesión no cubre los INSERT.
- THE SYSTEM SHALL exigir que las referencias de un evento de timeline
  (`property_id`, `reservation_id`, `actor_user_id`, `guest_id`) se hayan resuelto dentro
  del tenant antes de escribirlo: las claves ajenas de `timeline_events` no son compuestas
  con `tenant_id` y la base de datos aceptaría un evento mal anclado.

## Estado y deuda conocida

- **Sin recepción de webhooks** (`POST /api/v1/webhooks/{provider}` de PRD §16): requiere
  `WebhookEvent` (PRD §7.26) de `domain-foundation-financial` y el job
  `process_webhook_events` de `celery-jobs`. Entrada de roadmap propia:
  `reservations-webhooks`.
- **Sin `AuditLog`** (regla 9 de `steering/security.md`): la entidad pertenece a
  `domain-foundation-financial` y su **escritor ya existe** desde `user-management`
  (`app/audit/domain/`: `ChangeSet`, `AuditLogFactory`, puerto y adaptador). Queda pendiente
  añadir la escritura a los **seis** casos de uso mutadores de aquí — los cuatro de
  `reservations` y los dos de `integrations`—, que ahora es trabajo mecánico en vez de un
  bloqueo. Ojo a dos cosas del contrato de `user-management` al hacerlo: el `ChangeSet` va
  ligado a un `entity_type` y solo admite los campos declarados de esa entidad, así que
  `reservations` tendrá que registrar los suyos; y los campos de texto libre
  (`internal_notes`, `special_requests`) se registran solo como que cambiaron, igual que ya
  hacen en el timeline. El rastro mientras tanto es el `TimelineEvent`.
- **La clave ajena `(tenant_id, property_id)` de `timeline_events` no es compuesta**, así
  que la precondición de arriba la garantiza quien llama y no el esquema. Convertirlo en
  imposible exige migración y pertenece a un change de esquema.
- ~~`app/auth/infrastructure/unit_of_work.py` y `app/core/unit_of_work.py` duplicados~~ —
  **cerrado en `user-management`**, que fue el siguiente change en tocar `auth`: la copia de
  `auth` se borró y `app/core/unit_of_work.py` es la única. El **Protocol** sigue declarado dos
  veces a propósito: `app/auth/domain/ports.py` tiene el suyo para que `auth/application/`
  importe sus puertos de su propio `domain/`, y unificarlo obligaría a esa capa a importar un
  módulo que trae `sqlalchemy` consigo.
- **La API no tiene salida a internet**: el túnel enruta solo al frontend, así que estos
  endpoints se verifican con tests y, en dev, por túnel SSH (`RUNBOOK.md` §7.4). Lo cambia
  `api-ingress-routing`.
- **Sin frontend**: llega con `dashboard-web`.

## Key files

- `backend/app/reservations/domain/` — `entities.py` (invariantes, campos actualizables y
  los que una ingesta puede poseer), `enums.py` (traducción de canal y estado),
  `repositories.py` (puerto, filtros, página), `exceptions.py`.
- `backend/app/reservations/application/use_cases.py` — los cinco casos de uso y el
  comando de creación.
- `backend/app/reservations/infrastructure/repositories.py` — adaptador SQLAlchemy.
- `backend/app/reservations/api/` — `router.py`, `schemas.py`, `dependencies.py`,
  `errors.py`.
- `backend/app/integrations/` — `domain/{ports,dtos,errors}.py` (puertos `PMSAdapter` y
  `ReservationCsvParser`, DTOs, `PmsUnavailableError`), `application/ingest.py`
  (`ReservationIngestor`, la única ruta de upsert), `application/use_cases.py`,
  `infrastructure/{mock_pms,csv_parser}.py`,
  `infrastructure/channex/{client,mapping,adapter}.py`, `api/`, `cli/pms_sync.py`.
- `backend/app/timeline/{domain,infrastructure}/repositories.py` — persistencia del
  timeline.
- `backend/app/{properties,guests}/{domain,infrastructure}/repositories.py` — resolución
  tenant-scoped de propiedad y huésped.
- `backend/app/core/{unit_of_work,tenancy,http_limits}.py` — transacción compartida, error
  único de escritura cross-tenant, cota de tamaño de cuerpo.
- `docs/reservations.md` — cómo se opera.
