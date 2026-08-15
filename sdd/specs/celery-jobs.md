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
- THE SYSTEM SHALL derivar tanto el `beat_schedule` como el TTL del lock de cada tarea de una
  única tabla de cadencias, de modo que no puedan desincronizarse.
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
  escalado que corresponda a su tipo.
- THE SYSTEM SHALL crear el escalado en estado `PENDING` y no SHALL intentar entregarlo por
  ningún canal: la entrega es de `dispatch_notifications`, que drena las filas `PENDING` cada
  minuto. La costura entre encolar y entregar es deliberada.
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
- **Dos jobs de PRD §8.3 no están aquí**: `generate_price_recommendations` (→ `revenue`) y
  `send_checkin_reminders` (→ `messaging-ai` / `access-notifications`), que son mensajes al
  huésped y no estado dependiente del reloj.
- **No hay sync periódico del PMS.** La cadencia sería función del presupuesto de créditos, ya
  medido contra Beds24, pero su adapter no existe: programarlo hoy sincronizaría el mock. Llega
  con `pms-beds24-adapter`, dueño de la `PMSAdapterFactory`. `pms_sync` sigue siendo la única
  vía de sincronización.
- **Una excepción a nivel de tarea depende del aislamiento de Celery**, no de código propio, y
  no tiene test de primera parte.
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
- `backend/app/notifications/{domain/escalation.py,application/use_cases.py}` — política de
  escalado pura y el caso de uso que la aplica.
- `backend/scripts/measure_tenant_filter.py` — la medición del filtro global.
- `docker-compose.yml`, `docker-compose.deploy.yml` — el servicio `beat`.
- `docs/celery-jobs.md` — cómo se opera.
