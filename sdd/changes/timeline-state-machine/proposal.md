# Proposal: timeline-state-machine

## Why

`domain-foundation-core` ya entrega `Property`, los 11 valores canónicos de
`PropertyOperationalState`, `PropertyStateTransition` y `TimelineEvent`, mientras
que `domain-foundation-ops` entrega las entidades operacionales que aportarán
contexto de limpieza e incidencias. Sin embargo, esas foundations contienen solo
datos: todavía no existe la política determinista que valide las transiciones de PRD
§8 ni el servicio central que produzca la trazabilidad exigida por PRD §3.1 y §10.

Este change implementa esa capacidad de dominio antes del orden literal de PRD §26,
conforme a la prioridad aprobada de PRD §30: primero visibilidad del estado
operacional y timeline. El resultado permitirá que los futuros módulos de reservas,
limpieza, mantenimiento y jobs soliciten cambios de estado. `PropertyStateMachine`
será la única autoridad para modificar el estado operacional; no existirá ningún
mecanismo alternativo para cambiarlo.

## What changes

Se añade la capacidad de validar de forma determinista las transiciones explícitas de
PRD §8 y garantizar que cada transición aceptada disponga de la trazabilidad exigida
por PRD §3.1 y §10, incluyendo el histórico de estado y el `TimelineEvent`
`PROPERTY_STATE_CHANGED` correspondiente.

La evaluación recibe todo el contexto como datos explícitos —estado actual, destino
o disparador, reservas, limpieza, incidencias, actor, motivo, instante e identificador
de correlación estable cuando exista— y devuelve un resultado determinista, sin leer
base de datos, reloj global, red ni servicios externos. Este change no persiste el
resultado ni modifica las entidades o modelos existentes; la aplicación y los
repositorios futuros serán responsables de la transacción durable y de deduplicar
solicitudes repetidas.

## Scope and dependencies

- Usa como contratos existentes `PropertyOperationalState`,
  `PropertyStateTransition`, `TimelineEvent`, `Reservation`, `CleaningTask` e
  `Incident`; no cambia su forma ni su esquema.
- Implementa el mapa completo de PRD §8.1, incluida la salida manual y explícita de
  `BLOCKED_BY_OWNER` aprobada por Marta.
- Implementa el cálculo contextual de PRD §8.2 con contexto temporal inyectado.
- Garantiza que toda transición aceptada contenga la información necesaria para
  construir el histórico de estado y el `TimelineEvent` correspondiente.
- Depende de las specs vivas `domain-foundation-core` y `domain-foundation-ops`,
  ambas ya implementadas y archivadas.
- Se adelanta a `domain-foundation-financial` y `auth-tenancy` por la prioridad de
  PRD §30. No depende de su implementación porque aquí no hay persistencia, queries,
  RBAC ni `AuditLog`.
- Los cambios futuros `celery-jobs`, `reservations`, `cleaning` y `maintenance`
  consumirán esta política; no se adelantan sus workflows.

## Requirements

### R1 — Estados operacionales canónicos

**As a** propietaria o manager, **I want** que todas las viviendas compartan un
catálogo único de estados, **so that** el sistema describa su situación operacional
sin nombres alternativos ni interpretaciones incompatibles.

Acceptance criteria:

1. WHEN la state machine reciba o produzca un estado, THE SYSTEM SHALL usar
   exclusivamente `VACANT_READY`, `AWAITING_CHECKIN`, `OCCUPIED_ESTIMATED`,
   `AWAITING_CLEANING`, `CLEANING_SCHEDULED`, `CLEANING_IN_PROGRESS`,
   `READY_FOR_NEXT_GUEST`, `MAINTENANCE_REQUIRED`, `CRITICAL_INCIDENT`,
   `BLOCKED_BY_OWNER` y `OUT_OF_SERVICE`, reutilizando el enum existente de
   `domain-foundation-core`.
2. IF una solicitud contiene un estado fuera de ese catálogo, THEN THE SYSTEM SHALL
   rechazarla sin producir una transición aceptada ni un evento de cambio de estado.
3. WHEN se evalúe ocupación, THE SYSTEM SHALL tratarla como
   `OCCUPIED_ESTIMATED` conforme a PRD §5.6 y SHALL NOT requerir un evento
   `DOOR_OPENED` ni una integración de cerradura.

### R2 — `PropertyStateMachine` como única política de transición

**As a** operadora, **I want** que cada cambio de estado siga el mapa completo y
explícito del PRD, **so that** ningún módulo pueda dejar una vivienda en un estado
imposible.

Acceptance criteria:

1. WHEN se solicite una transición, THE SYSTEM SHALL aceptarla únicamente si el
   origen, el destino, el disparador y el contexto satisfacen una transición de PRD
   §8.1.
2. IF la combinación origen/destino no está permitida, el contexto no cumple su
   condición o el estado solicitado coincide con el actual sin representar una
   transición, THEN THE SYSTEM SHALL rechazarla sin modificar el objeto de entrada
   ni producir históricos de éxito.
3. WHEN cualquier módulo futuro necesite cambiar el estado operacional, THE SYSTEM
   SHALL exigir que la decisión pase por `PropertyStateMachine`; no existirá una
   segunda tabla de transiciones ni una política alternativa por módulo.
4. WHEN se verifique la state machine, THE SYSTEM SHALL cubrir cada flecha declarada
   en PRD §8.1 y SHALL demostrar que pares no declarados son rechazados.
5. WHEN la evaluación dependa del tiempo, THE SYSTEM SHALL recibir explícitamente
   como entradas del dominio el instante de referencia y toda la información
   temporal necesaria para evaluar la transición.

### R3 — Transiciones operacionales y disparadores de dominio

**As a** desarrolladora de módulos operacionales, **I want** una política común para
reservas, limpieza, incidencias y acciones manuales, **so that** cada workflow futuro
solicite el estado correcto sin duplicar reglas.

Acceptance criteria:

1. WHEN se abra la ventana de check-in de una reserva confirmada para hoy, se alcance
   la hora estimada de entrada, se alcance el checkout o se cancele antes del
   check-in, THE SYSTEM SHALL evaluar respectivamente los destinos previstos por PRD
   §8.1 para el estado de origen recibido.
2. WHEN una limpieza sea asignada, rechazada, iniciada o completada, THE SYSTEM SHALL
   evaluar las transiciones de limpieza de PRD §8.1 usando el estado de la tarea y el
   contexto de la reserva, sin implementar el workflow de limpieza.
3. WHEN una incidencia se cree con severidad `HIGH` o `CRITICAL`, cambie su severidad
   operacional a una de ellas —incluido el cambio entre ambas— o se resuelva, THE
   SYSTEM SHALL evaluar `MAINTENANCE_REQUIRED`, `CRITICAL_INCIDENT` o el estado
   contextual correspondiente conforme a PRD §8.
4. WHEN un owner solicite `BLOCKED_BY_OWNER`, o un owner/manager solicite
   `OUT_OF_SERVICE` o su reactivación, THE SYSTEM SHALL exigir que el caller
   proporcione actor y motivo no vacío como datos de entrada; el caller SHALL ser
   responsable del enforcement de RBAC y el dominio SHALL limitarse a validar los
   datos recibidos.
5. IF una acción pertenece al workflow completo de reservas, limpieza,
   mantenimiento, jobs o notificaciones, THEN THE SYSTEM SHALL limitar este change a
   evaluar la transición solicitada y SHALL dejar la orquestación al change
   propietario.

### R4 — Resolución contextual de incidencias

**As a** manager, **I want** que una vivienda recupere su situación operacional real
al resolver incidencias, **so that** no vuelva automáticamente a un estado que
contradiga una reserva o limpieza activa.

Acceptance criteria:

1. WHEN se resuelva una incidencia y permanezca al menos otra incidencia
   `CRITICAL` activa, THE SYSTEM SHALL producir `CRITICAL_INCIDENT`.
2. WHEN no permanezcan incidencias `CRITICAL` pero exista al menos una incidencia
   `HIGH` activa, THE SYSTEM SHALL producir `MAINTENANCE_REQUIRED`.
3. WHEN no queden incidencias `HIGH` ni `CRITICAL`, THE SYSTEM SHALL priorizar una
   limpieza en estado `CREATED`, `ASSIGNED` o `ACCEPTED` como
   `AWAITING_CLEANING`, y una limpieza `IN_PROGRESS` como
   `CLEANING_IN_PROGRESS`.
4. WHEN no haya limpieza pendiente o en progreso, THE SYSTEM SHALL producir
   `OCCUPIED_ESTIMATED` si existe una reserva activa cuyo checkout no ha pasado,
   `AWAITING_CHECKIN` si la próxima reserva entra hoy,
   `READY_FOR_NEXT_GUEST` si la próxima reserva entra después de hoy y
   `VACANT_READY` si no aplica ninguno de esos contextos, conforme a PRD §8.2.
5. IF el contexto contiene datos incompatibles o insuficientes que impiden obtener
   un único estado conforme a las reglas del PRD, THEN THE SYSTEM SHALL rechazar el
   cálculo con un error de dominio explícito en vez de seleccionar silenciosamente
   un estado.

### R5 — Bloqueo y desbloqueo manual trazable

**As a** owner o manager cuya autorización ha comprobado el caller, **I want**
desbloquear una vivienda indicando el destino y el motivo, **so that** una decisión
manual nunca restaure un estado obsoleto de forma automática.

Acceptance criteria:

1. WHEN un owner solicite la transición a `BLOCKED_BY_OWNER`, THE SYSTEM SHALL
   exigir un motivo no vacío y conservar la identidad del actor en el resultado.
2. WHEN el caller proporcione un owner o manager cuya autorización RBAC ya ha
   comprobado para salir de `BLOCKED_BY_OWNER`, THE SYSTEM SHALL exigir explícitamente
   un destino del catálogo canónico y un motivo no vacío, y SHALL limitarse a validar
   los datos recibidos.
3. WHEN se solicite ese desbloqueo, THE SYSTEM SHALL validar el destino y su contexto
   mediante `PropertyStateMachine` y SHALL NOT restaurar automáticamente el estado
   anterior.
4. IF el caller no proporciona un actor, un destino explícito o un motivo, THEN THE
   SYSTEM SHALL rechazar el desbloqueo sin producir transición ni `TimelineEvent` de
   éxito.

### R6 — Resultado correlacionado e inmutable para timeline

**As a** responsable operativa, **I want** que cada transición aceptada produzca su
histórico y evento correlacionados, **so that** pueda reconstruirse qué ocurrió, por
qué y quién lo provocó.

Acceptance criteria:

1. WHEN `PropertyStateMachine` acepte una transición, THE SYSTEM SHALL producir en
   un único resultado de dominio los datos completos de `PropertyStateTransition` y
   de un `TimelineEvent` con `event_type=PROPERTY_STATE_CHANGED`.
2. WHEN se produzca ese resultado, ambas evidencias SHALL compartir `tenant_id`,
   `property_id`, estados origen/destino, actor, motivo, instante y un identificador
   de correlación cuando haya sido proporcionado.
3. WHEN se construyan las evidencias, THE SYSTEM SHALL reutilizar las entidades y
   enums existentes, SHALL tratarlas como registros inmutables y SHALL incluir
   metadata estructurada suficiente para trazabilidad posterior.
4. IF no pueden producirse las dos evidencias válidas, THEN THE SYSTEM SHALL fallar
   la transición lógica completa; nunca devolverá solo una de ellas como resultado
   válido de la transición.
5. WHEN la misma solicitud se evalúe con idénticos estado, entrada, contexto, actor e
   instante, THE SYSTEM SHALL producir exactamente el mismo resultado lógico. La
   deduplicación durable por identificador de correlación pertenece a
   aplicación/persistencia y queda fuera de este change.
6. WHEN otros módulos necesiten generar TimelineEvents no asociados a una transición
   de propiedad, THE SYSTEM SHALL permitir que apliquen las mismas reglas de dominio
   sin duplicar lógica y sin que este change implemente sus workflows.

### R7 — Dominio puro y verificación exhaustiva

**As a** equipo de desarrollo, **I want** que state machine y timeline sean
deterministas y testeables sin infraestructura, **so that** sus invariantes puedan
verificarse antes de integrar casos de uso y repositorios.

Acceptance criteria:

1. WHEN se implemente este change, THE SYSTEM SHALL ubicar reglas, políticas,
   errores y objetos de valor en capas `domain/` y SHALL NOT importar SQLAlchemy,
   FastAPI, Pydantic, Celery, Redis ni adapters externos.
2. WHEN se ejecute la suite de dominio, THE SYSTEM SHALL verificar en tests unitarios
   puros todas las transiciones válidas, transiciones inválidas, resolución
   contextual, bloqueo/desbloqueo y correlación de evidencias sin base de datos ni
   red.
3. WHERE los tests necesiten reservas, limpiezas, incidencias, actores o instantes,
   THE SYSTEM SHALL usar fixtures, factories o builders no productivos y SHALL NOT
   introducir el seed data de PRD §27.
4. WHEN se revise el diff de implementación, THE SYSTEM SHALL demostrar que no se
   modificaron entidades existentes, modelos SQLAlchemy, migraciones ni esquema.
5. IF durante diseño o implementación aparece una necesidad inevitable de cambiar
   cualquiera de esos contratos persistidos, THEN THE SYSTEM SHALL registrar un
   bloqueo y detener ese cambio hasta obtener aprobación explícita.

## Out of scope

- Modificar `Property`, `PropertyStateTransition`, `TimelineEvent`, `Reservation`,
  `CleaningTask`, `Incident`, `Conversation`, `Message` o sus enums existentes.
- Modelos SQLAlchemy, repositorios concretos, migraciones Alembic, PostgreSQL o
  cualquier cambio de esquema.
- Persistir atómicamente `Property`, `PropertyStateTransition` y `TimelineEvent`; la
  unidad de trabajo/transacción pertenece a aplicación e infraestructura futuras.
- Deduplicación durable o almacenamiento de identificadores de idempotencia.
- `AuditLog` y su persistencia, reservados para su change propietario.
- JWT, RBAC, tenant isolation y autorización efectiva de owner/manager; el dominio
  recibe el actor y el hecho de autorización desde el caller.
- `Conversation` y `Message` como comportamiento; pertenecen a `messaging-ai` y solo
  podrán referenciarse como entidades existentes si fuera estrictamente necesario.
- Adapters de PMS, acceso, IA, WhatsApp, email, storage, sensores o cualquier otro
  sistema externo.
- Endpoints o schemas FastAPI.
- Jobs Celery, Redis, scheduler, SLA enforcement y disparo automático de
  transiciones.
- Workflows completos de reservas, limpieza, mantenimiento, mensajería o acceso.
- Frontend, dashboard, visualización del timeline o aplicaciones de campo.
- Seed data de PRD §27; permanece en `hardening-release`.
- Infraestructura, Terraform, Docker, CI/CD o despliegue.
- Modificar specs vivas existentes; durante archive se creará únicamente la nueva
  spec `timeline-state-machine`.

## Risks

- La atomicidad durable entre `Property`, `PropertyStateTransition` y
  `TimelineEvent` queda diferida; la futura capa de aplicación deberá impedir,
  dentro de su transacción, que una evidencia parcial se persista o se interprete
  como resultado válido.
- Los módulos consumidores todavía no existen, por lo que los contratos deben
  permanecer pequeños y expresados en términos del dominio ya aprobado, sin puertos
  especulativos de persistencia.
- El cálculo contextual combina reservas, limpiezas e incidencias; aceptar contexto
  incoherente produciría estados incorrectos. La validación explícita y el reloj
  inyectado mitigan ese riesgo.
- Adelantar este change respecto a `auth-tenancy` exige mantener la autorización y
  tenant isolation fuera del dominio puro, sin confundir los datos de actor
  proporcionados por el caller con enforcement real.
- El timeline visible requerirá localización futura. Este change produce datos
  estructurados y trazables; no introduce UI ni una estrategia nueva de i18n.

## Affected specs

- `sdd/specs/timeline-state-machine.md` *(no existe aún — se creará al archivar)*.

Las specs `sdd/specs/domain-foundation-core.md` y
`sdd/specs/domain-foundation-ops.md` son dependencias de referencia y no se
modifican en este change.
