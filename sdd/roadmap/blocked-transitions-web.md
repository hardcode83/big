# blocked-transitions-web

[FE] pintar los desajustes entre el calendario y el estado donde el manager ya mira.

Encargo explícito del design D11 de `cleaning-stall-blocks-next-stay`, escrito allí porque
«ningún gate posterior lo delataría si se olvidase», y creado al archivar ese change
(2026-08-24).

## Por qué existe

`cleaning-stall-blocks-next-stay` entregó el dato y **no** la pantalla: su entrada de roadmap era
`[BE]` y el change es `kind: tech`. Colar una pantalla mínima habría cruzado ese límite y
arrastrado i18n y contrato de frontend, así que se rechazó a propósito.

La consecuencia es que la lectura literal de su R2 —«que no me enteré por un huésped»— **no se
cumple todavía**: `GET /api/v1/blocked-transitions` existe, es consultable por el rol correcto y
se vacía solo, pero un manager no lee JSON. Lo que ese change garantiza es que el dato existe;
esta entrada es la que lo hace llegar a una persona.

## Qué hay hecho, y con qué forma

`GET /api/v1/blocked-transitions`, permiso `READ_PROPERTIES` —lo tienen `PROPERTY_MANAGER` y
`TENANT_OWNER`, es decir también la propietaria que PRD §1 describe operando dos viviendas desde
el móvil—. Envelope paginado de PRD §23, ordenado por `due_since` ascendente: lo primero es lo que
lleva más tiempo parado. Cada entrada trae `property_id`, `property_code`, `reservation_id`,
`trigger`, `blocking_state` y `due_since`.

Comportamiento en `sdd/specs/celery-jobs.md` §Desajustes entre el calendario y el estado; cómo se
opera, en `docs/properties.md`.

## Lo que esta entrada tiene que decidir

- **Dónde se pinta.** La card de la vivienda en el dashboard o `/cleaning` —o las dos—. El dato es
  por vivienda + reserva + trigger, así que no encaja tal cual en una lista de tareas.
- **El catálogo de traducciones que estrena.** `trigger` y `blocking_state` viajan como los
  **literales canónicos** (`CHECKIN_TIME_REACHED`, `CLEANING_IN_PROGRESS`), sin prosa y sin color:
  el mismo trato que `dashboard-api` da a `operational_state`. Se hizo así a propósito para no
  estrenar un catálogo de traducciones con un consumidor que aún no existía — y ese catálogo, en
  `locales/es` **y** `locales/en`, es de esta entrada.
- **La acción al lado del aviso.** Un desajuste sin salida es el mismo silencio con otra forma. Las
  dos salidas reales son cancelar la limpieza
  (`POST /api/v1/cleaning-tasks/{task_id}/cancel`, `MANAGE_CLEANING_TASKS`, con motivo obligatorio)
  y resolver la incidencia. Ojo: la propietaria **ve** el aviso con `READ_PROPERTIES` pero **no
  puede cancelar** —`MANAGE_CLEANING_TASKS` es sólo del `PROPERTY_MANAGER`—, así que la pantalla
  tiene que separar ver de poder actuar en vez de ofrecer un botón que responde `403`.

## Dos límites del backend que la pantalla hereda

- **La ventana es de 30 días atrás y 2 adelante**, la misma `candidate_window` que las candidatas.
  Un atasco de más de 30 días **deja de aparecer en la colección**: no es un bug de la pantalla y
  no se arregla en ella. Conviene que la UI no prometa exhaustividad que la fuente no tiene.
- **`PropertyRepository.list_all` no está paginado en origen.** Con dos viviendas es irrelevante;
  con doscientas son dos consultas grandes por petición. La palanca está escrita: filtrar por el
  complemento de estados origen por trigger, como hace el job. Si esta pantalla lo pone en un
  polling, esa deuda pasa a importar.
