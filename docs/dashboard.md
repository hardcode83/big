# Dashboard

Cómo se usa y se opera el dashboard del propietario/manager, **API y pantalla**. El
*qué hace* vive en las specs —
[`sdd/specs/dashboard-api.md`](../sdd/specs/dashboard-api.md) para los endpoints y
[`sdd/specs/dashboard-web-frontend.md`](../sdd/specs/dashboard-web-frontend.md) para
las pantallas —; aquí va el *cómo se trabaja con ello*.

> **Estado: la pantalla consume la API agregada mediante `HttpDashboardSource`.** El
> change `dashboard-api` entregó los cuatro endpoints de lectura (abajo) y el runtime
> del dashboard los utiliza desde el único punto de composición,
> `frontend/features/dashboard/data/index.ts`. `MockDashboardSource` y sus fixtures
> quedan únicamente como soporte de tests. No hay acciones de escritura por ninguna
> de las dos vías: los cuatro endpoints son de lectura pura.

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
- **Bloques que hoy llegan vacíos, y por qué**: el financiero espera a `revenue`;
  `last_cleaning_photos` espera a `cleaning-photos-storage`, porque una foto se sirve
  por URL firmada y no exponiendo su `storage_key`. Los dos consultan su tabla real,
  así que el contrato no cambiará cuando esos changes aterricen — solo los datos.
  `open_incidents` y `pending_approvals` estaban en esta lista y ya no: `maintenance`
  les dio escritor, así que traen datos reales sin que su contrato haya cambiado —
  que era exactamente lo que esta nota predecía.
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
- **`/timeline`** — la cronología como pantalla propia: un selector elige la
  vivienda y debajo se monta **el mismo** componente de cronología que el detalle.
  Hasta que elijas una vivienda no se pide nada al servidor, y no hay
  autoselección: con varias viviendas cualquier elección automática sería
  arbitraria. La elección vive **solo en memoria** y se descarta si cambia el
  tenant. **No hay cronología global** de todas las viviendas a la vez: el backend
  sirve una por petición.

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
activo. Se puede filtrar por **tipo de evento**, **actor**, **severidad** y
**rango de fechas**, y se recorre por páginas de 20.

- El desplegable de tipos ofrece siempre **los 47 tipos** del contrato, traducidos
  — no solo los que trajo la página que estás viendo. Que un tipo no devuelva nada
  es una respuesta correcta: 18 de los 47 todavía no tienen quien los escriba.
- El **rango de fechas** es inclusivo en los dos extremos y se manda con zona
  horaria (el día local que elegiste, de su principio a su final). Si pones un
  «hasta» anterior al «desde», sale un error junto al campo y **no se pide nada**.
- La **barra de páginas** solo aparece si hay más de una página. Cambiar cualquier
  filtro vuelve a la página 1; un rango inverso, que no llega a aplicarse, no la
  mueve.
- Cambiar de propiedad reinicia los filtros y la página.

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
- `http://localhost:3000/timeline` — la cronología como pantalla: elige vivienda en
  el selector.

## Deuda pendiente

- **Tiempo real**: la API entrega lectura con filtros y paginación. Empujar cambios
  al cliente (WebSocket/SSE) no lo cubre `dashboard-api` y no tiene todavía entrada
  propia.
- **Cronología global**: `GET /api/v1/timeline` (PRD §23) no existe, así que
  `/timeline` pide vivienda. Servir varias a la vez sería trabajo de backend y no
  tiene entrada.
- **Barra de páginas repetida**: la cronología, el portfolio y las reservas tienen
  cada uno su propia navegación de páginas. Unificarlas tocaría features ya
  archivadas y ninguna entrada lo ha decidido.
- **Hora de entrada y salida**: `check_in`/`check_out` viajan como fecha, no como
  instante — combinar la fecha con la hora exige resolver la zona horaria de la
  vivienda, y equivocarse ahí son horas de diferencia en la pantalla de un operador.
