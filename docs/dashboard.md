# Dashboard (frontend)

Cómo se usa y se opera el dashboard del propietario/manager. El *qué hace*
(requisitos EARS) vive en [`sdd/specs/dashboard-web-frontend.md`](../sdd/specs/dashboard-web-frontend.md);
aquí va el *cómo se trabaja con ello*.

> **Estado: solo lectura sobre datos mock.** El dashboard ya está construido, pero
> el backend agregado que lo alimentará (`GET /api/v1/properties/{id}/dashboard`,
> roadmap `dashboard-web`) todavía no existe. Hoy consume datos fijos de las dos
> viviendas de desarrollo (REDES11, PAJARITOS8). No hay acciones de escritura.

## Rutas

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

## Deuda / cuando llegue el backend

- **Sustituir el mock por HTTP**: la UI consume una interfaz `DashboardDataSource`
  con un único punto de composición (`frontend/features/dashboard/data/index.ts`).
  Cuando exista `dashboard-web`, se cambia ahí la implementación mock por una HTTP
  contra los endpoints §23 — sin tocar la UI ni los hooks.
- **`tenantId` real**: hoy se usa un `DEV_TENANT_ID` centralizado; se sustituirá
  por el contexto de sesión de `auth-tenancy`.
- **Tiempo real**: la cronología es sobre datos fijos; el streaming llega con el
  backend.
