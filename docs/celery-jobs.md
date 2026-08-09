# Jobs programados (Celery beat)

Cómo se opera el scheduler que mueve el estado operacional de las viviendas con el reloj.
El *qué hace* está en [`sdd/specs/celery-jobs.md`](../sdd/specs/celery-jobs.md); esta página
es el *cómo se usa y se diagnostica*.

## Los siete jobs

| Job | Cadencia | Qué hace |
|---|---|---|
| `check_checkin_windows` | cada 5 min | Reserva confirmada que entra hoy y ya está en ventana → `AWAITING_CHECKIN` |
| `mark_occupied_estimated` | cada 5 min | Hora de check-in alcanzada → `OCCUPIED_ESTIMATED` |
| `process_checkouts` | cada 5 min | Hora de check-out pasada → `AWAITING_CLEANING` **+ crea la `CleaningTask`** (change `cleaning`), y la asigna si hay una sola limpiadora activa → `CLEANING_SCHEDULED` |
| `check_sla_breaches` | cada minuto | `NotificationLog` con SLA vencido → marca + escalado en cola |
| `dispatch_notifications` | cada minuto | Drena las filas `PENDING` por su canal → `SENT` / `FAILED` / `SKIPPED` (change `access-notifications`) |
| `provision_access_records` | cada 5 min | Reserva confirmada sin `AccessRecord` → lo crea en `PENDING`, revoca los de reservas canceladas y arranca el registro legal de PRD §17 (change `access-notifications`) |
| `process_webhook_events` | cada 60 s | Drena la cola de avisos del PMS y relee por API (change `reservations-webhooks`) — ver [`reservations-webhooks.md`](reservations-webhooks.md) |

Las cadencias viven en `backend/app/scheduler/schedule.py`. De esa misma tabla sale el TTL del
lock de cada job, así que no se pueden desincronizar.

**Los cuatro primeros son los de PRD §8.3, con sus cadencias. Los tres últimos no están en el
PRD**, y es una divergencia declarada (`access-notifications` design D2 y D3, `reservations-webhooks`
design D10): el PRD dice *qué* tiene que pasar —§14 entrega notificaciones, §15 le da un registro de
acceso a cada reserva confirmada, §16 recibe los avisos del PMS— y no dice qué lo dispara. Los tres
son idempotentes y dependen del reloj, así que beat es su sitio; los nombres de los cuatro originales
no se han tocado. `test_schedule.py` los separa (`PRD_8_3` frente a `BEYOND_PRD_8_3`) para que nadie
invoque «lo dice el PRD» sobre un número que el PRD no ha visto nunca.

**Por qué `provision_access_records` es un barrido y no un enganche a la confirmación**: ya hay
reservas confirmadas en la base de datos. Un hook en la transición solo cubriría las futuras y
dejaría el histórico sin registro para siempre. Además las confirmaciones entran por tres
caminos (el PATCH, el import CSV y el sync del PMS, los dos últimos vía `parse_ingested`, que
confirma por defecto).

**Los 60 s de `process_webhook_events` son un parámetro de seguridad, no de tuning**: el job
coalesce todo un tick en una llamada por destino, así que la cadencia *es* el techo de llamadas
salientes al proveedor — acortarla lo sube.

**Los otros dos jobs de PRD §8.3 no están aquí a propósito**: `generate_price_recommendations`
pertenece a `revenue` y `send_checkin_reminders` a `messaging-ai` / `access-notifications` —
son mensajes al huésped, no estado dependiente del reloj.

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
