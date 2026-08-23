# Limpieza — cómo se opera

Capability de los changes `cleaning` y `cleaning-photos-storage` (PRD §11, §26.10). Esta página
cuenta **cómo se usa y se opera**; el *qué hace* está en `sdd/specs/cleaning.md` con sus
criterios EARS, y el contrato HTTP en `backend/openapi.json`.

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
sube las fotos           POST /photos          (multipart, una por llamada)
        ▼
cierra                   POST /complete
        │  exige: todos los ítems `required`
        │        + al menos una foto de cada `photo_type` `required` de la plantilla
        │        + ninguna incidencia CRITICAL abierta
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
| Ver las fotos de una tarea | todas | todas | **solo las de las suyas** |
| Crear, asignar y validar | no | sí | no |
| Aceptar, rechazar, iniciar, cerrar, marcar checklist, **subir fotos** | no | **no** | sí |

Las dos filas de abajo no se solapan a propósito: PRD §11 dice «la limpiadora asignada» sin
excepción, así que ejecutar es solo de ella y lo que el manager necesita —reasignar, crear,
validar— va por su propio permiso.

Para una limpiadora, una tarea que no es suya responde **`404`**, no `403`, y con el mismo
cuerpo que un id inexistente: un `403` convertiría el endpoint en una sonda para averiguar qué
tareas existen.

## El contexto de la tarea: a qué piso hay que ir, y con qué margen

`GET /api/v1/cleaning-tasks/{task_id}/context` (change `cleaner-task-context`) existe para una
razón concreta: el rol `CLEANER` tiene cinco permisos y **ni `READ_PROPERTIES` ni
`READ_RESERVATIONS` están entre ellos**, así que las rutas de propiedades y reservas le
contestan `403` y `CleaningTaskResponse` solo le da `property_id` y `reservation_id` como UUID
pelados. Sin esta ruta, la app de la limpiadora no puede decirle a qué piso tiene que ir.

Devuelve **once campos y ninguno más**: nombre y código interno de la propiedad, sus seis campos
de dirección, el `timezone`, y los dos instantes de la ventana de trabajo. No es un volcado de
`Property` ni de `Reservation` — es una proyección con lista cerrada, y eso es lo que mantiene
fuera las notas en claro (`access_notes`, `cleaning_notes`, `emergency_notes`) y todo el dinero,
el canal y el huésped de la reserva. El *qué devuelve* exactamente está en
`sdd/specs/cleaning.md` y la forma en `backend/openapi.json`; aquí va lo que no se deduce de
ninguno de los dos.

**Quién ve qué es la regla de siempre**: una limpiadora alcanza solo sus tareas, un manager o
una propietaria las de todo su tenant. Sale del rol persistido del token y **ningún parámetro de
la petición lo ensancha**. Una tarea que no es suya responde `404` con el mismo cuerpo que un id
inexistente, igual que el resto del módulo.

### Los dos instantes son la respuesta de ahora, no el plan

`checkout_at` y `next_checkin_deadline` se resuelven **en el momento de la lectura**, contra las
reservas que haya. No son `scheduled_start` y `scheduled_end`, que son el **plan** con el que se
creó la tarea y sobre el que se construyeron la asignación y el SLA.

Los dos pares pueden discrepar, y no es un bug: se llaman distinto justo para que la
discrepancia no se lea como una contradicción. La instantánea guardada la calcula el job con una
ventana de dos días, así que una llegada a cinco días vista deja `scheduled_end` vacío **para
siempre**; y una tarea creada a mano toma los dos valores del cuerpo de la petición sin resolver
nada. La lectura viva no tiene ninguno de los dos problemas.

### Qué significa `null` en cada uno, que no es lo mismo

Los dos campos son anulables y cada `null` dice una cosa distinta:

| Campo | `null` significa |
|---|---|
| `checkout_at` | La tarea **no tiene reserva saliente** —es una tarea manual creada por `POST /cleaning-tasks`—, o los límites locales de la estancia no se pueden materializar (una hora que no existe por el cambio de hora). Nunca es una hora inventada. |
| `next_checkin_deadline` | **No hay ninguna llegada `CONFIRMED` en los 14 días siguientes** al ancla — que es el checkout, o `now` si no lo hay. Ojo: no es «no hay próxima llegada», es «no la hay dentro del horizonte». Una llegada `PENDING` tampoco impone deadline. |

El horizonte de 14 días es una decisión declarada (`ASSUMPTION`, design D10), no una
consecuencia de cómo se consultó: el deadline existe para que una limpiadora ordene su jornada, y
una llegada a dos semanas no aprieta la limpieza de hoy.

Un tercer caso, más raro: si la tarea apunta a una reserva que **ya no resuelve dentro del
tenant** —borrada, o un puntero cruzado—, la respuesta degrada a `checkout_at: null` y deja un
`warning` en el log, en vez de negar el contexto entero. La dirección es la mitad de lo que esta
ruta existe para dar, y perderla por un puntero colgado sería el peor de los dos males (design
D6, addendum del 2026-08-18).

Ambos instantes viajan en ISO 8601 **con offset explícito**, en el timezone de la propiedad —que
también viaja, para que el cliente pueda leer ese offset como un lugar.

## Las fotos de la limpieza

Las tres cláusulas de PRD §11 se aplican ya: ítems `required`, **fotos `required`** e
incidencias `CRITICAL`. Lo que sigue es cómo se opera; el *qué hace*, con sus criterios EARS,
está en `sdd/specs/cleaning.md`, y la forma exacta de cada petición y respuesta en
`backend/openapi.json` (o en `/docs`).

Qué fotos pide una tarea lo decide su plantilla, en el mismo `required_photos` del ejemplo de
más arriba. Una plantilla sin ninguna foto `required` es legítima: entonces el cierre no exige
ninguna.

### Subir

```bash
curl -X POST .../api/v1/cleaning-tasks/<task_id>/photos \
  -H 'Authorization: Bearer <token de la limpiadora asignada>' \
  -F photo_type=kitchen \
  -F file=@cocina.jpg
```

`201` con la foto y su URL firmada. Lo que conviene saber antes de operar:

- **Una foto por llamada**, `multipart/form-data`. Varias del mismo `photo_type` están
  permitidas a propósito — la que falta es la que no tiene ninguna, no la que tiene dos.
- El formato se decide por los **bytes**, nunca por el `Content-Type` que manda el cliente:
  JPEG, PNG y WebP. Cualquier otra cosa es un `422`. **HEIC/HEIF queda fuera**, y eso es lo que
  más se va a notar operando: es el formato nativo de la cámara del iPhone, así que una
  limpiadora con un iPhone tiene que tener el móvil en «Más compatible» o la subida le rebotará.
  Es una decisión tomada, no un olvido: soportarlo obliga a transcodificar, porque Chrome y
  Firefox no lo pintan.
- La tarea tiene que estar **`IN_PROGRESS`**: contra cualquier otro estado es `409`. No se
  archiva evidencia de una limpieza que no ha empezado o que ya se cerró.
- Un `photo_type` que la plantilla no declara es `404`. Una tarea de otro tenant o de otra
  limpiadora, también `404`, y con el mismo cuerpo que un id inexistente — misma razón que en la
  tabla de arriba.
- Tope de tamaño **propio**, `PHOTO_UPLOAD_MAX_BYTES` (10 MB por defecto): por encima es `413`,
  cortado antes de leer el cuerpo entero. Si una foto no cabe, **sube esa variable y no
  `REQUEST_MAX_BYTES`**: el techo general lo comparten todas las rutas JSON, y subirlo por una
  foto se lo afloja a todas ellas. Esta variable existe justamente para no tener que tocarlo.
- Si el almacén rechaza la escritura es `502` y **no queda fila**: el objeto se escribe primero y
  la fila después, nunca al revés, para que no exista una foto en la base de datos que no exista
  en disco.

### Listar

`GET /api/v1/cleaning-tasks/<task_id>/photos` devuelve `{"data": [...]}` con las fotos de la
tarea, de la más antigua a la más reciente y **cada una ya con su URL firmada**. Lo lee la
limpiadora asignada, y también el manager y el owner del tenant, que es como se revisa el
trabajo sin tener que ser quien lo hizo.

`storage_key` **no es un campo de la respuesta** y no va a serlo: la respuesta enumera sus
campos uno a uno en vez de volcar la entidad, precisamente para que la ruta interna del objeto
no se publique el día que alguien busque la forma cómoda.

### La ruta que sirve la foto es anónima, y es deliberado

`GET /api/v1/cleaning-photos/<photo_id>?exp=<...>&sig=<...>` **no lleva `require(...)`**. No es
un olvido ni una regla que falte: un `<img src>` no manda cabecera `Authorization`, y una URL
firmada que solo funcione desde `fetch` no sirve para mostrar una foto. **La firma es la
credencial** — un HMAC sobre la clave interna del objeto (que empieza por `tenants/{tenant_id}/`)
y sobre `exp`, así que no se puede trasladar a otra foto, a otro tenant ni a un plazo posterior.
Vive 3600 s.

Firma ausente, incorrecta, caducada, manipulada o de una foto que no existe: **las cinco
contestan el mismo `403` con el mismo cuerpo**, byte a byte. Distinguirlas convertiría una ruta
sin credenciales en un oráculo para averiguar qué fotos existen.

Los bytes salen con el `Content-Type` derivado de la extensión almacenada,
`X-Content-Type-Options: nosniff` —sin él, un fichero que empiece por `FF D8 FF` y lleve HTML
dentro se ejecutaría como XSS almacenado en el origen de la API— y
`Cache-Control: private, max-age=<lo que le quede a la firma>`, para que la copia del navegador
caduque a la vez que la credencial que la trajo.

### Dónde viven las fotos

Cada tenant tiene un `storage_type`, `LOCAL` por defecto, y no se cambia desde el `update` de
tenant: darle la vuelta dejaría apuntando a un almacén las fotos que están en el otro. La única
vía es el **seed** — `BOOTSTRAP_STORAGE_TYPE` y una re-ejecución de `python -m app.cli.bootstrap`,
que converge la configuración del tenant— y sigue teniendo la misma consecuencia, así que hay que
comprobar antes que ese tenant no tenga fotos ya subidas (procedimiento en
`infra/environments/dev/RUNBOOK.md` §9.2).

- **`LOCAL`** — el adaptador escribe bajo **`/app/media`** dentro del contenedor `backend`, que
  es el volumen con nombre `backend_media` de `docker-compose.yml`. El objeto queda en
  `tenants/<tenant_id>/cleaning-tasks/<task_id>/<photo_id>.<ext>`, así que el tenant es el primer
  segmento de la clave y por tanto de lo que firma el HMAC. La URL es **relativa**
  (`/api/v1/cleaning-photos/<photo_id>?exp=…&sig=…`), la resuelve el cliente contra su propio
  origen, y **no contiene la ruta interna del objeto**.
- **`S3`** — la URL firmada la emite el propio proveedor, así que necesariamente lleva el bucket
  y la clave del objeto: es inherente a cómo funciona un presigned URL y no es algo que esta API
  pueda recortar. **Aceptado por escrito**, con su razón y las dos alternativas descartadas, en
  [ADR 0008](adr/0008-object-storage-provider-dev.md). Para un tenant `S3` la ruta de servido de
  arriba contesta `404`, porque el navegador va directo al almacén.

  Qué almacén hay detrás es **configuración**, no código: `S3_BUCKET`, `S3_REGION` y
  `S3_ENDPOINT_URL`, más el par `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` que boto3 lee de su
  cadena estándar. Con las cinco vacías —el caso local— nada cambia: `LOCAL` funciona igual y un
  tenant `S3` falla ruidosamente en vez de caer a disco. En `dev` el proveedor es OCI Object
  Storage y Terraform aprovisiona el bucket; qué vale cada ajuste en OCI, AWS S3, Cloudflare R2 y
  MinIO está tabulado en el mismo ADR.

**Coste que hay que conocer: `docker compose down -v` borra el volumen y con él todas las fotos
subidas.** `make down` no lo hace —para los contenedores y conserva los volúmenes—, pero el
`-v` es un reflejo frecuente para «empezar limpio» y aquí se lleva por delante la evidencia de
todas las limpiezas. Es un stack de desarrollo y no hay copia de seguridad de nada de eso.

### Al cerrar

`POST /complete` comprueba, **en este orden**: ítems `required` → fotos `required` →
incidencias `CRITICAL` abiertas. Si falta alguna foto responde `409` **enumerando los
`photo_type` que faltan**, ordenados, con la misma forma que el `409` de los ítems:

```json
{"error": {"code": "CONFLICT",
           "message": "Required photos are not uploaded: bathroom, kitchen",
           "details": {}}}
```

Cuenta como cubierto un `photo_type` con **al menos una** foto subida para esa tarea. Fotos de
otra tarea no cuentan, aunque sean del mismo tipo.

## El límite que queda, y los dos que ya no lo son

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

**Ese límite ya no existe, y conviene leer lo que ocupó su sitio.** Esta página decía que las
incidencias no se podían crear todavía, que `maintenance` no tenía capa de aplicación y que la
precondición de cierre respondía siempre «ninguna abierta». Las tres cosas eran ciertas y ya no lo
son: `maintenance` tiene su flujo desde el 2026-08-15, y `cleaner-incident-report` le da a la
limpiadora una ruta para abrir una incidencia **desde la tarea que está haciendo** —
`POST /api/v1/cleaning-tasks/{task_id}/incidents`, descrita en
[`maintenance.md`](maintenance.md#reportar-una-incidencia-desde-una-limpieza).

**Y eso acopla reportar con cerrar, así que aquí va cómo se comporta de verdad**, porque es la
pregunta que hace una limpiadora en cuanto usa el botón:

- La incidencia que abre nace `MEDIUM`. **No le bloquea el cierre en ese momento**: puede reportar
  la caldera rota y terminar la limpieza a continuación.
- Solo empieza a bloquear si el job de clasificación la sube a `CRITICAL` — o si ya había una
  `CRITICAL` sin resolver en esa vivienda por cualquier otra vía.
- Cuando bloquea, el `409` dice la causa y nada más: «una incidencia CRITICAL sin resolver». No
  lleva el identificador, ni el título, ni la descripción, porque el rol `CLEANER` no puede leer
  incidencias y ese cuerpo sería justo esa lectura.
- El acotamiento es **la vivienda, no la tarea**. Una `CRITICAL` abierta por un huésped, o durante
  otra limpieza del mismo piso, bloquea igual. Estrecharlo a la tarea sería relajar la regla, no
  afinarla, y es un cambio con su propia entrada de roadmap.

Los otros dos límites que esta página llegó a listar ya están cerrados: el escalado por SLA,
arriba, y **las fotos requeridas al cerrar**, en §«Las fotos de la limpieza».

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
redibujado: recortarlo a lo construido borraría el destino que `access-notifications` va a
levantar. Lo que sí conviene saber al leerlo es qué partes no existen aún, para no buscarlas en
el código:

| En el diagrama | Hoy |
|---|---|
| `NotificationAdapter` → «WhatsApp / email (mock)» | Este módulo solo **escribe** la fila de `notification_logs`, en `PENDING`. El envío lo hace `dispatch_notifications` (change `access-notifications`), que es lo que la marca `SENT`. |
| «subir fotos requeridas» | **Ya existe** (`cleaning-photos-storage`): subida, listado, URL firmada y la tercera cláusula del cierre. El adaptador se llama `FileStoragePort` y vive en `app/integrations/`, no `StorageAdapter`. |
| `AIAdapter.validate_cleaning_photo()` | No existe. La foto se guarda y se sirve, pero nada la valida; `ai_validation_result` no se escribe ni se devuelve. Es de `messaging-ai`. |
| `PropertyStateMachine` «crear CleaningTask» | La crea `ProvisionCleaningTaskUseCase`, invocado **dentro** de la transacción del caso de uso que mueve el estado (design D1). La máquina sigue decidiendo la transición y nada más — crear entidades no es su trabajo. |

## Operar las limpiezas desde `/cleaning`

Hasta el change `cleaning-manager-view` el backend de limpieza estaba entero y no había ninguna
pantalla desde la que usarlo: la única forma de asignar una limpiadora era una llamada HTTP a
mano, y el segundo paso del flujo de PRD §11 —cuando la asignación automática no encuentra
limpiadora activa y la tarea «queda pendiente»— se rompía porque nadie tenía dónde recogerla.
`/cleaning` es esa pantalla.

Lo que **no** es: no valida limpiezas terminadas, no abre el detalle de una tarea (checklist,
fotos), no crea tareas a mano y no edita plantillas. Todo eso sigue donde estaba —§«El ciclo»,
§«Las fotos» y la app de la limpiadora— y las razones de dejarlo fuera están en el proposal del
change.

### Qué ve cada rol, y por qué

| | Owner (`TENANT_OWNER`) | Manager (`PROPERTY_MANAGER`) |
|---|---|---|
| La lista, con filtros y paginación | sí | sí |
| El nombre de la limpiadora asignada | sí | sí |
| El control para asignar o reasignar | **no** | sí |

La propietaria no ve el control porque **no tiene `MANAGE_CLEANING_TASKS`** — es la misma fila
«Crear, asignar y validar» de §«Quién puede hacer qué», ahora visible en la UI. Las dos ven la
misma lista porque las dos tienen `READ_CLEANING_TASKS`.

Y conviene ser preciso sobre qué garantiza eso: **el frontend oculta, el backend decide.** El
mapa rol→permiso del cliente (`frontend/lib/auth/permissions.ts`) es una pista de UX declarada
como parcial, no una autoridad. Si alguna vez mostrase el control a quien no debe, la petición
responde `403` y la pantalla lo cuenta como el fallo que es — nunca como un éxito. Por eso una
asignación rechazada no se pinta jamás: la fila sigue diciendo lo que el servidor tiene por
bueno.

### Filtrar y paginar

Se filtra **por vivienda y por estado**, y los dos filtros viajan en la petición
(`property_id`, `status`) — no se recorta una página ya descargada, así que el resultado es el
que el backend calcula con su propio `AND`. Cada filtro tiene su acción explícita de quitarlo, y
cambiar cualquiera de los dos **vuelve a la página 1**, para que no aparezca una página vacía por
un desplazamiento heredado del filtro anterior.

La lista abre **sin filtrar**, en el orden del backend (`created_at` descendente, `id` de
desempate) y en la página 1. Se descartó abrir pre-filtrada a `CREATED` + `ASSIGNED`: esconde
tareas por omisión y hace que un vacío parezca un resultado que nadie pidió.

Al asignar, la lista se **recarga**; no se parchea en memoria. Es lo que hace que una tarea que
sale del filtro activo al asignarse —`CREATED` → `ASSIGNED` con el filtro puesto en `CREATED`—
desaparezca de la página como debe, y que `total` y «página X de Y» sigan siendo ciertos. La
respuesta del `PATCH` es una tarea suelta y no sabe nada de la página en la que estaba.

### «Identidad no disponible», y por qué no es un error

`CleaningTaskResponse` trae `property_id` y `assigned_cleaner_id` como UUID desnudos, así que los
nombres se resuelven en el cliente contra `GET /properties` y `GET /users?role=CLEANER`. La celda
distingue **tres** situaciones, no dos:

- **«Sin asignar»** — la tarea no tiene limpiadora. Es un dato, no un fallo.
- un marcador neutro — el catálogo todavía está en vuelo. No dice ninguna identidad porque
  todavía no la sabe.
- **«Identidad no disponible»** — el catálogo llegó (o falló) y ese id no está en él.

La tercera es la que sorprende, así que merece decirse: **el resto de la fila se pinta igual**, y
la caída del catálogo **no** convierte la vista en una pantalla de error. Estado y fechas son lo
que importa para decidir, y ya están ahí. Un UUID no se pinta nunca.

Se pide el catálogo de limpiadoras **sin filtrar por estado** a propósito. Una tarea antigua puede
estar asignada a alguien ya desactivada: con el catálogo filtrado su nombre lo tendríamos y no lo
encontraríamos, y convertiríamos un dato disponible en «identidad no disponible», que existe para
lo contrario. Como candidata a una asignación nueva, en cambio, no se ofrece.

### El límite de 100, que hay que rehacer antes de vender esto

Los dos catálogos se piden en **una sola página de `per_page=100`**, que es el techo del backend
en los tres listados. Consecuencia, marcada `ASSUMPTION` en el código: **un tenant con más de 100
viviendas o más de 100 limpiadoras verá «identidad no disponible» a partir de la centésima.**

No es un fallo silencioso —degrada exactamente por donde está especificado que degrade— pero deja
de ser correcto como cobertura, y con dos viviendas y un puñado de limpiadoras no se nota. Hay que
rehacerlo antes de la fase SaaS.

### Asignar: hay que confirmar, y eso es deliberado

El control es un desplegable de candidatas —solo limpiadoras **activas**— más un **botón de
confirmación**. El botón no es adorno: en un desplegable navegado con las flechas el evento de
cambio se dispara en cada opción por la que pasas, así que sin confirmación explícita se
reasignarían tareas a quien solo estaba mirando la lista.

Si la persona elegida ha dejado de ser una limpiadora activa del tenant entre que se cargó el
catálogo y se confirma, el backend responde `422` y la pantalla lo dice con esas palabras — «esa
persona ya no está» — en lugar de un «ha fallado» genérico. Las demás respuestas tienen su propio
mensaje: `403` sin permiso, `404` si la tarea ya no existe, y **dos `409` distintos** que la
sección siguiente explica. El texto lo elige el **estado HTTP y, dentro del `409`, el código del
sobre** — nunca el mensaje del backend, que es técnico y está en inglés.

Cada resultado —éxito o fallo— se anuncia en una **región viva**, de modo que un lector de
pantalla lo perciba sin depender del color.

### La primera asignación exige la vivienda pendiente de limpieza

**Asignar una tarea `CREATED` mueve la vivienda a `CLEANING_SCHEDULED`, y esa transición solo es
legal desde `AWAITING_CLEANING`.** Es la única fila que la matriz de `PropertyStateMachine` admite
para el disparador `CLEANER_ASSIGNED`, así que sobre una vivienda en cualquier otro estado la
primera asignación se rechaza. Reapuntar una tarea que ya está `ASSIGNED` no mueve la vivienda y
por tanto no depende de su estado.

Eso convierte el `409` en dos cosas distintas, y el API las distingue por código:

| Quién se niega | Código | Qué se enseña |
|---|---|---|
| El ciclo de vida de la tarea (ya está `ACCEPTED`, `IN_PROGRESS`…) | `CONFLICT` | «Esa tarea ya no admite un cambio de asignación» |
| El estado operacional de la vivienda | `PROPERTY_STATE_CONFLICT` | «La vivienda todavía no está pendiente de limpieza» |

Antes los dos compartían código y la pantalla culpaba a la tarea de una precondición de la
vivienda — que es el fallo que se midió operando `dev` el 2026-08-22 y el motivo del change
`cleaning-assign-preconditions`. El código nuevo lo produce **toda** operación de limpieza que la
máquina de estados bloquee, no solo la asignación: el cierre de una limpieza con el siguiente
huésped ya dentro responde el mismo `PROPERTY_STATE_CONFLICT`.

**La pantalla lo dice por adelantado, y no es la autoridad.** Cada fila del listado trae
`assignment_blocked_by`: `TASK_STATUS` si se niega la tarea, `PROPERTY_STATE` si se niega la
vivienda, o nulo si nada conocido lo bloquea. Cuando no es nulo, el botón de confirmar queda
deshabilitado y debajo aparece el motivo; el desplegable **sigue operable**, porque deshabilitar
un elemento con el foco lo manda al `<body>` y dejaría tirado a quien navega con teclado. Elegir
es inofensivo, solo enviar tiene que esperar.

Que sea una cortesía y no un permiso importa: el indicador se calcula al leer la página, así que
puede quedarse viejo antes de que nadie pulse. Si la vivienda se mueve entre la carga y el clic,
el backend rechaza igual y **ese** rechazo es el que manda — con el mensaje correcto, que es la
mitad del arreglo que de verdad protege al operador. Un nulo obsoleto ofrece un botón que acabará
en `409`; un no-nulo obsoleto esconde un botón que habría funcionado hasta el siguiente refresco.
Nulo también es lo que se envía cuando la lectura de la página no resolvió el estado de esa
vivienda: **falla abierto** a propósito, ofrece la acción y deja decidir al servidor.

## Entradas de roadmap relacionadas

- `cleaning-photos-storage` — **ya entregada**: fotos, almacenamiento (`LOCAL`/`S3`), URL
  firmadas y la tercera cláusula de la regla de validación. Lo que aportó se cuenta arriba, en
  §«Las fotos de la limpieza».
- `access-notifications` — **entregado**: trajo el emisor que marca `SENT` y el cierre del plazo al responder.
- `maintenance` — creación de incidencias, incluida la que bloquea el cierre.
- `cleaner-task-context` — **ya entregada**: la proyección de arriba, §«El contexto de la
  tarea». Es lo que hace implementable la pantalla de la limpiadora sin ampliarle permisos.
- `cleaner-app` — la app mobile-first de la limpiadora que consume todo esto.
- `cleaning-manager-view` — **ya entregada**: la pantalla del manager descrita arriba,
  §«Operar las limpiezas desde `/cleaning`». Cero cambios de backend; consume los cuatro
  endpoints que ya existían.
