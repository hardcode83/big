# Design: expense-approval-response

## Context

`backend/app/maintenance/application/use_cases.py` expone
`RespondOwnerApprovalUseCase.execute(...)` (`backend/app/maintenance/application/use_cases.py:1652`),
que carga `OwnerApproval` por `OwnerApprovalRepository.get(...)`, lo carga de nuevo como `Incident`
por `approval.related_id` con `IncidentRepository.get(...)`, muta la incidencia y la salva
(`backend/app/maintenance/application/use_cases.py:1699-1725`), escribe `OWNER_APPROVAL_ANSWERED` en
`AuditLog` y un `TimelineEvent` (`OWNER_APPROVED_EXPENSE` / `OWNER_REJECTED_EXPENSE`) sobre
`Incident.timeline`. La ruta `POST /api/v1/owner-approvals/{id}/respond` está en
`backend/app/maintenance/api/approvals_router.py:82` y declara `response_model=IncidentResponse`.

El problema: para `related_type = OTHER` (`OwnerApprovalRelatedType.OTHER`), `approval.related_id`
es un id de `Expense` (`statements`); `IncidentRepository.get(...)` resuelve `None`, el caso de uso
levanta `IncidentNotFoundError` y la API responde `404`. Por construcción, esa aprobación es
**nunca** respondible desde la API; sólo el job `reconcile_owner_approvals_for_expenses` puede
materializar un `status` distinto de `PENDING` — y ese job **no** actualiza
`owner_approvals.status`: lee `responded_at IS NOT NULL`, no escribe nada en
`owner_approvals` (`backend/app/statements/infrastructure/reconciliation.py:55-100`,
`backend/app/statements/application/reconciliation.py:99-243`). Resultado: una aprobación `OTHER`
queda pendiente para siempre salvo que la respuesta llegue por un canal externo que no existe.

`maintenance` mantiene su `OwnerApprovalRepository` (`backend/app/maintenance/domain/repositories.py:365-400`)
con `get` / `add` / `save` / `find_approved_for_incident`; `statements` lo consume a través del
adaptador SQLAlchemy (`backend/app/statements/infrastructure/repositories.py:417-440`). El módulo
`statements` no tiene su propio repositorio de aprobaciones — la propiedad del agregado raíz
`OwnerApproval` está en `maintenance`, y abrir un segundo repositorio duplicaría
`AUDITABLE_FIELDS["OWNER_APPROVAL"]` y la guarda `storable_text` sobre `response_notes`.

## Decisions

### D1 — Ensanchar `POST /api/v1/owner-approvals/{id}/respond`, no abrir una segunda ruta

**Chosen:** ampliar el caso de uso y la ruta existente, que ya cargan
`OwnerApproval` por su repositorio canónico. La rama `OTHER` salta la carga de la
incidencia, el guardado, el `TimelineEvent`, el `PropertyStateMachine` y la notificación
al técnico. La materialización sobre `Expense` la sigue haciendo
`ReconcileOwnerApprovalsForExpensesUseCase` — que ya cubre cualquier `status` en
`owner_approvals` sin importar quién lo escribió.

Rejected: **abrir `POST /api/v1/owner-approvals/{id}/respond-expense`** en `maintenance` o
`statements` — duplicaría la ruta, la dependencia `require()` y el mapping de errores
(`RespondOwnerApprovalRequest` ya existe; R1.5 obliga a validarlo igual); además, la nueva
ruta tendría que devolver un DTO nuevo y dividiría el permiso `RESPOND_OWNER_APPROVALS` por
ruta, lo que el principio de mínimo privilegio no pide.

Rejected: **abrir la ruta nueva en `statements`** — `statements` no es dueño del agregado
raíz `OwnerApproval`. Hacerlo obligaría a reescribir `AUDITABLE_FIELDS["OWNER_APPROVAL"]` y
el cálculo de `reason`/`response_notes` (regla 11), y el `OwnerApprovalRepository` actual
queda acoplado a `maintenance.application` (`RespondOwnerApprovalUseCase` ya lo usa); abrir
una segunda ruta en otro módulo duplicaría superficie sin simplificar nada.

### D2 — Cargar la aprobación **antes** que la incidencia

**Chosen:** `RespondOwnerApprovalUseCase.execute(...)` lee
`self._approvals.get(tenant_id, approval_id)`, valida que existe y luego **mira
`approval.related_type`**: si es `OTHER`, sólo escribe la respuesta y el `AuditLog`; si es
`INCIDENT` o `MAINTENANCE_COST`, sigue el flujo actual (carga la incidencia, muta, salva,
timeline, `PropertyStateMachine`, notificación).

Rejected: **cargar la aprobación y la incidencia en paralelo** — la rama `OTHER` no necesita
la incidencia, y cargar dos filas en paralelo para descartarla sería una lectura desperdiciada
por cada `OTHER` respondido; el camino `INCIDENT`/`MAINTENANCE_COST` ya hace una lectura
extra si la aprobación no existe (`_approvals.get` antes de `_incidents.get`).

Rejected: **ramificar por `related_type` antes de cargar la aprobación** — el caso de uso
necesita el `related_type` para ramificar, y ese campo vive en `OwnerApproval`. No hay
manera de ramificar sin leer antes la fila.

### D4 — `AuditLog` usa la misma acción, con la misma forma

**Chosen:** escribir `OWNER_APPROVAL_ANSWERED` (acción ya registrada en
`backend/app/audit/domain/actions.py:344`) con el mismo `ChangeSet` que ya se usa:
`status`, `responded_by`, `responded_at` — los tres campos auditables hoy
(`backend/app/audit/domain/value_objects.py:385`). `response_notes` y `reason` siguen
fuera del `ChangeSet` y la guarda estructural del `ChangeSet` (`redacted()` /
`diff()` rechaza campos fuera de `AUDITABLE_FIELDS`) ya impide nombrarlos.

Rejected: **añadir `OWNER_APPROVAL_EXPENSE_ANSWERED` como acción nueva** —
`AUDITABLE_FIELDS["OWNER_APPROVAL"]` es un set, no un set por `related_type`; cualquier
nueva acción tendría que reescribir la guarda o duplicarla, y los tres campos que se
auditan son los mismos. El cambio no aporta información útil para auditoría.

### D5 — Respuesta HTTP: `Union` de los dos DTOs, mismo `200`

**Chosen:** la ruta declara `response_model=Union[IncidentResponse, OwnerApprovalResponse]`.
FastAPI serializa la respuesta a través del `Union` y el cliente TypeScript recibe un
`oneOf` con ambos cuerpos documentados. Para la rama `INCIDENT`/`MAINTENANCE_COST`,
la respuesta sigue siendo `IncidentResponse`; para la rama `OTHER`, `OwnerApprovalResponse`.
El handler elige el DTO en función de `related_type` y devuelve uno u otro con
`status_code=200`. La documentación OpenAPI declara ambos como un `oneOf`.

Rejected: **`response_model=OwnerApprovalResponse` con el otro cuerpo vía
`responses={200: {"model": IncidentResponse, ...}}`** — era la primera idea y el
diseño original la nombró como la forma preferida. **No funciona**: FastAPI valida
el payload runtime contra `response_model=`, no contra los `responses=`, y un
`IncidentResponse` no satisface `OwnerApprovalResponse` (le faltan
`approval_id`/`amount`/`currency`, y `status` es de tipo distinto). El test 4.6 de
Sección 4 cazó la regresión — la rama `INCIDENT` quedó inalcanzable por HTTP. La
solución correcta es `Union` (la presente aquí), no `response_model=` con un cuerpo
único.

Rejected: **`response_model=None` y ambos cuerpos vía `responses={}`** — desactiva la
validación pero deja el `oneOf` mal documentado en OpenAPI (no se genera un esquema
para el `200` por defecto, sólo se documenta el alternativo). Pierde la coherencia
con el resto del módulo, donde cada ruta declara un `response_model` aunque su
esquema sea trivial.

Rejected: **devolver `IncidentResponse` siempre, con la incidencia del
`related_id` poblada por la materialización del job** — el job corre cada 5 minutos
(`revenue-statements` R5.7) y devolver un id de `Expense` como si fuera un id de
`Incident` mentiría sobre el resultado de la petición. La pantalla del cliente no sabe
qué hacer con eso sin un discriminador explícito.

### D6 — DTO `OwnerApprovalResponse` con seis campos

**Chosen:** `approval_id`, `status`, `responded_at`, `property_id`, `amount`, `currency`
(constante `"EUR"`). Los nombres siguen literalmente la lista de R5.3 de la propuesta
(`approval_id, status, responded_at, property_id, amount, currency`): se llama
`approval_id` y no `id` para que la pantalla cliente distinga este id del id de
incidencia que ya devuelve `IncidentResponse` en la rama `INCIDENT` /
`MAINTENANCE_COST`. `currency` se incluye por simetría con
`OwnerApprovalListItemResponse`, aunque la constante de hoy es única
(`OWNER_APPROVAL_CURRENCY = "EUR"`, `backend/app/maintenance/domain/read_models.py`);
si un día cambia, este campo ya está preparado. `related_type` se omite — la pantalla
que sepa distinguir `OTHER` no consume este endpoint (`approvals-web` R4 dice que
oculta los controles en `OTHER`); un cliente que llame a este endpoint para una `OTHER`
recibe un `200` y la pantalla que sea, decide.

Rejected: **devolver `OwnerApprovalListItemResponse`** — incluiría `requested_at` y el
`OwnerApprovalPropertyRefResponse` con `name` + `internal_code`, que son nombres
resueltos por `ListOwnerApprovalsUseCase` y no los tenemos aquí sin una segunda consulta a
`PropertyRepository.list_for_ids` (R1.3 de `approvals-web`). Para una respuesta inmediata,
devolver sólo el id de la vivienda es suficiente.

### D7 — El job de reconciliación no se toca

**Chosen:** `ReconcileOwnerApprovalsForExpensesUseCase` y
`SqlAlchemyReconciliationStore` quedan intactos. La única diferencia entre "respondida
desde esta ruta" y "respondida por un canal externo" es la identidad del actor en
`AuditLog` (el `user_id` del `TENANT_OWNER`); el job lee `owner_approvals.status` y
materializa, sin preguntar cómo se escribió.

Rejected: **añadir un trigger inmediato en la ruta para correr la reconciliación** —
`revenue-statements` D4 ya documenta la latencia de hasta 5 minutos como comportamiento
aceptado; un trigger inmediato acoplaría `maintenance.api` a `statements.application` y
rompería el principio de agregado raíz.

### D8 — Aislamiento por tenant, sin cambios

**Chosen:** `OwnerApprovalRepository.get(tenant_id, approval_id)` ya devuelve `None`
fuera del tenant (`backend/app/maintenance/domain/repositories.py:374-379`); el caso de uso
lo trata como `OwnerApprovalNotFoundError` (`404`) con el mismo cuerpo que para
`INCIDENT`/`MAINTENANCE_COST`. La regla 1 de `steering/security.md` se sostiene por la
firma del método.

Rejected: **añadir `repository.get_with_related_type(...)` que filtrara por
`related_type`** — el filtro por `related_type` es estructural en el caso de uso (rama de
control), no de SQL; meterlo al repositorio cambiaría la semántica del `get` actual para
todos sus llamantes (`ListOwnerApprovalsUseCase`, el panel, etc.).

### D9 — `IncidentResponse` no se devuelve en la rama `OTHER`

**Chosen:** el handler elige el `response_model` por `related_type`: `IncidentResponse`
para las dos ramas existentes; `OwnerApprovalResponse` para la rama `OTHER`. La
documentación OpenAPI registra ambos como posibles respuestas `200`.

Rejected: **devolver siempre `IncidentResponse`, con un id sintético** — un id sintético
no existe en la base de datos y obligaría al cliente a no fiarse del campo, lo que
rompe la invariante "el id que devuelve el POST es una fila real".

### D10 — Sin tocar `OwnerApprovalRepository`

**Chosen:** el repositorio no se ensancha: `get(tenant_id, approval_id)` ya devuelve la
aprobación con su `related_type`, y `save(tenant_id, approval)` ya persiste la
mutación. No hace falta un método específico para `OTHER`.

Rejected: **añadir `OwnerApprovalRepository.get_for_other(...)` o un wrapper** —
sería un método que sólo existe para una rama de un único caso de uso; el principio
de segregación de interfaces (`steering/backend-architecture.md`) lo prohíbe.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Domain entity | `backend/app/maintenance/domain/entities.py` | sin cambios — `OwnerApproval.answer()` ya cubre la rama `OTHER` |
| Domain repository | `backend/app/maintenance/domain/repositories.py` | sin cambios — `get`/`save` ya cubren la rama |
| Application | `backend/app/maintenance/application/use_cases.py` | `RespondOwnerApprovalUseCase.execute(...)` ramifica por `related_type`: la rama `OTHER` omite `IncidentRepository.get`, la mutación de la incidencia, el `TimelineEvent`, `PropertyStateMachine` y la notificación al técnico. Audit log idéntico. |
| API schemas | `backend/app/maintenance/api/schemas.py` | nueva clase `OwnerApprovalResponse` (seis campos: `approval_id`, `status`, `responded_at`, `property_id`, `amount`, `currency`); `RespondOwnerApprovalRequest` sin cambios |
| API router | `backend/app/maintenance/api/approvals_router.py` | `respond_owner_approval` elige `response_model` por `related_type` (`IncidentResponse` para `INCIDENT`/`MAINTENANCE_COST`, `OwnerApprovalResponse` para `OTHER`); `status_code` y ruta sin cambios |
| Errors | `backend/app/maintenance/api/errors.py` | sin cambios — los códigos `404`/`409`/`422`/`403` ya están mapeados |
| Scheduler | `backend/app/scheduler/tasks.py`, `backend/app/scheduler/schedule.py` | sin cambios — el job de reconciliación sigue intacto |
| Statements | `backend/app/statements/**` | sin cambios — `ReconcileOwnerApprovalsForExpensesUseCase` intacto |
| OpenAPI | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados en el mismo PR (`api-contract.md` R6.2) |
| Tests | `backend/tests/maintenance/test_use_cases.py` | añadir tests para la rama `OTHER`: respond con `APPROVED` y `REJECTED`, idempotencia (segunda llamada = `409`), tenant cruzado = `404`, rol no-`TENANT_OWNER` = `422`, no mutación de incidente, no `TimelineEvent`, no `PropertyStateMachine` |
| Tests | `backend/tests/maintenance/test_api.py` (o donde esté hoy el test de `POST /owner-approvals/{id}/respond`) | añadir tests de integración HTTP: la ruta devuelve `200` con `OwnerApprovalResponse` para `OTHER`; el `AuditLog` `OWNER_APPROVAL_ANSWERED` se escribe; la reconciliación (en el siguiente tick del job en CI, vía `ReconcileOwnerApprovalsForExpensesUseCase.execute`) materializa `expenses.approved_by` |
| Docs | `docs/maintenance.md` | sección sobre `/owner-approvals/{id}/respond` actualizada para indicar que también sirve `OTHER`; el bloque "la ruta resuelve por incidencia" se sustituye por "depende de `related_type`" |
| Docs | `docs/revenue-statements.md` | sección "Permisos, aislamiento, auditoría" actualizada para indicar que `POST /owner-approvals/{id}/respond` sí sirve las `OTHER` y que la materialización sigue siendo del reconciliador |
| Spec | `sdd/specs/maintenance.md` | sustituido el párrafo final de R4 ("`OwnerApprovalRelatedType.OTHER` no puede responderse por esta ruta", hoy cerrado por el bug medido) por la afirmación de que la ruta sí la sirve; R8 (párrafo de exposición de la ruta de respuesta, la 404 actual) sustituido por la forma "responde `OwnerApprovalResponse` para `OTHER`, `IncidentResponse` para las demás" |
| Spec | `sdd/specs/revenue-statements.md` | el párrafo "Permisos, aislamiento, auditoría" (corrección de `approvals-web` D11) que hoy dice "hoy no hay ninguna ruta que responda una `OwnerApproval(OTHER)`" se sustituye por la afirmación de que `POST /owner-approvals/{id}/respond` sí la sirve, con el límite de que la materialización sobre `expenses` la hace el job de reconciliación |
| Spec | `sdd/specs/approvals-web.md` | sólo nota explicativa: el cambio de backend queda invisible hasta que un change de FE habilite los controles de decisión en filas `OTHER` (R4 sigue diciendo "NEVER SHALL ofrecer los controles de decisión en una fila `relatedType = OTHER`", intacto) |

## Data & interfaces

- **Esquema SQL**: sin cambios. `owner_approvals.related_type = OTHER`, `related_id` apuntando
  a `expenses.id`, ya está en `backend/alembic/versions/96d526599bc1_domain_foundation_financial.py:102`.
  `OwnerApproval.answer()` ya cubre la rama `OTHER`.
- **Contrato HTTP**: `POST /api/v1/owner-approvals/{id}/respond` declara **dos** respuestas
  `200` posibles (`IncidentResponse` o `OwnerApprovalResponse`) vía `responses={...}`. El
  cuerpo de petición (`RespondOwnerApprovalRequest`) no cambia. Códigos de error:
  - `401 UNAUTHENTICATED`: token ausente (existente).
  - `403 FORBIDDEN`: rol sin `RESPOND_OWNER_APPROVALS` (existente).
  - `404 NOT_FOUND`: aprobación inexistente, de otro tenant, o `related_type != OTHER` cuando el
    cliente esperaba esa rama — **mismo cuerpo constante** en los tres casos (R1.3, R2.6 de
    `maintenance`).
  - `409 CONFLICT`: aprobación ya respondida (existente).
  - `422 VALIDATION_ERROR`: rol no-`TENANT_OWNER` o `response_notes` con `U+0000` o > 2000
    caracteres (existente).
- **Eventos**: `AuditLog OWNER_APPROVAL_ANSWERED` se escribe en ambas ramas; `TimelineEvent`
  `OWNER_APPROVED_EXPENSE` / `OWNER_REJECTED_EXPENSE` **sólo** en la rama `INCIDENT` /
  `MAINTENANCE_COST`. No hay eventos nuevos.
- **Config / env vars**: ninguna nueva.
- **OpenAPI**: `OwnerApprovalResponse` registrado en `maintenance.api.schemas.OwnerApprovalResponse`;
  la regeneración del contrato lo lleva a `backend/openapi.json` y a
  `frontend/lib/api/generated/openapi.d.ts` en el mismo PR.

## Risks & mitigations

- **Regresión silenciosa de `RespondOwnerApprovalUseCase` en `INCIDENT`** — la rama existente
  se modifica (la carga de la incidencia ahora es condicional). Mitigación: los tests
  existentes de `INCIDENT`/`MAINTENANCE_COST` siguen siendo el contrato; los nuevos tests
  para `OTHER` se añaden al lado; `mark-recertified` exige que la suite pase entera. El
  coverage de la rama `OTHER` es lo que protege la rama `INCIDENT` (cambiar el flujo
  compartido rompe ambas suites).
- **El frontend `/approvals` sigue ocultando controles en `OTHER`** — la pantalla
  `approvals-web` R4 dice "NEVER SHALL ofrecer los controles de decisión en una fila
  `relatedType = OTHER`". El cambio de backend queda **invisible** hasta que un change propio
  de FE habilite los controles en esa fila. Mitigación: se documenta en
  `sdd/specs/approvals-web.md` como candidato para un change ad-hoc; el PR del backend deja
  un `assumed` o un comentario visible en la descripción, dependiendo del criterio del
  archivador.
- **Latencia de hasta 5 minutos entre la respuesta y la materialización en `expenses`** —
  comportamiento aceptado por `revenue-statements` R5.7 (D4); este change no la cambia.
  Mitigación: los tests que cubran la materialización pueden inyectar la corrida del job
  manualmente — el job ya expone un endpoint programable
  (`ReconcileOwnerApprovalsForExpensesUseCase.execute(now=...)`).
- **Duplicación del manejo de errores** — la rama `OTHER` no introduce nuevos códigos; los
  códigos `404`/`409`/`422`/`403` ya están mapeados en
  `backend/app/maintenance/api/errors.py`. Mitigación: tests unitarios por código,
  manteniendo `_MAPPING` exhaustivo.
- **Documentación desactualizada** — `sdd/specs/revenue-statements.md` y `docs/maintenance.md`
  tienen frases que decían "no hay ruta para responder un `OTHER`"; tras el archivado de
  este change se sustituyen. Mitigación: el archivado (`/sdd:archive`) actualiza ambas
  frases en el mismo PR, y `sdd:doctor` no las vuelve a marcar como desactualizadas.

## Open questions

- (Asumida) **Asumida** — `response_notes` se queda con la misma guarda `storable_text`
  (`MultiLineText`, `max_length=2000`) que ya usa la rama `INCIDENT`. No se relaja ni se
  endurece. **Asumida por simetría con R2.6 de `maintenance` y con D12 de `approvals-web`**;
  un cambio de contrato aquí sería un change propio.
- (Asumida) **Asumida** — el DTO `OwnerApprovalResponse` no incluye
  `pending_owner_approval_id` (no tiene sentido: la respuesta ya **es** sobre esa
  aprobación) ni `Expense`-related fields (un GET posterior a `/api/v1/expenses/{id}` ya
  los resuelve). **Asumida por la spec D13 de `revenue-statements`**; añadir campos aquí
  sería duplicar el trabajo de la ruta de gastos.
- (Asumida) **Asumida** — la respuesta del endpoint en la rama `OTHER` no escribe
  `TimelineEvent` alguno, ni de incidente (no hay incidente) ni de gasto (no hay
  `Expense`-timeline). La materialización del job tampoco escribe timeline — es una
  decisión de D4, no de este change. **Asumida por la decisión explícita de `revenue-statements`
  de no abrir timeline de gastos**; si un día se quiere uno, es un change aparte.