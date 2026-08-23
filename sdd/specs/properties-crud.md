# Propiedades — alta, consulta y edición

## Purpose

Da al inventario de viviendas su vía de escritura por API: alta, listado paginado, detalle y
edición parcial, con los cuatro endpoints que declara PRD §23. Es el paso previo a cualquier
reserva, porque las tres vías de entrada de reservas —el alta manual, el import CSV y el sync del
PMS— resuelven primero la propiedad, y ninguna puede resolver lo que no existe.

**El API no es el único llamante de `CreatePropertyUseCase`**: `make seed-demo` lo invoca en
proceso, sin HTTP, para crear las dos viviendas de PRD §27 (spec `seed-data-demo`). No es una vía
de escritura nueva —es un cliente más del mismo caso de uso, que es justo lo que evita un segundo
escritor con invariantes duplicados—, pero sí significa que las filas de `properties` y sus
`audit_logs` pueden existir sin que nadie haya llamado al endpoint.

**El módulo ya no expone sólo esos cuatro**: `dashboard-api` añadió al mismo router la lectura
ligera `GET /api/v1/properties/{id}/state` (PRD §23:1942), que vive aquí porque `properties` posee
la columna que reporta y el historial del que la data. Es lectura pura y no resuelve nada: el
estado es el que `PropertyStateMachine` escribió por última vez. Bajo el mismo prefijo `/properties`
se sirve además `GET /api/v1/properties/{id}/dashboard`, pero ese es un agregado multidominio y su
router es el de `app/dashboard/`; ambos se describen en [`dashboard-api.md`](dashboard-api.md).

**Y ya no es sólo API**: `properties-web` entregó `/properties`, el índice paginado de sólo lectura
del portfolio, que es la única pantalla donde se ve el `status` de una vivienda y el único sitio
donde un UUID de propiedad se resuelve a un nombre. Se describe abajo, en «La pantalla del
portfolio»; el alta, la edición y la retirada siguen siendo sólo API.

El *cómo se opera* está en [`docs/properties.md`](../../docs/properties.md); aquí vive el *qué
hace*.

## Requirements

### Lectura

- WHEN se solicita `GET /api/v1/properties`, THE SYSTEM SHALL devolver únicamente las propiedades
  del tenant del token, con el envelope `{data, total, page, per_page, total_pages}` de PRD §23.
- THE SYSTEM NEVER SHALL llevar en los items del listado paginado las tres notas de texto libre
  —`access_notes`, `cleaning_notes` y `emergency_notes`—, y SHALL conseguirlo con un **esquema de
  respuesta propio y más estrecho** (`PropertyListItemResponse`, 23 campos construidos
  explícitamente) y no con una exclusión de campos ni con un campo opcional: un campo que el llamante
  pudiera pedir no sería una exclusión. El detalle sí las conserva. Es el precio de la **excepción
  6** de la regla 11 de `steering/security.md`, concedida a `access_notes` en
  [`tech-incident-context`](tech-incident-context.md) el 2026-08-21, y la forma de la regla 4 —«jamás
  en listados»—: este listado devolvía las instrucciones de acceso de **todas** las viviendas del
  tenant en una sola respuesta, y era la única superficie de bulto que existía. La exclusión alcanza
  a las tres y no solo a la censada porque es un solo esquema y el mismo coste, y un listado que
  esconde una nota y muestra dos no es una forma explicable; salir del listado **no** mete a las
  otras dos en el censo.
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
- **Estas rutas no son la única lectura de campos de `Property`, y las otras no pasan por aquí.**
  [`cleaner-task-context`](cleaner-task-context.md) sirve nueve campos —`name`, `internal_code`, los
  seis de dirección postal y `timezone`— a un rol que **no** tiene `READ_PROPERTIES`, con su propia
  lista cerrada y sobre un conjunto de filas más estrecho que el que este permiso daría: la propiedad
  de una tarea de limpieza, y solo mientras esa tarea sea alcanzable por el llamante.
  [`tech-incident-context`](tech-incident-context.md) sirve esos mismos nueve **más `access_notes`**
  al rol `TECHNICIAN`, acotado a la incidencia que tiene asignada. Y el portal del huésped devuelve
  `access_notes` verbatim como `arrival_notes` a un portador anónimo de token
  ([`guest-portal-api`](guest-portal-api.md)). La regla que separa todas de este permiso es que **una
  proyección puede estrechar, nunca unir**: un campo que este permiso guarda *como un todo* no se
  añade allí.

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
- THE SYSTEM SHALL aplicar la regla en las **tres** vías de entrada. Las de lote difieren solo en
  cómo resuelven la propiedad —por `internal_code` el CSV, por `pms_external_id` el sync— y todas
  entregan el resultado al mismo punto del ingestor, así que la regla vive ahí una sola vez. Los
  llamantes de ese punto son **tres** desde `seed-data-demo`: el seed le pasa un tercer
  `resolve_property`, también por `internal_code`, y hereda la regla sin repetirla.

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
- THE SYSTEM SHALL NOT llevar `wifi_password_encrypted`, `has_wifi_password`, `access_notes`,
  `cleaning_notes` ni `emergency_notes` en la proyección de
  [`cleaner-task-context`](cleaner-task-context.md). Allí la exclusión es **estructural** y no una
  denylist: la respuesta se construye desde un dataclass de once campos y la entidad `Property` no
  se serializa nunca, así que un campo que no está en él no tiene dónde aterrizar. Es lo que hace
  que las tres columnas de notas —auditables pero no denylisted por la regla 11 de
  `steering/security.md`— no ganen un lector nuevo al ganarlo la dirección.
- THE SYSTEM SHALL NOT llevar `wifi_password_encrypted`, `has_wifi_password`, `cleaning_notes` ni
  `emergency_notes` en la proyección de [`tech-incident-context`](tech-incident-context.md), que **sí**
  lleva `access_notes` por diseño y con su fila del censo. La exclusión es estructural por el mismo
  mecanismo: un dataclass congelado de once campos, y ninguna entidad `Property` serializada.
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
  están denegados por nombre en `ChangeSet`, así que esa disciplina vive en el caso de uso
  (`REDACTED_ON_AUDIT` de `properties/application/property_admin.py`): son el sitio donde un operador
  pega un código de puerta, y `audit_logs.changes` es un sumidero de texto en claro bajo la regla 11
  de `steering/security.md`.
- **Esa disciplina no es un invariante, y la diferencia está medida.** `access_notes` está **dentro**
  de `AUDITABLE_FIELDS["PROPERTY"]` y **fuera** de `REDACTED_FIELDS`, así que un
  `ChangeSet("PROPERTY").diff("access_notes", …)` es aceptado y **almacena el valor literal**;
  comprobado el 2026-08-22 al concederle la excepción 6 en
  [`tech-incident-context`](tech-incident-context.md), y anotado allí y en `steering/security.md` con
  su medición. Es más débil que la exclusión de `incidents.assignment_note`, que `ChangeSet` rechaza
  por construcción en las dos formas. Cerrarlo significa mover las tres notas a un conjunto de
  solo-redacción, y no se hizo: consta como hueco con su forma, no como promesa cumplida.
- THE SYSTEM SHALL registrar `actor_user_id` del token y `actor_ip` resuelta con el mismo
  mecanismo que el resto de la API.
- WHERE el alta la hace `make seed-demo` en lugar de una petición, THE SYSTEM SHALL registrar el
  `actor_user_id` del `TENANT_OWNER` del tenant y `actor_ip` **nula**: un comando no tiene token ni
  IP de cliente, y el caso de uso acepta la IP como opcional precisamente porque no todo llamante
  tiene una. Así que un entorno sembrado tiene filas `PROPERTY_CREATED` atribuidas al owner y sin
  IP (spec `seed-data-demo`).
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

### La pantalla del portfolio (`/properties`)

`frontend/features/properties/` sirve la ruta como tabla paginada de **sólo lectura** sobre
`GET /api/v1/properties`. No estrena ruta, ni clave de navegación, ni mutación: el registro de
rutas ya declaraba `properties` y `property-detail`, y la pantalla sólo dejó de ser un
`RoutePlaceholder`.

- WHEN la operadora abre `/properties`, THE SYSTEM SHALL pedir `GET /api/v1/properties` y renderizar
  una fila por elemento de `data`, leyendo la paginación del sobre plano
  `{data, total, page, per_page, total_pages}` y NEVER SHALL asumir un `meta` anidado.
- THE SYSTEM SHALL pintar exactamente **seis** campos por fila, en este orden: nombre, código
  interno, ciudad, capacidad (`max_guests`/`bedrooms`/`bathrooms`), estado operativo y `status`.
  Los otros 17 campos que el listado devuelve —dirección, `country`, `timezone`, horas por defecto,
  `wifi_name`, `has_wifi_password`, el vínculo con el PMS y los sellos de tiempo— son datos de ficha
  y NEVER SHALL pintarse: una lista que pinta todo el payload deja de ser una lista.
- THE SYSTEM SHALL renderizar los mismos seis campos en **dos maquetaciones** por breakpoint —una
  tarjeta apilada con pares etiqueta/valor por debajo de `sm`, la tabla de seis columnas desde `sm`—
  y NEVER SHALL resolver el ancho con desplazamiento horizontal. `steering/frontend.md` exige
  mobile-first, y con scroll lateral la propietaria tendría que desplazarse para leer `status`, que
  es justo el dato que sólo existe aquí. El coste es que el DOM lleva las filas dos veces; en un
  navegador la mitad oculta sale del árbol de accesibilidad por `display:none`, y en jsdom no, así
  que los tests acotan sus consultas a una de las dos.
- THE SYSTEM SHALL ofrecer exactamente los **dos** filtros que el endpoint acepta —`status` y
  `current_operational_state`, cada uno con una opción «todos» que omite el parámetro— y NEVER
  SHALL ofrecer búsqueda por texto, ordenación elegible ni filtro por ciudad: el endpoint no los
  acepta y añadirlos exigiría backend nuevo.
- THE SYSTEM SHALL derivar las once opciones del filtro de estado de `PROPERTY_OPERATIONAL_STATES`,
  que el componente compartido deriva de las claves de su mapa de colores, y NEVER SHALL
  transcribirlas: una lista escrita a mano dejaría de ofrecer un estado doce en silencio.
- WHEN la operadora cambia cualquier filtro, THE SYSTEM SHALL volver a la página 1 antes de pedir,
  para no quedarse en una página que el conjunto filtrado no tiene y devolver un vacío que la
  pantalla no puede distinguir de «no hay propiedades así».
- THE SYSTEM SHALL ofrecer navegación anterior/siguiente **sólo cuando `total_pages` es mayor que
  1**, deshabilitando cada control en su extremo.
- WHEN se activa el nombre de una fila, THE SYSTEM SHALL navegar a `/properties/{id}`, el detalle
  que `dashboard-web-frontend` ya sirve. El enlace es la **celda del nombre** y no la fila entera,
  con su nombre accesible localizado.
- THE SYSTEM SHALL enrutar la lectura por TanStack Query v5 con clave de ámbito de tenant
  (`['tenant', tenantId, 'properties-list', filtros]`, que lanza si el tenant falta), emitiendo las
  claves del objeto de filtros en **orden fijo** y canonizando `page` ausente a `1`, de modo que dos
  estados de interfaz equivalentes no produzcan dos entradas de caché.
- THE SYSTEM SHALL mostrar el estado de carga transversal mientras la petición está en vuelo, un
  estado «prohibido» localizado ante un `403`, un estado de validación localizado ante un `422` —sin
  renderizar el cuerpo del error del servidor—, un estado vacío localizado cuando `data` llega vacío,
  y el estado de error genérico con reintento manual para todo lo demás.
- IF la respuesta es `401`, THEN THE SYSTEM SHALL tratarlo como **carga** y no como error, para no
  parpadear mientras corre la rotación de token.
- IF la respuesta es `404`, THEN THE SYSTEM SHALL tratarlo como error genérico: una lista no «no
  existe», así que un `404` aquí significa que el proxy o la ruta base están rotos, no que falte un
  recurso.
- THE SYSTEM NEVER SHALL reintentar automáticamente una respuesta `4xx`, vía el `retryPolicy`
  compartido; los fallos transitorios (`5xx`, red) se reintentan dos veces.
- THE SYSTEM NEVER SHALL renderizar `access_notes`, `cleaning_notes` ni `emergency_notes`, que el
  listado no devuelve por la excepción 6 de la regla 11 de `steering/security.md`, ni la contraseña
  del WiFi en ninguna forma —`has_wifi_password` es la única señal del contrato, y la pantalla no la
  pinta.
- THE SYSTEM NEVER SHALL llamar a `GET /api/v1/properties/{id}` ni a `GET /api/v1/properties/{id}/state`
  desde el listado para completar una fila: reconstruiría esa superficie de bulto, y además con una
  llamada por fila.
- THE SYSTEM SHALL renderizar como texto, nunca como HTML, todo campo de origen externo que pinte
  (`name`, `internal_code` y la ciudad): la interpolación de JSX escapa por defecto y no existe
  `dangerouslySetInnerHTML` en la feature.
- THE SYSTEM SHALL declarar un namespace `properties` en `locales/es` y `locales/en`, registrado en
  `lib/i18n/resources.ts`, y SHALL leer las once etiquetas de estado operativo del namespace
  `dashboard` donde ya existen, NEVER creando un segundo catálogo del mismo enum. Un test de la
  feature fija que los once valores de `PropertyOperationalState` y los dos de `PropertyStatus`
  resuelven en ES y EN, y que `properties.json` **no** tiene clave `state` en ninguno de los dos
  idiomas: `catalog-parity.test.ts` compara paridad entre idiomas, no cobertura del enum.
- THE SYSTEM SHALL exponer de la feature únicamente `PropertiesView`; los DTOs, el cliente HTTP,
  las claves de query, el mapeo de errores y el componente de filtros son privados.
- THE SYSTEM SHALL registrar la página graduada en `REAL_PAGE_ROUTE_IDS` de
  `frontend/app/route-coverage.test.ts`. Ese test deduce el `routeId` leyendo la prop
  `routeId="…"`, que sólo existe mientras la página es un `RoutePlaceholder`; sin la entrada, la
  página queda «sin cubrir» y el test de páginas huérfanas falla. Es el mecanismo previsto, y toda
  página que se gradué tiene que tocar ese tercer fichero.

**Dos huecos medidos, que constan como huecos y no como promesas cumplidas**: `per_page` viaja en el
DTO, en el cliente y en los tests, pero **ninguna ruta de la interfaz lo fija**, así que una petición
real nunca lo emite y el tamaño de página es el defecto del backend (20). Y el sobre de la respuesta
se consume con un **cast** y no con una validación en tiempo de ejecución: los tests fijan la forma,
pero un payload malformado (`data` ausente) lanza dentro del `queryFn` y sale como el estado de error
genérico en vez de detectarse en la frontera.

**El color del estado operativo no vive aquí.** Lo posee `components/property-state-badge.tsx`, el
componente transversal que `properties-web` extrajo del panel para que la tabla de colores de PRD
§9.1 tenga una sola copia en el árbol; se especifica en
[`dashboard-web-frontend.md`](dashboard-web-frontend.md).

**La pantalla no añade autorización.** No hay guarda de permiso en el frontend para `/properties`:
el `403` del backend es toda la historia de acceso, y es el backend quien decide. Un `TENANT_OWNER`
y un `PROPERTY_MANAGER` la ven; `CLEANER`, `TECHNICIAN` y `SUPER_ADMIN` reciben el estado
«prohibido» localizado.

## Key files

- `backend/app/properties/api/` — `router.py` (los cuatro endpoints de PRD §23 más
  `GET /{id}/state`, que añadió `dashboard-api`), `schemas.py` (las
  cotas, `extra="forbid"`, el rechazo de nulos explícitos y la respuesta sin secreto),
  `errors.py` (el `_MAPPING` a los códigos del envelope), `dependencies.py`.
- `backend/app/properties/application/property_admin.py` — los cuatro casos de uso, el cifrado del
  wifi, el diccionario `written` que decide a la vez qué se persiste y qué se audita, y la
  redacción de los campos de texto libre.
- `backend/app/properties/domain/repositories.py` — el puerto, `PATCHABLE_PROPERTY_FIELDS` como
  único hogar de la regla, `PropertyFilters` y `Page`. Incluye `states_for(tenant_id, property_ids)`,
  la lectura estrecha de estado operacional por lote que consume `cleaning` para decir en su listado
  si una tarea es asignable ahora (`cleaning.md`); es deliberadamente distinta de las lecturas de
  portfolio completo del mismo puerto, que alimentan barridos y no pantallas.
- `backend/app/properties/infrastructure/repositories.py` — los escritores, la guarda de tenant, la
  comprobación de estado en el alta y la traducción de las constraints.
- `backend/app/properties/domain/exceptions.py` — `PropertyNotFoundError`,
  `DuplicateInternalCodeError`, `DuplicatePmsExternalIdError`, `PropertyValidationError`.
- `backend/app/cli/seed_demo.py` — llamante de `CreatePropertyUseCase` fuera del API, y de
  `find_by_internal_code` como clave de idempotencia (spec `seed-data-demo`).
- `backend/app/reservations/application/use_cases.py` y
  `backend/app/integrations/application/ingest.py` — las dos guardas de propiedad retirada.
- `backend/alembic/versions/f2b9c7a41d38_properties_pms_external_id_unique.py` — el índice parcial
  y funcional.
- Tests: `backend/tests/properties/`.
- `frontend/features/properties/` — la pantalla: `data/dto.ts` (23 campos en camelCase, con
  `PropertyStatus`/`PropertyOperationalState`/`PMSProvider` **re-exportadas** del generado en vez de
  transcritas), `data/http/http-properties-source.ts` (el único llamante HTTP), `data/index.ts`
  (punto de composición `getPropertiesDataSource()`, sin `Mock*Source`), `hooks/query-keys.ts`
  (`propertiesKeys.list` sobre `tenantScopedKey` + `normalizePropertyFilters`),
  `hooks/use-properties.ts`, `lib/error-mapping.ts` (la unión discriminada de estados),
  `components/list/{properties-view,properties-filters}.tsx`, `locales/properties-locale.test.ts`,
  `index.ts` (fachada: sólo `PropertiesView`).
- `frontend/components/property-state-badge.tsx` — el mapa de colores de PRD §9.1, compartido con
  `/dashboard` (ver [`dashboard-web-frontend.md`](dashboard-web-frontend.md)).
- `frontend/app/(workspace)/properties/page.tsx` — monta `PropertiesView`; `generateMetadata` intacto.
- `frontend/locales/{es,en}/properties.json`, registrado en `frontend/lib/i18n/resources.ts`;
  `frontend/app/route-coverage.test.ts` (la página graduada en `REAL_PAGE_ROUTE_IDS`).
