# Proposal: expense-approval-response

## Why

`OwnerApproval(related_type=OTHER)` lo crea `CreateExpenseUseCase` en `revenue-statements` D4 cuando un
`Expense` cruza `TenantConfig.owner_approval_threshold_eur`. `revenue-statements.md` y la docstring de
`statements/application/reconciliation.py` decían que la propietaria respondía esa aprobación por
`POST /api/v1/owner-approvals/{id}/respond` — la ruta de `maintenance`. Medido falso al diseñar
`approvals-web` (D11, 2026-09-05): `RespondOwnerApprovalUseCase` carga la incidencia desde
`approval.related_id` sin condición y falla con `IncidentNotFoundError` (`404`) cuando no existe, y
para una aprobación `OTHER` ese `related_id` es un id de `Expense`, no de incidencia — la ruta no
puede servirla nunca. `approvals-web` corrigió la docstring y la spec de `revenue-statements`, pero
no arregló el hueco: ensanchar la ruta de respuesta (o abrir una propia) es de quien tome esta
entrada. Hoy la única salida para una `OwnerApproval(OTHER)` es el job
`reconcile_owner_approvals_for_expenses` (D4), que la **asume** respondida — si nadie la contesta
desde la API, queda pendiente para siempre.

## What changes

`POST /api/v1/owner-approvals/{id}/respond` queda habilitado para aprobaciones `related_type =
OTHER`, además de `INCIDENT` y `MAINTENANCE_COST` que ya sirve. La rama `OTHER` solo escribe la
respuesta sobre `OwnerApproval` (`status`, `responded_at`, `responded_by`, `response_notes`) y
lanza el `AuditLog OWNER_APPROVAL_ANSWERED`; **no** carga ni muta la incidencia, **no** dispara
timeline de incidencia, **no** dispara `PropertyStateMachine`, **no** notifica al técnico. La
materialización sobre `expenses` sigue siendo del job
`reconcile_owner_approvals_for_expenses` (latencia hasta 5 min, aceptada por D4 de
`revenue-statements`).

El permiso `RESPOND_OWNER_APPROVALS` y el rol `TENANT_OWNER` no cambian. La pantalla
`/approvals` (`approvals-web`) sigue ocultando los controles en filas `OTHER` hasta que un change
propio de FE habilite la fila respondible — fuera de alcance aquí.

## Requirements

### R1 — La ruta de respuesta sirve las aprobaciones `OTHER`

**As a** `TENANT_OWNER`, **I want** `POST /api/v1/owner-approvals/{id}/respond` sobre una
aprobación `related_type = OTHER`, **so that** la respuesta llegue a `expenses.approved_by`
(reconciliación materializa) sin esperar a un canal externo.

Acceptance criteria:

1. WHEN el `approval_id` del path resuelve a una `OwnerApproval` del tenant del token y su
   `related_type` es `OTHER` y su `status` es `PENDING`, THE SYSTEM SHALL escribir
   `status = APPROVED|REJECTED`, `responded_at = now`, `responded_by = actor.user_id`,
   `response_notes` (opcional) en la misma fila, en una sola transacción.
2. THE SYSTEM SHALL seguir exigiendo rol `TENANT_OWNER` y permiso `RESPOND_OWNER_APPROVALS` (R2.6
   de `maintenance`); una respuesta desde otro rol SHALL fallar con `MaintenanceValidationError`
   (`422`), no `403` — la autoridad sigue siendo `require()` en el router.
3. THE SYSTEM SHALL responder `404` con el mismo cuerpo constante si el `approval_id` no existe o
   pertenece a otro tenant — indistinguible del `404` que ya devuelve para `INCIDENT` /
   `MAINTENANCE_COST` (R2.6 de `maintenance`).
4. THE SYSTEM SHALL responder `409` (`OwnerApprovalAlreadyAnsweredError`) si la aprobación ya está
   respondida (`status != PENDING`), con el mismo cuerpo que para `INCIDENT` / `MAINTENANCE_COST`.
5. THE SYSTEM SHALL validar `response_notes` con la misma guarda `storable_text`
   (`MultiLineText`, `max_length=2000`) que ya protege la respuesta para `INCIDENT` /
   `MAINTENANCE_COST` — `RespondOwnerApprovalRequest` no se toca, `maintenance/api/schemas.py`
   R12 de `approvals-web` aplica.
6. THE SYSTEM SHALL responder `200` con un cuerpo reducido — `{approval_id, status,
   responded_at}` o equivalente — **no** con `IncidentResponse`. La rama `OTHER` no tiene
   incidencia que devolver, y devolver `IncidentResponse` obligaría a inventar un id de incidencia.

### R2 — La rama `OTHER` no toca la incidencia

**As a** sistema, **I want** la rama `OTHER` aislada del flujo de incidencias, **so that** un
fallo del flujo de mantenimiento no rompa la respuesta de un gasto.

Acceptance criteria:

1. THE SYSTEM SHALL NO cargar `incidents` por `approval.related_id` cuando `related_type = OTHER`:
   `RespondOwnerApprovalUseCase` resuelve la aprobación con `OwnerApprovalRepository.get(...)` y
   la guarda; si `related_type` es `OTHER` no llama a `IncidentRepository.get(...)`.
2. THE SYSTEM SHALL NO mutar el estado de una incidencia desde esta ruta (no `resume_after_approval`,
   no `cancel`, no `assign`, no `final_cost`): la aprobación `OTHER` referencia un `Expense`, no
   una `Incident`.
3. THE SYSTEM SHALL NO escribir `TimelineEvent` `OWNER_APPROVED_EXPENSE` / `OWNER_REJECTED_EXPENSE`
   para una aprobación `OTHER` — esos eventos viven sobre `Incident.timeline`, y para `OTHER` no
   hay fila de incidencia a la que atarlos. La materialización posterior del job de reconciliación
   deja `expenses.approved_by` (APPROVED) o borra la fila (REJECTED) sin escribir timeline
   tampoco.
4. THE SYSTEM SHALL NO disparar `PropertyStateMachine` desde esta ruta — el rechazo de una
   aprobación de gasto no cambia el estado operacional de la vivienda; sólo la materialización
   del job sobre `expenses.statement_id IS NOT NULL` lo haría, si llegara.

### R3 — Auditoría sigue siendo la misma acción, con la misma forma

Acceptance criteria:

1. THE SYSTEM SHALL escribir `AuditLog OWNER_APPROVAL_ANSWERED` con `ChangeSet` que difiere
   exactamente los **tres** campos ya auditados hoy (`status`, `responded_by`, `responded_at`)
   sobre la entidad `OWNER_APPROVAL` — los auditables siguen siendo los mismos que `maintenance` R9
   declara; no se introduce ningún audit log adicional para la rama `OTHER`.
2. THE SYSTEM SHALL no auditar `response_notes` (regla 11) — ya está fuera de
   `AUDITABLE_FIELDS["OWNER_APPROVAL"]` y SHALL seguir estándolo.
3. THE SYSTEM SHALL rechazar cualquier intento de auditar `reason` o `response_notes` en un
   `ChangeSet(OWNER_APPROVAL)` por la guarda estructural de `ChangeSet` (regla 11). Esa guarda ya
   existe — este cambio no la toca.

### R4 — El job de reconciliación queda intacto

Acceptance criteria:

1. THE SYSTEM SHALL no modificar `ReconcileOwnerApprovalsForExpensesUseCase` ni su adaptador
   SQL — la materialización de la respuesta sobre `expenses` ya funciona para cualquier fila
   `OwnerApproval(OTHER)` cuyo `status` sea `APPROVED` o `REJECTED`, y la única diferencia entre
   "respondida por esta ruta" y "respondida por un canal externo" es la identidad del llamante en
   `AuditLog`.
2. THE SYSTEM SHALL no introducir una nueva tarea Celery, ni un nuevo `CADENCES`, ni un nuevo
   cron — la latencia de hasta 5 minutos que `revenue-statements` R5.7 declara se mantiene, y
   este change la deja inalterada.

### R5 — Aislamiento por tenant y permisos, sin cambios

Acceptance criteria:

1. THE SYSTEM SHALL leer `tenant_id` únicamente del token verificado, pasarlo explícito al
   `OwnerApprovalRepository.get(...)`, y SHALL responder `404` con cuerpo constante si la
   aprobación no pertenece al tenant del token — el mismo `404` que ya devuelve para `INCIDENT`.
2. THE SYSTEM SHALL no introducir un permiso nuevo: `RESPOND_OWNER_APPROVALS` cubre ambas ramas;
   `ROLE_PERMISSIONS` no se toca (R8 de `maintenance`).
3. THE SYSTEM SHALL no exponer `related_id` de la aprobación en la respuesta del endpoint —
   el cuerpo reducido de R1.6 sólo lleva `approval_id`, `status`, `responded_at`, `property_id`
   (id de la vivienda afectada, ya presente en la fila `OwnerApproval`), `amount` (constante de
   la aprobación), `currency` (`EUR`, constante de `OWNER_APPROVAL_CURRENCY`). Una pantalla que
   quiera resolver el `Expense` lo hará con `GET /api/v1/expenses/{id}` por `pending_owner_approval_id`
   cuando el campo esté disponible (D13 de `revenue-statements`).

### R6 — `IncidentResponse` no se devuelve; el contrato HTTP se ajusta

Acceptance criteria:

1. THE SYSTEM SHALL devolver `200` con `OwnerApprovalResponse` (DTO nuevo en
   `maintenance/api/schemas.py`) cuando la respuesta se aplica a una aprobación `OTHER`; cuando
   se aplica a `INCIDENT` o `MAINTENANCE_COST`, SHALL seguir devolviendo `IncidentResponse`
   intacto — esa rama no cambia.
2. THE SYSTEM SHALL registrar `OwnerApprovalResponse` en `OpenAPIContract` (regla de
   `api-contract.md`): cualquier cuerpo de respuesta nuevo aparece en `backend/openapi.json` y en
   `frontend/lib/api/generated/openapi.d.ts` en el mismo PR.

### R7 — La lista de aprobaciones ya muestra las `OTHER`

Acceptance criteria:

1. THE SYSTEM SHALL NO ensanchar el `GET /api/v1/owner-approvals` (R1.1 de `approvals-web` ya
   las lista con la nota genérica y `incident = None`). El listado no se toca.
2. THE SYSTEM SHALL NO añadir un nuevo parámetro de filtro — `status`, `page`, `per_page` siguen
   siendo el contrato.

## Out of scope

- **Pantalla `/approvals` mostrando los controles de decisión sobre filas `OTHER`** — eso es
  frontend; `approvals-web` R4 dice que **nunca** los muestra. Habilitarlo requiere un change
  propio que toque `use-respond-approval.ts`, `approvals-view.tsx`, `error-mapping.ts` y los dos
  catálogos `locales/{es,en}/approvals.json`. Apuntado a un candidato de roadmap ad-hoc, no en
  este change.
- **Notificar al manager del tenant cuando se responde una aprobación `OTHER`** — la actualiza
  del estado del `Expense` se ve en el listado de gastos; el manager que quiera enterarse ya
  tiene `GET /api/v1/expenses` con el campo `pending_owner_approval_id` que se vacía cuando la
  reconciliación corre (D13 de `revenue-statements`).
- **Rechazo del `Expense` sin pasar por aprobación** — la materialización del job borra la fila
  de `expenses` cuando `status = REJECTED`, pero eso es comportamiento del job, no de la ruta
  nueva; ya está en `revenue-statements` D4.
- **Apertura de una ruta propia bajo `statements`** — la decisión de dónde cuelga la ruta es
  del diseño (D1). El diseño concluirá si se ensancha la ruta existente o se abre una nueva.
- **`OwnerApprovalStatus.EXPIRED`** — sigue sin escritor; sin cambios (deuda documentada de
  `maintenance`).
- **Cifrado en reposo de `response_notes`** — pendiente del change
  `plaintext-sink-encryption-at-rest` (roadmap), sin cambios aquí.

## Affected specs

- `sdd/specs/maintenance.md` — R4 (párrafo final, hoy dice "seguid respondiendo 404 a
  `POST /owner-approvals/{id}/respond` para una de ellas") se sustituye por la afirmación de
  que la ruta **sí** sirve las `OTHER`, con R1-R7 detallados. R8 (párrafo de exposición de la
  ruta de respuesta, la 404 actual) se sustituye por la forma "responde `OwnerApprovalResponse`
  para `OTHER`, `IncidentResponse` para las demás".
- `sdd/specs/revenue-statements.md` — el párrafo de "Permisos, aislamiento, auditoría" (la
  corrección de `approvals-web` D11) que hoy dice "hoy no hay ninguna ruta que responda una
  `OwnerApproval(OTHER)`" se sustituye por la afirmación de que `POST /owner-approvals/{id}/respond`
  sí la sirve, con el límite de que la materialización sobre `expenses` la hace el job de
  reconciliación.
- `sdd/specs/approvals-web.md` — el R4 (que dice "NEVER SHALL ofrecer los controles de decisión
  en una fila `relatedType = OTHER`") no se toca en este change: la pantalla sigue ocultándolos
  hasta que un change propio de FE los habilite. La corrección de la limitación de backend se
  documentará aquí como nota para el change de FE.
- `docs/maintenance.md` y `docs/revenue-statements.md` — actualizados en el archivado para
  reflejar la ruta sirviendo las `OTHER` y la nota sobre `/approvals` ocultando los controles.
- `backend/app/maintenance/api/schemas.py` — añadido `OwnerApprovalResponse` (DTO nuevo) y
  registrada en `OwnerApprovalResponse.__init__` con los campos de R1.6 y R5.3.
- `backend/app/maintenance/application/use_cases.py` — `RespondOwnerApprovalUseCase.execute()`
  ampliado: branch sobre `approval.related_type` antes de tocar incidentes (R2.1); resto del
  flujo igual.
- `backend/app/maintenance/api/approvals_router.py` — `respond_owner_approval` elige el
  `response_model` en función de `related_type` (`OwnerApprovalResponse` para `OTHER`,
  `IncidentResponse` para las demás). La firma del endpoint no cambia: misma ruta, mismo método,
  mismo cuerpo de petición, misma respuesta HTTP `200`.
- `backend/app/maintenance/domain/entities.py` — `OwnerApproval` no se toca.
- `backend/app/maintenance/domain/repositories.py` — `OwnerApprovalRepository` no se toca (el
  `get(tenant_id, approval_id)` ya cubre el caso).
- `backend/tests/maintenance/test_use_cases.py` y `backend/tests/maintenance/test_api.py` (o
  donde vivan los tests de `RespondOwnerApprovalUseCase` hoy) — tests para la rama `OTHER`
  (R1.1, R1.3, R1.4, R1.6, R2.1, R2.2, R2.3, R3.1, R5.1).
- `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts` — regenerados en el mismo
  PR (R6.2, `api-contract.md`).