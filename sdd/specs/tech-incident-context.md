# Contexto operativo de una incidencia asignada

## Purpose

Dice al técnico **a qué piso va y cómo entra**, sin concederle ninguno de los permisos que guardan
las propiedades. Es la lectura que PRD §12 exige de la app del técnico —dirección de la vivienda,
instrucciones de contacto/acceso y notas del propietario/manager: tres de las once cosas que
enumera— entregada como una **proyección de solo lectura acotada a la incidencia asignada al
llamante**.

Existe porque el rol `TECHNICIAN` tiene exactamente cinco permisos y `READ_PROPERTIES` no está entre
ellos (`backend/app/auth/domain/policy.py`): propiedades, dashboard, timeline y reservas le contestan
`403`, y `IncidentResponse` le da `property_id` como UUID pelado. La alternativa barata —concederle
`READ_PROPERTIES`— quedó descartada por lo mismo que la descartó
[`cleaner-task-context`](cleaner-task-context.md): abriría el CRUD entero de propiedades, con sus
`cleaning_notes`, sus `emergency_notes` y la fila completa, para resolver un nombre y una dirección.

Cuelga de una incidencia de [`maintenance`](maintenance.md) y reusa su acotamiento por rol sin
ampliarlo. Es la **segunda** proyección de esta forma: la primera es `cleaner-task-context`, y ésta
la calca con dos lecturas en vez de cuatro.

Trajo además dos cosas que no son la pantalla y que sobreviven a ella: la columna
`incidents.assignment_note`, que es la fuente que PRD §12 daba por supuesta para «notas del
propietario/manager» y que no existía, y la **excepción 6** de la regla 11 de
`steering/security.md`, que es la decisión de steering que `sdd/roadmap/cleaner-app.md` tenía
aparcada sobre `properties.access_notes`. El *cómo se opera* está en
[`docs/maintenance.md`](../../docs/maintenance.md).

## Requirements

### La proyección: a qué propiedad va el técnico

- WHEN se solicita `GET /api/v1/incidents/{incident_id}/context` sobre una incidencia alcanzable por
  el llamante, THE SYSTEM SHALL devolver `200` con el `property_name` y el `property_internal_code`
  de la propiedad y sus campos de dirección postal (`address_line1`, `address_line2`, `city`,
  `province`, `postal_code`, `country`).
- THE SYSTEM SHALL incluir el `timezone` de la propiedad.
- THE SYSTEM SHALL incluir el `access_notes` de la propiedad, que es lo que PRD §12 pide como
  «instrucciones de contacto/acceso». No hay columna de contacto en `properties`, así que esa línea
  del PRD la sirve esta columna y no una estructurada; inventar la columna es de otro change.
- THE SYSTEM SHALL incluir el `assignment_note` de la incidencia, que es la nota que el manager
  escribe al asignar.
- THE SYSTEM SHALL devolver **once campos y solo once**: los nueve de la propiedad más las dos
  notas. `property_name`, `property_internal_code`, `country` y `timezone` están siempre; los otros
  siete pueden ser `null`.
- IF un campo es `NULL` en origen, THEN THE SYSTEM SHALL devolverlo como `null` **con su clave**, y
  no omitirla. No hay `exclude_none` ni `response_model_exclude_none` en ninguna parte de
  `backend/app`, así que es comportamiento heredado de pydantic: lleva su propio test contra el
  cuerpo serializado en vez de darse por hecho, y los once campos son `required` en el contrato.
- THE SYSTEM SHALL entender ese `null` como «la columna no está informada», y NEVER SHALL usarlo
  para decir «no se pudo resolver el dato»: una propiedad que no resuelve es un `404`, nunca una
  respuesta parcial.
- THE SYSTEM SHALL fijar el conjunto de campos con un test propio, de modo que añadir uno sea un
  acto deliberado y no una deriva.

### Lo que la proyección nunca lleva

- THE SYSTEM SHALL construir la respuesta desde un dataclass congelado del dominio
  (`IncidentContext`, once campos, Python puro sin pydantic ni SQLAlchemy) espejado campo a campo en
  el contrato, y NEVER SHALL serializar una entidad `Property` ni `Reservation`. Es lo que convierte
  las exclusiones de abajo en **estructurales**: un campo que no está en el dataclass no tiene dónde
  aterrizar. El esquema de respuesta sí usa `from_attributes=True`, y eso no debilita nada, porque
  lo que vuelca es el dataclass cerrado y no una entidad.
- THE SYSTEM NEVER SHALL incluir `wifi_password_encrypted`, `has_wifi_password`, `wifi_name`,
  `cleaning_notes` ni `emergency_notes`.
- THE SYSTEM NEVER SHALL incluir ningún campo de reserva —importe bruto, comisión de la OTA, importe
  neto, estado de pago, canal, `guest_id`, `special_requests` ni `internal_notes`—: no se lee el
  repositorio de reservas en esta ruta. PRD §12 no pide la reserva en esta pantalla.
- THE SYSTEM NEVER SHALL incluir `reported_by_guest_token`, `reported_by_user_id` ni
  `ai_classification`, que [`maintenance`](maintenance.md) R8 ya excluye del contrato de incidencia,
  ni los identificadores que el cliente ya tiene (`id`, `property_id`, `tenant_id`,
  `assigned_technician_id`, `reservation_id`).
- **La regla para quien añada un campo: una proyección puede estrechar, nunca unir.** Un campo que
  un permiso guarda *como un todo* no entra aquí: pasa por la decisión D10 de
  [`dashboard-api`](dashboard-api.md). Esta capacidad **diverge** de «agregar no puede conceder» a
  propósito y con el mismo alcance acotado que `cleaner-task-context`: su sujeto es una incidencia
  que el llamante ya puede leer entera, y lo que añade son diez campos de una propiedad sobre un
  conjunto de filas **más estrecho** que el que `READ_PROPERTIES` daría.

### Acotamiento por fila y autorización

- THE SYSTEM SHALL exigir `READ_INCIDENTS` en la puerta, y responder `403` antes de tocar la base de
  datos cuando el llamante no lo tiene. NEVER SHALL crear un permiso nuevo: uno propio lo tendrían
  exactamente los roles que ya tienen éste y acotaría exactamente las filas que ya están acotadas.
- THE SYSTEM SHALL exigir el permiso de **lectura** y no el de ejecución: un `PROPERTY_MANAGER` y
  una `TENANT_OWNER` también leen esta pantalla.
- WHILE el llamante tiene rol `TECHNICIAN`, THE SYSTEM SHALL restringir la consulta a las
  incidencias cuyo `assigned_technician_id` sea el suyo, derivado de
  `IncidentActor.restrict_to_technician_id` —que se calcula del rol **persistido** que se relee de
  la fila del usuario en cada petición— y NEVER SHALL aceptar ni ensanchar esa restricción desde la
  petición: no existe parámetro para ella, ni de scope ni de técnico.
- WHILE el llamante tiene rol `PROPERTY_MANAGER` o `TENANT_OWNER`, THE SYSTEM SHALL devolver el
  contexto de cualquier incidencia de su tenant, sin ese acotamiento.
- IF la incidencia no existe, pertenece a otro tenant, está asignada a otro técnico, o su
  `property_id` no resuelve dentro del tenant, THEN THE SYSTEM SHALL responder `404 NOT_FOUND` con
  un cuerpo **idéntico** en los cuatro casos. Sale de `IncidentNotFoundError`, ya en la tabla de
  `maintenance/api/errors.py`: no hace falta excepción nueva ni fila nueva, y la identidad del
  cuerpo es por construcción —la misma excepción con el mismo mensaje— y no por coincidencia.
- IF el `property_id` de la incidencia no resuelve dentro del tenant, THEN THE SYSTEM SHALL además
  registrar un `logger.warning` con `tenant_id`, `incident_id` y `property_id`, y NEVER SHALL
  degradar a respuesta parcial. Es la **asimetría deliberada** con `cleaner-task-context`, que sí
  degrada cuando su reserva queda colgando: allí la reserva alimentaba uno de once campos y la
  propiedad nueve; aquí la propiedad alimenta **diez de los once**, así que sin ella no hay contexto
  que dar. Un puntero cruzado es además una anomalía que una persona debe ver.
- THE SYSTEM SHALL llevar un `tenant_id` explícito en cada una de las **dos** lecturas que compone,
  tomado únicamente del token verificado, en lugar de un `SELECT` conjunto propio, y NEVER SHALL
  aceptarlo en ningún esquema de petición. Es la regla D2 de [`dashboard-api`](dashboard-api.md) —un
  adaptador de proyección sería el segundo sitio donde se escribe el scope de tenant— y aquí la
  composición además es **más estricta** que un `JOIN`: `incidents.property_id` es una clave ajena
  simple, no compuesta con `tenant_id`, así que la base de datos acepta una incidencia del tenant A
  colgada de una propiedad del tenant B, y con composición esa fila resuelve a `None` y se convierte
  en `404`. Con un `JOIN` habría que acordarse de un segundo `WHERE`, que es la fila que el panel de
  seguridad de [`guest-portal-api`](guest-portal-api.md) tuvo que cerrar a mano.
- THE SYSTEM SHALL demostrar con tests propios el cruce de tenant, incluida la incidencia que apunta
  a la propiedad de otro tenant, y que el filtro de tenant de la primera lectura sostiene por sí
  solo: la composición lo cierra, pero eso se demuestra, no se afirma.
- THE SYSTEM NEVER SHALL exponer esta ruta al rol `CLEANER` —que no tiene `READ_INCIDENTS`, así que
  recibe `403` antes de la base de datos— ni al portador de un token de huésped, que no pasa por
  `require()` y recibe `401` igual que un llamante anónimo.
- THE SYSTEM SHALL escribir el acotamiento por fila en **un único sitio**, y ese sitio SHALL tener
  su propio test de unicidad. Ver «El acotamiento por fila vive en un solo sitio».

### El acotamiento por fila vive en un solo sitio

- THE SYSTEM SHALL resolver el par «cargar la incidencia dentro del tenant + `404` si el técnico no
  es el asignado» en una **corrutina de módulo** (`_load_incident_in_scope`) usada por sus **tres**
  llamantes: el mixin de transiciones, la lectura de detalle y esta proyección.
- THE SYSTEM SHALL mantenerla como función de módulo y no como mixin, porque uno de sus llamantes
  sostiene solo el repositorio de incidencias y no podría heredarlo.
- Esto **bajó de dos copias a una**, no de una a tres: la regla estaba escrita dos veces antes de
  este change, y añadir la proyección habría hecho la tercera. La exigencia de que el `404` sea
  idéntico en cuatro casos es lo que hace que una regla replicada sea la que divergirá. **No cierra**
  el candidato `tenant-scoping-enumeration-guard` que [`maintenance`](maintenance.md) nombra en su
  §Estado —la tercera puerta del módulo, `RespondOwnerApprovalUseCase`, sigue resolviendo por su
  cuenta—, pero es la parte que se podía cerrar cuando el diff era de tres líneas por llamante.

### La nota de la asignación

- THE SYSTEM SHALL almacenar la nota del manager en `incidents.assignment_note`, columna
  `VARCHAR(2000)` nullable, sin backfill: toda incidencia anterior a la migración queda con `NULL`,
  que es la respuesta honesta —nadie escribió una nota— y no un valor inventado.
- THE SYSTEM SHALL declarar la cota de longitud **en el DDL y en el esquema**, y no solo en el
  segundo: es el patrón de `properties` y evita la situación que
  [`properties-crud`](properties-crud.md) tuvo que arreglar a posteriori en cuatro columnas sin
  ancho.
- WHEN se llama `POST /api/v1/incidents/{incident_id}/assign`, THE SYSTEM SHALL aceptar
  `assignment_note` como campo **opcional** del cuerpo, manteniendo `extra="forbid"`, el permiso
  `MANAGE_INCIDENTS` y la tabla de transiciones de [`maintenance`](maintenance.md) R1 sin cambios.
  Una nota por encima de la cota es un `422`.
- THE SYSTEM SHALL escribir el valor **siempre**: enviarla la fija, no enviarla la deja a `NULL`. La
  nota pertenece a la **asignación vigente**, no a la incidencia, así que reasignar sin nota borra la
  anterior. `assign` admite reasignación desde cuatro de sus cinco estados de origen, y la
  alternativa —preservar la nota cuando el cuerpo no la trae— enseñaría al técnico B lo que el
  manager escribió para el técnico A: una nota obsoleta presentada como vigente es peor que ninguna.
  Evita además el centinela «no enviado» vs. «enviado como `null`» que el `PATCH` de propiedades
  tuvo que construir; aquí `POST /assign` es una operación completa, no un parche.
- THE SYSTEM SHALL devolver la nota en esta proyección y NEVER SHALL añadirla a `IncidentResponse`:
  el listado paginado no la necesita y el contrato de incidencia no cambia.
- THE SYSTEM SHALL documentar en la `description` de la operación que la nota es la de la asignación
  vigente y que una reasignación sin nota borra la anterior. Es el coste asumido de la decisión, y
  la `description` y `docs/maintenance.md` son lo único que evita que el manager lo descubra por
  sorpresa.

### Las dos exclusiones de la nota son estructurales por ausencia del allowlist

- THE SYSTEM SHALL mantener `assignment_note` **fuera** de `AUDITABLE_FIELDS["INCIDENT"]` —que
  pasó a **doce** campos en [`cleaner-incident-report`](cleaner-incident-report.md), al entrar
  `cleaning_task_id`—, y esa exclusión SHALL ser **estructural**: nombrarla en un `ChangeSet` levanta
  `AuditContractError` por no ser un campo declarado de la entidad, en **las dos formas** —`diff()` y
  `redacted()`—. Es el mismo mecanismo exacto que ya excluye `title`, `description`, `ai_summary` y
  `ai_classification`.
- THE SYSTEM SHALL mantenerla también **fuera** de `REDACTED_FIELDS`, y esa segunda ausencia SHALL
  ser deliberada y asertada: denylistar obliga a **añadir** al allowlist —si no, `redacted()` también
  falla—, lo que sería estrictamente más superficie. Aquí no hay nada que registrar ni redactado: que
  el manager haya dejado una nota no es un hecho operacional del que se audite el cambio.
- THE SYSTEM SHALL escribir el `AuditLog` y el `TimelineEvent` de la asignación como antes de este
  change, y el `metadata` del evento SHALL llevar **solo** `incident_id` y `technician_id`: el texto
  de la nota no viaja al timeline ni a su título.
- THE SYSTEM SHALL declarar la columna en el censo de sumideros de la regla 11 de
  `steering/security.md` con forma **excepción 3, ensanchada para nombrarla** en vez de abrir una
  séptima. El escritor es una persona autenticada con `MANAGE_INCIDENTS` tecleando prosa suya sobre
  un trabajo de su tenant, acotada, y no propaga: es la misma concesión que
  `owner_approvals.response_notes`, y el steering dice literalmente que en ese caso «se ensancha el
  enunciado en lugar de abrir una excepción nueva por parecido».
- THE SYSTEM NEVER SHALL reusar `description` para esta nota: es la palabra de quien reporta, bajo la
  excepción 2, y mezclar en ella prosa nuestra o del manager es exactamente lo que esa excepción dice
  que no autoriza.

### `properties.access_notes`: excepción 6, y el precio que la paga

Es la decisión de steering que `sdd/roadmap/cleaner-app.md` tenía aparcada, y la disparó esta
capacidad al darle un lector nuevo a la columna. Aprobada en el gate de `/sdd:design` el 2026-08-19.

- THE SYSTEM SHALL declarar `properties.access_notes` en el censo de la regla 11 con una excepción
  **nueva y nombrada, la 6**, y no con la 3. Por la letra encaja en la 3 —la teclea una persona
  autenticada con `MANAGE_PROPERTIES` sobre su propia vivienda—, pero la cláusula que **concede** la
  excepción 3 es «el valor no es nuestro y **no lo hemos ido a buscar**», y aquí lo hemos ido a
  buscar: el propósito declarado de la columna *es* la instrucción de acceso, y un código de portal
  dentro de ella no es un accidente del operador descuidado sino el contenido esperado. Una fila del
  censo que promete «no fuimos a buscarlo» sobre una columna que existe para eso sería una fila que
  miente, y la propia regla 11 dice que eso es peor que una columna sin censar.
- THE SYSTEM SHALL declarar en esa fila **todos** los lectores efectivos de hoy y no solo lo que esta
  capacidad añade: el detalle `GET /api/v1/properties/{id}` para quien tenga `READ_PROPERTIES`, el
  **portal del huésped** —que la devuelve verbatim como `arrival_notes` a un portador anónimo de
  token— y esta proyección. El censo llevaba **un change de retraso**, no cero: el disparador que el
  roadmap describe ya se había disparado una vez, en [`guest-portal-api`](guest-portal-api.md), y se
  resolvió con documentación en vez de con una fila. Eso no invalidó el requisito, lo reforzó.
- THE SYSTEM SHALL pagar el precio de la excepción 6 con **mecanismo y no solo con documentación**:
  la columna sale del listado paginado de propiedades. Es la forma de la regla 4 —«jamás en
  listados»— de la que la regla 11 es una aplicación, y responde a la única superficie de bulto que
  existía: `GET /api/v1/properties` devolvía las instrucciones de acceso de **todas** las viviendas
  del tenant en una sola respuesta.
- THE SYSTEM SHALL hacer que esa exclusión alcance a las **tres** notas de `properties`
  —`access_notes`, `cleaning_notes` y `emergency_notes`—, no solo a la censada: es un solo esquema y
  el mismo coste, y un listado que esconde una nota y muestra dos es una forma que nadie podrá
  explicar dentro de seis meses. Salir del listado **no** es entrar en el censo: el censo se hace por
  quién escribe la columna y qué transporta.
- THE SYSTEM NEVER SHALL cifrar `access_notes` en reposo como parte de esta capacidad. El disparador
  que el roadmap nombra es de **audiencia**, y la exclusión de listados es el remedio con la misma
  forma que el problema; el cifrado responde a otra amenaza —lectura offline de la base, de un backup
  o de una réplica— cuya exposición esta capacidad no mueve, y que es **idéntica** para las cuatro
  columnas de texto libre que pueden transportar un valor de la regla 3. Pagarlo aquí sería arbitrario
  (una de cuatro) o arrastraría cuatro columnas y una migración de datos a un change sobre la pantalla
  de un técnico. Queda como entrada de roadmap con nombre —`plaintext-sink-encryption-at-rest`— y no
  como deuda tácita.

### Por qué esto no cubre las otras tres columnas

`sdd/roadmap/cleaner-app.md` pedía cubrir las cuatro columnas juntas o decir explícitamente por qué
no. Éste es el «por qué no», y deja a las otras tres donde estaban:

- **`properties.cleaning_notes` y `properties.emergency_notes`** no las lee esta proyección, así que
  no ganan lector, y su propósito **no** es transportar un valor de la regla 3 —una instrucción de
  limpieza no es un código—, así que no les corresponde la excepción 6 ni una fila propia del censo
  hoy. Lo que **sí** les llegó, y consta porque es más de lo que se pedía: salen del listado junto con
  `access_notes`. `emergency_notes` es la primera candidata a excepción 6 el día que gane lector: un
  código de caja de llaves cabe ahí igual de bien.
- **`access_records.notes`** no se lee aquí en absoluto —`TECHNICIAN` no tiene `READ_ACCESS_RECORDS`
  y PRD §12 no pide accesos registrados— y sigue siendo de `cleaner-app`. Su mitigación actual
  (`AccessRecord.register_manual_code` rechaza la petición cuando el código aparece en las notas)
  **no es trasladable** a `access_notes`: no hay código en claro almacenado contra el que comparar
  ([`access-notifications`](access-notifications.md) D9), así que ese mecanismo no está disponible.

### Contrato publicado

- THE SYSTEM SHALL declarar la operación en `backend/openapi.json` con su esquema de respuesta
  enumerado campo a campo, y SHALL mantener regenerado y commiteado el artefacto derivado del
  frontend `frontend/lib/api/generated/openapi.d.ts` — las dos mitades del mismo puente
  ([`api-contract.md`](api-contract.md), `steering/documentation.md`).
- THE SYSTEM SHALL declarar su `404` en la propia ruta con el sobre de error de PRD §23 y el código
  `NOT_FOUND`, con un `responses=` per-endpoint que es una **única** entrada; el `401`, el `403` y el
  `422` los hereda del router.
- THE SYSTEM SHALL documentar en la `description` de la operación que el conjunto de incidencias
  visibles depende del **rol persistido del token** y no es ensanchable por parámetro —porque no
  existe el parámetro—, qué significa cada `null`, que `assignment_note` es la nota de la asignación
  vigente, y qué es lo que la ruta nunca lleva.
- THE SYSTEM SHALL reflejar en el contrato el campo opcional que `assign` gana, con su cota y con
  `additionalProperties: false`.

## Consultas por petición

**Dos** sentencias sobre una sola incidencia: `incidents.get` y `properties.get`. **Una** en los
caminos que terminan en `404` por la incidencia. Es el coste de la composición y se paga en la
lectura de una incidencia, no en un listado; hay tests que lo fijan por número de sentencias.

## Fuera de alcance

- **La UI del técnico.** `/tech` y `/tech/incidents/[id]` los implementa `tech-app`, que declara esta
  entrada en su `needs`. El andamio (`frontend/app/(field)/tech/`, `TechnicianShell`, `AuthGuard`) ya
  existía y no se tocó.
- **Fotos de la incidencia**, y el par antes/después: son de `incident-photos`.
- **`reject`, ETA, materiales y «en ruta».** Fueron de `tech-cycle-completion`, que las entregó el
  2026-08-22 tocando la tabla de transiciones de [`maintenance`](maintenance.md) R1: `start` pasó a
  llamarse `en_route` y a escribir `TECHNICIAN_EN_ROUTE`, sin cambiar orígenes ni destino, y
  `resume_work` conservó `TECHNICIAN_STARTED`, así que no se retiró ningún miembro del vocabulario.
- **Cifrado en reposo de las cuatro columnas de texto libre.** Rechazado con su motivo escrito y
  aplazado con nombre a `plaintext-sink-encryption-at-rest`.
- **Conceder `READ_PROPERTIES` o `READ_RESERVATIONS` a `TECHNICIAN`.** El conjunto de permisos del
  rol no cambió.
- **El contexto embebido en el listado.** `IncidentPageResponse` no lo lleva; lo decidirá `tech-app`
  con una pantalla real delante, y con 2 viviendas en el MVP N es pequeño.
- **Una columna de contacto estructurado.** PRD §12 pide «instrucciones de contacto/acceso» y esa
  línea la sirve `access_notes`. Si `tech-app` encuentra con una pantalla delante que hace falta un
  teléfono del conserje o del propietario, es columna nueva y es de otro change.
- **Una ruta de creación de incidencias.** [`maintenance`](maintenance.md) R8 la niega
  explícitamente y esa negativa sobrevive.

## Estado

- **La «no propagación» de la excepción 6 es más débil que la de la 3, y consta medida.**
  `assignment_note` está fuera de `AUDITABLE_FIELDS["INCIDENT"]`, así que `ChangeSet` la rechaza por
  construcción; `access_notes` en cambio **sí** está dentro de `AUDITABLE_FIELDS["PROPERTY"]` y fuera
  de `REDACTED_FIELDS`, así que un `ChangeSet("PROPERTY").diff("access_notes", …)` es **aceptado y
  almacena el valor literal**. Lo que hoy la redacta es disciplina del caso de uso
  (`REDACTED_ON_AUDIT` de `properties/application/property_admin.py`), no el tipo. Cerrarlo significa
  mover las tres notas a un conjunto de solo-redacción, y no se hizo aquí: queda escrito en
  `steering/security.md` con su medición, no como promesa.
- **`access_notes` no tiene ancho en el DDL** y su cota de 5000 caracteres vive solo en pydantic, al
  contrario que `assignment_note`, que la tiene en los dos sitios. Es la asimetría que
  [`properties-crud`](properties-crud.md) ya nombra sobre sus cuatro columnas `String()` sin ancho.
- **El acotamiento por fila del módulo sigue en dos sitios, no en uno.** Esta capacidad bajó de dos
  copias a una en la puerta de las incidencias, pero `RespondOwnerApprovalUseCase` resuelve por su
  propio par de consultas. El candidato con nombre sigue siendo
  `tenant-scoping-enumeration-guard`.
- **Cifrado en reposo pendiente y con nombre**: `plaintext-sink-encryption-at-rest` cubre las cuatro
  columnas. Conviene no venderla como si cerrase también el riesgo por API: cifrar `access_notes`
  mientras `GET /api/v1/guest/info/{token}` la devuelve verbatim a un portador anónimo compra poco
  contra esa otra amenaza, que es de audiencia.

## Key files

- `backend/app/maintenance/domain/read_models.py` — `IncidentContext`, el dataclass congelado de
  once campos, y el docstring que enumera por qué la lista está cerrada y qué queda fuera.
- `backend/app/maintenance/domain/entities.py` — `Incident.assignment_note` y `Incident.assign`, que
  la escribe siempre.
- `backend/app/maintenance/application/use_cases.py` — `_load_incident_in_scope` (la corrutina de
  módulo con sus tres llamantes), `IncidentActor.restrict_to_technician_id` y
  `GetIncidentContextUseCase`.
- `backend/app/maintenance/api/schemas.py` — `IncidentContextResponse` (espejo con
  `from_attributes=True`), `MAX_ASSIGNMENT_NOTE` y `AssignIncidentRequest`.
- `backend/app/maintenance/api/incidents_router.py` — `GET /{incident_id}/context`,
  `_INCIDENT_CONTEXT_RESPONSES` y la `description` del contrato.
- `backend/app/maintenance/api/dependencies.py` — `get_incident_context_use_case`, con los dos
  repositorios ya inyectados en el módulo.
- `backend/alembic/versions/b9d24e70c1af_incident_assignment_note.py` — la columna, sin backfill.
- `backend/app/properties/api/schemas.py` — `PropertyListItemResponse`, el esquema paralelo sin las
  tres notas, y `PropertyPageResponse` que lo usa.
- `backend/app/audit/domain/value_objects.py` — `AUDITABLE_FIELDS["INCIDENT"]` y el
  `_check_auditable` de `ChangeSet` que hace estructural la exclusión.
- `backend/tests/maintenance/test_incident_context_{read_model,use_case,api}.py` — el conjunto de
  campos fijado, el `null` sobre el cuerpo serializado, el cruce de tenant, los cuatro `404`
  idénticos, el recuento de sentencias y los rechazos de `CLEANER` y del token de huésped.
- `backend/tests/maintenance/test_free_text_sink_contract.py` — las dos exclusiones de la nota y el
  `metadata` del evento de asignación.
- `backend/tests/properties/test_api.py` — el listado sin las tres notas y el detalle con ellas.
- `sdd/steering/security.md` — el censo de la regla 11, la excepción 6 y la 3 ensanchada.
- `docs/maintenance.md` — cómo se opera, y el aviso al operador.
