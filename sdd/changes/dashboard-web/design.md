# Design: dashboard-web

## Context

La feature `frontend/features/dashboard/` ya separa la presentación de los
datos mediante `DashboardDataSource`, DTO en `data/dto.ts` y un único punto de
composición en `data/index.ts`. Hoy ese punto instancia
`MockDashboardSource`; los hooks de TanStack Query y los componentes ya
dependen solo de la interfaz.

El contrato tipado publicado en
`frontend/lib/api/generated/openapi.d.ts` expone las respuestas snake_case de
los tres endpoints que consume este change: cards, detalle agregado y
timeline por propiedad. El cliente común de `frontend/lib/api` ya serializa
errores como `ApiError`, aporta cabeceras de sesión y limita la recuperación
de `401` a un único reintento.

El endpoint adicional `/api/v1/properties/{property_id}/state` pertenece a
`dashboard-api`, pero no es necesario para esta sustitución. No se llamará ni
se añadirá al adapter: el detalle ya contiene `operational_state` y R2.1 limita
el change a las tres respuestas consumidas.

## Decisions

### D1 — Adapter HTTP detrás de la interfaz existente

**Chosen:** añadir `HttpDashboardSource` en
`frontend/features/dashboard/data/http/` e implementar los tres métodos de
`DashboardDataSource`. `data/index.ts` será el único lugar que cambie de
`MockDashboardSource` a `HttpDashboardSource`.

La elección conserva el límite de sustitución ya probado por
`boundary.test.ts`: componentes, hooks, stores y query keys no conocerán la
implementación concreta.

Rejected: modificar hooks o componentes para llamar al API directamente —
rompería la interfaz intercambiable y mezclaría acceso HTTP con presentación.

### D2 — Cliente tipado y sesión existente

**Chosen:** extraer en `frontend/lib/api/authenticated-client.ts` la creación
del `ApiClient` autenticado que hoy vive dentro de `AuthProvider`. Tanto
`AuthProvider` como la composición del dashboard reutilizarán esa factory;
`HttpDashboardSource` recibirá el `ApiClient` ya configurado. Su composición
usará la ruta same-origin `/api` ya proporcionada por el proxy de
`frontend/app/api/[...path]/route.ts`; la factory aceptará `apiBaseUrl` y el
dashboard usará el valor same-origin por defecto. El adapter no implementará `fetch`,
refresh, headers ni parseo de errores por su cuenta.

El cliente conservará las cabeceras derivadas de la sesión en memoria y su
recuperación coordinada ante `401`. Para que el adapter sea determinista y
testeable, el cliente se inyectará en el constructor/factory y las pruebas
usarán un doble tipado, sin levantar backend.

Rejected: crear un cliente HTTP privado con otro formato de error o con otra
lógica de refresh — duplicaría seguridad y podría provocar más de una
recuperación de sesión.

### D3 — Mapeadores explícitos y cerrados al contrato consumido

**Chosen:** definir mapeadores pequeños y puros para cada nivel de respuesta:
envelope paginado, card, detalle, reserva, acción, huésped, acceso, foto,
incidencia, bloque financiero, aprobación y entrada de timeline. Cada
mapeador leerá únicamente las claves snake_case presentes en el tipo OpenAPI
del endpoint correspondiente y escribirá las claves camelCase del DTO
existente.

Los tres métodos llamarán exclusivamente a:

- `GET /api/v1/dashboard/properties`;
- `GET /api/v1/properties/{property_id}/dashboard`;
- `GET /api/v1/timeline/{property_id}`.

Los filtros se convertirán con una tabla explícita (`eventType` →
`event_type`, `actorType` → `actor_type`, `from`/`to` sin renombrar y
`severity` sin renombrar) y solo se incluirán los valores definidos. Las
respuestas paginadas conservarán `data`, `total`, `page`, `per_page` y
`total_pages` sin reordenar entradas.

Los importes decimales que el backend entrega como strings se convertirán
explícitamente al tipo numérico que exige el DTO actual; `null` permanecerá
`null`. Las fechas y textos se conservarán como strings recibidos, sin
normalizar zona horaria ni traducir datos dinámicos. Las URLs de fotos se
copiarán tal cual; nunca se derivarán desde un storage key.

Si una capacidad o campo no aparece en una de esas respuestas, el adapter no
lo inventará, no consultará otra ruta y no ampliará el DTO o el alcance para
rellenarlo. La forma de ausencia será la que ya fija el DTO y el contrato
publicado (`null` para bloques nullable y listas vacías cuando la respuesta
las entrega vacías).

Rejected: usar `camelcase-keys`, `fromEntries`, serialización automática o
`from_attributes` — ocultaría el contrato campo a campo y permitiría que un
campo backend nuevo se filtrase sin una decisión explícita.

### D4 — Paginación y filtros sin ampliar la interfaz

**Chosen:** mantener las firmas actuales de `DashboardDataSource`. Cards y
timeline solicitarán los valores por defecto del contrato, mientras que el
timeline expondrá mediante query params solo los filtros ya presentes en
`TimelineFilters`. No se añadirá paginación configurable ni se consumirá el
endpoint global de timeline en este change.

Así se conservan las query keys y la API de hooks existentes; los envelopes
siguen disponibles para la UI y para futuras capacidades, sin introducir una
nueva superficie de producto.

Rejected: añadir parámetros de página al puerto en este change — exigiría
cambiar hooks, query keys y comportamiento de la UI sin estar en la propuesta.

### D5 — Errores y autenticación delegados

**Chosen:** propagar directamente los errores que produzca `ApiClient`, en
particular `ApiError` con `status === 404` para detalle o timeline. El adapter
no traducirá códigos, no ocultará detalles adicionales en una excepción nueva
y no hará reintentos; TanStack Query conserva la política existente.

Rejected: envolver `ApiError` en un error de dashboard — perdería el contrato
común que usa `PropertyDetailView` para distinguir el estado not-found.

## Changes by area

| Área | Archivos | Cambio |
|---|---|---|
| Adapter | `frontend/features/dashboard/data/http/http-dashboard-source.ts` | Implementación HTTP y mapeadores explícitos para las tres rutas permitidas. |
| Composición | `frontend/features/dashboard/data/index.ts` | Instanciar `HttpDashboardSource` en lugar de `MockDashboardSource`; conservar el único composition point. |
| Cliente autenticado | `frontend/lib/api/authenticated-client.ts`, `frontend/lib/auth/auth-provider.tsx` | Compartir la factory de cliente, cabeceras de sesión y recuperación única ante `401` entre auth y dashboard. |
| API de datos | `frontend/features/dashboard/data/dto.ts` | Solo ajustar comentarios/tipos si la implementación necesita documentar la correspondencia exacta; no añadir capacidades no presentes en las respuestas. |
| Pruebas del adapter | `frontend/features/dashboard/data/http/http-dashboard-source.test.ts` | Verificar rutas, filtros, envelopes, mapeo snake_case/camelCase, nulls, importes, fechas, URLs y propagación de `ApiError`. |
| Pruebas de frontera | `frontend/features/dashboard/data/boundary.test.ts` | Mantener la garantía de que la UI y los hooks no importan mock ni adapter concreto. |

No se modifican componentes, hooks, query keys, stores, locales ni el contrato
OpenAPI generado. El mock y sus pruebas permanecen aislados para conservar la
referencia local de comportamiento durante la sustitución.

## Data & interfaces

No hay cambios de base de datos, endpoints, permisos, modelos backend,
variables de entorno, eventos ni dependencias npm.

La interfaz pública de `DashboardDataSource` permanece igual. El adapter
consume los tipos generados de `frontend/lib/api/generated/openapi.d.ts` y
devuelve los DTO de `frontend/features/dashboard/data/dto.ts`.

El endpoint `/api/v1/properties/{property_id}/state` y cualquier endpoint
global de timeline quedan explícitamente fuera de la interfaz y de la
implementación de este change.

## Risks & mitigations

- **Deriva entre OpenAPI y DTO:** los tests de mapeo construirán respuestas con
  la forma snake_case generada y comprobarán cada campo convertido; `api:check`
  queda como validación de contrato del frontend.
- **Pérdida de precisión al convertir importes:** la conversión será explícita,
  acotada al DTO numérico existente y cubierta con valores decimales; no se
  usará conversión implícita ni cálculo financiero en el adapter.
- **Exposición de datos sensibles:** los mapeadores solo leerán los campos de
  las respuestas agregadas; no accederán a endpoints de documentos, códigos o
  storage, y las fotos usarán exclusivamente la URL firmada recibida.
- **Regresión de sesión:** las pruebas del cliente/adapter verificarán que las
  cabeceras y el `ApiError` siguen delegados al cliente común; no se añadirá un
  segundo mecanismo de refresh.
- **Respuesta parcial o capacidad futura:** no se rellenarán campos ausentes
  ni se harán llamadas compensatorias. La ausencia se preservará conforme al
  contrato actual, en línea con R2.1.

## Open questions

None. Las decisiones de este diseño dejan fuera las capacidades backend que
no forman parte de las tres respuestas consumidas y no requieren modificar la
propuesta aprobada.
