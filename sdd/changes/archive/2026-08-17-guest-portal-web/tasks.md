# Tasks: guest-portal-web

## 1. Data source anónimo y contrato de rutas

- [x] 1.1 Crear `frontend/features/guest-portal/data/guest-portal-source.ts`, sus DTOs y el composition point en `data/index.ts`, con exactamente los cuatro métodos `getStayInfo`, `getCheckinStatus`, `submitCheckin` y `reportIncident`; no añadir ninguna operación de lectura o gestión de incidencias [R1, R2, R3, R5].
- [x] 1.2 Implementar `frontend/features/guest-portal/data/http/http-guest-portal-source.ts` sobre `createApiClient({ baseUrl: "" })`, traduciendo únicamente los cuatro endpoints publicados y mapeando explícitamente los schemas snake_case a DTOs camelCase; probar que solo se construyen `GET /api/v1/guest/info/{token}`, `GET /api/v1/guest/checkin/{token}`, `POST /api/v1/guest/checkin/{token}` y `POST /api/v1/guest/incident/{token}`, exactamente esas cuatro rutas y ninguna más [R1, R2, R3, R5].
- [x] 1.3 Cubrir en las pruebas del data source la ausencia de `Authorization` y de cualquier interacción con JWT o sesión (`createAuthenticatedClients`, `getSessionTokens`, almacenamiento/refresco de sesión); verificar además que dos peticiones con tokens distintos no comparten datos por sus DTOs ni por el estado del módulo [R5].
- [x] 1.4 Probar los mapeadores DTO contra respuestas completas, campos nullable y campos desconocidos adicionales: normalizar los nullable de `StayInfoResponse` a ausencia segura, omitir `null`/`undefined` en la presentación y tolerar campos de respuesta no publicados sin renderizarlos [R1, R5].
- [x] 1.5 Probar que `SubmitCheckinRequest` emite exactamente `full_name`, `nationality`, `date_of_birth`, `document_type`, `document_number` y `document_expiry_date`, y que `ReportIncidentRequest` emite exactamente `title` y `description`; demostrar que no se envían `tenant_id`, `reservation_id`, fechas de reserva ni otros campos adicionales [R2, R5].

## 2. Hooks y política de reintentos compartida

- [x] 2.1 Crear `frontend/features/guest-portal/hooks/{query-keys.ts,use-stay-info.ts,use-checkin.ts,use-report-incident.ts}` con claves que distingan el token en memoria, queries para estancia/estado de check-in y mutations para check-in/incidencia; mantener la carga de estancia como gate de autorización de la página [R1, R2, R3].
- [x] 2.2 Extraer sin cambios de lógica ni firma la `retryPolicy` inline de `frontend/features/dashboard/hooks/use-dashboard-data.ts` a `frontend/lib/api/retry-policy.ts`, hacer que dashboard y guest-portal la consuman y conservar el comportamiento existente: no reintentar 4xx, reintentar errores 5xx/red hasta dos veces y no reintentar automáticamente `429` [R2, R3, R5].
- [x] 2.3 Mantener intactas las expectativas de los tests existentes de dashboard y añadir o ajustar únicamente cobertura necesaria para demostrar que la extracción es behavior-preserving; ejecutar específicamente esos tests antes y después del cambio [R5].
- [x] 2.4 Implementar en los hooks el mapeo seguro de `404`, `422`, `429`, `413`, `5xx` y red según D7, sin reintentos de mutaciones definitivas ni confirmación falsa de una incidencia después de `429` [R2, R3, R5].

## 3. Página y presentación de la estancia

- [x] 3.1 Sustituir el placeholder de `frontend/app/(guest)/guest/[token]/page.tsx` por `GuestPortalView token={params.token}`, conservando `generateMetadata` con `routeMetadata("guest")`; mantener el portal fuera de la navegación autenticada y el token fuera de metadata, título, breadcrumbs y analytics [R1, R5].
- [x] 3.2 Crear `frontend/features/guest-portal/components/guest-portal-view.tsx` y `stay-info-section.tsx` como página única mobile-first: cargar primero estancia, mostrar fechas, horas, vivienda, dirección, WiFi, instrucciones, código ya enmascarado y soporte según el schema, y no mostrar literalmente `null`, `undefined` ni campos desconocidos [R1, R4].
- [x] 3.3 Implementar el gate de `info`: ante cualquier `404 NOT_FOUND` mostrar un único estado localizado de enlace no válido, indistinguible entre inexistente/revocado/expirado/cancelado/otro tenant, sin renderizar check-in ni incidencia; probar la uniformidad del status, cuerpo visible y ausencia de detalles internos [R1, R5].
- [x] 3.4 Añadir una prueba de regresión de seguridad de renderizado que recorra texto visible, títulos, metadata, breadcrumbs, errores y estados de la página y falle si aparece el token; comprobar también que el número de documento nunca se muestra ni se hace eco tras el check-in [R1, R2].

## 4. Check-in legal

- [x] 4.1 Crear `frontend/features/guest-portal/components/checkin-section.tsx` y `components/fields/*` con los seis campos siempre visibles, `<form noValidate>`, estado controlado, validación ligera requerida/no-vacía, `document_type` limitado a `GuestDocumentType` y controles con `id`/`htmlFor` y asociación accesible de errores [R2, R4].
- [x] 4.2 Renderizar `missing_fields` únicamente como información declarada por el backend, sin inferir completitud, pasos, reglas de presentación ni fechas de reserva; localizar `document_status` y `legal_registration_status` por valor canónico y mostrar el resultado del envío sin el número de documento [R2, R4].
- [x] 4.3 Cubrir envío correcto, bloqueo de duplicados durante la mutation, progreso `aria-live`, éxito con ambos estados, errores `422` por campo sin cuerpo crudo/trace/valores sensibles y errores seguros `404`/`413`/`5xx` [R2, R4, R5].

## 5. Incidencias, accesibilidad e i18n

- [x] 5.1 Crear `frontend/features/guest-portal/components/incident-section.tsx` para enviar únicamente título y descripción, mostrar un acuse localizado basado en los campos publicados que defina la UX (sin renderizar el UUID `id`) y no ofrecer listar, leer, modificar, asignar, clasificar ni resolver incidencias [R3, R4, R5].
- [x] 5.2 Cubrir validación local y `422` accionable sin payload crudo, `429` con el mensaje de espera que no confirme ni niegue la creación, `413` y errores reintentables; comprobar que una incidencia inválida no genera una llamada adicional [R3, R5].
- [x] 5.3 Añadir `frontend/locales/es/guest.json` y `frontend/locales/en/guest.json`, registrar el namespace en `frontend/lib/i18n/resources.ts` y cubrir paridad de claves: toda cadena visible nueva, estados de carga/vacío/error/autorización/validación/rate-limit/éxito y copias de enums deben existir en ambos catálogos con `es` como fallback [R4].
- [x] 5.4 Verificar con pruebas de componentes navegación mobile-first, foco, nombres accesibles, `aria-invalid`, `aria-describedby`, regiones de estado y ausencia de valores crudos sensibles en todas las secciones [R2, R3, R4].

## 6. Verification

- [x] 6.1 Ejecutar la suite frontend: `cd frontend && npm test` — 62 archivos y 408 tests en verde [R1, R2, R3, R4, R5].
- [x] 6.2 Ejecutar type-check, lint y build: `cd frontend && npm run typecheck`, `cd frontend && npm run lint` y `cd frontend && npm run build` [R4, R5].
- [x] 6.3 Ejecutar la comprobación de contrato de tipos guest contra `backend/openapi.json` usando la variante documentada para worktree enlazado: `docker compose cp backend/openapi.json frontend:/backend/openapi.json`, `docker compose exec -T frontend ln -sfn /app /frontend` y `docker compose exec -T frontend npm run api:generate`; después verificar la salida con `cd frontend && npm run api:check` [R5].
- [x] 6.4 Revisar el diff final y confirmar que solo toca la página, feature guest, retry policy compartida, catálogos/i18n y tests necesarios; no modifica backend, OpenAPI, autenticación, sesión, tokens ni capacidades fuera de proposal/design [R1, R2, R3, R4, R5].

## Gate operativo previo a `READY_FOR_PR`/ship

La comprobación de la política de logging del túnel Cloudflare de dev —en particular, confirmar si se retiene el URI completo que contiene el token— es un gate operativo obligatorio antes de `READY_FOR_PR`/ship. Está registrado como `deferred` en `BLOCKED.md`, no bloquea la implementación ni esta fase de tasks y no se resuelve eliminando o modificando dicho archivo [R1, R5].
