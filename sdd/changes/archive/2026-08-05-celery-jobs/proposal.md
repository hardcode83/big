# Proposal: celery-jobs

## Why

La propiedad es una máquina de estados (principio 1 de `steering/product.md`), pero
**hoy nadie la mueve con el reloj**. `timeline-state-machine` entregó
`PropertyStateMachine` como dominio puro —evalúa una solicitud y devuelve
`PropertyStateTransition` + `TimelineEvent`— y `backend/app/properties/` sigue sin
`application/` ni `api/`: no existe ningún caso de uso que persista un cambio de estado
operacional, y `PropertyRepository` ni siquiera expone `save`. Consecuencia medible: una
reserva importada por `pms_sync` deja la propiedad en el estado en que estaba, y
`current_operational_state` solo cambia si alguien edita la fila a mano.

PRD §8.3 define seis jobs Celery que son el motor que faltaba, y PRD §14 define el
`check_sla_breaches` que hace que un SLA incumplido escale en vez de quedarse callado.
El worker Celery existe desde `local-environment` pero `backend/app/worker.py` son cinco
líneas sin una sola tarea, y ningún compose declara un `beat`.

Además, `backend/app/core/db.py:78` documenta que **las tareas Celery corren con sesión
sin marcar**, así que el filtro global de tenant está apagado para ellas. Ese hueco es
teórico mientras no haya tareas; deja de serlo con este change, que es el primero en
introducirlas.

Fuente: PRD §26.8, §8.1-8.3, §14 y la entrada `celery-jobs` de `sdd/roadmap.md`.

## What changes

Existirá un **scheduler operativo**: un servicio `beat` en los dos composes, un registro
de tareas periódicas en `app/worker.py` y cuatro jobs con las cadencias de PRD §8.3. Tres
de ellos mueven la máquina de estados con el reloj —`check_checkin_windows`,
`mark_occupied_estimated`, `process_checkouts`— y por tanto este change aporta la
**primera capa de aplicación de `properties`**: el caso de uso que evalúa la transición
contra `PropertyStateMachine`, actualiza `current_operational_state` y persiste
`PropertyStateTransition` + `TimelineEvent` en una sola transacción. El cuarto,
`check_sla_breaches`, detecta `NotificationLog` con SLA vencido, lo marca y **deja
escrita** la notificación de escalado en estado pendiente, sin enviarla. Todo ello
ejecutándose fuera de un contexto de petición, con una sesión marcada por tenant y sin
solaparse consigo mismo.

## Requirements

### R1 — Scheduler declarado y desplegable

**Como** operador, **quiero** que las tareas periódicas se disparen solas en dev y en el
entorno desplegado, **para que** el estado de las propiedades no dependa de que alguien
ejecute un comando.

Criterios de aceptación:

1. THE SYSTEM SHALL declarar el calendario de tareas periódicas **en código** (la
   configuración de la app Celery), no en un crontab del host ni en un fichero fuera de
   la imagen.
2. THE SYSTEM SHALL registrar exactamente las cadencias de PRD §8.3 para los jobs en
   alcance: `check_checkin_windows` cada 5 min, `process_checkouts` cada 5 min,
   `mark_occupied_estimated` cada 5 min y `check_sla_breaches` cada minuto.
3. WHEN se ejecuta `make up`, THE SYSTEM SHALL arrancar un servicio `beat` junto a
   `worker`, con la misma imagen y las mismas dependencias de arranque (`postgres`,
   `redis`, `migrate` completado).
4. THE SYSTEM SHALL declarar el mismo servicio en `docker-compose.deploy.yml` con
   healthcheck, igual que `app-deploy-dev` ya exige para `worker`.
5. WHERE haya más de una réplica del scheduler, THE SYSTEM SHALL seguir produciendo como
   mucho una ejecución por tarea y ventana — el despliegue nunca debe poder duplicar
   transiciones por relanzar `beat`.
6. IF una tarea lanza una excepción no controlada, THEN THE SYSTEM SHALL registrarla y
   dejar que el resto de tareas y de la siguiente ventana sigan ejecutándose; un fallo no
   SHALL detener el scheduler.

### R2 — Ejecución multi-tenant con el aislamiento intacto

**Como** responsable de seguridad, **quiero** que un job que recorre todos los tenants no
sea el agujero por el que se anula el aislamiento, **para que** la regla 1 de
`steering/security.md` siga siendo absoluta también fuera del ciclo de petición.

Criterios de aceptación:

1. WHEN una tarea procesa el trabajo de un tenant, THE SYSTEM SHALL usar una sesión
   **marcada con ese tenant** mediante `bind_session_to_tenant`, de modo que el filtro
   global de `_scope_statement_to_tenant` esté activo.
2. THE SYSTEM SHALL abrir **una sesión por tenant** y no SHALL reutilizar una sesión
   marcada para un segundo tenant ni intentar desmarcarla: `bind_session_to_tenant` ya lo
   rechaza y el job no SHALL sortearlo por otra vía (`session.info`, sesión sin marcar,
   SQL en crudo).
3. THE SYSTEM SHALL filtrar `tenant_id` explícitamente en cada consulta y comprobarlo en
   cada escritura, porque el filtro global no cubre los `INSERT` (límite 3 de
   `app/core/db.py`).
4. WHEN existan varios tenants con trabajo pendiente en la misma ventana, THE SYSTEM SHALL
   demostrar con test que el procesamiento del tenant A no lee, escribe ni transiciona
   nada del tenant B.
5. IF el trabajo de un tenant falla, THEN THE SYSTEM SHALL continuar con los demás
   tenants e informar del fallo por tenant; un tenant roto no SHALL impedir que los otros
   avancen.
6. THE SYSTEM SHALL enumerar los tenants desde una sesión **nunca marcada**, la única vía
   soportada para leer una tabla no acotada, y no SHALL usar esa sesión para ningún dato
   de dominio.

### R3 — Transiciones dependientes del reloj, persistidas

**Como** propietaria, **quiero** que el estado de la vivienda avance solo cuando llega la
hora, **para que** el dashboard diga la verdad sin que nadie toque nada.

Criterios de aceptación:

1. WHEN una reserva confirmada tiene entrada hoy y falta menos de
   `TenantConfig.checkin_window_hours_before` para la hora de check-in, THE SYSTEM SHALL
   transicionar la propiedad a `AWAITING_CHECKIN`.
2. WHEN se alcanza la hora de check-in de una reserva confirmada, THE SYSTEM SHALL
   transicionar la propiedad a `OCCUPIED_ESTIMATED`.
3. WHEN se alcanza la hora de check-out de la reserva activa, THE SYSTEM SHALL
   transicionar la propiedad a `AWAITING_CLEANING`.
4. THE SYSTEM SHALL resolver toda transición a través de `PropertyStateMachine`,
   entregándole un instante de referencia explícito y un actor `SYSTEM`, y no SHALL
   escribir `current_operational_state` por ninguna otra vía.
5. IF la propiedad no está en un estado de origen válido para ese trigger, THEN THE
   SYSTEM SHALL saltarla sin escribir nada y sin propagar el error de dominio como fallo
   de la tarea: una propiedad en `CRITICAL_INCIDENT` no se mueve porque llegue una hora.
6. WHEN una transición se acepta, THE SYSTEM SHALL persistir en **una única transacción**
   el nuevo `current_operational_state`, la fila de `PropertyStateTransition` y el
   `TimelineEvent` `PROPERTY_STATE_CHANGED` con el `correlation_id` compartido que el
   dominio ya produce; un fallo al escribir cualquiera de las tres SHALL dejar las tres
   sin escribir.
7. THE SYSTEM SHALL calcular las horas en la **zona de la propiedad**
   (`Property.timezone`), no en la del servidor ni en la del tenant, y SHALL comparar
   instantes efectivos en UTC.
8. WHERE la reserva no declara `check_in_time`/`check_out_time`, THE SYSTEM SHALL usar
   `default_check_in_time`/`default_check_out_time` de la propiedad.
9. IF la hora local resultante es inexistente o ambigua por el cambio de hora, THEN THE
   SYSTEM SHALL respetar la política que `timeline-state-machine` ya fija —rechazo en el
   salto de primavera, `fold` explícito en el de otoño— y SHALL registrar el caso en vez
   de normalizarlo en silencio.

### R4 — Idempotencia y no solapamiento

**Como** desarrollador, **quiero** que ejecutar un job dos veces sea inofensivo, **para
que** un reintento, un solape o un redespliegue no dupliquen historia.

Criterios de aceptación:

1. WHEN una tarea vuelve a ejecutarse sobre un estado ya alcanzado, THE SYSTEM SHALL no
   escribir ni fila de transición ni evento de timeline: el destino igual al estado
   actual ya es un rechazo del dominio y el job SHALL tratarlo como trabajo hecho, no
   como error.
2. WHILE una ejecución de una tarea sigue viva, THE SYSTEM SHALL impedir que una segunda
   ejecución de esa misma tarea la solape, y la segunda SHALL terminar informando que se
   saltó, no fallando.
3. THE SYSTEM SHALL acotar en el tiempo el mecanismo de exclusión, de modo que un worker
   muerto a mitad no deje la tarea bloqueada para siempre.
4. THE SYSTEM SHALL demostrar con test que dos ejecuciones consecutivas sobre el mismo
   conjunto de datos producen exactamente las mismas filas que una.

### R5 — SLA vencido: detectado, marcado y escalado en base de datos

**Como** manager, **quiero** que un aviso con SLA incumplido genere su escalado, **para
que** una limpieza sin aceptar no se quede muerta.

Criterios de aceptación:

1. WHEN un `NotificationLog` cumple `status = SENT`, `sla_deadline_at IS NOT NULL`,
   `sla_deadline_at < now()` y `sla_breached = FALSE`, THE SYSTEM SHALL marcarlo
   `sla_breached = TRUE` y crear la notificación de escalado que corresponda a su
   `notification_type`.
2. THE SYSTEM SHALL crear el escalado como una fila de `NotificationLog` en estado
   **pendiente**, y no SHALL intentar entregarlo por ningún canal: el envío y el
   `NotificationAdapter` pertenecen a `access-notifications`.
3. THE SYSTEM SHALL escribir en una única transacción la marca y la fila de escalado, de
   modo que no exista un `sla_breached = TRUE` sin su escalado ni un escalado duplicado.
4. WHEN el job vuelve a correr, THE SYSTEM SHALL no reescalar lo ya marcado.
5. THE SYSTEM SHALL cumplir la regla 11 de `steering/security.md` en las filas que crea:
   `subject`/`body` solo admiten el `****XX` de un código de acceso, y `last_error` va en
   forma estructurada, nunca el texto crudo de una excepción.
6. IF un `notification_type` no tiene acción de escalado definida, THEN THE SYSTEM SHALL
   marcarlo como incumplido y registrarlo sin inventar un destinatario.

### R6 — Coste del filtro global, medido y documentado

**Como** desarrollador, **quiero** saber lo que cuesta el filtro global bajo carga real,
**para que** la decisión de no memoizarlo se sostenga sobre un número y no sobre una
intuición.

Criterios de aceptación:

1. THE SYSTEM SHALL medir el coste que `_scope_statement_to_tenant` añade por sentencia
   con las clases acotadas que existan al ejecutar la medición, en el job de cadencia de
   un minuto, que es el consumidor de mayor frecuencia del proyecto.
2. THE SYSTEM SHALL documentar el método y el resultado de forma reproducible, de modo
   que una medición posterior sea comparable.
3. IF la medición muestra un coste que justifique cambiar el diseño, THEN THE SYSTEM
   SHALL registrar la deuda con dueño explícito en lugar de optimizar aquí: la decisión
   de no memoizar tiene su razón escrita en `app/core/db.py:55-61` y revertirla es un
   change propio.

## Out of scope

- **Crear la `CleaningTask` en `process_checkouts`** (PRD §8.3 y
  `TenantConfig.auto_create_cleaning_task`) → `cleaning`, que es dueño de esa entidad y
  de sus invariantes. Consecuencia asumida y explícita: hasta que llegue esa entrada,
  `AWAITING_CLEANING` es un estado terminal en la práctica y la precedencia contextual de
  `timeline-state-machine` verá siempre «sin limpieza pendiente».
- **Envío real de notificaciones y el puerto `NotificationAdapter`** (PRD §14) →
  `access-notifications`, primer escritor y dueño del adapter. Aquí solo se escriben filas
  pendientes.
- **`generate_price_recommendations`** (PRD §8.3, diario 06:00) → `revenue`.
- **`send_checkin_reminders`** (PRD §8.3, cada hora) → `messaging-ai` /
  `access-notifications`: son mensajes al huésped, no transiciones de estado.
- **`process_webhook_events`** → `reservations-webhooks`, que es donde nace el endpoint
  que los produce.
- **Escalado telefónico** (`PhoneAdapter.call` de PRD §14 para `TECHNICIAN_ASSIGNED` +
  CRITICAL): no existe tal puerto en el proyecto. Se escala al manager y se documenta.
- **`AuditLog` de las transiciones**: el actor es `SYSTEM` y el rastro es el
  `TimelineEvent`, igual que decidió `reservations`. Si se añade, se añade con esa entrada.
- **Endurecer Redis** (loopback + `requirepass`) → `local-dev-network-hardening`, que ya
  lo tiene en el roadmap. Este change lo agrava —Redis pasa a ser también el broker del
  scheduler y el soporte de la exclusión de R4— y conviene decirlo en su design, pero
  arreglarlo aquí sería robarle el alcance.
- **API para disparar jobs a mano** y **frontend**: nadie los ha pedido; el dashboard es
  de `dashboard-web`.

## Affected specs

- `sdd/specs/celery-jobs.md` — *(no existe aún — se creará al archivar)*
- `sdd/specs/timeline-state-machine.md` — gana su primer consumidor que **persiste**
  transiciones de estado; hoy afirma que la capacidad no toca base de datos y eso sigue
  siendo cierto del dominio, pero deja de serlo de la cadena completa.
- `sdd/specs/reservations.md` — retira de su «Purpose» la exclusión *«ni transiciones de
  estado operacional dependientes del reloj (`celery-jobs`)»*.
- `sdd/specs/auth-tenancy.md` — su línea 178 enumera las tareas Celery entre las sesiones
  sin marcar; con R2 pasan a estar marcadas por tenant.
- `sdd/specs/local-environment.md` — líneas 17 y 51: nuevo servicio `beat` y el worker
  deja de ser «una app Celery mínima sin tareas reales».
- `sdd/specs/app-deploy-dev.md` — línea 27: el servicio `beat` y su healthcheck en el
  compose de despliegue.
- `sdd/specs/domain-foundation-financial.md` — su bullet de la regla 11 dice todavía «las
  otras cinco columnas siguen sin escritor» y atribuye a `access-notifications` las **tres**
  de `notification_logs`. Desde este change son dos, y `subject`/`body` ya tienen contrato con
  tests. Al archivar, ese bullet pasa a remitir a la tabla de `steering/security.md` en vez de
  re-listar dueños — cuatro copias de la misma señalización es exactamente cómo se
  desincronizó. Lo localizó el panel de seguridad de la sección 7.
- `sdd/roadmap.md` — **ya corregido en este change, no aplazado**: la entrada
  `access-notifications` era la **quinta** copia de la misma señalización y también había
  quedado falsa (decía heredar la regla 11 para `subject`/`body`/`last_error` y ser «el primer
  escritor de la tabla»). Ahora hereda solo `last_error` y remite al steering. La encontró la
  re-revisión de seguridad, después de que la corrección de la cuarta copia diera el recuento
  por cerrado — que es justamente el argumento para dejar de repetir la señalización.
