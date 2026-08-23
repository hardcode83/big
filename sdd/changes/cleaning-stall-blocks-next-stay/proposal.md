# Proposal: cleaning-stall-blocks-next-stay

## Why

Operando `dev` el **2026-08-22** apareció una vivienda parada desde el **16 de agosto**: REDES11 en
`CLEANING_IN_PROGRESS`, con una limpieza que nadie cerró (0 ítems de checklist, 1 foto, arrancada
cinco minutos después de crearse). Lo grave no es la tarea abandonada: es lo que arrastró.

**El check-in siguiente no ocurrió, y nadie lo supo.** La reserva `CONFIRMED` del 19 al 23 de agosto
sobre esa misma vivienda nunca pasó a `OCCUPIED_ESTIMATED`. Tres hechos verificados en el código lo
explican, y el tercero es el que convierte un fallo en un silencio:

1. **`CLEANING_IN_PROGRESS` tiene tres salidas y ninguna lleva a un check-in**:
   `CLEANING_COMPLETED`, `INCIDENT_HIGH` e `INCIDENT_CRITICAL`
   (`properties/domain/state_machine.py`). La única salida no excepcional es cerrar la limpieza.
2. **La limpieza no se puede cerrar mientras la estancia dure.** `after_cleaning_completion` se
   niega a resolver con una reserva activa (`properties/domain/state_resolution.py`), y responde
   `409` — el caso que `test_closing_a_cleaning_while_a_guest_is_in_is_a_conflict` ya fija. Así que
   la limpieza que bloqueó el check-in tampoco se puede cerrar por culpa de la estancia que bloqueó.
   El nudo se cierra sobre sí mismo y solo lo desata el calendario.
3. **El sistema no puede ni decir que no pudo.** `AdvancePropertyStatesUseCase` pide sus candidatas
   con `list_by_state(tenant_id, PropertyStateMachine.source_states_for(trigger))`, así que una
   vivienda cuyo estado no es origen del trigger **no llega a ser candidata**: no incrementa
   `report.candidates` ni ningún cubo, `not_eligible` incluido. El informe del job es correcto y
   está vacío de ella. No es que la descarte: es que no la mira.

**No es que el reloj no corra.** Comprobado el 2026-08-22 en `dev`: `beat` reparte sus tareas cada
cinco minutos, el worker las consume y ninguna falla. El tick de las 08:18 UTC dejó esto, con la
estancia del 19 al 23 sin aplicar desde tres días antes:

```
check_checkin_windows   → candidates: 0 … not_eligible: 0
mark_occupied_estimated → candidates: 0 … not_eligible: 0
```

Cero candidatas y cero de todo lo demás. El informe no miente: la vivienda nunca entró en él. Esa
es la medición del punto 3, y la razón de que R1 no pueda resolverse añadiendo un cubo al informe
—hay que detectar el desajuste **fuera** de la consulta de candidatas—.

**Y un segundo hallazgo del mismo sitio: un estado escrito por fuera de la máquina.**
`property_state_transitions` tiene **cinco filas en total**, y las dos de REDES11 son
`triggered_by = USER` con un segundo de diferencia (asignar a las 07:23:51, arrancar a las 07:23:52
del 2026-08-16: un script, no una persona). La primera declara `from_state = AWAITING_CLEANING`, así
que a esa hora la vivienda estaba ahí — y **no existe ninguna fila que la haya llevado**. Debería
haber cinco: las dos propiedades nacen `VACANT_READY` por defecto de DDL, y el único camino de la
matriz hasta `AWAITING_CLEANING` pasa por `AWAITING_CHECKIN`, `OCCUPIED_ESTIMATED` y un checkout,
cada uno con su fila.

Las tres explicaciones benignas están descartadas:

- **No fue el seed.** El `seed_demo` de esa fecha —el fichero anterior al merge de
  `seed-data-demo-extension`— documenta lo contrario: «`CreatePropertyCommand` has no such field, on
  purpose, so both homes take the DDL default `VACANT_READY` and the column stays where
  `PropertyStateMachine` governs it». Y su ejecución está fechada: los cuatro `*_CREATED` de las
  07:11:27.
- **No fue el aprovisionador del checkout.** El `CLEANING_TASK_CREATED` de las 07:18:12 **lleva
  actor**, así que es el `POST /cleaning-tasks` de una persona autenticada; el job escribe sin actor,
  como los dos `ACCESS_RECORD_CREATED` de las 07:14:29 de ese mismo día.
- **No fue la API de propiedades.** `current_operational_state` está deliberadamente fuera de sus
  dos esquemas de escritura (`properties/api/schemas.py`).

Y la pieza que convierte la eliminación en prueba directa: **una asignación legítima sí escribe su
fila**. Medido el 2026-08-22 a las 08:47:43 UTC sobre PAJARITOS8 —la misma operación, por la misma
pantalla— que dejó `AWAITING_CLEANING → CLEANING_SCHEDULED` con `triggered_by = USER` y el mismo
sello de tiempo que el `updated_at` de la tarea, es decir en la misma transacción. Ese camino de
código no puede mover la vivienda sin registrarlo; si el salto de REDES11 no tiene fila, no pasó por
ahí.

Queda que la columna se escribió a mano. Y el hueco de cinco minutos y medio entre crear la tarea
(07:18:12) y asignarla con éxito (07:23:51) encaja con haber chocado contra el `409` de
`cleaning-assign-preconditions` y haberlo rodeado por la base de datos — **eso último es inferencia,
no medición**: una petición rechazada no deja fila de auditoría, así que el motivo no consta. Lo que
sí está probado es que el estado se movió fuera de la máquina, contra el principio 1 de
`product.md`. Cuenta aquí porque es la evidencia de que un atasco sin salida legítima se rodea, que
es lo que R3 corrige; auditar la columna contra el registro de transiciones es otra cosa y queda
fuera (ver *Out of scope*).

Y no hay salida lateral. `reject` exige `ASSIGNED` o `ACCEPTED` y la tarea está `IN_PROGRESS`; las
catorce rutas de `cleaning/api/tasks_router.py` no incluyen ninguna operación de cancelar o
abandonar una tarea; y `current_operational_state` no es escribible por la API a propósito
(`properties/api/schemas.py` lo declara). La única puerta que queda abierta es perversa: crear una
incidencia `HIGH` mueve la vivienda a `MAINTENANCE_REQUIRED` y la descongela — un dato falso como
mecanismo de desbloqueo.

**De paso, un trigger muerto.** `CLEANING_ASSIGNMENT_EXPIRED` existe en el enum, tiene su fila en la
matriz (`CLEANING_SCHEDULED → AWAITING_CLEANING`) y su guarda de estados esperados… y **nadie lo
emite**: no está en `CADENCES`, no está en `DAILY_JOBS` y ningún caso de uso lo construye. La única
caducidad que el ciclo de limpieza tenía escrita nunca ha corrido. Es la misma forma de deuda que la
entrada `tech-cycle-completion` documenta para `TimelineEventType.TECHNICIAN_EN_ROUTE`, y se cierra
igual: o gana su escritor, o se retira.

Esto contradice de frente el principio 1 de `steering/product.md` («una vivienda es una máquina de
estados, toda transición genera TimelineEvent auditable») en su consecuencia práctica: una
transición que el calendario exige y la máquina no admite no genera nada — ni evento, ni recuento,
ni aviso. Y contradice el principio 2 (el dashboard dice qué pasa y quién tiene la próxima acción):
la próxima acción de REDES11 existía desde el 16 de agosto y no aparecía en ninguna pantalla.

Entrada de roadmap: `cleaning-stall-blocks-next-stay` (`needs: cleaning`).

## What changes

Después de este change, una vivienda que el calendario quiere mover y su estado no admite **deja de
ser invisible**, y una limpieza que no puede completarse **tiene una salida declarada** en vez de
congelar la vivienda hasta que el calendario la libere.

Tres piezas: la detección de ese desajuste como hecho propio (no como ausencia en un informe de
candidatas), su llegada a una persona con permiso para actuar, y una operación explícita para
retirar de circulación una tarea de limpieza que no va a cerrarse, resolviendo el estado de la
vivienda **por la máquina de estados** y nunca escribiendo la columna. Más la decisión pendiente
sobre el trigger de caducidad.

**No se relaja ninguna precondición existente.** Ni la matriz gana filas de conveniencia, ni
`after_cleaning_completion` deja de negarse con un huésped dentro: negarse es correcto en los dos
casos. Lo que falta es la salida y el aviso.

## Requirements

### R1 — Un desajuste entre el calendario y el estado es un hecho registrado

**As a** operador del sistema, **I want** que una transición que el calendario exige y el estado no
admite deje rastro, **so that** una vivienda parada no dependa de que alguien la mire por casualidad.

Acceptance criteria:

1. WHEN una reserva `CONFIRMED` o `CHECKED_IN_ESTIMATED` alcanza el instante de una transición de
   reloj, el estado operacional de su vivienda no es origen de ese trigger **y no consta que esa
   transición se haya aplicado ya para esa reserva**, THE SYSTEM SHALL registrar ese desajuste
   identificando la vivienda, la reserva, el trigger y el estado que lo impide.

   *Enmendado en el panel de la sección 3 de `/sdd:run`, 2026-08-23 (design D1/D3), decidido por
   Jose.* La redacción anterior —«alcanza el instante … y el estado no es origen de ese
   trigger»— parecía describir el atasco y describía **todo lo que está aguas abajo del
   trigger**, porque las dos condiciones se cumplen igual de bien cuando la transición ya
   ocurrió: `is_due` de `CHECKIN_TIME_REACHED` es verdad durante **toda** la estancia, y el de
   `CHECKOUT_TIME_REACHED` lo es **para siempre** después del checkout, mientras «no es origen»
   incluye cualquier estado posterior. Medido sobre la implementación literal: una vivienda
   `OCCUPIED_ESTIMATED` a mitad de estancia —que hizo su check-in correctamente— se reportaba
   como atascada en cada tick, y una `AWAITING_CLEANING` recién salida de un checkout también,
   durante 30 días. `report.blocked` acababa siendo el tamaño de la cartera activa y REDES11
   era indistinguible de una vivienda sana.

   La tercera condición es la que faltaba, y la evidencia ya existe: `property_state_transitions`
   guarda `reservation_id` y `trigger` en su `metadata`, así que «¿se aplicó ya el check-in de
   *esta* reserva?» es una pregunta contestable sin inventar estado nuevo.
2. THE SYSTEM SHALL NOT contabilizarlo como `not_eligible`: ese cubo significa «la hora no ha
   llegado», y confundir las dos cosas es exactamente lo que hoy oculta el caso
   (`AdvanceReport` ya documenta esa distinción para `ambiguous` y `unresolvable_time`).
3. THE SYSTEM SHALL detectarlo aunque la vivienda no sea candidata del job, porque la consulta de
   candidatas filtra por estado origen y por definición excluye este caso.
4. THE SYSTEM SHALL acotar la ventana temporal de la detección de forma declarada, con el mismo
   criterio con que `CANDIDATE_LOOKBEHIND` acota los checkouts pendientes (30 días, y lo que caiga
   fuera se dice en `docs/celery-jobs.md` en vez de dejarse descubrir).

### R2 — Llega a quien puede actuar

**As a** `PROPERTY_MANAGER`, **I want** ver que una vivienda está parada y por qué, **so that** no me
enteré por un huésped.

Acceptance criteria:

1. WHEN existe un desajuste de R1 vigente, THE SYSTEM SHALL hacerlo visible a un rol con
   `READ_PROPERTIES` **sin** que ese rol tenga que leer logs del servidor.

   *Enmendado en el gate de `/sdd:design` del 2026-08-23 (design D6).* Decía
   «`MANAGE_CLEANING_TASKS` o `MANAGE_PROPERTIES`», y los dos los tiene exactamente el mismo rol
   —`PROPERTY_MANAGER`— y ninguno más, así que la disyunción no discriminaba a nadie y dejaba
   fuera a la propietaria, que es quien PRD §1 describe operando dos viviendas desde el móvil.
   Se ensancha a `READ_PROPERTIES` porque el aviso **no expone nada** que ella no vea ya en su
   card del dashboard —el estado operacional de su vivienda y las fechas de su reserva—, así que
   el criterio 3 de abajo sigue cumplido al pie de la letra.
2. THE SYSTEM SHALL incluir el motivo: el trigger que no pudo aplicarse y el estado que lo impide.
3. THE SYSTEM SHALL respetar el aislamiento por tenant y el reparto de permisos vigente: la
   visibilidad no estrena acceso a datos que el rol no tuviera.
4. WHERE el desajuste se resuelve, THE SYSTEM SHALL dejar de mostrarlo sin intervención manual.

### R3 — Una limpieza que no puede cerrarse tiene salida

**As a** `PROPERTY_MANAGER`, **I want** poder retirar de circulación una tarea de limpieza que no va
a completarse, **so that** la vivienda vuelva a seguir su calendario.

Acceptance criteria:

1. THE SYSTEM SHALL ofrecer una operación que lleve una tarea de limpieza no terminal a un estado
   terminal, restringida a `MANAGE_CLEANING_TASKS`.
2. WHEN se aplica, THE SYSTEM SHALL resolver el estado operacional de la vivienda **a través de
   `PropertyStateMachine`**, y SHALL NOT escribir `current_operational_state` directamente.
3. WHEN se aplica, THE SYSTEM SHALL escribir su fila de `AuditLog` y su `TimelineEvent`, como toda
   transición del sistema (principio 1 de `product.md`).
4. IF la tarea ya está en un estado terminal, THEN THE SYSTEM SHALL responder `409` sin escribir
   nada.
5. THE SYSTEM SHALL declarar qué ocurre con la evidencia parcial de esa tarea —ítems completados y
   fotos ya subidas— en vez de dejarlo implícito: las fotos son objetos en un almacén que ninguna
   transacción deshace (`cleaning-photos-storage`).

### R4 — El trigger de caducidad deja de ser un camino falso

**As a** quien lee esta máquina de estados, **I want** que un trigger declarado tenga escritor o no
esté, **so that** la matriz describa el sistema y no una intención.

Acceptance criteria:

1. THE SYSTEM SHALL cerrar `CLEANING_ASSIGNMENT_EXPIRED` de una de las dos formas, y solo una: un
   emisor real que lo dispare cuando la asignación caduque, **o** la retirada del trigger, de su
   fila de la matriz y de su entrada en la guarda de estados esperados.
2. WHERE se elija el emisor, THE SYSTEM SHALL derivar el plazo de la configuración del tenant que
   ya gobierna el SLA de la asignación (`TenantConfig.sla_medium_minutes`, la que
   `assignment_notification` ya usa), y SHALL NOT introducir un segundo plazo paralelo.
3. WHERE se elija la retirada, THE SYSTEM SHALL dejar constancia de la decisión en la spec, para que
   el siguiente lector no lo reintroduzca como olvido.

## Out of scope

- **El mensaje del `409` de asignación y la guarda de la UI de `/cleaning`**: es la entrada
  `cleaning-assign-preconditions`, del mismo día de operación.
- **Ampliar la matriz** con filas de conveniencia desde `CLEANING_*` hacia estados de check-in.
  Negarse es correcto; lo que falta es la salida explícita de R3 y el aviso de R1.
- **Relajar `after_cleaning_completion`** para que cierre con un huésped dentro. Ese `409` es una
  garantía, no un defecto.
- **Desatascar REDES11 en el `dev` actual**, que es operación y no código: su reserva termina el 23
  de agosto y a partir de ahí la limpieza se puede cerrar por el camino normal.
- **Rediseñar el informe de los jobs de reloj** más allá de lo que R1 exige.
- **Auditar `properties.current_operational_state` contra el registro de transiciones**, que es lo
  que delataría el salto sin fila del 2026-08-16. Es una garantía transversal de la máquina de
  estados, no del ciclo de limpieza, y merece su propia entrada; aquí solo se retira el incentivo
  para escribir esa columna a mano.

## Affected specs

- `sdd/specs/cleaning.md` — la operación de R3, su terminal y su evidencia parcial.
- `sdd/specs/timeline-state-machine.md` — el desajuste de R1 y lo que se escribe (o no) cuando una
  transición exigida no es aplicable.
- `sdd/specs/celery-jobs.md` — la detección de R1, su ventana y el destino del trigger de R4.
- `sdd/specs/dashboard-api.md` — solo si R2 se resuelve por el dashboard.
- `sdd/specs/api-contract.md` — si R3 estrena ruta en el contrato publicado.
