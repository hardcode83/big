# Design: reservation-create-web

## Context

`/reservations` y `/reservations/[id]` ya consumen las lecturas tipadas y las
queries tenant-scoped de la feature, pero `HttpReservationsSource` no expone las
tres operaciones mutantes que ya sirve el backend. Este diseño completa el ciclo
manual en frontend sin cambiar el contrato API ni introducir una fuente de verdad
paralela.

## Decisions

### D1 — Extender la fuente HTTP existente

`frontend/features/reservations/data/http/http-reservations-source.ts` añadirá
`createReservation`, `updateReservation` y `cancelReservation`. POST y PATCH
devuelven `ReservationSummaryDto` porque el contrato responde
`ReservationResponse`; DELETE devuelve `void` por su `204`. La invalidación
posterior obtiene el detalle completo con la query existente. Los payloads se tiparán con
`components["schemas"]["CreateReservationRequest"]` y
`components["schemas"]["UpdateReservationRequest"]`.

Se elige la fuente existente porque `data/index.ts` ya es el único composition
point autenticado y el cliente compartido ya delega `401` a la sesión. No se
creará un cliente específico ni se duplicará el transporte.

Alternativas rechazadas: llamar a `fetch` desde los componentes (rompe la
frontera de adapter) o crear un `ReservationsMutationSource` separado (duplica
autenticación y composición).

### D2 — Hooks de mutación con invalidación confirmada

`frontend/features/reservations/hooks/use-reservations.ts` añadirá hooks para
crear, modificar y cancelar. Cada mutación usará `retry: false`; tras terminar
—con éxito o error— invalidará las claves tenant-scoped relevantes. Las escrituras
no harán optimistic updates: la respuesta del backend es la única confirmación.

Crear invalidará el prefijo de listado. Actualizar y cancelar invalidarán el
detalle afectado y el prefijo de listado. La invalidación será esperada para que
la UI no pinte el estado previo después de resolver una mutación.

Alternativas rechazadas: parche optimista del cache (puede mostrar noches,
ocupación o estado que el backend rechazó) y recargar la página completa (pierde
el estado local y contradice la navegación App Router).

### D3 — Guardia UX por `MANAGE_RESERVATIONS`

`frontend/lib/auth/permissions.ts` incorporará `MANAGE_RESERVATIONS` para
`PROPERTY_MANAGER`, dejando al owner en lectura. Las páginas siguen dependiendo
del backend para autorización; la mirror solo oculta/deshabilita controles.
Los componentes de alta, edición y cancelación usarán `useHasPermission` y no
enviarán ninguna mutación si no existe el permiso.

Alternativa rechazada: inferir permisos directamente desde el nombre del rol en
cada componente, porque dispersa la política y puede divergir del cliente.

### D4 — Formulario manual y payload cerrado

Se añadirá un formulario de alta en el listado y un formulario de edición en el
detalle, reutilizando controles compartidos, estados accesibles y las
traducciones de `reservations`. La propiedad se seleccionará desde
`useProperties({ status: "ACTIVE", page, perPage })`; el selector cargará todas
las páginas necesarias (o mostrará paginación explícita) y distinguirá loading,
error y página vacía. Se mostrarán zona horaria y horas por defecto devueltas por
la propiedad.

El alta construirá solo campos admitidos por `CreateReservationRequest`: fechas,
horas opcionales, propiedad, adultos/niños, canal `DIRECT`/`MANUAL`, importes,
divisa, peticiones/notas y `guest` opcional. El guest contendrá únicamente
`full_name`, email, teléfono e idioma; nunca se renderizará `guest_id`. Los
valores vacíos opcionales se omitirán, no se transformarán en cadenas vacías.
Las horas se mantienen como hora local civil de la propiedad y las fechas como
`YYYY-MM-DD`.

La edición calculará un diff respecto al detalle cargado y enviará solo campos
modificados de `UpdateReservationRequest`. Para canales no manuales se
deshabilitarán los campos incluidos en `INGEST_OWNED_FIELDS`; el backend sigue
siendo la autoridad. La cancelación usará `DELETE` y no pedirá un motivo porque
el endpoint generado no admite body de motivo.

Alternativas rechazadas: enviar el objeto completo en cada PATCH (borra valores
nullable sin intención) y permitir canales OTA en el alta (el contrato manual
solo admite `DIRECT`/`MANUAL`).

### D5 — Errores y estados de interfaz

Se añadirá `frontend/features/reservations/lib/mutation-error-mapping.ts` con un
mapper puro que distinga `401` (flujo de sesión), `403`, `404`, `409`, `422` y
error genérico para mutaciones. Sus tests fijarán el contrato para `ApiError`,
errores de red y respuestas 5xx. Los errores permanecen visibles en
la vista y conservan los valores locales del formulario. Botones de submit y
cancelación quedan deshabilitados mientras la mutación está pendiente y exponen
`aria-busy`; éxito se comunica con texto/alerta localizado, no solo con color.
Los formularios usan `onSubmit` con `preventDefault`, no declaran `action` ni
`method` que pueda provocar GET, y no guardan PII en URL, `localStorage` o
`sessionStorage`; el test inspecciona explícitamente estas garantías.

La validación cliente bloqueará únicamente campos estructuralmente inválidos
(fechas invertidas, números negativos o campos requeridos vacíos), sin imponer
restricciones de disponibilidad ni prohibir check-in el mismo día si el backend
lo admite.

### D6 — Localización y cobertura

Todos los textos nuevos vivirán en `frontend/locales/es/reservations.json` y
`frontend/locales/en/reservations.json`. Se añadirán tests de fuente HTTP,
hooks/cache invalidation, permisos, formularios y locales. La verificación
usará los comandos de `sdd/project.md`: `cd frontend && npm test`,
`cd frontend && npm run lint`, y `cd frontend && npm run api:check` cuando el
contrato se toque.

## Requirement coverage

- R1: D1, D2, D4 y D5 cubren alta, payload cerrado, `PENDING`, canales manuales,
  errores y refresco del listado.
- R2: D4 cubre propiedad, guest opcional, zona horaria, horas, fechas, importes
  y la prohibición de `guest_id`.
- R3: D1, D2, D4 y D5 cubren PATCH por diff, campos ingeridos, DELETE como
  cancelación, recalculo y errores.
- R4: D2, D3 y D5 cubren permisos, tenancy, sesión, progreso y no duplicación.
- R5: D4, D5 y D6 cubren primitivas compartidas, accesibilidad, ES/EN,
  nullables y contrato tipado.

## Affected files

- `frontend/features/reservations/data/http/http-reservations-source.ts`
- `frontend/features/reservations/data/dto.ts`
- `frontend/features/reservations/hooks/use-reservations.ts`
- `frontend/features/reservations/hooks/query-keys.ts`
- `frontend/features/reservations/components/list/reservations-view.tsx`
- `frontend/features/reservations/components/detail/reservation-detail-view.tsx`
- `frontend/features/reservations/components/detail/reservation-detail-sections.tsx`
- `frontend/features/reservations/components/{create,edit}-reservation*.tsx`
- `frontend/features/reservations/lib/mutation-error-mapping.ts`
- `frontend/features/properties/hooks/use-properties.ts`
- `frontend/features/properties/data/http/http-properties-source.ts`
- `frontend/lib/auth/permissions.ts`
- `frontend/locales/{es,en}/reservations.json`
- tests colocated with the files above

## Risks and mitigations

- El endpoint de propiedades puede devolver propiedades inactivas: el formulario
  muestra la respuesta del backend y no la convierte en éxito.
- Un PATCH con `null` puede limpiar un campo: el diff distingue ausencia de
  `null` explícito y tendrá tests de ambos casos.
- La mirror de permisos puede quedarse atrás: los `403` siguen siendo estados
  visibles y el backend nunca se confía al frontend.
- La suite frontend en Docker tiene los dos fallos de rutas documentados en
  `sdd/project.md`; se preparará el contenedor según ese documento antes de
  interpretar esos fallos como regresiones.

## Open questions

No quedan preguntas abiertas que cambien requisitos. El contrato `DELETE` no
acepta motivo y el alta nace en `PENDING`; cualquier acción posterior de estado
queda fuera de este change.
