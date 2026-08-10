# Dashboard

Cómo se usa y se opera el dashboard del propietario/manager, **API y pantalla**. El
*qué hace* vive en las specs —
[`sdd/specs/dashboard-api.md`](../sdd/specs/dashboard-api.md) para los endpoints y
[`sdd/specs/dashboard-web-frontend.md`](../sdd/specs/dashboard-web-frontend.md) para
las pantallas —; aquí va el *cómo se trabaja con ello*.

> **Estado: la API agregada existe; la pantalla todavía consume el mock.** El change
> `dashboard-api` entregó los cuatro endpoints de lectura (abajo). La UI sigue
> leyendo datos fijos de REDES11 y PAJARITOS8 hasta que `dashboard-web` cambie
> `MockDashboardSource` por la implementación HTTP — un solo punto de composición,
> `frontend/features/dashboard/data/index.ts`. No hay acciones de escritura por
> ninguna de las dos vías: los cuatro endpoints son de lectura pura.

## La API (`dashboard-api`)

Cuatro rutas, todas autenticadas con `require(Permission.READ_PROPERTIES)`, todas
tenant-scoped y todas de solo lectura:

| Ruta | Qué devuelve |
|---|---|
| `GET /api/v1/dashboard/properties` | una card por vivienda del tenant, en el envelope de paginación de PRD §23 |
| `GET /api/v1/properties/{id}/dashboard` | el agregado de PRD §9.2 para una vivienda |
| `GET /api/v1/properties/{id}/state` | estado operacional canónico + instante de la última transición |
| `GET /api/v1/timeline/{property_id}` | la cronología de la vivienda, filtrable y paginada (PRD §10) |

Lo que conviene saber al operarlas:

- **La colección no hace N+1.** Resuelve la página entera con un número fijo de
  consultas, sea cual sea el tamaño de la cartera; hay un test que cuenta sentencias
  y compara 2 propiedades contra 10.
- **El idioma sale del usuario, no de `Accept-Language`.** `title`,
  `cleaning_status`, `next_action.label` y las etiquetas de incidencia y aprobación
  llegan ya compuestos en el `preferred_language` de quien llama (`es`/`en`, con
  degradación a `es` ante cualquier otro valor). Los literales canónicos
  (`operational_state`, `event_type`, `actor_type`, `severity`) **no se traducen**.
- **`description` es la excepción: llega sin traducir, y a propósito.** Lo que hay en
  ese campo lo escribió una persona —el motivo que `PropertyStateMachine` exige para
  bloquear una vivienda o ponerla fuera de servicio—, así que no se compone desde el
  catálogo ni se traduce: se entrega tal cual se guardó. Una misma entrada puede, por
  tanto, traer el `title` en tu idioma y la `description` en el de quien la escribió.
- **Un `404` no distingue** entre una vivienda que no existe y una de otro tenant.
- **Agregar no concede.** Un rol sin el permiso que protege el origen de un bloque
  recibe ese bloque a `null`, no su contenido: reserva y huésped con
  `READ_RESERVATIONS`, limpieza con `READ_CLEANING_TASKS`, acceso con
  `READ_ACCESS_RECORDS`.
- **Bloques que hoy llegan vacíos, y por qué**: `open_incidents` y
  `pending_approvals` esperan al change `maintenance`; el financiero, a `revenue`;
  `last_cleaning_photos` espera a `cleaning-photos-storage`, porque una foto se sirve
  por URL firmada y no exponiendo su `storage_key`. Los tres consultan su tabla real,
  así que el contrato no cambiará cuando esos changes aterricen — solo los datos.
- **`notes` llega siempre `null`**, a propósito: ninguna columna lo posee, y las
  candidatas (`access_notes`, `cleaning_notes`, `emergency_notes`) son texto libre
  donde un operador puede haber pegado un código de puerta.
- **Los importes viajan como cadena decimal**, no como número: un `float` pierde
  céntimos.

## Rutas de la pantalla

- **`/dashboard`** — property cards (PRD §9.1): una tarjeta por vivienda con su
  estado operacional y color, reserva actual/próxima, huésped, check-in/out,
  estado de limpieza, incidencias abiertas, próxima acción + responsable y último
  evento. "Ver detalle" lleva a la propiedad.
- **`/properties/[id]`** — detalle (PRD §9.2): reserva, huésped, acceso, limpieza,
  incidencias, financiero, notas, aprobaciones pendientes, fotos de la última
  limpieza, y la **cronología** de la propiedad.

## Lectura rápida de las tarjetas

En `/dashboard`, la tarjeta prioriza la lectura en este orden: estado
operacional, incidencias abiertas, próxima acción, reserva y huésped, limpieza y
último evento. En desktop, tablet y móvil las tarjetas conservan esa jerarquía,
alinean cabecera, regiones principales y enlace «Ver detalle», y envuelven los
textos largos sin desplazamiento horizontal. El enlace mantiene navegación por
teclado, foco visible y nombre localizado en ES/EN.

## Colores de estado (PRD §9.1)

| Color | Estados operacionales |
|-------|-----------------------|
| 🟢 verde | `VACANT_READY`, `READY_FOR_NEXT_GUEST`, `AWAITING_CHECKIN` |
| 🔵 azul | `OCCUPIED_ESTIMATED`, `CLEANING_IN_PROGRESS` |
| 🟡 ámbar | `AWAITING_CLEANING`, `CLEANING_SCHEDULED`, `MAINTENANCE_REQUIRED` |
| 🔴 rojo | `CRITICAL_INCIDENT` |
| ⚫ gris | `BLOCKED_BY_OWNER`, `OUT_OF_SERVICE` |

## Cronología

La cronología de una propiedad se muestra en orden inmutable y en el idioma
activo. Se puede filtrar por **tipo de evento**, **actor** y **severidad**; las
opciones de tipo se derivan de los eventos que tiene esa propiedad. Cambiar de
propiedad reinicia los filtros.

## Idiomas

Todo el texto de interfaz está en ES/EN (namespace `dashboard` en
`frontend/locales/{es,en}/dashboard.json`). El conmutador de idioma del topbar
cambia el idioma en caliente.

## Probarlo en local

```bash
make up SERVICE=frontend   # o: cd frontend && npm run dev
```

- `http://localhost:3000/dashboard` — las dos tarjetas.
- `http://localhost:3000/properties/redes11` — detalle + cronología.
- `http://localhost:3000/properties/<id-inexistente>` — estado "no encontrado".

## Deuda / lo que falta por conectar

- **Sustituir el mock por HTTP**: la UI consume una interfaz `DashboardDataSource`
  con un único punto de composición (`frontend/features/dashboard/data/index.ts`).
  Los endpoints contra los que hacerlo **ya existen** (arriba); es `dashboard-web`
  quien cambia ahí la implementación mock por una HTTP — sin tocar la UI ni los hooks.
- **`tenantId` real**: hoy se usa un `DEV_TENANT_ID` centralizado; se sustituirá
  por el contexto de sesión de `auth-tenancy`. La API no lo necesita: el tenant sale
  del token y ningún endpoint lo acepta como parámetro.
- **Tiempo real**: la API entrega lectura con filtros y paginación. Empujar cambios
  al cliente (WebSocket/SSE) no lo cubre `dashboard-api` y no tiene todavía entrada
  propia.
- **Hora de entrada y salida**: `check_in`/`check_out` viajan como fecha, no como
  instante — combinar la fecha con la hora exige resolver la zona horaria de la
  vivienda, y equivocarse ahí son horas de diferencia en la pantalla de un operador.
