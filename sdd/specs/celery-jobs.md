# Jobs programados (Celery beat)

## Purpose

Esta capacidad es el reloj del sistema: mueve el estado operacional de las viviendas cuando
llega la hora y escala los SLA vencidos, sin que nadie ejecute nada. Es quien **conduce** la
máquina de estados que `timeline-state-machine` dejó como decisión pura — hasta esta
capacidad `current_operational_state` solo cambiaba editando la fila a mano — y aporta por
tanto la primera capa de aplicación de `properties` y de `notifications`.

Corre fuera de cualquier petición, así que resuelve por su cuenta lo que un endpoint recibe
del token: qué tenant, con qué sesión y bajo qué transacción.

Cómo se opera, cómo se lee su informe y qué límites tiene: [`docs/celery-jobs.md`](../../docs/celery-jobs.md).

## Requirements

### El calendario y su despliegue

- THE SYSTEM SHALL declarar el calendario de tareas periódicas en código, dentro de la imagen,
  y no en un crontab del host.
- THE SYSTEM SHALL registrar los cuatro nombres literales de PRD §8.3 con sus cadencias:
  `check_checkin_windows`, `process_checkouts` y `mark_occupied_estimated` cada 5 minutos, y
  `check_sla_breaches` cada minuto.
- THE SYSTEM SHALL registrar el quinto nombre de PRD §8.3, `generate_price_recommendations`,
  **a una hora del día y no a una cadencia**: es el único job del calendario que corre «diario
  06:00» y no cada N minutos ([`revenue-pricing`](revenue-pricing.md) R4.1). Un
  `timedelta(days=1)` no serviría: dispararía 24 h después de arrancar beat en vez de a la hora
  que el PRD nombra.
- THE SYSTEM SHALL registrar además las cuatro tareas que PRD §8.3 no nombra: `dispatch_notifications`
  cada minuto y `provision_access_records` cada 5 minutos, las dos de `access-notifications`,
  `process_webhook_events` cada 60 segundos, de `reservations-webhooks`, y `classify_incidents`
  cada 5 minutos, de [`maintenance.md`](maintenance.md). El PRD dice qué debe
  ocurrir, no qué lo dispara, así que nombrarlas fue una decisión de cada change y no una
  contradicción; los cuatro originales no se tocaron. `dispatch_notifications` va a un minuto porque
  una fila solo puede incumplir su plazo **después** de entregarse: un emisor más lento retrasaría
  cada escalado en su propia cadencia.
- THE SYSTEM SHALL tratar la cadencia de `process_webhook_events` como un **parámetro de seguridad,
  no de tuning**: ese job coalesce todo un tick en una llamada saliente por destino
  (`specs/reservations-webhooks.md`), así que su cadencia **es** el techo de llamadas al proveedor y
  acortarla lo sube. Los 60 segundos van holgados frente al techo de cuota medido en
  `specs/pms-beds24-spike.md` (un ciclo de sync por cuenta cada 30 s).
- THE SYSTEM SHALL sostener el calendario sobre **dos tablas y un solo derivador**: `CADENCES`
  para los jobs periódicos y `DAILY_JOBS` para los de hora del día, con `beat_schedule()`
  derivado de las dos. La partición no es cosmética: un job periódico saca el TTL de su lock del
  **mismo** número que usa beat mediante `lock_ttl_for`, así que una cadencia no puede cambiarse
  en un sitio y quedar rancia en el otro.
- THE SYSTEM SHALL derivar el `beat_schedule` y el TTL del lock de cada tarea periódica de
  `CADENCES`, de modo que no puedan desincronizarse.
- THE SYSTEM SHALL declarar el TTL del lock de un job diario **explícitamente** y no por la
  derivación de `lock_ttl_for`: esa función devuelve cadencia x 3, que sobre un job diario son
  tres días, y un worker muerto a mitad de ejecución dejaría el job encallado hasta el jueves.
  `generate_price_recommendations` lleva 3 h — holgado frente a una ejecución de minutos y muy
  por debajo de la ventana siguiente.
- THE SYSTEM SHALL interpretar la hora de un job diario en **UTC**, porque el proceso fija
  `celery_app.conf.timezone = "UTC"` y nunca interpreta zonas; las horas locales se derivan de
  la zona de cada vivienda. Una fila de calendario por zona de tenant serían N filas compradas
  para nada en un job que planifica un horizonte de 60 días.
- WHEN se ejecuta `make up`, THE SYSTEM SHALL arrancar un servicio `beat` junto a `worker`, con
  la misma imagen y las mismas dependencias de arranque.
- THE SYSTEM SHALL declarar `beat` también en el compose de despliegue, en la red `private` y
  con healthcheck propio. `celery inspect ping` no sirve: ese protocolo lo responde un
  *worker*, así que el healthcheck comprueba que PID 1 sigue siendo beat, en Python y no con
  `pgrep`, que no existe en la imagen base.
- THE SYSTEM SHALL ejecutar `beat` como servicio propio y no como `worker --beat`: con más de
  un worker, el beat embebido dispararía cada tarea N veces.
- IF una tarea lanza una excepción no controlada, THEN THE SYSTEM SHALL registrarla sin
  detener el scheduler ni las ventanas siguientes.

### Ejecución multi-tenant

- WHEN una tarea procesa el trabajo de un tenant, THE SYSTEM SHALL usar una sesión marcada con
  ese tenant mediante `bind_session_to_tenant`, de modo que el filtro global de
  `_scope_statement_to_tenant` esté activo.
- THE SYSTEM SHALL abrir una sesión nueva por tenant y no SHALL reutilizar una marcada para un
  segundo tenant ni desmarcarla por ninguna vía.
- THE SYSTEM SHALL enumerar los tenants activos desde una sesión **nunca marcada**, cerrada
  antes de que empiece el trabajo de ningún tenant, y no SHALL usarla para dato de dominio
  alguno.
- THE SYSTEM SHALL filtrar `tenant_id` explícitamente en cada consulta y comprobarlo en cada
  escritura, porque el filtro global no cubre los `INSERT`.
- IF el trabajo de un tenant falla, THEN THE SYSTEM SHALL hacer rollback de su sesión,
  registrar el fallo con su `tenant_id` y continuar con los demás; la tarea termina con éxito
  informando de los fallos. Solo un fallo **anterior** al bucle —Redis, o la enumeración de
  tenants— hace fallar la tarea.
- THE SYSTEM SHALL construir recursos **por ejecución** y no cacheados por proceso: engine con
  `NullPool` propio del worker y cliente Redis por ejecución. Cada tarea corre su corrutina
  con `asyncio.run`, que cierra su bucle al terminar, así que cualquier conexión cacheada
  quedaría atada a un bucle muerto y la siguiente ejecución del proceso fallaría.

### Transiciones dependientes del reloj

- WHEN una reserva confirmada entra hoy y ha llegado la ventana de
  `TenantConfig.checkin_window_hours_before`, THE SYSTEM SHALL transicionar la propiedad a
  `AWAITING_CHECKIN`.
- WHEN se alcanza la hora de check-in, THE SYSTEM SHALL transicionar a `OCCUPIED_ESTIMATED`.
- WHEN se ha pasado la hora de check-out, THE SYSTEM SHALL transicionar a `AWAITING_CLEANING`
  **y crear la `CleaningTask`** en la misma transacción, honrando
  `TenantConfig.auto_create_cleaning_task` y `Reservation.cleaning_required`.
- IF la creación no procede —configuración desactivada, `cleaning_required` falso, ya hay una
  tarea viva para esa reserva, o no hay plantilla de checklist resoluble—, THEN THE SYSTEM SHALL
  transicionar igualmente y contarlo aparte en `transitioned_without_task`, sin fallar la
  ejecución del tenant. El detalle de la creación vive en `cleaning.md`.
- THE SYSTEM SHALL resolver toda transición a través de `PropertyStateMachine`, con un instante
  de referencia explícito y actor `SYSTEM`, y no SHALL escribir `current_operational_state` por
  ninguna otra vía.
- THE SYSTEM SHALL preguntar a la máquina por **cada** reserva candidata y clasificar por su
  veredicto; no SHALL decidir por su cuenta que una reserva no vence. La única política propia
  del job es la ventana de check-in, que es elección del operador sobre *cuándo* dentro del día
  legal, no sobre qué es legal.
- WHEN dos reservas de una propiedad obtienen veredicto favorable a la vez, THE SYSTEM SHALL
  saltar esa propiedad informándolo, y no SHALL elegir una.
- WHEN una transición se acepta, THE SYSTEM SHALL persistir en una única transacción el nuevo
  `current_operational_state`, la fila de `property_state_transitions` y el `TimelineEvent`
  `PROPERTY_STATE_CHANGED`, compartiendo `correlation_id`.
- THE SYSTEM SHALL calcular las horas en la zona de cada propiedad, no en la del servidor, y
  comparar instantes en UTC. WHERE la reserva no declara hora, SHALL usar la de la propiedad.
- IF la hora local de una reserva no existe o es ambigua por el cambio de hora, THEN THE SYSTEM
  SHALL contarla aparte de «aún no toca» y seguir con las demás; esa propiedad no avanza sola
  y necesita intervención.
- THE SYSTEM SHALL acotar la búsqueda de reservas a 2 días de adelanto y 30 de retraso. El
  adelanto está derivado —los triggers de entrada están acotados al día local y ninguna zona
  IANA se aleja más de 24 h—; el retraso es un límite operativo, porque un check-out vencido
  sigue venciendo y una caída del worker más larga deja la propiedad atascada.

### Desajustes entre el calendario y el estado

- WHEN el calendario exige un trigger de reloj sobre una reserva y el estado operacional de su
  vivienda no admite ese trigger, THE SYSTEM SHALL registrar el desajuste identificando la
  vivienda, la reserva, el trigger y el estado que lo impide, y SHALL contarlo en el cubo
  `blocked` de `AdvanceReport`.
- THE SYSTEM SHALL derivarlo **fuera de la consulta de candidatas**, sobre el complemento de los
  estados origen del trigger (`PropertyOperationalState` menos `source_states_for(trigger)`): una
  vivienda atascada no es candidata **por definición**, así que ningún cubo de esa consulta puede
  contarla. Es el único contador del informe que no se deriva de ella.
- THE SYSTEM SHALL NOT contabilizarlo como `not_eligible`, que significa «la hora aún no ha
  llegado». Confundir las dos cosas es exactamente lo que mantuvo invisible una vivienda parada
  desde el 2026-08-16 hasta que se operó `dev` el 2026-08-22: el informe decía `candidates: 0` y
  `not_eligible: 0`, y era cierto — la vivienda no entraba en él.
- THE SYSTEM SHALL considerar atascada una reserva sólo si se cumplen **todas** estas
  condiciones, y las dos últimas no son refinamientos: sin ellas el cubo mide el tamaño de la
  cartera activa y no el atasco, porque `is_due` de `CHECKIN_TIME_REACHED` es verdad durante toda
  la estancia y el de `CHECKOUT_TIME_REACHED` lo es para siempre después del checkout.
  1. La hora ha llegado, resuelto por `PropertyStateMachine.is_due`, que valida las precondiciones
     temporales del trigger **sin consultar la matriz** —la pregunta «¿vence?» es independiente de
     «¿es legal?»—. WHERE el trigger es `CHECKIN_WINDOW_OPENED`, THE SYSTEM SHALL exigir además la
     ventana del operador (`opens_checkin_window` sobre `TenantConfig.checkin_window_hours_before`),
     que es política del job y no de la máquina, igual que en la transición.
  2. El estado de la vivienda **no es origen** del trigger.
  3. **No consta que esa transición se haya aplicado ya para esa reserva.**
  4. El estado **no es destino** del trigger cuando ésa es la **única** estancia vencida para él.
- THE SYSTEM SHALL contestar «¿se aplicó ya?» con la evidencia que ya existía:
  `PropertyStateTransitionRepository.applied_clock_triggers` lee `reservation_id` y `trigger` del
  `metadata` de `property_state_transitions` **como texto**, acotada al tenant y a las reservas de
  la ventana, y no SHALL reconstruir el enum desde datos almacenados.
- WHERE dos estancias solapadas están vencidas para el mismo trigger, THE SYSTEM SHALL abstenerse
  del atajo del destino: resolver una no SHALL ocultar el atasco de la otra.
- THE SYSTEM SHALL contar **viviendas** en `blocked` —la misma precedencia «un cubo por vivienda»
  que el resto del informe— y emitir **una línea por desajuste** en
  `scheduler.blocked_transition`, con vivienda, reserva, trigger, estado que bloquea e instante
  vencido. Dos estancias solapadas dan `blocked = 1` y dos líneas.
- THE SYSTEM SHALL no escribir nada al detectar, y SHALL derivar el desajuste en cada ejecución:
  no hay fila que marcar ni cerrar, así que un atasco deja de contarse y de listarse en cuanto se
  resuelve, sin intervención manual.
- THE SYSTEM SHALL acotar la detección a la **misma** `candidate_window` que las candidatas —30
  días atrás, 2 adelante— sin horizonte propio, y SHALL declarar en `docs/celery-jobs.md` que un
  atasco de más de 30 días deja de aparecer y necesita una transición manual. Es el precio del
  límite, el mismo que `CANDIDATE_LOOKBEHIND` ya paga para los checkouts pendientes.
- WHERE la vivienda está `OUT_OF_SERVICE` o `BLOCKED_BY_OWNER` y tiene una estancia vencida, THE
  SYSTEM SHALL reportarla igualmente: el calendario y el estado se contradicen, y cuál de los dos
  está mal no lo decide un barrido.
- THE SYSTEM SHALL servir esos mismos desajustes por `GET /api/v1/blocked-transitions` a todo rol
  con `READ_PROPERTIES` —incluida la propietaria—, con el envelope paginado de PRD §23 y cada
  entrada llevando `property_id`, `property_code`, `reservation_id`, `trigger`, `blocking_state`,
  `due_since`, `cleaning_task_id` e `incident_id`. `trigger` y `blocking_state` viajan como los
  literales canónicos, sin prosa: la traducción es del cliente, el mismo trato que `dashboard-api`
  da a `operational_state`.
- WHEN el `blocking_state` está en `{AWAITING_CLEANING, CLEANING_IN_PROGRESS, CLEANING_SCHEDULED}`,
  THE SYSTEM SHALL poblar `cleaning_task_id` con el id de la tarea de limpieza **abierta** de esa
  vivienda dentro del `tenant_id` del token verificado, y SHALL dejar `incident_id = null`; si la
  vivienda no tiene tarea de limpieza abierta, SHALL dejar ambos ids en `null`. La ausencia de la
  tarea es un dato, no un error, así que la fila sigue listándose aunque no haya acción posible.
- WHEN el `blocking_state` no es de limpieza, THE SYSTEM SHALL poblar `incident_id` con el id de
  la incidencia **abierta** de esa vivienda dentro del mismo `tenant_id`, y SHALL dejar
  `cleaning_task_id = null`; sin incidencia abierta, SHALL dejar ambos ids en `null`.
- THE SYSTEM SHALL no poblar ambos ids para una misma fila: una vivienda no se queda con tarea de
  limpieza **y** incidencia abierta bajo el mismo `blocking_state`, y si las reglas se solapanan
  en el futuro la prioridad la da el `blocking_state` actual, no «la primera que se encuentre».
- THE SYSTEM SHALL resolver cada id como **una sola** llamada batch por tabla y página: nunca N+1
  sobre el listado paginado, y el camino SQL filtra por `tenant_id` antes de tocar la fila, igual
  que el resto del módulo (`steering/security.md` regla 1).
- THE SYSTEM SHALL derivar esa colección de la misma función que el job (`stalls.detect`) y de la
  misma ventana, de modo que el cubo y la colección no puedan discrepar; la diferencia es que el
  job pregunta por un trigger por ejecución y la colección por los tres.
- THE SYSTEM SHALL respetar el aislamiento por tenant en esa lectura y no SHALL estrenar acceso a
  datos que el rol no tuviera: el aviso expone el estado operacional de su vivienda y las fechas
  de su reserva, que ya están en su card del dashboard.
- THE SYSTEM SHALL paginar los **desajustes** —no las viviendas—, con `total` contando desajustes,
  y SHALL ordenarlos por `due_since` ascendente, con desempate estable por vivienda, reserva y
  trigger: lo primero que el operador necesita es lo que lleva más tiempo parado.
- THE SYSTEM SHALL no escribir en esa petición, ni siquiera la fila de configuración del tenant:
  `TenantConfigRepository.checkin_window_hours` lee una columna con su default en vez de pasar por
  `get_or_create`, que es lo que haría un `GET` escribir.
- **Quién consume esa colección**: desde `blocked-transitions-web`, la card de cada vivienda en
  `/dashboard`. Es el único consumidor, y es lo que cierra el «que no me entere por un huésped» que
  motivó la detección: la propietaria ve el aviso con su `READ_PROPERTIES` y el `PROPERTY_MANAGER`
  ve además la acción que lo desatasca. Los literales viajan sin prosa precisamente porque esa
  pantalla los pinta tal cual; el contrato de la pantalla vive en
  [`dashboard-web-frontend.md`](dashboard-web-frontend.md) §Blocked transitions on the card.

### Idempotencia y no solapamiento

- WHEN una tarea vuelve a ejecutarse sobre un estado ya alcanzado, THE SYSTEM SHALL no escribir
  ni transición ni evento. Una propiedad que ya transicionó deja de estar entre los candidatos.
- WHILE una ejecución de una tarea sigue viva, THE SYSTEM SHALL impedir que otra la solape
  mediante un lock en Redis por nombre de tarea, y la segunda SHALL informar que se saltó, no
  fallar.
- THE SYSTEM SHALL liberar el lock comparando el token que lo tomó, de modo que una ejecución
  que se pasó de TTL no borre el lock de su sucesora, y SHALL acotarlo con un TTL de tres veces
  la cadencia para que un worker muerto no lo deje bloqueado.

### SLA vencido

- WHEN un `NotificationLog` cumple `status = SENT`, `sla_deadline_at` no nulo y vencido, y
  `sla_breached = FALSE`, THE SYSTEM SHALL marcarlo incumplido y crear la notificación de
  escalado que corresponda a su tipo. Los dos tipos con política definida escalan a tipos
  **distintos**: `CLEANING_TASK_ASSIGNED` produce `SLA_BREACH` y `TECHNICIAN_ASSIGNED` produce
  `TECHNICIAN_NO_RESPONSE` desde `notification-writers-gap`, de modo que quien lee la bandeja
  distingue un técnico que calla de cualquier otro plazo incumplido sin abrir la fila que lo
  originó. La política sigue teniendo **dos** entradas: cambió lo que una produce, no cuántas hay.
- THE SYSTEM SHALL mantener el `subject` de la fila de escalado como la constante `"SLA breach"`
  en ambas ramas: es un hecho cierto de la fila —el plazo se incumplió— y lo que distingue el caso
  es el `notification_type`, que es donde lo lee la bandeja.
- THE SYSTEM SHALL crear el escalado en estado `PENDING` y no SHALL intentar entregarlo por
  ningún canal: la entrega es de `dispatch_notifications`, que drena las filas `PENDING` cada
  minuto. La costura entre encolar y entregar es deliberada.
- THE SYSTEM SHALL abanicar el escalado en **una fila por canal resuelto** por
  `notifications/domain/channel_resolver.py`, igual que cualquier otro aviso operativo, y SHALL
  fijar `sla_deadline_at = NULL` en todas — los plazos pertenecen a la fila original
  incumplida, no a las del escalado. El plazo sigue cancelándose con
  `cancel_sla_deadline(tenant_id, related_type, related_id, notification_type)`, que casa
  por el par polimórfico y por tanto cierra **todas** las filas hermanas de un mismo aviso
  en una sola llamada, sin tocar el canal.
- THE SYSTEM SHALL encontrar candidatos reales desde que existe ese emisor. La consulta exige
  `status = SENT` y, hasta `access-notifications`, **nada escribía ese valor**: cada ejecución
  encontraba cero. `check_sla_breaches` cambió de comportamiento sin cambiar de código.
- WHEN una fila deja de tener plazo porque su destinatario ya respondió —`cancel_sla_deadline`,
  de `cleaning`— THE SYSTEM SHALL dejar de considerarla candidata por la condición
  `sla_deadline_at IS NOT NULL`, sin que nadie haya tocado `status` ni `sla_breached`.
- THE SYSTEM SHALL escribir en una única transacción la marca y todas las filas de escalado de
  ese incumplimiento.
- THE SYSTEM SHALL dirigir el escalado a cada `PROPERTY_MANAGER` activo del tenant, con una
  fila por cada uno, y WHERE no haya ninguno SHALL recurrir al `TENANT_OWNER`.
- THE SYSTEM SHALL resolver esos destinatarios a través del servicio de dominio común
  `RoleRecipients` y no con una consulta propia en línea. Este job fijó el patrón y desde
  `notification-writers-gap` lo **comparte** en vez de encabezar copias de sí mismo
  ([`access-notifications.md`](access-notifications.md) §El censo de escritores). Lo que **no**
  se movió es lo que es suyo: el contador `recipients_truncated` del informe y la clave de log
  `scheduler.escalation_recipients_truncated`, que nombra este sitio y no el helper. Es una
  refactorización sin cambio observable —la caída al owner y el recuento de truncación ya
  funcionaban así—, y su valor es que la pregunta deje de estar escrita dos veces.
- THE SYSTEM SHALL conservar aquí la caída al `TENANT_OWNER` en vez de usar
  `managers_or_owners`: el rol primario lo dicta la política del escalado y no está fijado a
  `PROPERTY_MANAGER`, así que este job pide `active_holders` del rol que la política nombre y
  recurre al owner sólo si ese rol no era ya el owner.
- IF no hay ni manager ni owner activo, THEN THE SYSTEM SHALL dejar el incumplimiento **sin
  marcar** y registrarlo, de modo que se reintente hasta que alguien arregle el roster. Marcarlo
  lo volvería inescalable para siempre mientras la fila afirmaba haberse atendido.
- IF el tipo de notificación no tiene escalado definido, THEN THE SYSTEM SHALL marcarlo y
  registrarlo sin inventar destinatario.
- THE SYSTEM SHALL construir la fila de escalado a partir de identificadores y una plantilla
  fija, sin recibir la entidad incumplida, de modo que el `subject`/`body` original —único
  sumidero del esquema autorizado a llevar un código enmascarado— no pueda propagarse.
- WHEN vuelve a ejecutarse, THE SYSTEM SHALL no reescalar lo ya marcado: el filtro
  `sla_breached = FALSE` de la consulta de candidatos es el mecanismo completo.
- IF hay más destinatarios que una página, THEN THE SYSTEM SHALL informarlo en su recuento y no
  solo en el log.

## Estado y deuda conocida

- **`process_checkouts` sí crea la `CleaningTask`** que PRD §8.3 pide en el mismo job, desde
  `cleaning` (2026-08-07). La creación entra por `CleaningProvisioningPort`, un colaborador
  opcional que `AdvancePropertyStatesUseCase` invoca tras cada transición aceptada de
  `CHECKOUT_TIME_REACHED` y **antes de su único `commit`**, de modo que la transición y la tarea
  son una escritura o ninguna. Los otros dos jobs de reloj lo reciben a `None` y se comportan
  exactamente igual que antes. `AWAITING_CLEANING` ha dejado de ser terminal en la práctica.
- **Sólo un job de PRD §8.3 sigue sin estar aquí**: `send_checkin_reminders`
  (→ `messaging-ai` / `access-notifications`), que es un mensaje al huésped y no estado
  dependiente del reloj. Lo que le falta no es el reloj —esa es la mitad trivial— sino el
  adapter de canal y la plantilla; una entrada de beat apuntando a una tarea que nadie ha
  escrito falla una vez, a las 03:00, en un log de worker que nadie está leyendo.
  **`generate_price_recommendations` sí está** desde
  [`revenue-pricing`](revenue-pricing.md) (2026-08-18), y es quien estrenó `DAILY_JOBS`: hasta
  entonces el calendario sólo sabía expresar intervalos.
  Desde `pricing-web` (2026-08-23) su **puerta manual** —`POST /api/v1/price-recommendations/generate`,
  que comparte el generador con el job— tiene consumidor de frontend: el botón «Regenerar ahora»
  de `/pricing`. No cambia nada del calendario, y se anota porque el reloj deja de ser la única
  vía por la que se ejercita ese generador en la práctica.
- **No hay sync periódico del PMS.** La cadencia sería función del presupuesto de créditos, ya
  medido contra Beds24, pero su adapter no existe: programarlo hoy sincronizaría el mock. Llega
  con `pms-beds24-adapter`, dueño de la `PMSAdapterFactory`. `pms_sync` sigue siendo la única
  vía de sincronización.
- **Una excepción a nivel de tarea depende del aislamiento de Celery**, no de código propio, y
  no tiene test de primera parte.
- **`AdvancePropertyStatesUseCase` ya no se invoca sólo desde beat** (2026-08-17). El comando
  `make seed-demo` ([`seed-data-demo.md`](seed-data-demo.md)) lo ejecuta con los mismos
  disparadores que los tres jobs de reloj, para que el estado operacional de las viviendas de la
  demo sea **consecuencia** de unos hechos y no una columna escrita a mano. Es la confirmación de
  que esta capacidad es el **calendario** y no el dueño del caso de uso: el caso de uso vive en
  `properties` y ya recibía su `now` y su unidad de trabajo por parámetro, así que un segundo
  llamante no necesitó abrir ninguna costura nueva. Lo que ese llamante sí hace y beat no es
  pasar un `now` **histórico** —reproduce hechos de hace días— y encadenar los disparadores en
  orden cronológico explícito, porque la política de transiciones es sensible al orden.
- **El cubo `blocked` es el único que no sale de la consulta de candidatas** (2026-08-23,
  `cleaning-stall-blocks-next-stay`). Nació de un caso medido en `dev`: una vivienda en
  `CLEANING_IN_PROGRESS` desde el 2026-08-16 con una reserva `CONFIRMED` del 19 al 23 que nunca
  aplicó su check-in, y tres jobs informando `candidates: 0 … not_eligible: 0` sin mentir. Lo que
  faltaba no era un cubo más en la clasificación de candidatas, sino **una segunda pregunta**,
  hecha sobre el complemento de los estados origen.
- **La detección se afinó dos veces durante la implementación, y las dos veces por medición.** La
  definición literal del requisito —«la hora llegó y el estado no es origen»— describe también
  **todo lo que está aguas abajo del trigger**, así que reportaba como atascada cada vivienda
  `OCCUPIED_ESTIMATED` a mitad de estancia y cada `AWAITING_CLEANING` recién salida de un checkout,
  durante 30 días: `blocked` acababa siendo el tamaño de la cartera activa. Las condiciones 3 y 4
  —evidencia por reserva y el atajo del destino acotado a la única estancia vencida— son la
  corrección, y la cuarta sólo apareció al correr el flujo completo contra la pila real.
- **`CLEANING_ASSIGNMENT_EXPIRED` se retiró en vez de ganar emisor** (2026-08-23). Era la única
  caducidad que el ciclo de limpieza tenía escrita —enum, fila de matriz y guarda— y **nadie la
  emitía**: no estaba en `CADENCES`, ni en `DAILY_JOBS`, ni la construía ningún caso de uso. El
  razonamiento de la retirada vive en
  [`timeline-state-machine.md`](timeline-state-machine.md); aquí se anota porque este calendario es
  donde habría vivido su emisor, y no lo tuvo nunca.
- **Dos deudas declaradas de la colección de desajustes**, escritas aquí en vez de dejarse
  descubrir: `PropertyRepository.list_all` no está paginado en origen —irrelevante con dos
  viviendas, dos consultas grandes por petición con doscientas, y la palanca es filtrar por el
  complemento de estados origen como hace el job—, y la lectura de evidencia filtra por
  `metadata->>'reservation_id'`, que ningún índice cubre: `property_state_transitions` sólo tiene
  `ix_property_state_transitions_property_id_created_at`, así que es un escaneo acotado por tenant
  y por las reservas de la ventana. La palanca es un índice de expresión sobre
  `(tenant_id, (metadata->>'reservation_id'))` si alguna vez pesa.
- **Un `beat` colgado pero vivo pasa el healthcheck**: comprueba que el proceso es beat, no que
  esté planificando.
- **Coste del filtro global medido**: ~280 µs por sentencia con 22 clases acotadas, ~14 % del
  job de un minuto. No justifica rediseño; la palanca, si alguna vez lo hiciera, es reducir
  sentencias por ejecución y no memoizar el escaneo (`app/core/db.py` explica por qué).

## Key files

- `backend/app/scheduler/` — `schedule.py` (cadencias y `beat_schedule`), `tasks.py` (las ocho
  tareas), `runner.py` (puente asyncio, engine y cliente Redis por ejecución, bucle por tenant,
  y el helper de sesión marcada por lote de tenants que usa `process_webhook_events`),
  `locks.py` (lock Redis con liberación por token).
- `backend/app/worker.py` — la app Celery; junto a `app/scheduler/**` es el único sitio que
  importa Celery, verificado por `tests/test_layering.py`.
- `backend/app/properties/application/use_cases.py` — `AdvancePropertyStatesUseCase` y su
  informe por cubos.
- `backend/app/properties/domain/clock_triggers.py` — ventana de candidatos, ventana de check-in
  y materialización de límites locales.
- `backend/app/properties/domain/stalls.py` — `BlockedTransition` y `detect`, la definición única
  del desajuste, pura y sin reloj propio: recibe `now`, la ventana del operador y la evidencia de
  lo ya aplicado. Sus dos llamantes son el cubo `blocked` del job y la colección de lectura.
- `backend/app/properties/application/use_cases.py` — además del caso de uso del reloj,
  `ListBlockedTransitionsUseCase` y la función compartida `reservations_by_property`, que es lo que
  hace imposible que el cubo y la colección usen ventanas distintas.
- `backend/app/properties/domain/repositories.py` — `PropertyStateTransitionRepository.applied_clock_triggers`,
  la evidencia de «esta transición ya se aplicó a esta reserva», leída como texto.
- `backend/app/tenants/domain/repositories.py` — `TenantConfigRepository.checkin_window_hours`, la
  lectura de una columna con su default que mantiene el `GET` sin escrituras.
- `backend/app/notifications/{domain/escalation.py,application/use_cases.py}` — política de
  escalado pura y el caso de uso que la aplica.
- `backend/scripts/measure_tenant_filter.py` — la medición del filtro global.
- `docker-compose.yml`, `docker-compose.deploy.yml` — el servicio `beat`.
- `docs/celery-jobs.md` — cómo se opera.
