# Dashboard — API agregada de lectura

## Purpose

Da al dashboard del propietario/manager (PRD §9, §10) su backend: siete endpoints de
**lectura pura**, tenant-scoped y autenticados, que responden «¿qué pasa y quién tiene la
próxima acción?» sin obligar al cliente a componer siete dominios. Son la colección de cards,
el agregado de detalle de una propiedad, su estado operacional, su timeline filtrable (por
propiedad y a nivel de tenant), los tres contadores operacionales a nivel de tenant y la
serie semanal de ocupación a nivel de tenant.

No crea ninguna tabla, ninguna columna y ninguna vía de escritura: compone lo que otras
capacidades ya persisten. El *cómo se opera* está en
[`docs/dashboard.md`](../../docs/dashboard.md); las pantallas que lo consumirán, en
[`dashboard-web-frontend.md`](dashboard-web-frontend.md).

**Dónde vive**: un módulo propio `app/dashboard/` con `domain/`, `application/` y `api/` y
**sin `infrastructure/`** — compone los puertos de los demás dominios en vez de escribir un
segundo sitio donde se aplica el scope de tenant. El agregado toca siete dominios
(`properties`, `reservations`, `guests`, `cleaning`, `maintenance`, `statements`, `access`)
más `timeline`; alojarlo en `properties` habría convertido al dominio que custodia la máquina
de estados en un hub que importa a los otros siete.

## Requirements

### Reparto de rutas

- THE SYSTEM SHALL servir exactamente estas siete rutas de lectura, y ninguna de escritura:

  | Ruta | Router | Por qué ahí |
  |---|---|---|
  | `GET /api/v1/dashboard/properties` | `app/dashboard/api/router.py` | agregado multidominio, prefijo propio |
  | `GET /api/v1/dashboard/operational-kpis` | `app/dashboard/api/router.py` | contadores multidominio a nivel de tenant, mismo prefijo |
  | `GET /api/v1/dashboard/occupancy-series` | `app/dashboard/api/router.py` | serie multidominio a nivel de tenant, mismo prefijo |
  | `GET /api/v1/properties/{property_id}/dashboard` | `app/dashboard/api/router.py` | agregado multidominio, con la ruta que fija PRD §23:1943 |
  | `GET /api/v1/properties/{property_id}/state` | `app/properties/api/router.py` | lectura de un solo dominio, del módulo que posee la columna |
  | `GET /api/v1/timeline/{property_id}` | `app/timeline/api/router.py` | dominio propio, con la capa `api/` que estrena |
  | `GET /api/v1/timeline` | `app/timeline/api/router.py` | la variante sin `property_id` de la misma ruta de PRD §23:1951, mismo router (`dashboard-activity-feed`) |

- THE SYSTEM SHALL servir la colección bajo su propio prefijo `/dashboard` y no bajo
  `/properties`. `/properties/dashboard` y `/properties/{id}` compiten en FastAPI, que resuelve
  por orden de registro: `dashboard` se parsearía como `{id}` y la ruta respondería `422` en vez
  de existir. Junto con `/dashboard/operational-kpis` y `/dashboard/occupancy-series` —que
  tampoco existen en el PRD, al no agregar ningún dato sobre una propiedad concreta— son las
  **únicas** rutas que el PRD no nombra, así que son las únicas que pueden moverse; las dos de
  §23:1942-1943 se quedan literales.
- **La pantalla no se alimenta sólo de aquí, y estas seis rutas siguen siendo de lectura**: desde
  `blocked-transitions-web` la card del dashboard lee además
  `GET /api/v1/blocked-transitions` (`celery-jobs.md`) y, con permisos de escritura, llama a
  `cleaning` y `maintenance`. Ninguna de esas rutas es de esta capacidad y ninguna se añade aquí; se
  nombra para que «el dashboard es de sólo lectura» no se lea como una promesa de la pantalla.

### Forma del contrato

- THE SYSTEM SHALL nombrar los campos de respuesta en `snake_case`, que es el nombre Python del
  campo: ningún modelo declara `alias_generator` ni `populate_by_name`.

  **Es una divergencia declarada frente al contrato del frontend**, que los tipa en `camelCase`
  (`frontend/features/dashboard/data/dto.ts`). El proyecto no tiene camelCase en ninguna
  respuesta, y `backend/openapi.json` —regenerado— es la fuente de verdad de la que
  `frontend/lib/api/generated/openapi.d.ts` deriva. La conversión es, por tanto, trabajo de
  `dashboard-web` al sustituir el mock, no una promesa incumplida aquí.
- THE SYSTEM SHALL declarar **presentes** todas las claves de cada respuesta, incluidas las que
  viajan `null`: una clave ausente y una clave nula no son lo mismo para el cliente, y todas
  figuran como `required` en el contrato publicado.
- THE SYSTEM SHALL serializar los importes como **string**, nunca como float, para no perder
  precisión decimal en el JSON.
- THE SYSTEM SHALL mapear cada campo explícitamente desde el modelo de dominio y SHALL NOT usar
  `from_attributes`: un campo nuevo en una entidad no debe poder aparecer en una respuesta sin
  que alguien lo escriba.
- THE SYSTEM SHALL devolver el envelope de paginación de PRD §23 —`{data, total, page,
  per_page, total_pages}`— en las dos rutas paginadas, y el envelope de error
  `{error:{code,message,details}}` en los fallos.
- THE SYSTEM SHALL mantener `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts`
  regenerados y versionados, de modo que los workflows `api-contract` y `frontend-api-contract`
  no detecten deriva.

### Colección de cards (`GET /api/v1/dashboard/properties`)

- WHEN un usuario autenticado la solicita, THE SYSTEM SHALL devolver una card por propiedad
  **de su tenant**, paginada, y ninguna de otro tenant.
- THE SYSTEM SHALL incluir en cada card exactamente estos campos: `property_id`,
  `property_code`, `operational_state`, `current_or_next_reservation`, `cleaning_status`,
  `open_incidents_count`, `next_action`, `last_event_label` y `last_event_at`.
- THE SYSTEM SHALL emitir `operational_state` como uno de los literales canónicos de
  `PropertyOperationalState` (PRD §3.1), **sin traducir**, y SHALL NOT calcular ningún color:
  el mapeo de color es del frontend (PRD §9.1).
- THE SYSTEM SHALL aceptar `page` (1..100.000) y `per_page` (1..100) con las mismas cotas que
  `GET /api/v1/properties`, importadas de su módulo para que no puedan divergir, y IF están
  fuera de rango THEN THE SYSTEM SHALL responder `422` con el envelope de error.
- WHERE una propiedad no tiene reserva actual ni próxima, THE SYSTEM SHALL devolver
  `current_or_next_reservation: null` en vez de omitir la clave.
- WHEN se elige la reserva «actual o próxima», THE SYSTEM SHALL descartar las estancias ya
  terminadas, ordenar por fecha de entrada con desempate determinista y quedarse con la
  primera, dentro de un **horizonte de 90 días** (`ASSUMPTION`: ni PRD §9.1 ni el contrato del
  frontend fijan uno, y sin horizonte la consulta arrastraría toda la agenda futura).
- WHEN la página de propiedades viene vacía, THE SYSTEM SHALL responder sin emitir ninguna de
  las consultas de composición.

### Contadores operacionales (`GET /api/v1/dashboard/operational-kpis`)

Tres cifras a nivel de **tenant**, no de propiedad: cuántas limpiezas hay hoy, cuántos
check-ins llegan en los próximos días y cuántas incidencias siguen abiertas con su desglose
de urgentes. Ninguna de las tres existía como agregado — cada dominio ya tenía el dato, pero
no una vía de contarlo para todo el tenant de una vez.

- WHEN se solicita el endpoint, THE SYSTEM SHALL contar las `CleaningTask` del tenant cuyo
  `status` esté en `LIVE_STATUSES` (`CREATED, ASSIGNED, ACCEPTED, IN_PROGRESS`) y cuyo
  `scheduled_start` caiga en el día de hoy (UTC), comparando contra el rango explícito
  `[hoy, hoy + 1 día)` y nunca contra `func.date(scheduled_start)`, que invalidaría cualquier
  índice sobre la columna.
- WHEN se solicita el endpoint, THE SYSTEM SHALL contar las `Reservation` del tenant cuyo
  `check_in_date` caiga entre hoy (UTC, inclusive) y hoy + 7 días (inclusive) —
  `UPCOMING_CHECKIN_WINDOW_DAYS = 7`, una constante propia, distinta de
  `RESERVATION_LOOKAHEAD_DAYS` (90 días, usada para "la reserva actual o próxima" de la
  colección de cards; responden preguntas distintas y no comparten constante)— y SHALL excluir
  las que estén en `CANCELLED` o `NO_SHOW`. (`ASSUMPTION`: la ventana de 7 días no está en el
  PRD ni en la maqueta del dashboard rediseñado; decidida al proponer este endpoint.)
- WHEN se solicita el endpoint, THE SYSTEM SHALL contar los `Incident` del tenant cuyo `status`
  esté en `OPEN_INCIDENT_STATUSES` (`frozenset(IncidentStatus) - {RESOLVED, CANCELLED}`) y
  SHALL desglosar, dentro de ese mismo conteo y en la misma consulta, cuántos tienen `severity`
  en `{HIGH, CRITICAL}` como subconjunto "urgentes". (`ASSUMPTION`: el umbral
  `HIGH`+`CRITICAL` frente a solo `CRITICAL` tampoco está en el PRD; misma decisión.)
- IF el tenant no tiene ninguna limpieza/check-in/incidencia que contar, THEN THE SYSTEM SHALL
  devolver `0` (o `{total: 0, urgent: 0}` para incidencias), nunca `null` — el `null` de este
  endpoint está reservado para "no puedes verlo" (ver «Permisos: agregar no concede»).
- THE SYSTEM SHALL devolver `open_incidents` como un único bloque anidado `{total, urgent}`,
  redactado como unidad — nunca un campo presente y el otro `null` —, siguiendo la misma
  convención que un permiso que protege más de un número a la vez (`financial`, `access` del
  agregado de detalle).
- THE SYSTEM SHALL resolver cada conteo con **una consulta por dominio, filtrada por
  `tenant_id` sola**, sin enumerar las propiedades del tenant primero: a diferencia de la
  colección de cards, este endpoint no desglosa por propiedad, así que no hay nada que
  agrupar por lotes y el coste de la consulta no depende del tamaño de la cartera.

### Serie semanal de ocupación (`GET /api/v1/dashboard/occupancy-series`)

Siete puntos, uno por día de la semana ISO en curso (lunes a domingo, UTC), a nivel de
**tenant**: qué porcentaje de las viviendas activas estuvo ocupada cada día. A diferencia de
los otros cinco endpoints, no es una lectura directa de un dominio existente — compone una
definición propia de "noche ocupada" que no existía en el sistema (`app/dashboard/domain/occupancy.py`).

- WHEN se solicita el endpoint, THE SYSTEM SHALL devolver exactamente siete puntos, uno por
  día calendario de la semana ISO en curso del tenant (lunes a domingo, ambos inclusive,
  UTC), ordenados de lunes a domingo. **No** es una ventana móvil de 7 días terminando hoy, y
  no es configurable (`ASSUMPTION`: lectura literal de la maqueta rediseñada, que rotula siete
  barras `L M X J V S D` de una semana calendario).
- THE SYSTEM SHALL incluir en cada punto `date` (fecha ISO-8601), `occupied_properties`
  (número de viviendas activas del tenant ocupadas ese día), `total_properties` (total de
  viviendas activas del tenant) y `occupancy_pct` (`occupied_properties / total_properties *
  100`, `Decimal` a un decimal, `ROUND_HALF_UP`). IF `total_properties` es cero, THEN THE
  SYSTEM SHALL devolver `occupancy_pct: null` los siete días, nunca una división por cero.
- THE SYSTEM SHALL NOT calcular ningún color ni etiqueta de día de la semana: el frontend
  deriva ambos de `date`, la misma línea que ya sostiene `operational_state` en la colección
  de cards.
- THE SYSTEM SHALL contar una vivienda como ocupada en un día calendario `D` si se cumple
  **cualquiera** de estas tres condiciones, unidas en un `set` por vivienda de modo que la
  unión nunca cuente dos veces la misma vivienda el mismo día:
  - tiene una `Reservation` cuyo rango `[check_in_date, check_out_date)` cubre `D` y cuyo
    `status` no está en `FREE_STATUSES` (`{CANCELLED, NO_SHOW}`), el mismo frozenset que
    `app/pricing/domain/occupancy.py` declara para "noche ocupada" por reserva — **importado**,
    no redeclarado;
  - estuvo en `PropertyOperationalState.BLOCKED_BY_OWNER` en algún instante de `D`;
  - estuvo en `PropertyOperationalState.OUT_OF_SERVICE` en algún instante de `D`.

  `OCCUPIED_ESTIMATED` y el resto de estados operacionales **no** cuentan por sí mismos: es un
  estado que la máquina de estados *deriva* del mismo calendario que esta función ya lee, así
  que contarlo también duplicaría el voto del calendario.
- THE SYSTEM SHALL resolver el estado ocupado/bloqueado/fuera de servicio de una vivienda en
  un día pasado o en curso reconstruyéndolo desde su historial de
  `PropertyStateTransitionModel` — el `to_state` de la transición vigente al **final** de ese
  día (medianoche UTC del día siguiente, exclusiva) — nunca desde el `operational_state`
  actual de la fila `properties`, que solo describe el instante presente. Un bloqueo abierto y
  cerrado dentro del mismo día calendario **no** cuenta como ocupado ese día: la transición que
  libera el bloqueo, si ocurre antes del final del día, es la vigente en el último instante de
  `D` (comportamiento fijado por test, no accidental).
- WHERE una vivienda no tiene ninguna transición registrada antes de o durante `D`, THE SYSTEM
  SHALL tratarla como no bloqueada ni fuera de servicio ese día — el alta no es una transición,
  mismo criterio que `GET /properties/{id}/state`.
- THE SYSTEM SHALL contar los tres orígenes sobre el mismo día calendario **UTC** con el que se
  agrega la serie, sin mezclar husos horarios entre el criterio de reservas (por fecha) y el
  de transiciones (por instante).
- THE SYSTEM SHALL añadir a `PropertyStateTransitionRepository` un método de lectura,
  `history_for_properties(tenant_id, property_ids, start, end)`, que devuelva — por vivienda,
  disperso, sin mapear una vivienda sin historial a `()` — la última transición anterior a
  `start` (si existe, el estado con el que la vivienda "entra" a la ventana) seguida de toda
  transición dentro de `[start, end]`. Un `property_ids` vacío devuelve un mapa vacío sin
  consultar. THE SYSTEM SHALL NOT modificar `PropertyStateTransitionRepository.add` ni dar a
  este método ninguna vía de escritura: la tabla es un registro de auditoría (regla 9 de
  `steering/security.md`) que ningún lector reescribe.
- THE SYSTEM SHALL resolver la serie completa con un **número fijo de consultas**, independiente
  del número de viviendas del tenant — reutilizando `ReservationRepository.list_for_properties`
  para las reservas y el nuevo `history_for_properties` para las transiciones — y un test SHALL
  demostrarlo contando las sentencias emitidas, siguiendo la misma regla que «Composición por
  lotes, sin N+1» de este documento.
- THE SYSTEM SHALL declarar `require(Permission.READ_PROPERTIES)` en la ruta, igual que las
  otras cinco. WHERE el rol que llama carece de `Permission.READ_RESERVATIONS`, THE SYSTEM
  SHALL devolver la serie completa (`data`) como `null` en vez de una serie parcial que sólo
  cuente bloqueos y fuera de servicio: el componente de reservas es el origen mayoritario de
  "noche ocupada", así que una serie sin él no es una lectura estrecha de la misma serie, es un
  número distinto con la misma forma — **una proyección puede estrechar, nunca unir** (ver
  «Permisos: agregar no concede»). Esta redacción es de todo el bloque, no cuesta ninguna
  consulta cuando el rol carece del permiso.
- THE SYSTEM SHALL derivar el `tenant_id` del `RequestContext` autenticado, nunca de un
  parámetro de la petición, y SHALL incluirlo en toda consulta contra `reservations`,
  `properties` y `property_state_transitions`. THE SYSTEM SHALL demostrar con un test de
  aislamiento, sembrando reservas y transiciones de un tenant vecino, que la serie de un
  tenant no cuenta viviendas ni noches del otro.

### Agregado de detalle (`GET /api/v1/properties/{property_id}/dashboard`)

- WHEN un usuario autenticado lo solicita sobre una propiedad de su tenant, THE SYSTEM SHALL
  devolver las secciones de PRD §9.2 en estos campos: `property_id`, `property_code`,
  `operational_state`, `current_or_next_reservation`, `guest`, `access`, `cleaning_status`,
  `last_cleaning_photos`, `open_incidents`, `financial`, `notes` y `pending_approvals`.
- THE SYSTEM SHALL devolver en `guest` únicamente el nombre, y en `access` únicamente una
  etiqueta de estado: nunca el número de documento y nunca un código de acceso, ni siquiera
  enmascarado. El huésped se proyecta con `GuestSummary`, que excluye el documento **por
  construcción**, y el código en claro no existe en la base de datos —`AccessRecordModel` no
  tiene columna para él—, así que no hay nada que enmascarar.
- THE SYSTEM SHALL componer el título de cada incidencia a partir de su **categoría**
  localizada, y SHALL NOT devolver la columna `incidents.title`, que es texto libre.
- WHERE el dominio que escribe un bloque todavía no existe, THE SYSTEM SHALL consultar
  igualmente su tabla real y devolver la lista vacía o `null`, de modo que el contrato no
  cambie cuando esos changes aterricen. **La apuesta se cobró con `maintenance`** (2026-08-15):
  `incidents` y `owner_approvals` ya los puebla su flujo operativo y los dos bloques devuelven
  datos reales **sin que el agregado cambiara de forma ni de código**. Sólo los gastos siguen
  esperando a `revenue`.
- THE SYSTEM SHALL resolver la moneda del bloque financiero así: la de la reserva, o `EUR` por
  defecto; con **exactamente una** moneda en los gastos pendientes, ésa y su total, conservando
  el total de la reserva sólo si coincide la moneda; con cero o dos o más monedas, la de la
  reserva y `pending_expenses: null` (`ASSUMPTION`: ni el PRD ni el contrato dicen qué hacer con
  una propiedad que acumula gastos en dos monedas).

### Estado operacional (`GET /api/v1/properties/{property_id}/state`)

- WHEN un usuario autenticado lo solicita sobre una propiedad de su tenant, THE SYSTEM SHALL
  devolver su `PropertyOperationalState` canónico y el instante ISO-8601 UTC de su última
  transición.
- THE SYSTEM SHALL **leer** ese estado, no resolverlo: es el que `PropertyStateMachine` escribió
  por última vez. THE SYSTEM SHALL NOT reimplementar la resolución contextual en la capa de
  lectura.
- WHERE una propiedad nunca ha transicionado, THE SYSTEM SHALL devolver la fecha de última
  transición como `null`, porque el alta no es una transición.

### Timeline por propiedad (`GET /api/v1/timeline/{property_id}`)

- WHEN un usuario autenticado lo solicita sobre una propiedad de su tenant, THE SYSTEM SHALL
  devolver sus eventos paginados, **ordenados por instante descendente con desempate
  determinista por `id`**, de modo que paginar no repita ni omita entradas. El índice existente
  cubre la primera clave; el desempate ordena en memoria dentro de un mismo instante, que es un
  puñado de filas, y sin él la paginación es incorrecta.
- THE SYSTEM SHALL aceptar los filtros de PRD §10 —`event_type`, `severity`, `actor_type`, y el
  rango temporal con los nombres de contrato `from` y `to`— y SHALL combinarlos con AND, con
  ambos extremos del rango **inclusivos**.
- IF el rango es inverso (`to` anterior a `from`), o alguno de sus extremos llega sin zona
  horaria, THEN THE SYSTEM SHALL rechazarlo con `422` y el envelope de error.
- THE SYSTEM SHALL incluir en cada entrada exactamente `id`, `occurred_at`, `actor_type`,
  `event_type`, `severity`, `title` y `description`, y SHALL NOT serializar la columna
  `metadata`, que es JSON libre y no forma parte del contrato de lectura. La ausencia es
  **estructural**: el modelo de dominio de la entrada renderizada tampoco tiene ese campo, así
  que no hay nada que un serializador pudiera alcanzar.
- THE SYSTEM SHALL contar en `total` el mismo conjunto filtrado que devuelve en `data`, nunca
  todos los eventos de la propiedad.
- THE SYSTEM SHALL comprobar que la propiedad existe **antes** de consultar los eventos: la
  consulta de eventos por sí sola devolvería una página vacía con `200` sobre una propiedad
  ajena o inexistente, y eso filtraría por el código de estado lo que el 404 oculta.

### Feed de actividad a nivel de tenant (`GET /api/v1/timeline`) — `dashboard-activity-feed`

La variante sin `property_id` de la misma ruta: en vez del historial de una vivienda, la
actividad de **todas** las del tenant, mezclada en una sola página. Alimenta el widget
«Actividad Reciente» del dashboard rediseñado (PRD §23:1951), y es exactamente la unión de N
peticiones a `GET /api/v1/timeline/{property_id}` que un portador de `READ_PROPERTIES` ya podía
hacer una por una.

- WHEN un usuario autenticado con `READ_PROPERTIES` la solicita, THE SYSTEM SHALL devolver
  eventos de todas las propiedades de su tenant, paginados con `page`/`per_page`, **ordenados
  por instante descendente con el mismo desempate determinista por `id`** que usa la ruta por
  propiedad — mismo código de ordenación, no una copia.
- THE SYSTEM SHALL contar en `total` el mismo conjunto filtrado que devuelve en `data`, nunca
  todos los eventos del tenant.
- THE SYSTEM SHALL aceptar los mismos filtros AND-combinados y los mismos nombres de contrato
  que la ruta por propiedad —`event_type`, `severity`, `actor_type`, `from`/`to` inclusivos en
  ambos extremos— y SHALL rechazar con `422` un rango invertido o sin zona horaria, con el
  mismo `TimelineFilters` reutilizado sin cambios.
- THE SYSTEM SHALL NOT aceptar ni exigir un `property_id`: es una ruta de colección, no de
  recurso. IF el tenant no tiene ninguna propiedad o ninguna tiene eventos, THEN THE SYSTEM
  SHALL devolver una página vacía con `200`, nunca `404` — a diferencia de la ruta por
  propiedad, aquí no hay un identificador de recurso que pueda no existir, así que no hay
  comprobación de propiedad previa.
- THE SYSTEM SHALL incluir en cada entrada, además de los siete campos que ya expone
  `GET /api/v1/timeline/{property_id}` (`id`, `occurred_at`, `actor_type`, `event_type`,
  `severity`, `title`, `description`), los campos `property_id`, `property_name` y
  `property_internal_code` de la vivienda que originó el evento — mismo patrón que
  `reservation-property-identity` fijó para reservas. `property_id` es siempre no nulo;
  `property_name` y `property_internal_code` viajan `null` cuando el `property_id` del evento
  no resuelve dentro del tenant (fila con clave ajena no compuesta con `tenant_id`, deuda
  registrada en `reservations.md`), lo que es una forma válida y nunca un motivo para descartar
  la entrada o fallar la petición. Las tres claves están siempre presentes.
- THE SYSTEM SHALL resolver `property_name` y `property_internal_code` con un lector por lotes
  (`PropertyRepository.list_for_ids`), **una sola vez por página y después de la consulta de
  eventos**, nunca una consulta por entrada: el número de sentencias es fijo (`count`, página,
  lote de propiedades), independiente de `per_page` y del número de propiedades del tenant.
- THE SYSTEM SHALL NOT serializar la columna `metadata` en esta ruta tampoco (misma ausencia
  estructural que la ruta por propiedad).
- THE SYSTEM SHALL gatear esta ruta con el mismo `READ_PROPERTIES` que la ruta por propiedad y
  SHALL NOT declarar un permiso nuevo: agregar por tenant no ensancha quién puede leer qué,
  porque cualquier portador de `READ_PROPERTIES` ya podía leer las mismas propiedades y el
  mismo timeline uno a uno.
- THE SYSTEM SHALL derivar el `tenant_id` del `RequestContext` autenticado y SHALL restringirlo
  explícitamente en la consulta de eventos y en la de identidad de propiedad (convención D2 de
  este documento), de modo que ningún evento ni ninguna identidad de otro tenant aparezca en la
  respuesta.
- THE SYSTEM SHALL componer `title` en el idioma de `preferred_language` del usuario
  autenticado contra el mismo catálogo de la sección «Textos legibles en el idioma del
  usuario», y SHALL devolver `description` verbatim, sin traducir, y SHALL NOT traducir los
  literales canónicos — mismas reglas que la ruta por propiedad, misma función `render()`.

### Textos legibles en el idioma del usuario

- WHEN el sistema compone una entrada de timeline o una etiqueta de card, THE SYSTEM SHALL
  renderizarla en el idioma de `preferred_language` del usuario autenticado, que viaja ya
  resuelto en el `RequestContext` (ver [`auth-tenancy.md`](auth-tenancy.md)) y no cuesta
  ninguna consulta adicional.
- THE SYSTEM SHALL derivar el `title` de cada entrada de su `event_type` y de su `metadata`
  contra un catálogo que cubre **los 47 valores de `TimelineEventType` en ambos idiomas**, y un
  test SHALL fallar si el enum crece sin que el catálogo lo siga.
- IF un `event_type` no tiene entrada en el catálogo, o le falta un dato de sustitución, THEN
  THE SYSTEM SHALL degradar al `title` almacenado en vez de fallar la petición.
- THE SYSTEM SHALL interpolar en las plantillas **solo** los valores de `metadata` que una
  lista blanca por tipo de evento autoriza, y sólo si son escalares acotados (texto de hasta 200
  caracteres, entero o decimal; nunca un booleano). Cualquier otro valor degrada la entrada al
  título almacenado. `metadata` es JSON libre escrito por cada capacidad que emite eventos, y
  sin la lista blanca su contenido acabaría en un texto que lee cualquier portador de
  `READ_PROPERTIES`.
- THE SYSTEM SHALL entregar `description` **tal cual, sin traducir**. Lo que los escritores
  guardan ahí es texto humano —el motivo que teclea una persona al bloquear una vivienda o
  ponerla fuera de servicio—, no texto de sistema: traducirlo sería reescribir lo que dijo un
  operador, y no hay `metadata` desde la que componerlo. Consecuencia aceptada: una entrada
  puede llegar con el `title` en el idioma de quien lee y la `description` en el idioma en que
  la escribió el operador. Un `event_type` cuya `description` sí sea generada por el sistema
  puede ganar plantilla más adelante sin cambiar el contrato.
- THE SYSTEM SHALL conservar la columna `title` almacenada **sin modificarla nunca**, como copia
  de auditoría en inglés, coherente con la norma de que los mensajes de sistema se escriben en
  inglés. Un test lo verifica releyendo la fila después de la petición HTTP.
- THE SYSTEM SHALL NOT traducir los literales canónicos —`PropertyOperationalState`,
  `event_type`, `actor_type`, `severity`—: viajan como valores exactos del PRD y el frontend los
  mapea.
- IF `users.preferred_language` contiene un valor no soportado —la columna es `String(5)` y no
  lo restringe—, THEN THE SYSTEM SHALL degradar al castellano en vez de fallar.
- THE SYSTEM SHALL alojar el **mecanismo** de localización en `app/core/i18n.py` (el tipo
  `Locale` y un `Catalog` que resuelve clave+idioma→plantilla) y las **tablas de mensajes** en el
  `domain/` de quien posee el vocabulario. Son `str` y `dict`, Python puro, sin framework.
- THE SYSTEM SHALL validar cada plantilla **al construir** el catálogo —rechazando campos
  posicionales, travesía de atributos o índices, especificadores de formato y conversiones—, de
  modo que un error de redacción sea un test en rojo y no un `500` en producción.

### Próxima acción

- WHEN se compone una card, THE SYSTEM SHALL derivar `next_action` del estado operacional con
  esta tabla determinista, exhaustiva sobre `PropertyOperationalState`:

  | Estado | Acción | Responsable |
  |---|---|---|
  | `AWAITING_CLEANING` | asignar limpiadora | manager |
  | `CLEANING_SCHEDULED` | pendiente de aceptar | limpiadora asignada |
  | `CLEANING_IN_PROGRESS` | limpieza en curso | limpiadora asignada |
  | `AWAITING_CHECKIN` | entregar acceso | manager |
  | `MAINTENANCE_REQUIRED` | revisar incidencia | — (ver nota) |
  | `CRITICAL_INCIDENT` | atender incidencia | — (ver nota) |
  | `OCCUPIED_ESTIMATED`, `READY_FOR_NEXT_GUEST`, `VACANT_READY`, `BLOCKED_BY_OWNER`, `OUT_OF_SERVICE` | `next_action: null` | — |

  La tabla es un `ASSUMPTION`: PRD §9.1 pide «próxima acción requerida y responsable» y da un
  ejemplo, pero no la define. Acordada en el gate de diseño del 2026-08-09.

  **Nota sobre los dos estados de incidencia.** Su acción es real (`review_incident`,
  `attend_incident`) y su responsable sigue viajando `null`. El motivo original era que nadie
  podía asignar un técnico; `maintenance` cerró eso el 2026-08-15 —ya hay
  `assigned_technician_id` y un rol `TECHNICIAN` con permisos— **y este read model no se
  revisó**: `Responsible` sigue teniendo dos miembros (`MANAGER`, `ASSIGNED_CLEANER`) y las dos
  entradas de `NEXT_ACTION_BY_STATE` siguen dando `None`
  (`backend/app/dashboard/domain/next_action.py`). Es deuda con dueño, no una decisión
  vigente: quien la cierre tiene que decidir si el responsable es el técnico asignado —y qué
  responde una incidencia sin asignar todavía—, y eso es una pregunta de producto, no una
  consulta más.
- THE SYSTEM SHALL expresar el responsable como un **rol**, no como una persona: resolver el
  nombre real cuesta una consulta más y «el manager» no está definido cuando un tenant tiene
  varios, decisión que el PRD no toma.
- IF se pide la próxima acción de un valor que no es un `PropertyOperationalState`, THEN THE
  SYSTEM SHALL fallar explícitamente en vez de devolver `null`, de modo que un estado nuevo
  rompa la suite en lugar de colarse en silencio.

### Permisos: agregar no concede

- THE SYSTEM SHALL declarar `require(Permission.READ_PROPERTIES)` en las seis rutas, de modo
  que `tests/test_route_authorization.py` las recorra.
- WHERE el rol que llama carece del permiso que protege el **origen** de un bloque, THE SYSTEM
  SHALL devolver ese bloque como `null` en vez de entregarlo, aunque la ruta se haya superado:
  `READ_RESERVATIONS` protege la reserva, el huésped y el total de la reserva;
  `READ_CLEANING_TASKS`, el estado de limpieza; `READ_ACCESS_RECORDS`, el bloque de acceso.

  El motivo es que **agregar no puede conceder**: `require()` acepta un solo permiso, así que
  una ruta con `READ_PROPERTIES` a secas entregaría en una respuesta lo que cuatro permisos
  distintos protegen por separado. Hoy no se observa —los dos roles con `READ_PROPERTIES` tienen
  los cuatro—, y se observaría en el primer rol que se añada, donde ya sería una fuga en
  producción y no una decisión de diseño.
- THE SYSTEM SHALL redactar el bloque **anulándolo, no omitiendo la clave**: el `null` de «no
  puedes verlo» es deliberadamente indistinguible del `null` de «no hay ninguno», y una clave
  que aparece y desaparece según el rol es en sí misma un canal.
- WHERE el rol tiene `READ_ACCESS_RECORDS` pero no `READ_RESERVATIONS`, THE SYSTEM SHALL leer
  igualmente la fila de reserva —porque el estado de acceso es una columna suya— pero SHALL NOT
  exponer ni la reserva, ni el huésped, ni el total de la reserva en el bloque financiero.
- THE SYSTEM SHALL decidir la autorización **antes** de consultar el recurso, de modo que un rol
  sin permiso reciba la misma respuesta para un `id` real y para uno inventado.

**Los contadores operacionales y la serie de ocupación redactan igual, pero un paso antes.**
Las otras tres rutas por propiedad consultan el bloque y lo anulan después si el permiso de
origen falta; `GET /api/v1/dashboard/operational-kpis` y `GET
/api/v1/dashboard/occupancy-series` deciden antes de consultar, no después. `operational-kpis`
comprueba primero `READ_CLEANING_TASKS` / `READ_RESERVATIONS` / `READ_INCIDENTS` para cada uno
de sus tres conteos; `occupancy-series` comprueba `READ_RESERVATIONS` una sola vez, porque la
serie entera es un único bloque. En los dos casos **no se emite ninguna consulta** si el rol
carece del permiso — un rol sin ninguno de los tres (hoy, `SUPER_ADMIN`) cuesta cero consultas
a los tres dominios de `operational-kpis`, no una consulta descartada, y el mismo rol cuesta
cero consultas a `occupancy-series`. El resultado observable es el mismo `null` de siempre; el
mecanismo que llega a él es distinto porque aquí no hay una raíz ya autorizada (la propiedad,
vía `READ_PROPERTIES`) de la que colgar el bloque — son conteos y series de tenant
independientes, cada uno protegido por el permiso de su propio dominio de origen.

**Alcance de esta regla, acotado el 2026-08-19 por `cleaner-task-context`.** Su sujeto es un
**agregado sobre una raíz que el llamante ya puede leer entera**: `GET /properties/{id}/dashboard`
entrega la propiedad, sus reservas, su dinero y sus huéspedes, así que la unión de cuatro permisos
*es* la respuesta, y ahí anular por permiso de origen es lo único que impide la fuga. No alcanza a
una **proyección que estrecha**: [`cleaner-task-context`](cleaner-task-context.md) sirve nueve
campos de `Property` y dos instantes derivados a un rol sin `READ_PROPERTIES`, sin importes, sin
huésped, sin notas y sin códigos de acceso, y sobre un conjunto de filas más estrecho que el que
ese permiso daría. La regla que sobrevive a las dos y que hay que citar la próxima vez: **una
proyección puede estrechar, nunca unir.** Un change que quiera añadir a una proyección un campo
que un permiso guarda *como un todo* —un importe de reserva, el nombre de un huésped— no lo añade
allí: pasa por esta sección.

### Aislamiento por tenant

- THE SYSTEM SHALL pasar el `tenant_id` explícito a cada método de repositorio, derivado
  únicamente del token, y SHALL NOT escribir ninguna comprobación de tenant a mano en los
  routers.
- IF el `property_id` no existe **o pertenece a otro tenant**, THEN THE SYSTEM SHALL responder
  `404` con un cuerpo **indistinguible** en ambos casos, en las tres rutas por propiedad.
- THE SYSTEM SHALL demostrar con tests, con el tenant vecino realmente sembrado, que un usuario
  del tenant A no lee propiedades, eventos ni agregados del tenant B por esta superficie. Los
  contadores operacionales tienen su propio test de aislamiento **por conteo** (limpiezas,
  check-ins, incidencias), sembrando en cada caso una fila del tenant vecino que el conteo
  contaría si el filtro fallara.

### Composición por lotes, sin N+1

- THE SYSTEM SHALL resolver la colección completa con un **número fijo de consultas**,
  independiente del número de propiedades, y un test SHALL demostrarlo contando las sentencias
  emitidas. No es una métrica: es un aserto con techo constante, porque un `for` que llame a un
  `get` por propiedad es sintácticamente idéntico al código correcto.
- THE SYSTEM SHALL obtener cada bloque mediante un lector por lotes en el puerto **del dominio
  que posee el dato**, y agrupar en memoria. THE SYSTEM SHALL NOT crear un repositorio que haga
  JOIN entre las siete tablas: sería el segundo sitio donde se escribe el scope de tenant.
- THE SYSTEM SHALL crear en `maintenance` y `statements` **sólo la mitad de lectura** de su
  primer puerto —sin `add`, sin `save`—: la escritura llega con esos changes, y la firma es
  donde eso queda dicho.
- THE SYSTEM SHALL devolver los mapas por lotes **dispersos**: una propiedad sin eventos o sin
  incidencias está ausente del mapa, no mapeada a `None` o a `0`.

## Deuda declarada

- **`notes` viaja siempre `null`** (`ASSUMPTION`). PRD §9.2 lista «notas», pero ninguna columna
  las posee: los únicos candidatos —`access_notes`, `cleaning_notes`, `emergency_notes`— están
  registrados como sumideros de texto en claro donde «un operador puede pegar el código de la
  puerta o la clave del wifi». Volcar uno en una respuesta que lee cualquier portador de
  `READ_PROPERTIES` publicaría justo lo que el resto del sistema cifra y enmascara. El campo se
  queda en el contrato para que `dashboard-web` no cambie de forma dos veces, y lo rellena el
  change que dé a las notas de operación una columna propia. Un test afirma que el agregado
  nunca devuelve el contenido de ninguna de las tres columnas.
- **`last_cleaning_photos` viaja siempre `[]`** (`EXTERNAL_DEPENDENCY`). `cleaning_photos`
  persiste un `storage_key`, no una URL, y firmarla es `StorageAdapter.get_signed_url`, que
  entrega `cleaning-photos-storage`. THE SYSTEM SHALL NOT construir ninguna URL de
  almacenamiento ni exponer el `storage_key`.
- **`incidents` y `owner_approvals` ya llegan poblados** desde `maintenance` (2026-08-15); **los
  gastos siguen llegando vacíos** hasta que `revenue` los pueble. Las tres tablas se leen, no se
  escriben aquí, y esa separación es la que permitió que los dos primeros bloques pasaran de
  vacíos a reales sin tocar el agregado.
- **`check_in` / `check_out` viajan como fecha**, no como instante, aunque el contrato del
  frontend los tipa como fecha-hora ISO. Es una divergencia deliberada: la columna es una fecha
  y fabricar una hora sería inventar precisión.
- **«Abierta» para contar incidencias** es un conjunto de estados elegido aquí (`ASSUMPTION`):
  el PRD pide el contador sin definir dónde cae la línea.
- **Sin realtime**: PRD §9.2 dice «timeline en tiempo real» y esta capacidad entrega lectura con
  filtros y paginación. Empujar cambios al cliente (WebSocket/SSE) no está entregado por ninguna
  de las dos mitades.
- **`description` es el primer campo de texto libre que esta capacidad publica.** No está entre
  las columnas enumeradas como sumideros de texto en claro, pero es de la misma clase. Hoy no
  hay cruce de privilegio —los dos roles con `READ_PROPERTIES` tienen también
  `READ_ACCESS_RECORDS`—, así que la decisión de publicarla se toma a sabiendas; **el primer rol
  de sólo-auditoría que se añada obliga a revisarla.**

## Key files

- `backend/app/dashboard/api/` — `router.py` (las cuatro rutas del agregado), `schemas.py` (los
  modelos de respuesta y su `from_domain` explícito), `dependencies.py` (el wiring, que compone
  adaptadores ajenos).
- `backend/app/dashboard/application/use_cases.py` — `GetDashboardCardsUseCase`,
  `GetPropertyDashboardUseCase`, `GetOperationalKpisUseCase` y `GetOccupancySeriesUseCase`: la
  composición por lotes (la primera y la última), por conteo directo (la tercera), y la
  redacción por permiso.
- `backend/app/dashboard/domain/` — `read_models.py` (proyecciones `frozen`, incluidas
  `OperationalKpis` y `OccupancyPoint`), `labels.py` (los seis catálogos de etiquetas,
  exhaustivos sobre sus enums), `next_action.py` (la tabla de próxima acción), `financials.py`
  (la regla de moneda), `occupancy.py` (`week_bounds`, `occupancy_series`: la definición de
  "noche ocupada", Python puro sin I/O, `dashboard-occupancy-series` R1-R2).
- `backend/app/cleaning/domain/repositories.py` /
  `backend/app/cleaning/infrastructure/repositories.py` — `count_live_for_day`.
- `backend/app/reservations/domain/repositories.py` /
  `backend/app/reservations/infrastructure/repositories.py` — `count_check_ins_in_range`,
  `list_for_properties` (reutilizado por `occupancy-series`).
- `backend/app/maintenance/domain/repositories.py` /
  `backend/app/maintenance/domain/value_objects.py` (`OpenIncidentCounts`) /
  `backend/app/maintenance/infrastructure/repositories.py` — `count_open_for_tenant`.
- `backend/app/properties/domain/repositories.py` /
  `backend/app/properties/infrastructure/repositories.py` — `PropertyStateTransitionRepository
  .history_for_properties` (`dashboard-occupancy-series` R3): el historial por lotes que
  reconstruye el estado de cada vivienda a lo largo de la semana, sin escritura.
- `backend/app/timeline/api/` — `router.py` (las dos rutas, por propiedad y de tenant),
  `schemas.py` (`TimelineEntryResponse`/`TimelinePageResponse` y, por herencia,
  `TenantTimelineEntryResponse`/`TenantTimelinePageResponse` de `dashboard-activity-feed`),
  `errors.py`, `dependencies.py`: la capa `api/` que el módulo estrena.
- `backend/app/timeline/application/use_cases.py` — `GetPropertyTimelineUseCase` y
  `ListTenantActivityUseCase` (`dashboard-activity-feed`): la segunda compone
  `TimelineEventReader.list_for_tenant` con `PropertyRepository.list_for_ids` en un número
  fijo de sentencias, sin `PropertyRepository.get` previo ni `404` — es una ruta de colección.
- `backend/app/timeline/domain/read_models.py` — `TenantActivityEntry` (`dashboard-activity-feed`):
  los siete campos de `RenderedEntry` más la identidad de la propiedad, y `from_rendered`;
  Python puro, sin tocar `rendering.py`.
- `backend/app/timeline/domain/rendering.py` — el catálogo de 47 tipos × 2 idiomas, la lista
  blanca de metadata sustituible y `render`, reutilizado sin cambios por las dos rutas.
- `backend/app/timeline/domain/repositories.py` — `TimelineEventReader`, separado del escritor
  (ver [`timeline-state-machine.md`](timeline-state-machine.md)): `list_for_property`,
  `list_for_tenant` (`dashboard-activity-feed`) y `last_for_properties`.
- `backend/app/timeline/infrastructure/models.py` — `ix_timeline_events_tenant_id_created_at`
  (`dashboard-activity-feed`), el índice que cubre `list_for_tenant` sin filtro.
- `backend/app/core/i18n.py` — `Locale` y `Catalog`: el mecanismo, sin mensajes.
- `backend/app/auth/domain/context.py` — `RequestContext.preferred_language`.
- `backend/app/maintenance/`, `backend/app/statements/`, `backend/app/guests/`,
  `backend/app/cleaning/`, `backend/app/properties/` — los lectores por lotes que cada dominio
  aporta a la composición.
- `backend/tests/dashboard/`, `backend/tests/timeline/`, `backend/tests/test_i18n.py` — el
  conteo de sentencias, el aislamiento, la matriz de roles, la cobertura del enum y la
  degradación. `backend/tests/dashboard/test_occupancy_series.py` cubre `occupancy_series` y
  `week_bounds` en aislamiento (sin base de datos); `test_isolation.py`,
  `test_no_n_plus_one.py`, `test_api.py` y `test_use_cases.py` cubren la ruta completa.
