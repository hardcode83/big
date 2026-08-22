# Design: properties-web

## Context

`frontend/app/(workspace)/properties/page.tsx` renderiza `RoutePlaceholder routeId="properties"`; el detalle hermano (`properties/[id]/page.tsx`) ya monta `PropertyDetailView` de `@/features/dashboard` y funciona. El registro de rutas está **completo para las dos**: `route-registry.ts` declara `properties` (`pattern: "/properties"`, `match: "prefix"`, `navigationGroup: "operation"`, `order: 3`) y `property-detail` (`match: "exact"`, sin `href`, con `breadcrumbKeys`), y `locales/{es,en}/navigation.json` ya trae sus cuatro claves.

El backend está entregado: `backend/app/properties/api/router.py` sirve `GET /api/v1/properties` con `page`/`per_page`/`status`/`current_operational_state`, devolviendo `PropertyPageResponse` cuyo `data` son `PropertyListItemResponse` — `PropertyResponse` **menos** las tres notas de texto libre, que `tech-incident-context` sacó del listado (excepción 6 de la regla 11, `steering/security.md`). `frontend/lib/api/generated/openapi.d.ts` ya declara la operación y los dos schemas.

Los dos precedentes a copiar son `features/reservations/` y `features/incidents/`, con la estructura `data/` + `data/http/` + `hooks/` + `lib/error-mapping.ts` + `components/list/` y su `index.ts` de fachada.

El color de estado operativo de PRD §9.1 vive hoy **dos veces y las dos privadas** dentro del panel: `features/dashboard/lib/state-color.ts` mapea estado → grupo semántico (con fallback a `gray`), y `STATE_BADGE_CLASS` en `features/dashboard/components/property-card.tsx:19-27` mapea grupo → clases Tailwind. `features/dashboard/index.ts` exporta sólo `DashboardView` y `PropertyDetailView`.

## Decisions

### D1 — Feature nueva `features/properties/`, no reutilizar `PropertyCard`

**Chosen:** una feature propia con tabla paginada. `PropertyCard` está tipada sobre `PropertyDashboardCard`, el DTO del **agregado** `GET /api/v1/dashboard/properties`; seis de sus nueve campos (`currentOrNextReservation`, `cleaningStatus`, `openIncidentsCount`, `nextAction`, `lastEventLabel`, `lastEventAt`) no existen en `PropertyListItemResponse`. Además responden preguntas distintas: `/dashboard` es «¿qué necesita mi atención?» (sin filtros, su endpoint no los acepta), `/properties` es «¿qué tengo y cómo está configurado?» (paginado y filtrable, y la única pantalla donde se ve `status`).

Rejected: reutilizar la tarjeta sintetizando nulos — pintaría «sin reserva · sin limpieza · 0 incidencias» sobre datos que no vinieron, una tarjeta que miente.
Rejected: pedir el agregado por fila para rellenar la tarjeta — N+1 sobre un listado paginado.

### D2 — El badge de estado se extrae a `frontend/components/property-state-badge.tsx`

**Chosen:** un componente transversal que se lleva **los dos** mapas (grupo semántico y clases Tailwind) y el fallback a `gray`, con firma `{ state, label }`: posee el color, recibe la etiqueta ya traducida. `PropertyCard` se refactoriza para consumirlo. Es la única forma de que la tabla de colores de **`PropertyOperationalState`** tenga una sola copia en el árbol.

**Alcance exacto de esa unicidad, para no vender más de lo que es** (verificado en la revisión del arquitecto): existe una tercera tabla con **los mismos valores Tailwind** en `frontend/features/cleaning/lib/task-status.ts:45-53`, copiada a mano desde `STATE_BADGE_CLASS` y así documentado en su propio comentario. **No entra en esta extracción y no se toca**: indexa otro enum (`CleaningTaskStatus`), y aquel change declaró a propósito que PRD §9.1 fija colores para el estado de la vivienda, no para el de la tarea. Así que lo que este change unifica es la tabla de `PropertyOperationalState`, no «los colores del árbol».

Rejected: copiar los mapas a `features/properties/` — dos tablas de colores de PRD §9.1, que es exactamente como divergen.
Rejected: exportar `stateColorGroup` desde `features/dashboard/index.ts` — una feature importando internos de otra, que es lo que ese `index.ts` existe para impedir.
Rejected: crear `components/property-state/` con su `index.ts` — inventa un directorio para un solo componente; el par `.tsx` + `.test.tsx` sueltos basta.

### D3 — El componente compartido se tipa sobre la unión generada

**Chosen:** `components["schemas"]["PropertyOperationalState"]` de `lib/api/generated/openapi.d.ts`. Hoy la unión de `features/dashboard/data/dto.ts` es estructuralmente idéntica (once valores, verificados contra `backend/app/properties/domain/enums.py`), pero tiparlo sobre ella volvería a acoplar lo que la extracción viene a desacoplar.

Rejected: tipar sobre la unión escrita a mano del panel — reintroduce la dependencia entre features por la puerta de atrás.

### D4 — Sin `Mock*Source`: HTTP directo

**Chosen:** `data/http/http-properties-source.ts` contra `lib/api`, con `data/index.ts` como punto de composición (`getPropertiesDataSource()`), igual que `reservations-web`. La indirección `Mock*Source` del panel existía porque su UI se adelantó al backend; aquí el backend lleva archivado desde el 2026-08-08.

Rejected: replicar `Mock*Source` por simetría — una capa sin el problema que la justificaba.

### D5 — DTOs en camelCase con las uniones re-exportadas del generado

**Chosen:** `data/dto.ts` traduce el payload snake_case a camelCase y **re-exporta** `PropertyStatus` y `PropertyOperationalState` del generado en vez de transcribirlas. Un `boundary` test vigila la frontera, como en el panel.

Rejected: transcribir los once valores a mano — un catálogo más que puede divergir del backend.

### D6 — Claves de query con ámbito de tenant y orden de filtros fijo

**Chosen:** `hooks/query-keys.ts` con `propertiesKeys.list(tenantId, filters)` sobre `tenantScopedKey`, de modo que toda clave empiece por `['tenant', tenantId, …]`. El objeto de filtros se construye con sus claves en **orden fijo**, para que dos renders equivalentes produzcan la misma clave y TanStack Query no invalide de más.

Rejected: clave global sin tenant — `tenantScopedKey` lanza si falta el tenant, a propósito.

### D7 — Los filtros son `useState` del componente, no un store

**Chosen:** el padre (`PropertiesView`) posee el estado de filtros y paginación y `PropertiesFilters` es controlado, calcado de `ReservationsFilters`. `steering/frontend.md` reserva Zustand para estado ligero de UI y prohíbe duplicar server state.

Rejected: un store de Zustand para los filtros — estado de una sola pantalla que no sobrevive a la navegación.

### D8 — Mapeo de errores como unión discriminada, con 401 tratado como carga

**Chosen:** `lib/error-mapping.ts` devuelve `loading | forbidden | not-found | validation | error | ok`. **401 → `loading`**, para no parpadear mientras corre la rotación de token; **404 sobre un endpoint de lista → error genérico**, porque una lista no «no existe». Sin reintentos en 4xx, vía el `retryPolicy` compartido de `@/lib/api/retry-policy`.

Rejected: 401 como error — produce un parpadeo de error en cada refresh de sesión.

### D9 — Cambiar un filtro vuelve a la página 1

**Chosen:** todo cambio de filtro resetea `page` a 1 antes de pedir. Sin ello, filtrar desde la página 3 puede pedir una página que el conjunto filtrado no tiene y devolver `data` vacío, que la pantalla no puede distinguir de «no hay propiedades así».

Rejected: conservar la página — produce un estado vacío que miente.

### D10 — Las once etiquetas de estado se leen del namespace `dashboard`

**Chosen:** el namespace nuevo `properties` cubre cabeceras, filtros, paginación, las dos etiquetas de `status`, el texto accesible del enlace y las copias de estado; las once etiquetas de estado operativo se leen con `useTranslation("dashboard")`, donde ya existen en ES y EN. Leer un namespace ajeno es legal en react-i18next y es el precio más barato.

Rejected: duplicar las once etiquetas en `properties` — dos catálogos del mismo enum es como divergen.

### D11 — Seis columnas, lista cerrada

**Chosen:** nombre (con el enlace), código interno, ciudad, capacidad, estado operativo y `status`. Todo lo demás que viaja (dirección completa, `country`, `timezone`, horas por defecto, WiFi, vínculo PMS, sellos de tiempo) son datos de ficha y no se pintan. Mismo criterio que `reservations-web` D5, que rechazó pintar sus 25 columnas porque entonces la lista deja de ser lista.

Rejected: pintar todo el payload — la lista deja de ser escaneable y encima expone el vínculo con el PMS sin motivo.

### D12 — Test de cobertura de etiquetas sobre los dos enums

**Chosen:** un `locales/properties-locale.test.ts` calcado de `features/reservations/locales/reservations-locale.test.ts`, que fija que **los once** valores de `PropertyOperationalState` y **los dos** de `PropertyStatus` resuelven a una cadena en ES y en EN. Se añade por dos razones concretas: D10 lee las once etiquetas de un namespace **ajeno** (`dashboard`), así que un cambio en aquel namespace rompe esta pantalla sin que nada lo delate; y `catalog-parity.test.ts` sólo compara que los conjuntos de claves ES/EN coincidan — no que exista una clave **por valor del enum**, así que un enum con doce valores y once etiquetas le pasa por debajo en los dos idiomas a la vez.

El precedente pesa: ese test existe en `reservations` porque una revisión anterior señaló justamente esta falta de cobertura como defecto real. `features/incidents/` no lo tiene, así que no es unánime — pero aquí la lectura de namespace ajeno lo hace más necesario que en ninguno de los dos.

Rejected: confiar en `catalog-parity.test.ts` — comprueba paridad entre idiomas, no cobertura del enum.
Rejected: no añadirlo, como `incidents` — repetiría un defecto ya diagnosticado, y con un riesgo extra que aquellos no tenían.

### D13 — R5.4 (renderizar como texto) no necesita diseño

**Chosen:** nada que diseñar. La interpolación de texto de JSX escapa por defecto y el cumplimiento consiste en **no** introducir `dangerouslySetInnerHTML`, que no aparece hoy en ninguna parte de la feature ni de sus precedentes. Queda como comprobación de aceptación a nivel de tarea, no como decisión de arquitectura. Se declara explícitamente para que R5.4 no quede cubierto sólo por omisión.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Feature nueva | `frontend/features/properties/data/dto.ts` | DTOs camelCase + uniones re-exportadas del generado (D5) |
| | `frontend/features/properties/data/dto.test.ts` | Test de frontera del contrato |
| | `frontend/features/properties/data/http/http-properties-source.ts` (+ test) | Cliente HTTP contra `lib/api` (D4) |
| | `frontend/features/properties/data/index.ts` | Punto de composición `getPropertiesDataSource()` |
| | `frontend/features/properties/hooks/query-keys.ts` | `propertiesKeys.list` sobre `tenantScopedKey` (D6) |
| | `frontend/features/properties/hooks/use-properties.ts` (+ test) | Hook TanStack Query v5 con `retryPolicy` (D8) |
| | `frontend/features/properties/lib/error-mapping.ts` (+ test) | Unión discriminada de estados (D8) |
| | `frontend/features/properties/components/list/properties-view.tsx` (+ test) | Tabla, paginación, estados (R1, R3) |
| | `frontend/features/properties/components/list/properties-filters.tsx` (+ test) | Los dos filtros controlados (R2, D7) |
| | `frontend/features/properties/locales/properties-locale.test.ts` | **Nuevo**: 11 `PropertyOperationalState` + 2 `PropertyStatus` resuelven en ES y EN (D12) |
| | `frontend/features/properties/index.ts` | Fachada: exporta sólo `PropertiesView` |
| Componente transversal | `frontend/components/property-state-badge.tsx` (+ test) | **Nuevo**: los dos mapas + fallback (D2, D3). Su test **sí** fija las cadenas de clases por grupo de color y el fallback a `gray` — es la única red que van a tener, porque los tests del panel no las miran |
| Refactor del panel | `frontend/features/dashboard/components/property-card.tsx` | Consume el badge; se le quita `STATE_BADGE_CLASS` |
| | `frontend/features/dashboard/lib/state-color.ts` | Se retira (su mapa se muda al badge) |
| i18n | `frontend/locales/es/properties.json`, `frontend/locales/en/properties.json` | **Nuevos**: namespace `properties` (R6) |
| | `frontend/lib/i18n/resources.ts` | Registro en sus tres puntos: import, array, tablas `es`/`en` |
| Página | `frontend/app/(workspace)/properties/page.tsx` | `RoutePlaceholder` → `PropertiesView`; `generateMetadata` intacto |

## Data & interfaces

Ninguna migración, ningún endpoint nuevo, ninguna variable de entorno. El contrato consumido está congelado:

- **Petición**: `GET /api/v1/properties?page&per_page&status&current_operational_state`. `page` ≥ 1 (≤ 100.000), `per_page` 1..100 (por defecto 20). Los dos filtros combinan con AND y se omiten cuando valen «todos». Ojo: en Python el parámetro se llama `status_filter` con `alias="status"` — el nombre que viaja por el cable es `status`.
- **Respuesta**: `PropertyPageResponse` = `{data, total, page, per_page, total_pages}` (sobre de PRD §23, **no** `meta` anidado). Orden por `name` con `id` de desempate, así que paginar no repite ni omite filas.
- **Fila**: `PropertyListItemResponse`, 22 campos, **sin** `access_notes`/`cleaning_notes`/`emergency_notes` y sin `wifi_password`; `has_wifi_password: bool` es la única señal de WiFi.
- **Enums**: `PropertyStatus` (2 valores), `PropertyOperationalState` (11 valores).

Interfaz del componente extraído:

```ts
type PropertyOperationalState = components["schemas"]["PropertyOperationalState"];
export function PropertyStateBadge(props: { state: PropertyOperationalState; label: string }): JSX.Element;
```

## Risks & mitigations

- **Los colores del badge no los protege ningún test, así que un error en la mudanza es silencioso.** Verificado leyendo los dos tests del panel (revisión del arquitecto, 2026-08-22): `property-card.test.tsx` asserta sobre texto, `aria-label`/encabezado y `href`; `dashboard-view.test.tsx` asserta sobre `items-stretch`/`h-full`, que son del contenedor de la rejilla, no del badge. **Ninguno mira las clases Tailwind del badge.** Consecuencia práctica: esos dos tests seguirán verdes aunque la extracción se equivoque de color, así que no sirven de red. Lo que sí protegen es el texto traducido y la estructura DOM/aria, y eso es lo que el refactor no debe mover. Mitigación real: preservar literalmente las cadenas de clases (incluidas las variantes `dark:`) es una obligación **verificada a mano o con un test nuevo del propio badge**, no algo que la suite existente vaya a delatar.
- **Perder el fallback a `gray`.** `stateColorGroup` hace `?? "gray"` para que un estado nuevo del backend renderice neutro en vez de romper. La mudanza tiene que llevárselo; sin él, un valor no mapeado da `undefined` en la clase.
- **Reabrir la superficie de bulto.** La tentación natural al ver una fila incompleta es pedir el detalle por fila. Mitigación: está prohibido en R5.2 y el revisor de tenancy/seguridad del panel lo mira.
- **Divergencia ES/EN.** `frontend/lib/i18n/catalog-parity.test.ts` recorre los namespaces registrados y compara los conjuntos de claves, así que una clave que falte en `en` sale en rojo — pero **sólo si el namespace se registró** en `resources.ts`. Registrarlo es lo que activa la red.
- **Regenerar el contrato del frontend no funciona en un worktree enlazado** (`sdd/project.md`). No hace falta: los tipos ya están generados y commiteados, y este change no toca el backend. `npm test` sí necesita el copiado de nueve ficheros que `project.md` documenta, o salen 2 ficheros en rojo ajenos al change.

## Open questions

Ninguna. Las tres decisiones que podían quedar abiertas —si `/properties` duplica `/dashboard`, dónde vive el mapa de colores, y si el listado va a buscar las notas al detalle— están cerradas en D1, D2 y en R5 del proposal respectivamente, con su motivo y sus alternativas rechazadas.
