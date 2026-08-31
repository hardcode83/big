# Limpiadora — cómo se opera la app `/cleaner`

Capability del change `cleaner-app` (PRD §11, §26.19). Esta página cuenta **cómo se usa y se
opera** desde la pantalla de la limpiadora; el *qué hace* está en
`sdd/specs/cleaner-task-context.md`, `sdd/specs/cleaner-incident-report.md`,
`sdd/specs/cleaner-photo-requirements.md` y `sdd/specs/cleaning.md` con sus criterios EARS, y el
contrato HTTP en `backend/openapi.json`. La cara del manager (asignar, reasignar, validar) vive
en [`docs/cleaning.md`](cleaning.md) §«Operar las limpiezas desde `/cleaning`» y no se duplica
aquí.

## El ciclo, visto desde `/cleaner`

```
notificación CLEANING_TASK_ASSIGNED           (cuando el manager asigna)
        │
        ▼
/cleaner: lista "Mis tareas"
        │   filtrar por estado (7 chips: ASSIGNED, ACCEPTED, IN_PROGRESS,
        │                       PENDING_REVIEW, COMPLETED, REJECTED, CANCELLED)
        │   clicar una fila → /cleaner/tasks/[id]
        ▼
/cleaner/tasks/[id]:
        │   piso + dirección + ventana (de /context)
        │   checklist ítem a ítem (de /checklist)
        │   categorías de foto pedidas (de /photo-requirements)
        │   galería de fotos ya subidas (de /photos)
        │
        ├── estado ASSIGNED ──► Aceptar / Rechazar
        │                          Aceptar → POST /accept    → ACCEPTED
        │                          Rechazar → POST /reject  → REJECTED + vuelve a /cleaner
        │
        ├── estado ACCEPTED ──► Iniciar
        │                          Iniciar → POST /start    → IN_PROGRESS
        │
        ├── estado IN_PROGRESS ──► Cerrar limpieza
        │   │   Reportar incidencia (botón siempre visible en IN_PROGRESS)
        │   │   Marcar ítem del checklist (uno a uno, idempotente)
        │   │   Subir foto por categoría (una por categoría, multipart)
        │   │
        │   └── Cerrar → POST /complete
        │         ├── 200 → PENDING_REVIEW + panel reversible "Volver a mis tareas"
        │         └── 409 (3 cláusulas):
        │                 ├── faltan ítems `required`     → marcar cuáles
        │                 ├── faltan fotos `required`     → marcar cuáles
        │                 └── hay incidencia CRITICAL    → mensaje SIN identificador
        │
        ├── estado PENDING_REVIEW ──► ninguna acción ("a la espera de validación")
        ├── estado COMPLETED       ──► ninguna acción ("cerrada")
        ├── estado REJECTED        ──► ninguna acción ("rechazada")
        └── estado CANCELLED       ──► ninguna acción ("cancelada")
```

## Quién puede hacer qué

| | Owner | Manager | Limpiadora |
|---|---|---|---|
| Ver `CleaningTask` + las cinco proyecciones | todas | todas | **solo las suyas** |
| Aceptar / rechazar / iniciar / cerrar | no | no | sí |
| Marcar ítems del checklist | no | no | sí |
| Subir fotos por categoría | no | no | sí |
| Reportar incidencia desde la tarea | no | no | sí |
| Crear, asignar, reasignar, validar | no | sí | no |

El espejo de permisos del cliente (`frontend/lib/auth/permissions.ts`) lleva `CLEANER: []` a
propósito — la autorización la decide el backend, y el espejo solo recoge entradas que afectan a
UX (botones que se ocultan). En la pantalla de la limpiadora **no** se oculta nada por permiso:
la pantalla entera se ofrece al rol y el `AuthGuard allow={["CLEANER"]}` del layout es el único
escudo de UX. R8.5 lo deja por escrito.

Para una limpiadora, una tarea que no es suya responde **`404`**, no `403`, y con el mismo cuerpo
que un id inexistente — un `403` convertiría la ruta en una sonda para averiguar qué tareas
existen. Por eso los `404` se tratan como «tarea no disponible» sin distinguir.

## Las dos pantallas

### `/cleaner` — la lista «Mis tareas»

Pide `GET /api/v1/cleaning-tasks` **sin parámetros de identificación**: el acotamiento por fila
lo deriva el backend del token (`CleaningActor.restrict_to_cleaner_id`), y no existe parámetro de
consulta para él. La paginación respeta los parámetros `page` y `per_page` que el contrato
publica.

Cada fila muestra:

- **`property_name`** y **`property_internal_code`** resueltos en cliente desde
  `GET /api/v1/cleaning-tasks/{id}/context`. La limpiadora no tiene `READ_PROPERTIES`, así que
  **esta es la única vía** para mostrar el nombre del piso: la pantalla no llama a
  `/api/v1/properties/…` ni construye URLs de almacenamiento (R2.7).
- **`checkout_at`** y **`next_checkin_deadline`** del mismo `/context`, formateados en el
  `timezone` de la propiedad que también devuelve la ruta. **No** son el plan (`scheduled_start`
  / `scheduled_end`); son la respuesta de ahora contra las reservas que haya. La diferencia y
  las tres clases de `null` están en [`docs/cleaning.md`](cleaning.md) §«Los dos instantes».
- **estado** de la tarea con la paleta compartida de
  `frontend/features/cleaning/lib/task-status.ts` — un solo mapa de colores en todo el árbol.
- **em-dash `—`** cuando el contexto falla para una fila: el resto de la página sigue
  renderizándose, porque el fallo del contexto de una fila no es el fallo del listado.

Los chips de estado son **siete** (los visibles para una limpiadora sobre sus filas), no nueve:
`ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`, `PENDING_REVIEW`, `COMPLETED`, `REJECTED`, `CANCELLED`.
`CREATED` no se ofrece porque su filtro devolvería siempre vacío para `CLEANER` —no hay tareas
`CREATED` asignadas—. `FAILED` se pinta en la fila si llega (lo escribe el manager al validar
con `POST /validate`), pero **no** se ofrece como filtro: no es un estado sobre el que la
limpiadora tenga acción. `statusColorGroup` pinta los nueve por construcción sobre la unión
generada, así que añadir un décimo estado en el backend rompe la compilación en vez de dejar un
color fantasma.

El chip activo pulsado otra vez vuelve al estado sin filtro. Sin filtro, la lista se pide en el
orden que sirve el backend (`created_at` descendente) **y no** se reordena en cliente.

### `/cleaner/tasks/[id]` — el detalle

Monta en paralelo `GET /api/v1/cleaning-tasks/{id}` y las cuatro proyecciones hermanas —
`/context`, `/checklist`, `/photo-requirements`, `/photos`— bajo claves tenant-scoped distintas.
Abrir el detalle **no** vuelve a pedir el contexto de la fila: la clave de la lista y la del
detalle son la misma, así que TanStack deduplica.

#### Piso y contexto (R2.2)

De `/cleaning-tasks/{id}`: `id`, `status`, `property_id`, `reservation_id`, `scheduled_start`,
`scheduled_end`, `accepted_at`, `started_at`, `completed_at`, `validation_status`. De
`/context`: `property_name`, `property_internal_code`, los seis campos de dirección postal
(`address_line1`, `address_line2`, `city`, `province`, `postal_code`, `country`), `timezone`, y
los dos instantes (`checkout_at`, `next_checkin_deadline`) con su `description` documentada del
contrato. Nulos escalares se pintan como em-dash `—` (U+2014), nunca concatenados con su unidad
y nunca `?? ""` — la convención de `sdd/specs/frontend-foundation.md`.

#### Checklist (R4)

Items servidos por `/checklist` en el orden de la plantilla, cada uno con su `item_id`,
`label`, `required` y estado (`pending` vs `completed_at` + `completed_by`). Marcar un ítem es
`POST /api/v1/cleaning-tasks/{id}/checklist/{item_id}/complete` sin cuerpo, idempotente
(`INSERT … ON CONFLICT DO UPDATE` en backend). Solo se ofrece el control cuando la tarea está
`IN_PROGRESS`. Doble clic: el segundo `POST` resuelve al mismo estado sin error y el cliente no
muestra error.

- `404` (el `item_id` ya no pertenece a la plantilla —caso de una plantilla editada mientras se
  ejecuta—): refresca el checklist para que el ítem desaparecido deje de aparecer, sin reintento.
- `409` (la tarea no está `IN_PROGRESS`): muestra el mensaje localizado vía `mapCleanerError` y
  refresca la tarea para que la UI pinte el estado real; sin reintento automático.

#### Categorías de foto (R5.1)

Entradas servidas por `/photo-requirements` en el orden declarado en la plantilla, cada una con
`photo_type`, `label`, `required` y `uploaded`. Una categoría con `uploaded: true` se pinta como
«cubierta» y **no** ofrece el botón de subida. Una con `required: true` y `uploaded: false` se
pinta como pendiente y sí lo ofrece.

Subir una foto es la **primera ruta `multipart`** que esta feature usa, y la soporta el
`formData?: FormData` que el transporte compartido ya admitía desde `tech-app` D2: sin cabecera
`Content-Type: application/json`, sin `JSON.stringify` sobre el cuerpo, con cabecera de sesión,
reintento único ante `401` reenviando el mismo `FormData`, y `parseApiError` aplicado al cuerpo
no-OK.

```bash
curl -X POST .../api/v1/cleaning-tasks/<task_id>/photos \
  -H 'Authorization: Bearer <token de la limpiadora>' \
  -F photo_type=kitchen \
  -F file=@cocina.jpg
```

Lo que conviene saber al operarla:

- **El `photo_type` viene de la entrada que la usuaria tocó**, no de un campo libre. Un
  `photo_type` que la plantilla no declara responde `404`. Las dos rutas leen la misma plantilla,
  así que no hace falta adivinar identificadores.
- El formato lo deciden los **bytes**, nunca el `Content-Type` declarado: JPEG, PNG y WebP. HEIC
  / HEIF queda fuera (Chrome y Firefox no lo pintan) y eso es lo que más se va a notar
  operando: una limpiadora con un iPhone tiene que tener el móvil en «Más compatible» o la
  subida le rebotará con un `422` cuyo mensaje nombra los formatos admitidos. La acción que
  resuelve el `422` es **cambiar el formato**, no reintentar —por eso cada código tiene su
  mensaje y ninguno se reintenta automáticamente.
- **Una foto por llamada**: varias del mismo `photo_type` están permitidas; la que falta es la
  que no tiene ninguna, no la que tiene dos.
- `413` («demasiado grande»), `502` («almacenamiento no disponible»): ningún reintento.

#### Galería de fotos (R2.5)

`GET /api/v1/cleaning-tasks/{id}/photos` devuelve las fotos de la tarea, de la más antigua a la
más reciente, **cada una con su URL ya firmada**. La pantalla pinta esa URL **verbatim** en un
`<img src>` — sin `next/image`, sin reescribir, sin reconstruir. La firma es la credencial: un
HMAC sobre la clave interna del objeto y sobre `exp`, así que no se traslada a otra foto, a otro
tenant ni a un plazo posterior. Vive 3600 s.

Si una firma caduca mientras la pantalla está abierta, el `onError` de la imagen invalida
`cleanerKeys.photos(t, id)` **como mucho una vez por id de foto montado** (un `useRef<Set<string>>`
guarda los ya reintentados). Una foto que falle por otro motivo se ve rota tras ese único
reintento, que es preferible a un bucle de listados.

#### Reportar una incidencia (R6)

Botón «Reportar incidencia» siempre visible en `IN_PROGRESS` y también en `ASSIGNED` y `ACCEPTED`
(los tres estados de `INCIDENT_REPORTABLE_STATUSES`). En estados terminales y en `PENDING_REVIEW`
no se pinta. Al pulsarlo se abre un panel colapsable bajo la barra de acciones con exactamente
dos campos nativos — `<input maxLength={300}>` para `title`, `<textarea maxLength={5000}>` para
`description`— y validación local que revalida el backend: `title` entre 1 y
`MAX_INCIDENT_TITLE` (300) sin caracteres de control, `description` entre 1 y
`MAX_INCIDENT_DESCRIPTION` (5000) con tabulador y saltos admitidos.

`POST /api/v1/cleaning-tasks/{id}/incidents` con cuerpo `{title, description}` (`extra="forbid"`
cierra cualquier otro campo). El `201` devuelve un acuse de tres campos (`id`, `status`,
`created_at`); el panel se cierra y **no** vuelve a pintar `title` ni `description`. La pantalla
no lista, lee, clasifica ni resuelve incidencias: las quince rutas de `/api/v1/incidents`
siguen cerradas al rol, y este botón es el único camino que produce una fila de incidencia
desde la limpiadora.

- `409` (la tarea pasó a estado terminal entre el GET y el POST): mensaje localizado vía
  `mapCleanerError` y refresca la tarea; sin reintento.

#### Cerrar la limpieza (R7)

Botón «Cerrar limpieza» solo en `IN_PROGRESS`. `POST /complete` sin cuerpo. El `200` cierra la
tarea (`PENDING_REVIEW`), refresca la lista y la tarea, y muestra un **panel reversible de
salida** —«Cerrada — Volver a mis tareas»— que ejecuta `router.replace("/cleaner")` al pulsarlo.
Es la acción reversible de R7.2: el equivalente del toast que la app del técnico pinta para su
cierre, pero como botón y no como notificación efímera, porque la pantalla se opera con la mano
que sostiene el móvil.

El `409` del cierre es el caso interesante, porque **el backend aplica las tres cláusulas de
PRD §11** (ítems `required` → fotos `required` → incidencias `CRITICAL` abiertas) y la pantalla
las pinta, sin reinventar el vocabulario:

| `409` por | Lo que la pantalla hace |
|---|---|
| Faltan ítems `required` del checklist | Resalta los ítems con `pending: true` y `required: true`. El `409` del backend enumera los `item_id` en orden estable, así que no se reinventa la lista. |
| Faltan fotos `required` | Resalta las entradas de `/photo-requirements` con `uploaded: false` y `required: true`, con su `label`. |
| Hay una incidencia `CRITICAL` sin resolver en la propiedad | Mensaje localizado **sin** identificador, título ni descripción de la incidencia. `CLEANER` no tiene `READ_INCIDENTS` y un cuerpo que los incluyera sería la lectura que se le niega — [`docs/maintenance.md`](maintenance.md) §«Reportar una incidencia desde una limpieza». |

Los tres comparten `code: "CONFLICT"`; lo que los distingue es el estado refrescado que la
mutación ya invalidó. La pantalla **no** deriva su propio veredicto de `/photo-requirements`:
`uploaded` es un hecho, y la regla de validación vive **dentro de `CleaningTask.complete()` y en
ningún otro sitio** (`sdd/specs/cleaning.md` §Cierre y validación).

#### Estados compartidos y la postura mobile-first

Los estados de carga, vacío y error se montan sobre los primitivos compartidos
(`LoadingState`, `EmptyState`, `ErrorState` de `@/components/states`) con `aria-busy` en la
carga y `role="alert"` en el error; el detalle crudo del error **no** se renderiza nunca. El
`404` se trata como «tarea no disponible» con vuelta a `/cleaner`; el resto cae en `error` con
texto por código (`409` con la razón, `422` con el mensaje del backend si lo trae, `502` con
«almacenamiento no disponible`»).

Ambas pantallas viven en una sola columna (`mx-auto w-full max-w-md`), sin desplazamiento
horizontal a 360 px. La barra de acciones del detalle es el último elemento del flujo vertical y
se queda visible al hacer scroll sin `position: fixed` —la pantalla se opera con la mano que
sostiene el móvil y el panel inferior del navegador del sistema ocupa esa zona.

## Quién ve qué, y por qué

| | Owner | Manager | Limpiadora |
|---|---|---|---|
| Las tareas del tenant | todas | todas | **solo las suyas** |
| Las fotos de una tarea | todas | todas | **solo las de las suyas** |
| El contexto de una tarea (piso + ventana) | todas | todas | **solo las suyas** |

El acotamiento sale del rol persistido del token y **ningún parámetro de la petición lo
ensancha**. Las cinco rutas de `/api/v1/cleaning-tasks/...` que esta pantalla consume se sirven
sobre `READ_CLEANING_TASKS` y `EXECUTE_CLEANING_TASKS`, los únicos dos permisos del módulo que
`CLEANER` (`_SELF_SERVICE | _CLEANING_EXECUTE`) lleva.

## Lo que **no** es esta pantalla

No valida limpiezas terminadas (`POST /validate` exige `MANAGE_CLEANING_TASKS`), no abre el
detalle de una tarea desde el workspace del manager, no crea tareas a mano, no edita plantillas,
no asigna ni reasigna, y **no** cancela (`POST /cancel` exige `MANAGE_CLEANING_TASKS`). El botón
`cancel` no se pinta en ningún estado, y `R3.5` lo prohíbe por escrito.

## El formulario de reporte de incidencia y los dos retos que plantea

**El reto 1: `CLEANER` no tiene `READ_INCIDENTS`.** El reporte crea una fila; la pantalla no la
lee. Eso significa que no hay verificación local del tipo o la severidad: el `MEDIUM` inicial
lo escribirá luego el clasificador del módulo `maintenance`. La limpiadora solo ve el acuse
(`id`, `status`, `created_at`) y nada más.

**El reto 2: el `409` del cierre cuando hay `CRITICAL` es deliberadamente opaco.** El mensaje
no nombra identificador, título ni descripción de la incidencia, porque la limpiadora no podría
leerlos de ninguna forma sin un permiso que no tiene. Lo que sí sabe: que **la vivienda** tiene
una `CRITICAL` abierta, no necesariamente **la tarea**. Una `CRITICAL` reportada por el huésped
o durante otra limpieza del mismo piso bloquea igual. Estrecharlo a la tarea sería relajar la
regla, no afinarla.

## Entradas de roadmap relacionadas

- `cleaning-photos-storage` — **ya entregada**: fotos, almacenamiento (`LOCAL`/`S3`), URL
  firmadas y la tercera cláusula del cierre. Ver [`docs/cleaning.md`](cleaning.md) §«Las fotos
  de la limpieza».
- `cleaner-task-context` — **ya entregada**: la proyección que pinta el piso + ventana. Sin
  ella, la pantalla no podría darle a qué piso ir. Ver
  [`docs/cleaning.md`](docs/cleaning.md) §«El contexto de la tarea».
- `cleaner-incident-report` — **ya entregada**: la ruta que abre una incidencia desde la
  tarea. Ver [`docs/maintenance.md`](maintenance.md) §«Reportar una incidencia desde una
  limpieza».
- `cleaner-photo-requirements` — **ya entregada**: la ruta que lista las categorías pedidas.
  Ver [`docs/cleaning.md`](docs/cleaning.md) §«Las fotos de la limpieza».
- `cleaner-list-property-projection` — **pendiente `[BE]`**: la lista hoy pide
  `property_name` y `property_internal_code` por `/context`, una vez por fila. La proyección
  de estos campos en el item del listado (`cleaning-assign-preconditions` ya añadió
  `assignment_blocked_by` con la misma forma) cerraría el N+1 en el origen.
- `shared-datetime-formatter` — **pendiente**: sería la sexta copia del mismo formateador de
  fecha; la extracción a `lib/format/` se aplaza por alcance (toca cuatro features fuera del
  proposal). Anotado al archivar.
