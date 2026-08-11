# Proposal: dashboard-web

## Why

La UI real del dashboard ya existe en `/dashboard` y `/properties/[id]`, pero
todavía se alimenta de `MockDashboardSource`, con dos propiedades y datos
hardcodeados. El backend agregado ya está disponible en `dashboard-api` y la
sesión autenticada en `frontend-auth-session`, por lo que falta cerrar la
costura frontend consumiendo esos endpoints reales. El alcance y las
decisiones previas están documentados en [`sdd/roadmap/dashboard-web.md`](../../roadmap/dashboard-web.md)
y en [`sdd/specs/dashboard-web-frontend.md`](../../specs/dashboard-web-frontend.md).

## What changes

Se implementará `HttpDashboardSource` detrás de la interfaz existente
`DashboardDataSource`, usando el cliente tipado de `frontend/lib/api`,
convirtiendo explícitamente las respuestas `snake_case` de `dashboard-api` a
los DTO `camelCase` que ya consume la UI. El composition point dejará de
instanciar el mock. La sustitución mantendrá intactos los componentes, hooks,
query keys y estados de carga/error/vacío.

## Requirements

### R1 — Fuente HTTP tipada

**Como** propietaria o manager autenticada, **quiero** que el dashboard lea la
API agregada real, **para** ver propiedades y actividad actuales en lugar de
fixtures de desarrollo.

Acceptance criteria:

1. WHEN `DashboardDataSource.getDashboardCards` se invoca, THE SYSTEM SHALL
   solicitar `GET /api/v1/dashboard/properties` mediante el cliente tipado,
   incluyendo la sesión autenticada y devolviendo su envelope paginado en el
   DTO `PaginatedResponse<PropertyDashboardCard>`.
2. WHEN `getPropertyDetail` se invoca, THE SYSTEM SHALL solicitar
   `GET /api/v1/properties/{property_id}/dashboard` y devolver un
   `PropertyDetail` compatible con la interfaz existente.
3. WHEN `getPropertyTimeline` se invoca, THE SYSTEM SHALL solicitar
   `GET /api/v1/timeline/{property_id}`, transmitiendo los filtros soportados
   y devolviendo el envelope paginado sin reordenar sus entradas.

### R2 — Mapeo explícito del contrato

**Como** mantenedor del frontend, **quiero** una conversión explícita entre el
contrato HTTP y los DTO de la feature, **para** que los nombres, fechas, nulls,
importes y URLs firmadas no dependan de transformaciones implícitas.

Acceptance criteria:

1. WHEN la API responde correctamente, THE SYSTEM SHALL mapear explícitamente
   solo los campos realmente proporcionados por las respuestas de los tres
   endpoints consumidos por este change (`/api/v1/dashboard/properties`,
   `/api/v1/properties/{property_id}/dashboard` y
   `/api/v1/timeline/{property_id}`), desde `snake_case` a sus campos
   `camelCase` correspondientes. Las capacidades o campos que esas respuestas
   no proporcionen no SHALL sintetizarse, obtenerse mediante nuevas llamadas a
   endpoints fuera de este alcance ni incorporarse ampliando este change.
2. WHEN una respuesta contiene un campo nullable, THE SYSTEM SHALL preservar
   `null` y no omitirlo ni sustituirlo por un valor inventado; las fechas SHALL
   permanecer como strings ISO-8601 UTC y las URLs de fotos SHALL ser las
   proporcionadas por backend.
3. THE SYSTEM SHALL NOT calcular estados operativos, colores, acciones,
   traducciones de datos ni URLs de almacenamiento en `HttpDashboardSource`.

### R3 — Autenticación, errores y filtros

**Como** usuario autenticado, **quiero** que el dashboard respete la sesión y
los errores del contrato común, **para** recibir los estados localizados que ya
implementa la UI.

Acceptance criteria:

1. WHEN el cliente realiza una petición, THE SYSTEM SHALL obtener las cabeceras
   de autenticación del cliente compartido y SHALL dejar que su recuperación
   ante `401` se aplique una sola vez según la sesión existente.
2. WHEN la API responde con un error HTTP, THE SYSTEM SHALL propagar el
   `ApiError` producido por `lib/api`, incluyendo el `404` de una propiedad,
   sin exponer detalles crudos ni convertirlo en un error de dominio nuevo.
3. WHEN se proporcionan filtros de timeline, THE SYSTEM SHALL serializarlos
   como parámetros de consulta solo cuando estén definidos y SHALL omitir los
   parámetros ausentes.

### R4 — Sustitución aislada y verificable

**Como** mantenedor de la aplicación, **quiero** cambiar la implementación en
   un único composition point, **para** activar datos reales sin modificar la
   UI ni la forma de cachear sus consultas.

Acceptance criteria:

1. WHEN se resuelve `getDashboardDataSource`, THE SYSTEM SHALL devolver
   `HttpDashboardSource` y no `MockDashboardSource`.
2. THE SYSTEM SHALL mantener sin cambios la interfaz pública, los hooks, las
   query keys, los componentes y los estados de carga/error/vacío existentes.
3. WHEN se ejecutan las pruebas y validaciones del frontend, THE SYSTEM SHALL
   pasar type-check, lint, la suite colocada y build de producción sin requerir
   un backend en ejecución; las pruebas del adapter SHALL cubrir éxito, mapeo,
   filtros y errores.

## Out of scope

- Cambios visuales, de accesibilidad, responsive, i18n, componentes, hooks o
  query keys del dashboard; ya pertenecen a `dashboard-web-frontend`.
- Cambios en endpoints, modelos, permisos, tenant scoping u OpenAPI del
  backend; pertenecen a `dashboard-api`.
- Persistencia o hidratación de sesión, logout visible y cambios en la política
  JWT; pertenecen a `frontend-auth-session` o a un change posterior.
- Tiempo real por WebSocket/SSE, mutaciones del dashboard y composición de
  nuevas capacidades de negocio.

## Affected specs

- `sdd/specs/dashboard-web-frontend.md` — actualizar al archivar para reflejar
  que la implementación HTTP sustituye al mock y que la deuda queda cerrada.
- `sdd/specs/dashboard-api.md` — no se modifica; se consume como contrato vivo.
