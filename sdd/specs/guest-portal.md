# Portal del huésped — superficie web

## Purpose

Da al huésped una página móvil en `/guest/[token]` para consultar su estancia, completar el
check-in legal de PRD §17 y comunicar una incidencia, consumiendo las cuatro rutas anónimas que
publica [`guest-portal-api`](guest-portal-api.md) a través del proxy same-origin. No crea
identidad interna, sesión ni JWT para el huésped: el token de la ruta **es** la credencial, y la
página se limita a leer y escribir los campos que los schemas ya publican.

El contrato de backend, seguridad y ciclo de vida del token vive en
[`guest-portal-api`](guest-portal-api.md) y no se repite aquí; el *cómo se opera y se diagnostica*
está en [`docs/guest-portal.md`](../../docs/guest-portal.md). Esta spec cubre qué garantiza la
interfaz web.

## Requirements

### Acceso y presentación de la estancia

- WHEN `/guest/[token]` se carga con un token válido, THE SYSTEM SHALL consultar
  `GET /api/v1/guest/info/{token}` y mostrar fechas y horas de entrada/salida, nombre de la
  vivienda, dirección, ciudad, provincia, código postal, país, zona horaria, nombre de la WiFi,
  instrucciones de llegada, código de acceso enmascarado y vía de soporte, según el
  `StayInfoResponse` publicado.
- WHEN un campo nullable de `StayInfoResponse` (`address_line1/2`, `city`, `province`,
  `postal_code`, `wifi_name`, `arrival_notes`, `access_code_masked`, `support_channel`) llega como
  `null`, THE SYSTEM SHALL omitir la fila o mostrar una copia localizada de ausencia, y NEVER SHALL
  renderizar `null`, `undefined` ni romper el layout.
- THE SYSTEM SHALL renderizar el `access_code_masked` **tal como llega** ya enmascarado del
  backend, y NEVER SHALL desenmascararlo ni reconstruirlo.
- THE SYSTEM NEVER SHALL renderizar el token en texto visible, breadcrumbs, metadata, títulos,
  analytics ni mensajes de error, y SHALL mantener la superficie del huésped fuera de la
  navegación de usuario autenticado: la ruta `guest` no lleva `href` en el route registry, y
  `GuestShell` no renderiza navegación interna ni recibe el token.
- WHEN se genera la metadata de `/guest/[token]`, THE SYSTEM SHALL usar `routeMetadata("guest")`
  —genérica, `noindex/nofollow`, sin token ni canonical— sin interpolar el valor de la ruta.

### El fallo de `info` es el gate de autorización de la página

- IF `GET /api/v1/guest/info/{token}` responde el `404 NOT_FOUND` público, THEN THE SYSTEM SHALL
  mostrar un único estado localizado de "enlace no válido" para toda la página, que NEVER SHALL
  distinguir token inexistente, revocado, expirado, cancelado ni perteneciente a otro tenant.
- WHILE `info` no ha autorizado, THE SYSTEM SHALL NOT renderizar las secciones de check-in ni de
  incidencia: un enlace muerto no ofrece sus formularios.

### Check-in legal

- WHEN el portal obtiene `GET /api/v1/guest/checkin/{token}`, THE SYSTEM SHALL consumir
  `document_status`, `legal_registration_status` y `missing_fields` como información **declarada
  por el backend**, tratando `missing_fields` únicamente como los nombres de campos que el backend
  evalúa como ausentes; NEVER SHALL inferir de `missing_fields` pasos, completitud o reglas de
  presentación, ni mostrar o pedir fechas que pertenecen a la reserva.
- THE SYSTEM SHALL mostrar **siempre los seis campos** del contrato (`full_name`, `nationality`,
  `date_of_birth`, `document_type`, `document_number`, `document_expiry_date`), con
  `document_type` como selección sobre los miembros de `GuestDocumentType`, porque
  `SubmitCheckinRequest` no es un patch parcial.
- WHEN el huésped envía el formulario, THE SYSTEM SHALL enviar a
  `POST /api/v1/guest/checkin/{token}` exactamente esos seis campos y NEVER SHALL enviar
  identidad (`tenant_id`, `reservation_id`) ni fechas de reserva; la interfaz consume solo el tipo
  de request generado, así que ningún campo extra es expresable.
- WHEN el envío tiene éxito, THE SYSTEM SHALL mostrar los estados `document_status` y
  `legal_registration_status` de la respuesta y NEVER SHALL mostrar ni hacer eco del número de
  documento.
- WHILE el envío está en curso, THE SYSTEM SHALL deshabilitar el botón para impedir envíos
  duplicados y SHALL anunciar el progreso mediante una región `aria-live`; tras el éxito SHALL
  permitir continuar o revisar el resultado sin crear una sesión de usuario.

### Comunicación de incidencias

- WHEN el huésped envía un título y una descripción válidos, THE SYSTEM SHALL llamar a
  `POST /api/v1/guest/incident/{token}` y mostrar un acuse localizado basado únicamente en la
  respuesta publicada (`id`, `status`, `created_at`); THE SYSTEM SHALL mostrar la confirmación con
  el `status` traducido y `created_at`, y NEVER SHALL renderizar el `id` UUID.
- THE SYSTEM NEVER SHALL ofrecer al huésped rutas ni controles para listar, leer, modificar,
  asignar, clasificar o resolver incidencias: `GuestPortalDataSource` declara exactamente los
  cuatro métodos del contrato y ninguno lee una incidencia, así que la ausencia es estructural.
- IF la API responde `429 RATE_LIMITED` al comunicar una incidencia, THEN THE SYSTEM SHALL indicar
  que debe esperar antes de reintentar y NEVER SHALL presentar el reintento como confirmación de
  que la incidencia no se creó.

### Estados accesibles, localización y mapeo de errores

- WHEN se renderiza cualquier texto visible del portal, THE SYSTEM SHALL resolverlo mediante i18n
  ES/EN sobre el namespace `guest` (`locales/es/guest.json` y `locales/en/guest.json`), con `es`
  como fallback; toda clave introducida existe en ambos catálogos y ninguna cadena está
  hardcodeada.
- THE SYSTEM SHALL proporcionar estados accesibles y localizados de carga, vacío, error de
  autorización, error de validación, rate limit y éxito para cada uno de los tres recorridos, y
  SHALL mantener navegación mobile-first, foco y nombres accesibles para controles, campos,
  mensajes y regiones de estado.
- THE SYSTEM SHALL renderizar `document_status`, `legal_registration_status` e `IncidentStatus`
  como copia localizada indexada por el **valor exacto del enum** generado, y NEVER SHALL mover
  lógica de negocio o de transición al cliente.
- IF la API responde `422 VALIDATION_ERROR`, THEN THE SYSTEM SHALL asociar los errores a sus
  campos leyendo solo `details.errors[].loc` y mostrando copia localizada, y NEVER SHALL renderizar
  el cuerpo crudo, trazas ni el valor rechazado.
- IF la API responde `413 PAYLOAD_TOO_LARGE`, THEN THE SYSTEM SHALL mostrar un estado localizado
  de contenido demasiado grande en las operaciones cuyo contrato lo publica.
- WHEN una petición falla con `5xx`, error de red o `502` del proxy, THE SYSTEM SHALL mostrar un
  estado de error genérico reintentable, sin exponer URLs internas, detalles de tenant, trazas ni
  mensajes de infraestructura.

### Cliente anónimo y límites de seguridad

- THE SYSTEM SHALL construir el cliente con `createApiClient({ baseUrl: "" })` **sin**
  `getHeaders`, de modo que estructuralmente no pueda emitir `Authorization: Bearer`; NEVER SHALL
  crear, guardar ni refrescar un JWT o sesión para el huésped, y `baseUrl: ""` enruta por el proxy
  same-origin `app/api/[...path]`.
- THE SYSTEM SHALL consumir exclusivamente las cuatro rutas anónimas del portal y renderizar solo
  los campos publicados por los schemas de respuesta, ignorando cualquier campo adicional sin
  imponer validación runtime propia; cada sección de la página tiene su propio dato y estado, de
  modo que el fallo de una no derriba a las otras (salvo el gate de `info`).
- THE SYSTEM SHALL keyear las queries de TanStack por token solo como discriminante en memoria, no
  como sink renderizado.
- WHEN se regeneran los tipos frontend desde `backend/openapi.json`, THE SYSTEM SHALL mantener los
  tipos guest sincronizados con las respuestas nullable, enums, requests y códigos de error
  publicados.

### Reintentos

- THE SYSTEM SHALL aplicar la política de reintento compartida (`lib/api/retry-policy.ts`, la
  misma que consume `features/dashboard`): NEVER SHALL reintentar respuestas `4xx` (definitivas), y
  SHALL reintentar `5xx` y errores de red hasta dos veces. En particular NEVER SHALL reintentar
  `429` automáticamente, para no disparar `POST` de incidencia adicionales.

## Key files

- `frontend/app/(guest)/guest/[token]/page.tsx` — Server Component que resuelve `params.token` y
  renderiza `<GuestPortalView token={token} />`, conservando `generateMetadata → routeMetadata("guest")`.
- `frontend/features/guest-portal/data/{guest-portal-source.ts, dto.ts, index.ts, http/http-guest-portal-source.ts}`
  — interfaz `GuestPortalDataSource`, DTOs camelCase, punto de composición `getGuestPortalDataSource()`
  con cliente anónimo, e impl HTTP con mappers snake→camel y normalización de nullables.
- `frontend/features/guest-portal/hooks/{query-keys.ts, use-stay-info.ts, use-checkin.ts, use-report-incident.ts}`
  — `useQuery`/`useMutation` por sección, keys por token.
- `frontend/features/guest-portal/components/{guest-portal-view.tsx, fields/guest-fields.tsx}` —
  vista raíz con las secciones internas `StayInfoSection`/`CheckinSection`/`IncidentSection`, el
  campo accesible `GuestField` (`input`/`textarea`/`select`) y `fieldErrorsFrom422`.
- `frontend/features/guest-portal/index.ts` — export público (`GuestPortalView`).
- `frontend/lib/api/retry-policy.ts` — la `retryPolicy` compartida con `features/dashboard`.
- `frontend/lib/i18n/resources.ts`, `frontend/locales/{es,en}/guest.json` — namespace `guest` y
  catálogos ES/EN.
- `docs/guest-portal.md` — operación y diagnóstico del portal.
