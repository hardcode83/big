# Mantenimiento — cómo se opera

Capability del change `maintenance` (PRD §12, §26.11). Esta página cuenta **cómo se usa y se
opera**; el *qué hace* está en `sdd/specs/maintenance.md` con sus criterios EARS, y el
contrato HTTP en `backend/openapi.json`.

## El ciclo, de principio a fin

```
alguien reporta una avería            (el portal del huésped, la limpiadora,
                                       una conversación, o `make seed-demo`)
        │
        ▼
incidencia OPEN, sin categoría ni severidad
        │  classify_incidents (cada 5 min)  ── o ──  POST /incidents/{id}/classify
        ▼
   ¿confianza ≥ ai_confidence_threshold?
        │
        ├── sí ──► CLASSIFIED, con categoría y severidad
        │            │  si severidad HIGH/CRITICAL:
        │            └─► propiedad → MAINTENANCE_REQUIRED | CRITICAL_INCIDENT
        │
        └── no ──► sigue OPEN, con `ai_classification` escrita
                     (queda para triaje humano, y el job ya no vuelve a preguntar)
        ▼
el manager tría          PATCH /incidents/{id}     categoría, severidad, coste estimado
        │
        ├── coste ≤ umbral del tenant ──────────► sigue el flujo
        └── coste > umbral ─────────────────────► AWAITING_OWNER_APPROVAL
                                                   + OwnerApproval PENDING (related_type=INCIDENT)
                                                   + notificación a la propietaria
        ▼
la propietaria responde  POST /owner-approvals/{id}/respond
        ├── APPROVED ──► vuelve a CLASSIFIED, con `approved_cost` fijado
        └── REJECTED ──► CANCELLED, y la propiedad se recompone
        ▼
el manager asigna        POST /incidents/{id}/assign   → ASSIGNED
                                                        + notificación al técnico
                                                        + plazo de SLA según la severidad
        ▼
el técnico acepta        POST /incidents/{id}/accept   → ACCEPTED  (cancela el plazo)
empieza                  POST /incidents/{id}/start    → IN_PROGRESS
espera piezas            POST /incidents/{id}/wait-parts → WAITING_EXTERNAL_PARTS
reanuda                  POST /incidents/{id}/resume   → IN_PROGRESS
        ▼
cierra                   POST /incidents/{id}/resolve  { "final_cost": … }
        │
        ├── coste cubierto o bajo umbral ──────► RESOLVED, con `resolved_at`
        │                                        propiedad recompuesta
        └── coste > umbral y sin cubrir ───────► AWAITING_OWNER_APPROVAL, **sin** resolver
                                                 + OwnerApproval (related_type=MAINTENANCE_COST)
                                                 aprobada → vuelve a IN_PROGRESS y reintenta
```

Ninguna de esas flechas de estado de propiedad la escribe este módulo por su cuenta: todas
pasan por `PropertyStateMachine`, que es el único sitio donde ocurre una transición
(`sdd/steering/architecture.md`).

## Las dos puertas de la propietaria, y por qué son dos

PRD §12 pone el umbral sobre el **coste estimado**. Si sólo existiera esa puerta, estimar
90 € y gastar 500 se saltaría la regla de aprobación entera, así que hay una segunda sobre el
**coste real** al cerrar. Se distinguen por el `related_type` de la aprobación, que es también
lo que decide a dónde vuelve la incidencia cuando la propietaria dice que sí:

| `related_type` | Quién la abrió | Vuelve a |
|---|---|---|
| `INCIDENT` | el triaje, con un `estimated_cost` por encima del umbral | `CLASSIFIED` |
| `MAINTENANCE_COST` | el cierre, con un `final_cost` por encima del umbral y sin cubrir | `IN_PROGRESS` |

«Cubierto» significa que la incidencia ya lleva un `approved_cost` **mayor o igual** que el
coste final. Una aprobación de 450 € no estira para una factura de 500 €.

Al aprobar el coste real el sistema **no cierra la incidencia**: la devuelve a `IN_PROGRESS`
y el técnico repite el cierre. Cerrarla por él haría que `resolved_at` dejara de significar
«lo dio por terminado».

## Quién puede hacer qué

| | propietaria | manager | técnico | limpiadora |
|---|---|---|---|---|
| Ver incidencias | ✔ | ✔ | ✔ sólo las suyas | — |
| Clasificar, triar, asignar, cancelar | — | ✔ | — | — |
| Aceptar, empezar, esperar piezas, reanudar, resolver | — | ✔ | ✔ sólo las suyas | — |
| Responder una aprobación | ✔ | — | — | — |
| Abrir una incidencia desde su propia limpieza | — | — | — | ✔ |

Tres cosas que no se ven en la tabla y conviene saber:

- **El técnico sólo ve y opera las suyas**, y eso no es un filtro que la petición pida: sale
  del rol del token. Una incidencia asignada a otro técnico devuelve el **mismo `404`** que
  una que no existe — con el mismo cuerpo —, para que el endpoint no sirva de sonda.
- **El manager también puede conducir el ciclo del técnico**, para desatascar. Es la única
  diferencia con limpieza, donde ejecutar es sólo de la limpiadora.
- **La limpiadora abre incidencias y no lee ninguna**, y esa fila de la tabla es toda su
  relación con este módulo. Las once rutas de `/api/v1/incidents` le siguen respondiendo `403`;
  lo que puede hacer vive en otro sitio y se describe abajo. **Con una señal indirecta que
  conviene no negar**: al cerrar su limpieza puede recibir un `409` que le dice que en esa
  vivienda hay una incidencia `CRITICAL` sin resolver. Es un bit —existe o no—, sin id, sin
  título y sin descripción, y está descrito en [`cleaning.md`](cleaning.md).

## Reportar una incidencia desde una limpieza

`POST /api/v1/cleaning-tasks/{task_id}/incidents` — PRD §11 la pide entre los nueve elementos de
la app de la limpiadora y PRD §12 la lista como una de las cinco fuentes de creación.

**Cuelga de la tarea de limpieza, no de la incidencia**, y por eso la ruta no está bajo
`/api/v1/incidents`: el sujeto es la limpieza que está haciendo. Este módulo sigue sin exponer
ninguna ruta de creación propia.

Cómo se opera, y qué decide el sistema en lugar de quien llama:

- El cuerpo son **exactamente dos campos**, `title` y `description`. Cualquier otro —
  `property_id`, `source`, `severity`, un coste— se rechaza con `422` en vez de ignorarse.
- La vivienda **sale de la tarea**, nunca de la petición. La incidencia queda sellada
  `source = CLEANER`, atribuida a su usuario y vinculada a esa limpieza.
- Nace `OPEN` y **sin clasificar**: el job de arriba le pone categoría y severidad en su
  siguiente vuelta, y desde ahí es del manager.
- Solo alcanza **sus propias tareas**, por el rol persistido del token y sin que ningún campo
  pueda ensancharlo. Una tarea inexistente, de otro tenant o de otra limpiadora dan el **mismo
  `404`**, con el mismo cuerpo.
- Se puede reportar mientras el trabajo está vivo — `ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`. Sobre
  una tarea ya cerrada, rechazada o cancelada responde `409`: PRD §12 dice «durante checklist».
- La respuesta es un acuse de **tres campos** —`id`, `status`, `created_at`— y nada más. No
  devuelve la descripción: no hay nada que aprender de ella y es texto libre.

**Reportar no le bloquea cerrar la limpieza**, que es la duda inmediata en cuanto existe el botón.
La incidencia nace `MEDIUM` y el cierre solo lo frena una `CRITICAL` sin resolver **en la
vivienda**, así que empieza a bloquear si el clasificador la sube — o si ya había otra. El detalle
está en [`cleaning.md`](cleaning.md).

## El job de clasificación

`classify_incidents` corre cada 5 minutos y recoge lo que esté en `OPEN` **y sin
`ai_classification`**. Ese par es toda la regla, y da las dos propiedades que hacen falta:

- una incidencia cuyo adaptador **falló** vuelve a entrar, porque no se escribió nada;
- una de **confianza baja** no vuelve, porque su `ai_classification` sí está escrita — un
  adaptador determinista respondería lo mismo para siempre y el job giraría en vacío.

No se clasifica dentro de la petición que crea la incidencia, y el motivo es de seguridad: el
único escritor de `incidents` en `OPEN` es hoy una petición **anónima desde internet**, y
colgar de ella la llamada al clasificador es la forma que prohíbe la regla 12(d) de
`sdd/steering/security.md`. Con un proveedor de IA real detrás del puerto sería además un
coste por petición que decide un tercero no autenticado.

El clasificador de desarrollo (`RuleBasedIncidentClassifier`) es determinista y funciona por
palabras clave en español e inglés. Lo que no reconoce lo deja por debajo del umbral, es
decir, para triaje humano.

**Lo que hay que saber el día que se enchufe un proveedor de IA real**: una incidencia cuya
clasificación **falla** conserva `ai_classification` a `NULL`, así que vuelve a entrar en cada
tick — para siempre, si el fallo es permanente. El trabajo por tick está acotado por
`NOTIFICATION_BATCH_SIZE` y por tenant, así que no crece con el número de incidencias que
abra un anónimo (regla 12(d)), pero una avalancha de reportes que el proveedor no sepa
clasificar se convierte en carga saliente permanente y acotada. Se ve en el contador
`failed` del informe del job.

## Qué se guarda de lo que escribe la gente

`incidents.title` y `description` son la prosa de quien reporta, y se guardan tal cual — es la
excepción 2 de la regla 11 de `sdd/steering/security.md`. **Lo que se escribe desde nuestro
código es otra cosa** y va en forma estructurada:

- `ai_summary` sale del vocabulario cerrado del adaptador, nunca del texto de entrada. Si un
  adaptador devuelve un resumen que comparte ocho caracteres seguidos con lo reportado, el
  campo se descarta.
- `ai_classification` guarda cinco claves cerradas: categoría, severidad, confianza, adaptador
  e instante.
- `owner_approvals.reason` es una constante más el id de la incidencia.

Ninguna de las cuatro entra en `audit_logs.changes` ni en el `metadata` del timeline.

**Conviene decírselo a quien opera**: si el huésped teclea su número de documento en la
descripción, ahí queda. Es texto que él eligió enviar, y lo verá el técnico que reciba el
parte — la cara simétrica de la advertencia que `docs/guest-portal.md` da sobre
`properties.access_notes`.

## Rastro

Cada transición deja su fila en `audit_logs` y su hito en el timeline de la propiedad, en la
**misma transacción** que el cambio. Dos matices:

- La clasificación **automática** va sin actor (`actor_user_id` y `actor_ip` a `NULL`) y con
  actor `AI` en el timeline: la dispara el reloj, no una persona. Es la cuarta excepción
  nombrada de la regla 9. La clasificación manual de un manager sí lleva su actor.
- `WAITING_EXTERNAL_PARTS` **no genera evento de timeline**: el vocabulario de PRD §10 no
  tiene un tipo para esperar una pieza, y el hito ya lo cuenta el `status` de la incidencia.
  El coste asumido es que el timeline no explica por sí solo por qué una incidencia lleva
  días abierta; eso se ve en la incidencia.

## Lo que este change no trae

Fotos de la incidencia (el patrón es el de `cleaning-photos-storage`), el `Expense` al
resolver (es de `revenue`), la expiración automática de una aprobación, la UI del técnico
(`tech-app`), la detección del intent desde la mensajería (`messaging-ai`) y la alerta de
cerradura como fuente. Cada uno tiene dueño declarado en el proposal del change.

De la ruta de la limpiadora falta **su pantalla**: la API existe y el botón lo pone `cleaner-app`,
que declara `cleaner-incident-report` en su `needs`. Y ella sigue sin poder leer, listar ni seguir
lo que abrió: el acuse de tres campos es toda la lectura que tiene de una incidencia. Lo único que
aprende además es el bit del `409` de cierre —que en la vivienda hay una `CRITICAL` sin resolver—,
y se dice aquí porque «toda su lectura» a secas invita a tratar ese cuerpo como si no revelase
nada, que es justo el razonamiento con el que alguien lo ensancharía.
