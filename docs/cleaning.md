# Limpieza — cómo se opera

Capability del change `cleaning` (PRD §11, §26.10). Esta página cuenta **cómo se usa y se
opera**; el *qué hace* está en `sdd/specs/cleaning.md` con sus criterios EARS, y el contrato
HTTP en `backend/openapi.json`.

## El ciclo, de principio a fin

```
Hora de checkout alcanzada
        │  process_checkouts (cada 5 min)
        ▼
propiedad → AWAITING_CLEANING  +  CleaningTask creada   ← una sola transacción
        │
        ├── ¿exactamente una limpiadora activa? ──► asignada, propiedad → CLEANING_SCHEDULED
        │                                            + notificación con plazo de SLA
        └── ¿ninguna, o más de una? ─────────────► queda CREATED, se avisa al manager
                                                     (el manager asigna con PATCH)
        ▼
limpiadora acepta        POST /accept
        │  (o rechaza → POST /reject: la tarea queda REJECTED y nace su reemplazo sin asignar)
        ▼
limpiadora inicia        POST /start     → propiedad → CLEANING_IN_PROGRESS
        ▼
marca el checklist       POST /checklist/{item_id}/complete   (idempotente)
        ▼
cierra                   POST /complete
        │  exige: todos los ítems `required` + ninguna incidencia CRITICAL abierta
        ▼
propiedad → AWAITING_CHECKIN | READY_FOR_NEXT_GUEST | VACANT_READY   ← según sus reservas
        ▼
el manager valida        POST /validate   (PASSED | FAILED | WAIVED)
```

Ninguna de esas flechas de estado de propiedad la escribe este módulo por su cuenta: todas
pasan por `PropertyStateMachine`, que es el único sitio donde ocurre una transición
(`sdd/steering/architecture.md`).

## Antes de que nada funcione: la plantilla de checklist

`cleaning_tasks.checklist_template_id` es obligatoria, así que **un tenant sin plantilla activa
no puede tener tareas de limpieza**. El checkout transiciona igual, pero no crea la tarea y lo
cuenta aparte en el informe del job (`transitioned_without_task`), con un registro que lleva
`tenant_id` y `property_id`.

```bash
curl -X POST .../api/v1/cleaning-checklist-templates \
  -H 'Authorization: Bearer <token de manager u owner>' \
  -d '{"name":"Estándar",
       "items":[{"item_id":"kitchen","label":"Cocina","required":true}],
       "required_photos":[{"photo_type":"kitchen","label":"Cocina","required":true}]}'
```

Resolución, en este orden: la plantilla activa **de la propiedad**; si no hay, la activa **del
tenant** (`property_id` nulo). Dos activas en el mismo nivel es una ambigüedad y se **rechaza**
(`409`) en vez de desempatarse — elegir una anclaría el contenido del checklist a un criterio
arbitrario.

`item_id` es la clave con la que se marca el ítem y viaja como segmento de URL, así que solo
admite letras, dígitos, `.`, `_` y `-`, con un máximo de 100 caracteres, y es único dentro de la
plantilla.

## Quién puede hacer qué

| | Owner | Manager | Limpiadora |
|---|---|---|---|
| Ver y crear plantillas | sí | sí | no |
| Ver tareas | todas | todas | **solo las suyas** |
| Crear, asignar y validar | no | sí | no |
| Aceptar, rechazar, iniciar, cerrar, marcar checklist | no | **no** | sí |

Las dos filas de abajo no se solapan a propósito: PRD §11 dice «la limpiadora asignada» sin
excepción, así que ejecutar es solo de ella y lo que el manager necesita —reasignar, crear,
validar— va por su propio permiso.

Para una limpiadora, una tarea que no es suya responde **`404`**, no `403`, y con el mismo
cuerpo que un id inexistente: un `403` convertiría el endpoint en una sonda para averiguar qué
tareas existen.

## Dos límites que conviene conocer antes de operar

**Las fotos todavía no se piden.** La regla de PRD §11 tiene tres cláusulas y aquí se aplican
dos: ítems requeridos e incidencias `CRITICAL`. La tercera —«todas las fotos `required`
subidas»— llega con la entrada de roadmap `cleaning-photos-storage`, que trae el
`StorageAdapter`, la subida y las signed URL. **Hasta entonces una limpieza puede cerrarse sin
las fotos**, y eso es un hueco conocido, no un descuido.

**El escalado por SLA ya funciona** (desde `access-notifications`). Al asignar se escribe una
fila de `notification_logs` con `sla_deadline_at = ahora + TenantConfig.sla_medium_minutes` (240
min por defecto). `dispatch_notifications` la entrega y la marca `SENT`, que es la condición que
`check_sla_breaches` exige para considerarla candidata; si el plazo vence sin respuesta, el
manager recibe un `SLA_BREACH`.

**Y responder cierra el plazo.** Aceptar o rechazar la tarea anula el `sla_deadline_at` de esa
fila —sin tocar `status` ni `sla_breached`, así que ni se afirma un incumplimiento que no hubo ni
se niega una entrega que sí ocurrió—, de modo que una limpiadora que acepta en diez segundos no
genera un escalado cuatro horas después. Esta parte era la deuda que `cleaning` recortó en su
`/sdd:review` del 2026-08-06 por no existir todavía el emisor.

**Y las incidencias tampoco se pueden crear todavía.** La precondición de cierre consulta la
tabla `incidents` de verdad, pero `maintenance` no tiene capa de aplicación, así que en la
práctica siempre responde «ninguna abierta». El botón «reportar incidencia» de la app de la
limpiadora es de `maintenance` (PRD §26.11).

## Operar el job

`process_checkouts` corre cada 5 minutos bajo un lock de Redis, un tenant por sesión y una
transacción por tenant. Su informe distingue lo que hay que mirar de lo que es rutina:

| Contador | Qué significa |
|---|---|
| `transitioned` | checkout cerrado |
| `transitioned_without_task` | **mirar esto**: config desactivada, `cleaning_required=false`, ya había tarea viva, o no hay plantilla resoluble |
| `not_eligible` | la hora no ha llegado — el caso normal |
| `unresolvable_time` / `ambiguous` | necesitan una persona; no se arreglan solos |

Recupera atrasos hasta 30 días (`CANDIDATE_LOOKBEHIND`), así que una parada larga del worker se
reprocesa. La ventana de la limpieza (`scheduled_start`/`scheduled_end`) se ancla al checkout
efectivo y a la llegada del siguiente huésped, **no** al momento en que el job corrió: un
checkout procesado tarde conserva su plazo.

Una reserva no puede tener dos limpiezas vivas a la vez, y lo garantiza el índice
`uq_cleaning_tasks_live_reservation`, no una comprobación previa. Un rechazo y su reemplazo sí
coexisten, igual que una limpieza posterior de la misma reserva.

## Qué queda registrado

- **`property_state_transitions` + `TimelineEvent`** en cada movimiento de estado.
- **`AuditLog`** en cada acción de una persona: crear, asignar, aceptar, rechazar, iniciar,
  cerrar y validar. El alta automática del checkout va con actor `SYSTEM` y está exenta por la
  regla 9 de `sdd/steering/security.md`.
- **`notification_logs`** al asignar (con plazo) y cuando no hay a quién asignar (sin plazo).

Las columnas `notes` de `cleaning_tasks` y `cleaning_checklist_completions` **no se escriben ni
se devuelven** en este change: son texto libre que la regla 11 de `steering/security.md` no
enumera, y ampliar esa tabla es una decisión de steering (design D13).

## El diagrama de secuencia, y qué parte de él es todavía futuro

[`diagrams/2026-07-13_autohost-secuencia-limpieza.png`](diagrams/2026-07-13_autohost-secuencia-limpieza.png)
dibuja el flujo **completo** de PRD §11 y sigue siendo el objetivo, así que no se ha
redibujado: recortarlo a lo construido borraría el destino que `cleaning-photos-storage` y
`access-notifications` van a levantar. Lo que sí conviene saber al leerlo es qué tres cosas no
existen aún, para no buscarlas en el código:

| En el diagrama | Hoy |
|---|---|
| `NotificationAdapter` → «WhatsApp / email (mock)» | Este módulo solo **escribe** la fila de `notification_logs`, en `PENDING`. El envío lo hace `dispatch_notifications` (change `access-notifications`), que es lo que la marca `SENT`. |
| «subir fotos requeridas» y `AIAdapter.validate_cleaning_photo()` | Nada de eso existe: fotos y `StorageAdapter` son de `cleaning-photos-storage`, la validación con IA de `messaging-ai`. |
| `PropertyStateMachine` «crear CleaningTask» | La crea `ProvisionCleaningTaskUseCase`, invocado **dentro** de la transacción del caso de uso que mueve el estado (design D1). La máquina sigue decidiendo la transición y nada más — crear entidades no es su trabajo. |

## Entradas de roadmap relacionadas

- `cleaning-photos-storage` — fotos, `StorageAdapter`, signed URL, y la tercera cláusula de la
  regla de validación.
- `access-notifications` — **entregado**: trajo el emisor que marca `SENT` y el cierre del plazo al responder.
- `maintenance` — creación de incidencias, incluida la que bloquea el cierre.
- `field-apps` — la app mobile-first de la limpiadora que consume todo esto.
