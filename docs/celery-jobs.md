# Jobs programados (Celery beat)

Cómo se opera el scheduler que mueve el estado operacional de las viviendas con el reloj.
El *qué hace* está en [`sdd/specs/celery-jobs.md`](../sdd/specs/celery-jobs.md); esta página
es el *cómo se usa y se diagnostica*.

## Los nueve jobs

| Job | Cadencia | Qué hace |
|---|---|---|
| `check_checkin_windows` | cada 5 min | Reserva confirmada que entra hoy y ya está en ventana → `AWAITING_CHECKIN` |
| `mark_occupied_estimated` | cada 5 min | Hora de check-in alcanzada → `OCCUPIED_ESTIMATED` |
| `process_checkouts` | cada 5 min | Hora de check-out pasada → `AWAITING_CLEANING` **+ crea la `CleaningTask`** (change `cleaning`), y la asigna si hay una sola limpiadora activa → `CLEANING_SCHEDULED` |
| `check_sla_breaches` | cada minuto | `NotificationLog` con SLA vencido → marca + escalado en cola |
| `dispatch_notifications` | cada minuto | Drena las filas `PENDING` por su canal → `SENT` / `FAILED` / `SKIPPED` (change `access-notifications`) |
| `provision_access_records` | cada 5 min | Reserva confirmada sin `AccessRecord` → lo crea en `PENDING`, revoca los de reservas canceladas y arranca el registro legal de PRD §17 (change `access-notifications`) |
| `process_webhook_events` | cada 60 s | Drena la cola de avisos del PMS y relee por API (change `reservations-webhooks`) — ver [`reservations-webhooks.md`](reservations-webhooks.md) |
| `classify_incidents` | cada 5 min | Pasa por el clasificador toda incidencia `OPEN` que nadie ha mirado (change `maintenance`) — ver [`maintenance.md`](maintenance.md) |
| `generate_price_recommendations` | **diario, 06:00 UTC** | Recalcula el horizonte de 60 días de precio recomendado de cada vivienda activa con regla aplicable (change `revenue-pricing`) — ver [`pricing.md`](pricing.md) |

El calendario vive en `backend/app/scheduler/schedule.py`, en **dos tablas**: `CADENCES` para
los ocho que corren por periodo y `DAILY_JOBS` para el que corre a una hora del día.
`beat_schedule()` sale de las dos.

De `CADENCES` sale también el TTL del lock de cada job periódico —cadencia × 3—, así que esos
ocho no se pueden desincronizar. **El diario no puede derivarlo así**: cadencia × 3 sobre un
job diario son tres días de bloqueo si un worker muere a mitad de ejecución, de modo que
`DAILY_JOBS` lleva el suyo escrito (tres horas).

**Cinco son de PRD §8.3, con sus números: los cuatro primeros y el diario. Los otros cuatro no
están en el PRD**, y es una divergencia declarada (`access-notifications` design D2 y D3,
`reservations-webhooks` design D10, `maintenance` D2): el PRD dice *qué* tiene que pasar —§14
entrega notificaciones, §15 le da un registro de acceso a cada reserva confirmada, §16 recibe los
avisos del PMS, §12 pide que una incidencia llegue clasificada— y no dice qué lo dispara. Los
cuatro son idempotentes y dependen del reloj, así que beat es su sitio; los nombres del PRD no se
han tocado. `test_schedule.py` los separa (`PRD_8_3` y `PRD_8_3_DAILY` frente a `BEYOND_PRD_8_3`)
para que nadie invoque «lo dice el PRD» sobre un número que el PRD no ha visto nunca.

**Por qué `provision_access_records` es un barrido y no un enganche a la confirmación**: ya hay
reservas confirmadas en la base de datos. Un hook en la transición solo cubriría las futuras y
dejaría el histórico sin registro para siempre. Además las confirmaciones entran por tres
caminos (el PATCH, el import CSV y el sync del PMS, los dos últimos vía `parse_ingested`, que
confirma por defecto).

**Los 60 s de `process_webhook_events` son un parámetro de seguridad, no de tuning**: el job
coalesce todo un tick en una llamada por destino, así que la cadencia *es* el techo de llamadas
salientes al proveedor — acortarla lo sube.

**`generate_price_recommendations` no va por cadencia sino por hora del día**: corre a las
**06:00 UTC** desde una segunda tabla, `DAILY_JOBS`, de la que `beat_schedule()` también
deriva (`revenue-pricing`, 2026-08-18). Lleva su TTL de lock explícito —tres horas— en vez de
derivarlo de la cadencia como los demás, porque `lock_ttl_for` devuelve cadencia × 3 y para un
job diario eso serían tres días de bloqueo tras un worker muerto.

**El único job de PRD §8.3 que sigue sin estar aquí es `send_checkin_reminders`**, y no por
falta de reloj: es un mensaje al huésped, así que lo que le falta es el adaptador de canal y la
plantilla que traen `messaging-ai` / `access-notifications`.

## Arrancar y mirar

```bash
make up                      # levanta 'beat' junto a 'worker'
docker compose logs -f beat  # qué se despacha
docker compose logs -f worker # qué se ejecuta, con el informe de cada ejecución
```

Un despacho sano se ve así:

```
beat-1   | Scheduler: Sending due task check_sla_breaches-every-60s (check_sla_breaches)
worker-1 | Task check_sla_breaches[...] succeeded: {'tenants': 7, 'failed': 0, ...}
```

`beat` es un servicio propio, no `worker --beat`: con más de un worker, el beat embebido
dispararía N veces. Un reinicio que vuelva a disparar antes de tiempo es inofensivo — las
tareas son idempotentes y toman un lock.

Su fichero de planificación se comporta distinto según el entorno, y conviene saberlo: en
**deploy** vive dentro del contenedor y desaparece con él; en **dev** el compose bind-montea
`./backend:/app`, así que aparece como `backend/celerybeat-schedule` en tu árbol de trabajo y
sobrevive a los reinicios. Está en `.gitignore`. Si quieres que beat olvide su historial de
disparos, bórralo con el stack parado.

## Cómo leer el informe

Cada ejecución devuelve un informe por tenant. Los contadores están separados porque
significan cosas distintas para quien opera:

**Jobs de estado** (`AdvanceReport`), y cada propiedad candidata cae en exactamente un cubo:

| Contador | Significa | ¿Hay que hacer algo? |
|---|---|---|
| `transitioned` | La propiedad avanzó | No |
| `not_eligible` | Todavía no toca | No — es el caso normal |
| `already_there` | Ya estaba en el destino | No. Hoy **siempre vale 0**: los tres triggers tienen destino distinto del origen, así que una propiedad que ya transicionó deja de ser candidata |
| `unresolvable_time` | La hora local de la reserva no existe o es ambigua | **Sí.** Nunca avanzará sola |
| `ambiguous` | Dos reservas vencen a la vez para la misma propiedad | **Sí.** Nadie elige por ti |
| `blocked` | El calendario pedía mover la vivienda y su estado no lo admite | **Sí.** No se destasca sola |

`blocked` es el único contador que **no** sale de la consulta de candidatas, y por eso está fuera
de la frase de arriba: cuenta viviendas que la consulta de candidatas no puede ver. Detalle en
§«Viviendas atascadas» más abajo.

**Job de SLA** (`EscalationReport`):

| Contador | Significa | ¿Hay que hacer algo? |
|---|---|---|
| `escalated` | Incumplimiento marcado y escalado escrito | No |
| `without_action` | El tipo de notificación no tiene escalado definido | No, pero queda registrado |
| `without_recipient` | No hay manager ni owner activo a quien avisar | **Sí, urgente.** El incumplimiento se deja **sin marcar** y se reintenta cada minuto hasta que alguien arregle el roster |
| `recipients_truncated` | Había más destinatarios que una página (100) | **Sí.** Alguien no recibió el aviso |

### `dispatch_notifications`

| Contador | Significa | ¿Hay que hacer algo? |
|---|---|---|
| `sent` | Entregada y marcada `SENT` | No |
| `retrying` | Falló y le quedan intentos; vuelve en el siguiente tick | No, salvo que persista |
| `failed` | Agotó `NOTIFICATION_MAX_ATTEMPTS` (3 por defecto) | **Sí.** Nadie recibió el aviso; el motivo está en `last_error` en forma estructurada |
| `skipped` | El canal de la fila no tiene adapter (hoy solo `PUSH`) | No, es lo esperado hasta que exista |

La entrega es **at-least-once acotada**: el intento se registra y se comitea *antes* de llamar
al adapter, así que un proceso que muera a mitad reenvía como mucho hasta el techo de intentos,
en lugar de sin límite.

### `provision_access_records`

| Contador | Significa | ¿Hay que hacer algo? |
|---|---|---|
| `created` | Reserva confirmada que estrena `AccessRecord` en `PENDING` | No |
| `revoked` | Acceso de una reserva cancelada | No |
| `expired` | `valid_to` pasado | No. Hoy **siempre vale 0**: nada rellena `valid_to` hasta que haya un proveedor de accesos real |
| `legal_status_initialised` | Reserva que pasa a `PENDING_GUEST_DATA` (PRD §17 paso 1) | No |

## Viviendas atascadas (`blocked`)

Una vivienda está **atascada** cuando el calendario exige una transición de reloj, su estado
operacional no admite ese trigger, y **no consta que esa transición se haya aplicado ya para esa
reserva**. Las tres condiciones hacen falta: sin la tercera, el contador acaba siendo el tamaño
de la cartera activa (ver abajo).

El caso que lo motivó, medido en `dev` el 2026-08-22: REDES11 llevaba en `CLEANING_IN_PROGRESS`
desde el 16 con una limpieza que nadie cerró, y la reserva del 19 al 23 nunca pasó a
`OCCUPIED_ESTIMATED`. El tick de las 08:18 devolvió `candidates: 0 … not_eligible: 0` en los dos
jobs de check-in. El informe era correcto: la vivienda **nunca entró en él**, porque la consulta
de candidatas filtra por estado origen del trigger y una vivienda atascada por definición no está
en uno.

**`blocked` no es `not_eligible`, y la diferencia importa al operar.** `not_eligible` significa
«la hora no ha llegado» —el caso normal, no hay nada que hacer—. `blocked` significa «la hora
llegó y esta vivienda no puede obedecer». La segunda no se arregla esperando.

**Por qué la tercera condición.** `is_due` contesta «¿llegó ese instante?», no «¿está esta
vivienda esperándolo?»: para `CHECKIN_TIME_REACHED` es verdad durante **toda** la estancia y para
`CHECKOUT_TIME_REACHED` **para siempre** después del checkout. Y «su estado no es origen del
trigger» incluye todos los estados que una vivienda ocupa *después* de hacer bien esa misma
transición. Con sólo esas dos, una vivienda `OCCUPIED_ESTIMATED` a mitad de estancia y una
`AWAITING_CLEANING` recién salida de un checkout se reportaban las dos como atascadas, en cada
tick. La evidencia que las distingue ya estaba guardada: `property_state_transitions.metadata`
lleva `reservation_id` y `trigger`, así que «¿se aplicó ya el check-in de *esta* reserva?» es una
lectura, no una inferencia.

**La ventana, y lo que queda fuera.** La detección usa la misma `candidate_window` que las
candidatas: **30 días atrás y 2 adelante**. No hay un horizonte propio a propósito —dos ventanas
paralelas son otra cosa que mantener en sync—, y tiene una consecuencia que conviene decir en voz
alta: **un atasco de más de 30 días deja de aparecer**. Es el precio del límite, el mismo que
`CANDIDATE_LOOKBEHIND` ya paga para los checkouts pendientes, y no un descuido. Una vivienda que
lleve más de un mes parada necesita una transición manual.

**Qué se escribe.** Nada. El sweep cuenta y registra; no mueve la vivienda. Desatascarla es una
decisión de una persona —cancelar la limpieza que no va a cerrarse, resolver la incidencia— y un
job que lo hiciera solo estaría adivinando el motivo.

Cada desajuste deja una línea `scheduler.blocked_transition` con `tenant_id`, `property_id`,
`reservation_id`, `trigger`, `blocking_state` y `due_since`. **Una por desajuste, no por
vivienda**: dos reservas solapadas sobre la misma vivienda cuentan **una** en `blocked` y dejan
**dos** líneas, porque quien persigue una de las dos necesita saber de qué reserva habla.

**Se repite en cada tick mientras el atasco dure**, y eso es deliberado: nada lo resuelve
automáticamente, así que la línea desaparece cuando el atasco se arregla y no antes. Con la
tercera condición el volumen es proporcional a los atascos reales y no a la cartera; sin ella
—que fue el primer intento— eran todas las viviendas ocupadas, en cada tick, y habría ahogado
las líneas hermanas `scheduler.unresolvable_reservation_time` y
`scheduler.ambiguous_due_reservation`.

**Un caso que sí se reporta y puede sorprender**: una vivienda en `OUT_OF_SERVICE` o
`BLOCKED_BY_OWNER` con una reserva confirmada cuya hora llegó aparece como atascada. Es
intencionado —hay una reserva que nadie va a poder cumplir— pero significa que retirar una
vivienda de circulación **sin cancelar sus reservas** genera avisos hasta que se cancelen.

## Limitaciones conocidas

**Horas locales imposibles.** Una reserva cuya hora de entrada o salida no existe en la zona
de la propiedad (salto de primavera) o es ambigua (salto de otoño, porque la columna es un
`TIME` sin zona) **no avanza nunca sola**: el dominio se niega a inventar un instante, y
elegir por él sería normalizar en silencio. Aparece como `unresolvable_time` y necesita una
transición manual. Se arregla en el origen del dato, no en el reloj.

**`AWAITING_CLEANING` ya no es terminal** (change `cleaning`). `process_checkouts` crea también
la `CleaningTask` que PRD §8.3 le pide, en la misma transacción que la transición, y si hay
exactamente una limpiadora activa la asigna y mueve la propiedad a `CLEANING_SCHEDULED` en el
mismo run. Lo que hay que mirar en el informe es el contador nuevo
**`transitioned_without_task`**: cuenta los checkouts que transicionaron **sin** crear la tarea,
y sus cuatro causas son configuración del tenant (`auto_create_cleaning_task` desactivado,
`cleaning_required=false`), una tarea viva que ya existía, o **ninguna plantilla de checklist
resoluble** — la última necesita una persona. Detalle operativo en
[`cleaning.md`](cleaning.md).

**Un checkout perdido se recupera 30 días, no más.** Los triggers de entrada están acotados
al día local de la reserva, pero el de salida no: vence con `now >= fin` y sigue venciendo.
La ventana de búsqueda mira 30 días hacia atrás (`CANDIDATE_LOOKBEHIND`) para que una caída
del worker sea recuperable; más allá de eso la propiedad necesita una transición manual.

**Un `beat` colgado pero vivo pasa el healthcheck.** El de `docker-compose.deploy.yml`
comprueba que PID 1 sigue siendo beat, lo que basta para que un deploy roto falle en
`up -d --wait`, pero no prueba que esté planificando.

## Coste del filtro global por tenant

`check_sla_breaches` corre cada minuto y es el consumidor de mayor frecuencia del proyecto,
así que es donde se mide lo que cuesta el filtro global de tenant (`_scope_statement_to_tenant`
en `backend/app/core/db.py`, que adjunta un `with_loader_criteria` por clase acotada y por
sentencia, deliberadamente sin memoizar).

```bash
docker compose exec backend uv run python -m scripts.measure_tenant_filter
```

<!-- MEASUREMENT:START -->
**Medido el 2026-08-04** (3 ejecuciones, stack de dev, 50 incumplimientos y 3 managers →
150 filas de escalado):

| Magnitud | Valor |
|---|---|
| Clases acotadas (`tenant_scoped_classes()`) | **22** |
| Sentencias ORM interceptadas por ejecución | 53 |
| Tiempo dentro del listener | ~15 ms |
| **Coste por sentencia** | **~270-286 µs** |
| Porcentaje del tiempo total de la ejecución | **~14 %** |

**Lectura, y conviene no exagerarla en ninguna dirección.** En absoluto no es un problema:
15 ms una vez por minuto es ruido. Lo que el número sí dice es que **cada sentencia ORM paga
~0,3 ms solo en construir criterios de carga**, y ese coste es el producto de dos cosas que
crecen por separado: el número de clases acotadas (22 hoy; eran ~13 antes de
`domain-foundation-financial`) y el número de sentencias por ejecución. Por eso la medición
registra las clases: dentro de seis meses, con 30, este número no será comparable si no se
sabe contra cuántas se tomó.

**Qué hacer si algún día molesta**: no memoizar. `app/core/db.py:55-61` explica por qué —
`Base.registry.mappers` solo crece según se importan módulos, así que un resultado cacheado
excluiría para siempre cualquier entidad importada tarde, y `guests` (que guarda
`document_number`) es justo la que no puede quedarse fuera. La palanca es **reducir sentencias
por ejecución**, no abaratar el listener.
<!-- MEASUREMENT:END -->
