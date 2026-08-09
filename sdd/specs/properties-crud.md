# Propiedades — alta, consulta y edición

## Purpose

Da al inventario de viviendas su vía de escritura por API: alta, listado paginado, detalle y
edición parcial, con los cuatro endpoints que declara PRD §23. Es el paso previo a cualquier
reserva, porque las tres vías de entrada de reservas —el alta manual, el import CSV y el sync del
PMS— resuelven primero la propiedad, y ninguna puede resolver lo que no existe.

**El módulo ya no expone sólo esos cuatro**: `dashboard-api` añadió al mismo router la lectura
ligera `GET /api/v1/properties/{id}/state` (PRD §23:1942), que vive aquí porque `properties` posee
la columna que reporta y el historial del que la data. Es lectura pura y no resuelve nada: el
estado es el que `PropertyStateMachine` escribió por última vez. Bajo el mismo prefijo `/properties`
se sirve además `GET /api/v1/properties/{id}/dashboard`, pero ese es un agregado multidominio y su
router es el de `app/dashboard/`; ambos se describen en [`dashboard-api.md`](dashboard-api.md).

El *cómo se opera* está en [`docs/properties.md`](../../docs/properties.md); aquí vive el *qué
hace*.

## Requirements

### Lectura

- WHEN se solicita `GET /api/v1/properties`, THE SYSTEM SHALL devolver únicamente las propiedades
  del tenant del token, con el envelope `{data, total, page, per_page, total_pages}` de PRD §23.
- THE SYSTEM SHALL acotar `per_page` a 100 y `page` a 100.000, respondiendo `422` fuera de rango:
  `page` se convierte en un `OFFSET` de SQL y un valor sin cota desborda `int8` y sale como error
  de driver en vez de como respuesta del envelope.
- THE SYSTEM SHALL ordenar por `name` con el `id` como segundo criterio, de modo que paginar no
  muestre una fila dos veces ni omita otra cuando dos propiedades comparten nombre.
- THE SYSTEM SHALL combinar con AND los filtros `status` y `current_operational_state`, y SHALL
  contar el total **sobre la misma sentencia filtrada**, para que `total_pages` no describa un
  conjunto distinto del que viaja en `data`.
- WHEN se solicita `GET /api/v1/properties/{id}` dentro del tenant del token, THE SYSTEM SHALL
  devolver la propiedad completa salvo lo que la sección «Secretos» excluye.

### Alta

- WHEN se envía `POST /api/v1/properties` con un cuerpo válido, THE SYSTEM SHALL crear la
  propiedad en el tenant del token y responder `201` con el recurso creado.
- THE SYSTEM SHALL derivar el `tenant_id` únicamente del token y no SHALL aceptarlo en el cuerpo,
  la query ni la ruta; los esquemas de petición usan `extra="forbid"`, así que un `tenant_id`
  inyectado se rechaza con `422` en vez de ignorarse en silencio.
- THE SYSTEM SHALL exigir `name` e `internal_code` y SHALL aceptar como opcional el resto, que
  toma los valores por defecto del esquema (`ES`, `Europe/Madrid`, 2 huéspedes, entrada 15:00,
  salida 11:00, `status` `ACTIVE`).
- THE SYSTEM SHALL declarar una cota de longitud explícita para las cuatro columnas que el DDL
  crea como `String()` sin ancho —`access_notes`, `cleaning_notes`, `emergency_notes` y
  `wifi_password_encrypted`—, porque ahí no hay ancho de base de datos del que heredarla y sin
  cota una nota de varios megabytes es una escritura válida.
- THE SYSTEM SHALL devolver la fila **releída** tras el commit y no la entidad construida en
  memoria: `created_at` y `updated_at` salen de defectos de servidor, así que solo la base de
  datos conoce sus valores.
- THE SYSTEM SHALL registrar el proveedor de PMS **solo en el alta** (ver «Proveedor de PMS»).

### Conflictos de unicidad

- IF el `internal_code` ya existe en el tenant, THEN THE SYSTEM SHALL responder `409` con código
  `CONFLICT`.
- IF el `pms_external_id` ya está reclamado **por otra propiedad del mismo proveedor dentro del
  tenant**, THEN THE SYSTEM SHALL responder `409` con código `CONFLICT`.
- THE SYSTEM SHALL apoyar ambas unicidades en índices de base de datos —
  `uq_properties_tenant_id_internal_code` y `uq_properties_tenant_id_pms_external_id`— traducidos
  **por nombre de constraint**, y no en una comprobación previa: dos altas simultáneas pasarían
  las dos la comprobación y una acabaría en `500`.
- THE SYSTEM SHALL re-lanzar cualquier otro `IntegrityError` sin traducir, porque un `409` por una
  violación distinta sería una mentira que el cliente no puede accionar.
- THE SYSTEM SHALL aplicar la misma traducción en el `PATCH`, que colisiona con las mismas dos
  constraints que un alta: renombrar un `internal_code` a uno ya tomado, o reclamar el id externo
  de una fila vecina.

**La unicidad de `pms_external_id` es por proveedor y no por tenant**, y la diferencia es
deliberada: los ids externos son únicos solo dentro de un proveedor, de modo que un tenant a medio
migrar tiene legítimamente una propiedad en Beds24 y otra en Channex con el mismo id, y el sync ya
lo maneja acotando el emparejamiento al grupo que sincroniza. El índice es **parcial** (solo filas
con `pms_external_id` no nulo) y **funcional**, con clave
`(tenant_id, coalesce(pms_provider, 'MOCK'), pms_external_id)`. El `coalesce` no es un rodeo: es lo
que los valores significan —`pms_provider` nulo es «el defecto del bootstrap», que es `MOCK`— y sin
él Postgres trataría los nulos como distintos y dos propiedades sin proveedor podrían compartir id,
que es justo la ambigüedad que el índice existe para impedir.

### Proveedor de PMS

- THE SYSTEM SHALL aceptar `pms_provider` en el alta.
- WHEN se envía `pms_provider` en un `PATCH`, THE SYSTEM SHALL responder `422`: el campo no existe
  en el esquema de actualización y `extra="forbid"` lo rechaza.
- THE SYSTEM SHALL NOT exponer ninguna vía de API que lea o escriba una credencial de proveedor,
  ni siquiera enmascarada; `python -m app.integrations.cli.pms_credentials` sigue siendo la única
  forma de almacenarla.

Mover una propiedad de proveedor no es una escritura de columna cualquiera: al agrupar el índice
por `coalesce(pms_provider, 'MOCK')`, trasladar una fila puede chocar con una hermana que comparte
legítimamente su id externo. Eso necesita su propia operación con su propio manejo de conflicto, y
ninguna capability la pide todavía, así que el proveedor se elige al crear y no se cambia por API.

### Modificación y retirada

- WHEN se envía `PATCH /api/v1/properties/{id}`, THE SYSTEM SHALL aplicar únicamente los campos
  presentes en el cuerpo y devolver el recurso actualizado.
- THE SYSTEM SHALL distinguir «no enviado» de «enviado como `null`», y SHALL responder `422` ante
  un `null` sobre una columna que no es nullable, enumerando en el mensaje las que sí se pueden
  vaciar.
- WHEN un `PATCH` no cambia nada —cuerpo vacío, o campos con el valor que ya tenían— THE SYSTEM
  SHALL no escribir ni fila ni `AuditLog`: `audit_logs` es evidencia de cambios, no de peticiones.
  La única excepción es `wifi_password` (ver «Secretos»).
- THE SYSTEM SHALL modelar la retirada como `status = INACTIVE` mediante `PATCH`, y no SHALL
  exponer ningún `DELETE`. PRD §23 no lista uno, el PRD modela el borrado vía `status`, y el
  borrado físico es imposible de todos modos: `property_state_transitions`, `cleaning_tasks`,
  `incidents` y `access_records` referencian `properties.id` con `ON DELETE RESTRICT`.

### Una propiedad retirada no admite reservas nuevas

- WHEN se crea una reserva manual sobre una propiedad con `status = INACTIVE`, THE SYSTEM SHALL
  rechazarla con `409` y código `CONFLICT`.
- WHEN el import CSV o el sync del PMS encuentran una fila cuya propiedad está retirada, THE SYSTEM
  SHALL **saltar esa fila y continuar con el resto del lote**, anotando en el informe un motivo
  propio que la distingue de «la propiedad no existe».
- THE SYSTEM SHALL aplicar la regla en las **tres** vías de entrada. Las dos de lote difieren solo
  en cómo resuelven la propiedad —por `internal_code` el CSV, por `pms_external_id` el sync— y
  ambas entregan el resultado al mismo punto del ingestor, así que la regla vive ahí una sola vez.

El `409` y no `404` en la vía manual es deliberado: a diferencia de una propiedad de otro tenant,
esta el llamante ya la ve, la lista y puede reactivarla, así que esconderla convertiría un
conflicto accionable en un «mire en otro sitio», y no hay argumento de aislamiento porque la
propiedad está dentro de su tenant.

### El estado operacional no se escribe desde aquí

- THE SYSTEM SHALL rechazar `current_operational_state` en el cuerpo del alta y de la edición: está
  ausente de ambos esquemas y de `PATCHABLE_PROPERTY_FIELDS`, así que `extra="forbid"` lo convierte
  en un `422` que nombra el campo.
- THE SYSTEM SHALL crear toda propiedad en `VACANT_READY`.
- THE SYSTEM SHALL rechazar en el puerto una entidad que llegue al alta en cualquier otro estado,
  en lugar de normalizarla en silencio, de modo que un llamante que pidió un estado se entere de
  que no se le concedió.
- THE SYSTEM SHALL rechazar en el adaptador cualquier clave de `PATCH` fuera de
  `PATCHABLE_PROPERTY_FIELDS`, en lugar de filtrarla: descartarla en silencio dejaría creer a un
  llamante que escribió `current_operational_state`.
- WHEN se crea una propiedad, THE SYSTEM SHALL no escribir ninguna fila en
  `property_state_transitions` ni ningún `TimelineEvent`: crear no es transitar, y no existe tipo
  de evento de creación de propiedad.

**Cómo se sostiene la garantía, que no es uniforme y conviene no describir como si lo fuera**:
`update_details` y `set_wifi_password` nombran exactamente lo que escriben, de modo que sus
**firmas** hacen irrepresentable un cambio de estado. `add` recibe una `Property` entera y por eso
no puede tener esa garantía —una entidad lleva un estado quiera o no el llamante—, así que se
sostiene con una **comprobación en tiempo de ejecución** que rechaza cualquier entidad que no
llegue en `VACANT_READY`, y con un `INSERT` que no lista la columna. La obligación de persistir la
fila de `property_state_transitions` junto a un cambio de estado es la **regla 9 de
`steering/security.md`**; se cita ahí y no se reformula aquí.

### Secretos

- THE SYSTEM SHALL aceptar `wifi_password` en el alta y en la edición, cifrarlo antes de que
  alcance SQL y almacenar únicamente el texto cifrado.
- THE SYSTEM SHALL NOT devolver la contraseña de wifi en ninguna respuesta, en ninguna forma,
  enmascarada incluida: `PropertyResponse` carece estructuralmente del campo y expone en su lugar
  el booleano derivado `has_wifi_password`, que distingue «no hay ninguna guardada» de «hay una y
  no puedes verla».
- THE SYSTEM SHALL mantener el secreto **fuera de la entidad de dominio**, que es lo que toda ruta
  de lectura devuelve y de lo que se construyen los esquemas de respuesta: viaja como parámetro
  tipado de los dos escritores que lo fijan, y ese tipo rechaza por construcción cualquier valor
  que no sea un token Fernet.
- WHEN se envía `wifi_password` en un `PATCH`, THE SYSTEM SHALL contarlo **siempre** como cambio y
  escribir su fila de auditoría, aunque el valor sea idéntico al almacenado.
- THE SYSTEM SHALL registrar el cambio del secreto en `audit_logs` solo como que ocurrió, nunca su
  valor.

La excepción del `PATCH` es consecuencia directa de que no exista lector: no hay con qué comparar
la contraseña enviada. Compararla exigiría una vía de descifrado en lectura, que es exactamente lo
que el módulo de criptografía existe para mantener en un único punto auditado. Que el huésped
acabe necesitando esa contraseña tampoco autoriza a exponerla: la regla 4 de `steering/security.md`
no le concede forma enmascarada.

### Rastro de auditoría

- WHEN se crea o modifica una propiedad, THE SYSTEM SHALL registrar un `AuditLog` con entidad
  `PROPERTY` y acción `PROPERTY_CREATED` o `PROPERTY_UPDATED`, en la **misma transacción** que el
  cambio, de modo que un fallo al escribir el rastro deje el cambio sin aplicar.
- THE SYSTEM SHALL construir el `AuditLog` del alta **después** del `flush` que inserta la fila, de
  modo que un `409` por duplicado no deje rastro de una creación que no ocurrió.
- THE SYSTEM SHALL construir todo diff mediante un `ChangeSet` ligado al `entity_type` de la
  propiedad, que solo admite sus campos declarados como auditables.
- THE SYSTEM SHALL registrar los tres campos de texto libre —`access_notes`, `cleaning_notes` y
  `emergency_notes`— y la contraseña de wifi únicamente como que cambiaron. Los tres primeros no
  están denegados por nombre en `ChangeSet`, así que esa disciplina vive en el caso de uso: son el
  sitio donde un operador pega un código de puerta, y `audit_logs.changes` es un sumidero de texto
  en claro bajo la regla 11 de `steering/security.md`.
- THE SYSTEM SHALL registrar `actor_user_id` del token y `actor_ip` resuelta con el mismo
  mecanismo que el resto de la API.
- THE SYSTEM SHALL NOT declarar acción de borrado: la retirada es `status = INACTIVE` y llega como
  una actualización.

### Aislamiento y autorización

- THE SYSTEM SHALL declarar el permiso exigido en cada una de las cuatro rutas, y SHALL exigir
  `READ_PROPERTIES` para leer y `MANAGE_PROPERTIES` para mutar. La quinta ruta del router,
  `GET /{id}/state`, es lectura y SHALL declarar también `READ_PROPERTIES`.
- WHERE el rol es `PROPERTY_MANAGER`, THE SYSTEM SHALL permitir lectura y mutación.
- WHERE el rol es `TENANT_OWNER`, THE SYSTEM SHALL permitir la lectura y denegar la mutación con
  `403`.
- WHERE el rol es `CLEANER`, `TECHNICIAN` o `SUPER_ADMIN`, THE SYSTEM SHALL denegar los cuatro
  endpoints con `403`.
- THE SYSTEM SHALL filtrar `tenant_id` explícitamente en cada consulta y comprobarlo en cada
  escritura, porque el filtro global de sesión **no cubre los `INSERT`**.
- IF se referencia por `id` una propiedad que existe pero pertenece a otro tenant, THEN THE SYSTEM
  SHALL responder `404` con un cuerpo **indistinguible** del de un `id` inventado.
- THE SYSTEM SHALL decidir la autorización **antes** de consultar el recurso, de modo que un rol
  sin permiso reciba la misma respuesta para un `id` real y para uno inventado.
- THE SYSTEM SHALL demostrar con tests, para cada uno de los cinco roles y con el tenant vecino
  realmente sembrado, que un usuario del tenant A no lee ni modifica propiedades del tenant B a
  través de esta superficie.

**Que la propietaria no pueda dar de alta su propia vivienda es una consecuencia asumida y no un
descuido**: PRD §6 le concede «ver sus propiedades y reservas» y nada más, y el reparto es el mismo
que ya tiene `reservations`. El bootstrap crea las dos cuentas, así que un entorno nuevo sigue
pudiendo alcanzar la API — lo hace el manager. Es el único punto donde la intuición de producto y
PRD §6 divergen, resuelto a favor del PRD.

## Key files

- `backend/app/properties/api/` — `router.py` (los cuatro endpoints de PRD §23 más
  `GET /{id}/state`, que añadió `dashboard-api`), `schemas.py` (las
  cotas, `extra="forbid"`, el rechazo de nulos explícitos y la respuesta sin secreto),
  `errors.py` (el `_MAPPING` a los códigos del envelope), `dependencies.py`.
- `backend/app/properties/application/property_admin.py` — los cuatro casos de uso, el cifrado del
  wifi, el diccionario `written` que decide a la vez qué se persiste y qué se audita, y la
  redacción de los campos de texto libre.
- `backend/app/properties/domain/repositories.py` — el puerto, `PATCHABLE_PROPERTY_FIELDS` como
  único hogar de la regla, `PropertyFilters` y `Page`.
- `backend/app/properties/infrastructure/repositories.py` — los escritores, la guarda de tenant, la
  comprobación de estado en el alta y la traducción de las constraints.
- `backend/app/properties/domain/exceptions.py` — `PropertyNotFoundError`,
  `DuplicateInternalCodeError`, `DuplicatePmsExternalIdError`, `PropertyValidationError`.
- `backend/app/reservations/application/use_cases.py` y
  `backend/app/integrations/application/ingest.py` — las dos guardas de propiedad retirada.
- `backend/alembic/versions/f2b9c7a41d38_properties_pms_external_id_unique.py` — el índice parcial
  y funcional.
- Tests: `backend/tests/properties/`.
