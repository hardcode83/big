# Cola de aprobaciones (`/approvals`)

## Purpose

`/approvals` es la pantalla de la workspace donde la propietaria responde los gastos que superan
el umbral de su tenant y el manager consulta en qué punto está cada uno. Sustituye el
`RoutePlaceholder` que tenía antes: hasta esta capability la única pista de una aprobación
pendiente era el bloque sin botón del detalle de propiedad, y responder exigía conocer el id de la
aprobación. Cierra el callejón sin salida que dejaba al técnico bloqueado en
`AWAITING_OWNER_APPROVAL` sin que nadie con permiso para desatascarlo tuviera dónde hacerlo.

## Requirements

### R1 — Quién ve la pantalla y qué consulta

- THE SYSTEM SHALL mostrar `/approvals` a quien tenga el permiso `READ_OWNER_APPROVALS`:
  `TENANT_OWNER` y `PROPERTY_MANAGER`, y a nadie más.
- THE SYSTEM SHALL consultar `GET /api/v1/owner-approvals` sin filtro de estado para la cola
  pendiente (el `PENDING` por defecto del backend, ordenado por antigüedad), y dos consultas
  paralelas más —`status=APPROVED` y `status=REJECTED`, `per_page=5` cada una— para el histórico,
  fusionadas y reordenadas por `respondedAt` descendente y recortadas a cinco. Dos peticiones y no
  una porque el filtro `status` del backend admite un único valor
  (`frontend/features/approvals/hooks/use-approvals.ts`, mismo patrón que `useIncidentContexts`).
- WHILE cualquiera de las dos cargas o falla, THE SYSTEM SHALL usar los mismos estados de carga,
  vacío y error —con reintento— que ya usa `incidents-view.tsx`, sin inventar una forma nueva.

### R2 — La cola pendiente

- WHEN la pantalla carga con aprobaciones pendientes, THE SYSTEM SHALL pintar una fila por
  aprobación con: el nombre de la propiedad y su código interno (nunca el UUID), la categoría,
  severidad y título de la incidencia traducidos —o, si `relatedType` es `OTHER`, una nota
  genérica en su lugar—, el importe con su moneda, y cuánto lleva esperando en forma relativa
  (`waitingSince`, derivada de `requestedAt`).
- WHEN no hay ninguna pendiente, THE SYSTEM SHALL mostrar el estado vacío del sistema de diseño
  (`states:empty.*`), nunca una tabla sin filas.
- THE SYSTEM SHALL escribir toda cadena de esta pantalla en `locales/es/approvals.json` **y**
  `locales/en/approvals.json`, sin literales en el componente.
- THE SYSTEM NEVER SHALL pintar un UUID crudo en ninguna fila.

### R3 — El histórico corto

- THE SYSTEM SHALL mostrar, bajo la cola, un histórico con las últimas cinco aprobaciones
  respondidas (`APPROVED` o `REJECTED`), cada una con el resultado traducido, la propiedad, la
  incidencia (o la nota `OTHER`), el importe y la fecha de respuesta.
- WHEN el histórico está vacío, THE SYSTEM SHALL mostrar su propio texto vacío
  (`approvals:history.empty`), distinto del de la cola.

### R4 — La decisión de la propietaria

- WHERE quien mira la pantalla tiene `RESPOND_OWNER_APPROVALS` (sólo `TENANT_OWNER` —
  `frontend/lib/auth/permissions.ts`, D10), THE SYSTEM SHALL ofrecer en cada fila pendiente y **no
  `OTHER`** un campo de motivo opcional y los botones de aprobar/rechazar. La comprobación de
  permiso en el cliente es una ayuda de UX: la autoridad real es el `403` del backend.
- WHERE quien mira la pantalla es `PROPERTY_MANAGER`, THE SYSTEM SHALL mostrar la cola **sin**
  esos controles.
- WHEN se envía una decisión, THE SYSTEM SHALL invocar
  `POST /api/v1/owner-approvals/{id}/respond` con el `response_notes` tal cual lo escribió la
  persona (cadena vacía o ausente se envía como `undefined`, nunca `""`), y SHALL invalidar el
  prefijo de consulta de aprobaciones al terminar — con éxito o con `409` —, de modo que la cola y
  el histórico se refrescan solos (`useRespondOwnerApproval`).
- IF la respuesta es `409` (`OwnerApprovalAlreadyAnsweredError`), THEN THE SYSTEM SHALL mostrar el
  aviso traducido «ya respondida» junto a esa fila y refrescar la cola, en vez de dejar en pantalla
  una fila que ya no existe.
- THE SYSTEM SHALL mostrar, junto a los botones de cada fila respondible, el aviso de que
  rechazar **cancela la incidencia** y no es reversible desde esta pantalla — en la propia
  interfaz, no sólo en un diálogo de confirmación.
- THE SYSTEM NEVER SHALL ofrecer los controles de decisión en una fila `relatedType = OTHER`: se
  pinta con la nota genérica y ninguna acción, porque la ruta de respuesta 404 para ese tipo
  ([`maintenance.md`](maintenance.md) — `OwnerApprovalRelatedType.OTHER` no puede responderse por
  esta ruta).

### R5 — El enlace desde el detalle de propiedad

- THE SYSTEM SHALL mostrar, bajo el bloque de aprobaciones del detalle de propiedad
  (`property-detail-sections.tsx`), un enlace constante a `/approvals` — nunca a una aprobación
  concreta, así que ningún id cruza a la URL. `OwnerApprovalSummary` y el resto del contrato de
  ese bloque permanecen sin tocar.

## Key files

- `frontend/app/(workspace)/approvals/page.tsx` — la ruta; monta `ApprovalsView` en vez del
  `RoutePlaceholder` anterior. Registrada en `route-coverage.test.ts` como
  `"(workspace)/approvals/page.tsx": "approvals"`.
- `frontend/features/approvals/components/approvals-view.tsx` — la vista: cola, histórico,
  formulario de decisión.
- `frontend/features/approvals/hooks/use-approvals.ts` — `useApprovals` (cola) y
  `useApprovalsHistory` (histórico de cinco, fusionado).
- `frontend/features/approvals/hooks/use-respond-approval.ts` — `useRespondOwnerApproval`, la
  mutación de decisión y su invalidación de caché.
- `frontend/features/approvals/lib/error-mapping.ts` — mapea `401/403/404/409/422/5xx` a los
  estados de la vista, incluido `already-answered` para el `409`.
- `frontend/features/approvals/lib/waiting-since.ts` — el «lleva esperando» relativo de R2.
- `frontend/features/approvals/data/dto.ts`, `data/http/http-approvals-source.ts` — el DTO y el
  cliente HTTP contra `GET /api/v1/owner-approvals` y `POST /owner-approvals/{id}/respond`.
- `frontend/lib/auth/permissions.ts` — `RESPOND_OWNER_APPROVALS`, concedido sólo a
  `TENANT_OWNER`.
- `frontend/locales/{es,en}/approvals.json` — el namespace `approvals` completo en los dos
  idiomas.
- `frontend/features/dashboard/components/detail/property-detail-sections.tsx` — el enlace de R5.
- Backend: [`maintenance.md`](maintenance.md) R4 y R8 — la ruta de lista, la resolución de
  propiedad/incidencia y la notificación al técnico que esta pantalla consume y dispara.
- [`notifications-inbox-web.md`](notifications-inbox-web.md) — a dónde lleva la campana cuando
  llega `OWNER_APPROVAL_REQUIRED` (a esta pantalla) o una notificación de resultado al técnico (a
  `/tech/incidents/{id}`).
