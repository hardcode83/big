# Design: statements-web

## Context

`frontend/app/(workspace)/statements/page.tsx` solo renderiza `RoutePlaceholder`; el backend ya
publica el listado `OwnerStatementResponse`, el detalle `OwnerStatementDetailResponse` con
`reservations` y `expenses`, y las descargas CSV/PDF. El contrato del statement publica únicamente
`property_id`, mientras que el workspace ya dispone de `features/properties` y
`useActiveProperties()` para resolver identidades y poblar selectores. El `ApiClient` de
`frontend/lib/api/client.ts` está tipado para respuestas JSON y actualmente descarta los headers,
por lo que la descarga requiere una extensión acotada de transporte en frontend.

## Decisions

### D1 — Feature frontend por capas y DTOs propios

**Chosen:** crear `frontend/features/statements` con DTOs camelCase, una fuente HTTP autenticada,
hooks de TanStack Query y componentes de listado/detalle/exportación; la página de App Router solo
compondrá la vista. La UI no dependerá directamente de `components` generados por OpenAPI ni del
cliente HTTP en los componentes.

Rejected: implementar toda la lógica en `app/(workspace)/statements/page.tsx` — mezclaría transporte,
estado de servidor y presentación, contradiciendo la separación usada por `features/properties`,
`features/pricing` y `features/reviews`.

### D2 — Identidad de propiedad desde el directorio existente

**Chosen:** cargar el directorio completo de propiedades activas mediante `useActiveProperties()` y
resolver cada `OwnerStatementResponse.property_id` contra ese directorio. El mismo directorio
alimentará el filtro, que enviará solo el UUID seleccionado como `property_id`; la lista de
statements nunca será la fuente de opciones.

Rejected: derivar nombres y opciones recorriendo únicamente los statements de la página actual —
ocultaría propiedades sin statement en esa página y produciría labels incompletos al paginar.

Rejected: añadir una ruta de resolución de propiedades al backend — el endpoint y la fuente
existente de propiedades ya cubren esta necesidad y el proposal excluye cambios backend.

### D3 — Separar listado y detalle del contrato

**Chosen:** mapear el listado a un DTO de resumen basado en `OwnerStatementResponse` y el detalle a
un DTO aditivo basado en `OwnerStatementDetailResponse`. El detalle conservará los campos monetarios
planos y añadirá las filas de `reservations[]` y `expenses[]` sin recalcular totales.

Rejected: usar el mismo DTO para ambas respuestas y asumir que las colecciones siempre existen — el
listado no publica breakdowns y la UI debe distinguir sus estados de carga, vacío y error.

### D4 — Transporte binario opaco con headers preservados

**Chosen:** extender la capa compartida de `ApiClient` con una operación de respuesta binaria que
devuelva los bytes y los headers necesarios (`Content-Type`, `Content-Disposition` y demás headers
contractuales), conservando autenticación y recuperación única de `401`. La feature construirá un
`Blob` únicamente para entregar al navegador el payload recibido y usará el filename indicado por
la respuesta; no parseará, validará, re-encodeará, transformará ni reconstruirá CSV/PDF.

Rejected: reutilizar `request()` JSON — intenta ejecutar `response.json()` y pierde tanto los bytes
como los headers de descarga.

Rejected: generar el CSV/PDF desde las colecciones JSON — duplicaría la responsabilidad del backend
y podría producir un archivo distinto del contrato definitivo.

### D5 — Estado de UI explícito y filtros sin estado duplicado

**Chosen:** TanStack Query será la única fuente del estado remoto; los filtros y la página serán
estado ligero local de la vista, reiniciados al cambiar de tenant. Cada operación de descarga tendrá
estado pendiente/error propio y se deshabilitará solo su control mientras dure.

Rejected: copiar statements o propiedades a Zustand — duplicaría server state y abriría una ventana
para mostrar datos de otra sesión.

### D6 — Acceso e i18n mediante patrones existentes

**Chosen:** la ruta conservará `routeMetadata`, shell y guardas existentes; los componentes usarán
`useHasPermission`, estados compartidos, `react-i18next`, namespaces ES/EN y controles shadcn/ui con
focus visible y targets táctiles adecuados. La UI ocultará o bloqueará acciones según permisos, pero
el backend seguirá siendo la autoridad.

Rejected: crear un permiso o una ruta de autorización nueva — el contrato ya exige el permiso
existente `READ_OWNER_STATEMENTS` y el proposal excluye cambios de permisos.

## Changes by area

| Area | Files | Change |
|---|---|---|
| API transport | `frontend/lib/api/client.ts` y sus tests | Añadir respuesta binaria tipada, preservando bytes, headers, auth, refresh y errores. |
| Statements data | `frontend/features/statements/data/dto.ts`, `data/http/http-statements-source.ts`, `data/index.ts` | Mapear listado/detalle, filtros contractuales y descargas opacas. |
| Statements state | `frontend/features/statements/hooks/*` | Queries para listado, detalle y directorio de propiedades; mutations/estado para descargas. |
| Statements UI | `frontend/features/statements/components/*`, `frontend/app/(workspace)/statements/page.tsx` | Listado, filtros, paginación, detalle, breakdowns, estados UI y controles de descarga. |
| Property identity | Reutilización de `frontend/features/properties` | Resolver labels y poblar filtros con la fuente existente; no añadir endpoint. |
| i18n | `frontend/locales/es/statements.json`, `frontend/locales/en/statements.json`, `frontend/lib/i18n/resources.ts` | Etiquetas, estados, categorías, errores y ausencia de datos en ambos idiomas. |
| Tests | Tests junto a las áreas anteriores | Cubrir contrato, tenant/session boundaries, estados UI, accesibilidad, responsive y bytes/headers. |

## Data & interfaces

- No hay cambios backend, migraciones, permisos, endpoints ni variables de entorno.
- `GET /api/v1/owner-statements` se consume como página `{items,total,page,per_page}` de
  `OwnerStatementResponse`.
- `GET /api/v1/owner-statements/{statement_id}` se consume como `OwnerStatementDetailResponse`,
  con summary plano y las colecciones contractuales de reservas y gastos.
- Los importes nullable de reservas permanecen ausentes; la UI no los convierte en cero.
- La `currency` se muestra por fila de breakdown; el summary no publica una moneda global y la UI no
  inventará conversiones ni agregados entre monedas.
- Las exportaciones se transportan como bytes opacos. Se respetan `Content-Type`,
  `Content-Disposition`/filename y demás headers; el frontend no interpreta el contenido.

## Risks & mitigations

- **El directorio de propiedades falla o está cargando:** mostrar estado propio y no sustituir
  `property_id` por un nombre inventado; mantener filtros sin opciones hasta que la fuente esté lista.
- **El statement pertenece a otro tenant o no existe:** propagar el error 404 común sin distinguir
  causas, conforme al backend.
- **Headers de descarga no expuestos por el cliente actual:** cubrir la extensión con tests de
  `Content-Type`, `Content-Disposition`, bytes exactos y error sin Blob utilizable.
- **Descarga doble o parcial:** deshabilitar el control durante la petición, crear el objeto de
  descarga solo después de una respuesta exitosa completa y revocar la URL temporal después de usarla.
- **Overflow móvil o contenido no accesible:** usar layout mobile-first, estados explícitos, labels
  programáticos, foco visible, teclado y tests en los breakpoints soportados.

## Open questions

Ninguna. El proposal aprobado fija el contrato, el alcance y la responsabilidad de las descargas.
