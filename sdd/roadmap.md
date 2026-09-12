# Roadmap

Categorías:
[FE] Frontend / UX
[BE] Backend / Dominio
[INFRA] Infraestructura, CI/CD y despliegue
[TECH] Deuda técnica, upgrades, refactors y mantenimiento
[CROSS] Cambios transversales

<!-- ÍNDICE ordenado de changes, agrupando los 28 pasos del PRD §26 por módulo:
     una línea por entrada + su sub-línea de metadatos. Este fichero lo leen
     TODAS las fases, así que se mantiene corto a propósito.

     El análisis largo de una entrada NO va aquí — va a `sdd/roadmap/<feature>.md`,
     que solo lee el `/sdd:new` de esa entrada cuando le llega el turno. Una línea
     que acaba en " …" tiene su nota; el texto está entero allí, sin resumir.

     Quién escribe aquí: `/sdd:new` convierte la siguiente entrada en proposal
     just-in-time, y `/sdd:archive` la marca [x] con su "→ changes/archive/…"
     cuando prueba el merge. Nada más — el estado en curso (▶ ✓ PR ⛔) se DERIVA
     de `sdd/changes/<feature>/STATE.md` y no se anota aquí, porque duplicar
     estado derivado en un fichero compartido es lo que hacía conflictar el
     trabajo en paralelo (ADR 0001 D5 del toolkit). -->

- [x] local-environment — [INFRA] monorepo scaffold (/backend, /frontend, cada uno con su Dockerfile), docker-compose + Makefile, esqueleto mínimo ejecutable, git init (PRD §26.1, §25) → changes/archive/2026-07-15-local-environment/
- [x] infra-scaffold — [INFRA] convención de /infra por entorno (no por dominio), criterio de decisión de proveedor cloud (AWS/GCP/Vercel/Railway), sin IaC real ni proveedor elegido todavía (no está en el PRD original, añadido tras `local-environment`) → changes/archive/2026-07-15-infra-scaffold/
- [x] dev-hosting-provider — [INFRA] cierra el criterio de decisión de proveedor cloud de `infra-scaffold` para el entorno dev … → changes/archive/2026-07-19-dev-hosting-provider/
- [x] infra-dev-terraform — [INFRA] IaC real de `infra/environments/dev/` según ADR 0001 (Oracle Cloud, Ampere A1 Always Free) … → changes/archive/2026-07-20-infra-dev-terraform/
- [x] infra-dev-payg — [INFRA] reconciliación del entorno dev con el pivote a Oracle Pay-As-You-Go (ADR 0001, criterio de revisión #5) … → changes/archive/2026-07-22-infra-dev-payg/
- [x] infra-dev-hardening — [INFRA] endurecimiento de la infra dev antes de cerrarla, a partir de la revisión de Marta … → changes/archive/2026-07-24-infra-dev-hardening/
- [x] app-deploy-dev — [INFRA] CD de la app al entorno dev: GitHub Actions construye las imágenes arm64, las publica en GHCR y las despliega en la VM mediante un **runner self-hosted en la propia VM** (`docker compose pull && up -d`, sin SSH) … → changes/archive/2026-07-29-app-deploy-dev/
- [x] ingress-https-dev — [INFRA] ingress HTTPS público de la app en dev vía **Cloudflare Tunnel** (`cloudflared` en el compose de deploy, sin abrir ningún puerto) … → changes/archive/2026-07-29-ingress-https-dev/
- [x] ingress-https-hardening — [INFRA] cierra los 3 hallazgos **bloqueantes** que el panel de `/sdd:review` encontró en `ingress-https-dev` … → changes/archive/2026-08-04-ingress-https-hardening/
- [x] local-dev-network-hardening — [INFRA] acotar a loopback los puertos que `docker-compose.yml` publica en `0.0.0.0` (`5432:5432` de Postgres y `6379:6379` de Redis), igual que ya hace `docker-compose.deploy.yml` con `127.0.0.1:8000` y `127.0.0.1:3000`. → changes/archive/2026-08-05-local-dev-network-hardening/
- [x] compose-ports-guard — [INFRA] **la comprobación automática de la postura de red del compose local**, separada de `local-dev-network-hardening` el 2026-08-05 tras cinco rondas de revisión. … → changes/archive/2026-08-18-compose-ports-guard/
  completes: local-dev-network-hardening · size: L · kind: infra
- [x] worktree-parallel-stack — [INFRA] **permitir varios stacks de dev a la vez**, para que dos sesiones concurrentes en worktrees distintos puedan correr tests. → changes/archive/2026-08-05-worktree-parallel-stack/
  completes: local-dev-network-hardening · size: M · kind: infra
- [x] compose-stacks-diagnostic — [INFRA] **saber qué stacks de Compose hay vivos y cuáles son huérfanos** —su worktree ya no existe—, para recuperar el disco que retienen en silencio. Reencuadrada a la baja el 2026-08-17: la mitad de puertos caducó y con ella casi todo su modelo de amenaza (ver la nota). → changes/archive/2026-08-18-compose-stacks-diagnostic/
  completes: worktree-parallel-stack · size: S · kind: infra
- [x] worktree-port-offset — [INFRA] **recuperar el navegador en un worktree enlazado** … → changes/archive/2026-08-19-worktree-port-offset/
  needs: compose-ports-guard · completes: worktree-parallel-stack · size: M · kind: infra
- [ ] tunnel-host-surface-hardening — [INFRA] **mitigar el residual de radio del túnel que `ingress-https-hardening` documentó y midió pero no cerró** (2026-08-04).
- [x] ci-runner-oci — [INFRA] **migrar los 10 workflows a `[self-hosted, dev]`** (incluidos los `provenance`/`build-backend`/`build-frontend` de `deploy-dev.yml`; `multiarch-build-check` sujeto a la salvedad QEMU de R4) y dejar un runbook … → changes/archive/2026-09-04-ci-runner-oci/
  size: M · kind: infra
- [x] ci-runner-pool-oci — [INFRA] escalar el runner único de `ci-runner-oci` a un pool de N agentes en la misma VM (`runner_count`, default 4), para que dos jobs `pull_request`-triggered coincidentes se repartan entre agentes en vez de … → changes/archive/2026-09-04-ci-runner-pool-oci/
  size: S · kind: infra
- [x] app-version-visibility — [FE] **versión de build visible al abrir la app**, para saber qué está desplegado sin entrar en la VM. → changes/archive/2026-07-31-app-version-visibility/
- [x] app-version-badge-date — [FE] el badge muestra la cadena **canónica completa** (`0.1.0+2026-07-31.5872022`) en vez de recortar la fecha de build. → changes/archive/2026-07-31-app-version-badge-date/
- [x] frontend-ci — [INFRA] **gate de CI para la suite del frontend** (vitest + `eslint` + `tsc --noEmit`), espejo de `backend-tests.yml`. → changes/archive/2026-08-02-frontend-ci/
- [x] frontend-dependency-security — [TECH] revisar y corregir vulnerabilidades de las dependencias del frontend, manteniendo lockfile, build y suite de CI reproducibles. → changes/archive/2026-08-02-frontend-dependency-security/
- [x] dashboard-property-card-responsive — [FE] ajustar las tarjetas de propiedades del dashboard para que conserven jerarquía, legibilidad y acciones utilizables en móvil y escritorio.
- [x] frontend-api-contract-consumer — [FE] consumir en el frontend el `openapi.json` versionado producido por `api-contract-export` … → changes/archive/2026-08-03-frontend-api-contract-consumer/
- [x] ci-backend-tests-conditional-gate — [INFRA] **dejar de pagar 7 minutos por no ejecutar nada**. `backend-tests` tarda ~7m05s por Pull Request y otra vez por push a `main`, y el 89 % es un solo paso (`pytest -q -rs` = 6m15s, medido el 2026-08-03) … → changes/archive/2026-08-03-ci-backend-tests-conditional-gate/
- [x] rule11-ownership-single-source — [TECH] **la regla 11 declara que su contrato vive en un solo sitio, pero la *propiedad* de cada sumidero está reafirmada en seis artefactos y cada revisión encuentra uno más desincronizado**. → changes/archive/2026-08-18-rule11-ownership-single-source/
- [x] backend-suite-runtime — [TECH] **atacar los 6m15s de la suite del backend**, que es la única palanca que ayuda en los Pull Request que **sí** tocan backend (el gate condicional de `ci-backend-tests-conditional-gate` solo ahorra en los que no). → changes/archive/2026-08-10-backend-suite-runtime/
- [x] backend-pyright-tooling — [TECH] **tooling estático reproducible del backend** … → changes/archive/2026-09-01-backend-pyright-tooling/
- [x] build-identity-contract — [INFRA] **atar el validador del frontend a lo que el CD compone de verdad**. → changes/archive/2026-08-08-build-identity-contract/
- [x] app-version-provenance — [INFRA] **parear lo que se ve en pantalla con el PR que lo produjo**. → changes/archive/2026-08-10-app-version-provenance/
  needs: frontend-auth-session, build-identity-contract · size: M · kind: feature
- [ ] infra-github-iac — [INFRA] gestionar la parte GitHub-side como código con el provider `integrations/github` (Actions secrets/variables, instalación de la App, acceso a packages, ajustes de repo), eliminando los pasos a mano en GitHub que tuvo `app-deploy-dev` …
- [x] frontend-foundation — [FE] Application Shell de Next.js App Router (layout, navegación responsive, i18n ES/EN, TanStack Query, Zustand limitado a UI, testing y convenciones frontend), sin lógica de negocio ni integración backend (no está en el PRD original) → changes/archive/2026-07-21-frontend-foundation/
- [x] frontend-docker-deps-autosync — [FE] fix: el contenedor `frontend` en dev sincroniza `node_modules` con el lockfile en cada arranque (entrypoint + `npm ci`), evitando el `Module not found` por volumen nombrado desactualizado al cambiar dependencias (no está en el plan original, añadido tras `frontend-foundation`) → changes/archive/2026-07-21-frontend-docker-deps-autosync/
- [x] domain-foundation-core — [BE] entidades + enums + esquema DB/Alembic de Tenant, TenantConfig, User, Property, PropertyStateTransition, TimelineEvent, Guest, Reservation — backbone de identidad/tenencia/propiedad/reserva (PRD §26.2-3, §7.1-7.8) → changes/archive/2026-07-17-domain-foundation-core/
- [x] domain-foundation-ops — [BE] entidades + enums + esquema DB/Alembic de CleaningTask, CleaningChecklistTemplate, CleaningChecklistCompletion, CleaningPhoto, Incident, Conversation, Message, AccessRecord — dominios operativos, sobre `domain-foundation-core` (PRD §26.2-3, §7.9-7.16) → changes/archive/2026-07-17-domain-foundation-ops/
- [x] domain-foundation-financial — [BE] entidades + enums + esquema DB/Alembic de PricingRule, PriceRecommendation, OwnerApproval, Review, ReviewResponseDraft, OwnerStatement, Expense, NotificationLog, AuditLog, WebhookEvent … → changes/archive/2026-07-31-domain-foundation-financial/
- [x] auth-tenancy — [BE] JWT + RBAC + middleware, tenant isolation con tests (PRD §26.4-5, §6, §22) → changes/archive/2026-07-30-auth-tenancy/
- [x] api-contract-export — [BE] **el contrato OpenAPI como artefacto versionado**, no como estado de un proceso. → changes/archive/2026-08-02-api-contract-export/
- [x] user-management — [BE] administración del tenant: CRUD de `/api/v1/users` + asignación de roles con `AuditLog` de cambios de rol, y `GET`/`PATCH /api/v1/tenants/{id}` + `TenantConfig` … → changes/archive/2026-08-01-user-management/
- [x] timeline-state-machine — [BE] TimelineService central + PropertyStateMachine con todas las transiciones (PRD §26.6-7, §8, §10)
- [x] pms-provider-decision — [CROSS] **cerrar la elección de proveedor PMS/Channel Manager** que PRD §5.4 dejó como lista priorizada a ojo (Octorate → Smoobu → Beds24 → Hostaway) sin validar contra documentación técnica. → changes/archive/2026-08-03-pms-provider-decision/
- [x] channex-staging-adapter — [BE] **el primer PMS real contra el que se valida el backend**. → changes/archive/2026-08-03-channex-staging-adapter/
- [x] pms-beds24-spike — [BE] **medir Beds24 real antes de diseñar contra supuestos**. → changes/archive/2026-08-04-pms-beds24-spike/
- [x] celery-jobs — [BE] scheduler (checkin windows, checkouts, occupied_estimated) + SLA enforcement (PRD §26.8, §8.3, §14). → changes/archive/2026-08-05-celery-jobs/
- [x] sim-advance — [TECH] **avanzar el reloj de los jobs de estado en dev sin tocar el calendario** … → changes/archive/2026-09-11-sim-advance/
  needs: celery-jobs, seed-data-demo-extension · size: S · kind: tech
- [x] reservations-webhooks — [BE] cierra el cuarto ítem de `reservations`, que se entregó sin él … → changes/archive/2026-08-09-reservations-webhooks/
- [x] reservations — [BE] CRUD + MockPMSAdapter + import CSV (PRD §26.9, §16, §7.7). → changes/archive/2026-07-31-reservations/
- [x] properties-crud — [BE] **dar a `properties` una vía de escritura, que hoy no tiene ninguna** … → changes/archive/2026-08-08-properties-crud/
  size: M · kind: feature
- [x] seed-data-demo — [CROSS] **el seed completo de PRD §27**, para poder recorrer y demostrar el producto sin escribir SQL a mano … → changes/archive/2026-08-12-seed-data-demo/
  needs: properties-crud · size: S · kind: feature
- [x] seed-data-demo-extension — [CROSS] **lo que falta del dataset de PRD §27, que sólo puede sembrarse cuando existan sus dueños** … → changes/archive/2026-08-17-seed-data-demo-extension/
  completes: seed-data-demo · needs: maintenance · size: S · kind: feature
- [x] demo-user — [CROSS] **un tenant de demostración con credenciales conocidas, para que gente de fuera pueda trastear el producto en el `dev` público** (https://autohostai.digitalsec.work) … → changes/archive/2026-08-24-demo-user/
  needs: seed-data-demo-extension, app-deploy-dev, infra-dev-terraform, messaging-ai, guest-portal-api · size: M · kind: feature
- [x] cleaning — [BE] CleaningTask + checklist + fotos + StorageAdapter + validación (PRD §26.10, §11). → changes/archive/2026-08-08-cleaning/
- [x] cleaning-photos-storage — [BE] **las fotos de limpieza y el puerto de almacenamiento que no existe**. → changes/archive/2026-08-09-cleaning-photos-storage/
  completes: cleaning · size: M · kind: feature
- [x] object-storage-provisioning — [INFRA] **elegir proveedor de almacenamiento de objetos y provisionarlo**, para que el camino `S3` del puerto de ficheros deje de estar muerto. … → changes/archive/2026-08-16-object-storage-provisioning/
  completes: cleaning-photos-storage · size: M · kind: infra
- [x] backend-response-hardening — [CROSS] **postura de cabeceras y de topes de cuerpo para TODO el backend**, no ruta a ruta … → changes/archive/2026-08-15-backend-response-hardening/
  completes: cleaning-photos-storage · size: S · kind: tech
- [x] cleaning-completion-evidence-gatherer — [TECH] **extraer la orquestación de lectura del cierre de limpieza**, que hoy hace de `CompleteCleaningTaskUseCase` un caso de uso con 11 colaboradores. No toca D8: mueve la lectura, no la decisión, que sigue dentro de `CleaningTask.complete()` … → changes/archive/2026-08-16-cleaning-completion-evidence-gatherer/
  completes: cleaning-photos-storage · size: S · kind: tech
- [x] maintenance — [BE] Incident + clasificación IA + OwnerApproval + flujo técnico (PRD §26.11, §12) → changes/archive/2026-08-15-maintenance/
- [x] pms-provider-resolution — [BE] **la fundación que ADR 0006 pide construir antes del adapter real**: fijar `PMSMessagingPort` como puerto propio frente a `PMSAdapter` (decisión 3) y resolver **proveedor y credenciales por propiedad** (decisión 7). → changes/archive/2026-08-06-pms-provider-resolution/
  completes: channex-staging-adapter · size: L · kind: feature
- [x] pms-beds24-adapter — [BE] sustituir `MockPMSAdapter` por la integración real con Beds24 (ADR 0006) … → changes/archive/2026-08-07-pms-beds24-adapter/
  needs: pms-provider-resolution · inherits-from: pms-beds24-spike · size: L · kind: feature
- [ ] beds24-webhook-cutover-measurement — [BE] **medir los webhooks de Beds24 durante la ventana de corte** — lo único que `pms-beds24-spike` no pudo hacer.
  deferred-until: **dos condiciones, no una**. (1) La cuenta de medición de Beds24 esté viva: su trial venció el 2026-08-17 sin convertirse a pago y la API responde 401, así que hoy no hay contra qué medir — reactivarla cuesta ~€15,50/mes y es decisión de negocio, no de desarrollo (`docs/beds24-spike.md` §Alta de la cuenta). (2) Los canales OTA reales se conecten (ventana de corte de los dos anuncios de Madrid, sin fecha). El banco de medición ya está construido y probado, así que no espera a ningún desarrollo · size: S · kind: spike
- [ ] beds24-messaging-adapter — [BE] **la mensajería de Beds24: el primer implementador real de `PMSMessagingPort`**, que llega vacío de `pms-provider-resolution` y sigue vacío después de `pms-beds24-adapter`.
  needs: pms-beds24-adapter · deferred-until: los canales OTA reales se conecten a la cuenta de Beds24 (misma ventana de corte que `beds24-webhook-cutover-measurement`, sin fecha), porque sin canal no hay conversación que leer ni reserva de OTA a la que responder. **Ese «ni» está sin comprobar y hay sonda para ello**: lo medido fue un GET vacío, que solo prueba que no hay nada que *leer*; si `POST /bookings/messages` acepta `source: guest`, el camino de entrada de `messaging-ai` tiene fuente hoy y el aplazamiento se reduce a la mitad de lectura. El subcomando `beds24_probe.py messages` está construido, probado y mergeado (PR #93), y espera a que la cuenta de medición vuelva a estar viva — la condición (1) de `beds24-webhook-cutover-measurement` · size: M · kind: feature
- [x] pms-sync-schedule — [BE] **el sync periódico del PMS que hoy no existe** … → changes/archive/2026-09-12-pms-sync-schedule/
  needs: celery-jobs, pms-provider-resolution, pms-beds24-adapter · size: S · kind: feature
- [ ] pms-ingest-change-events — [BE] **una modificación o cancelación que llega del PMS actualiza la fila en silencio** …
  needs: reservations, reservations-webhooks, pms-sync-schedule · size: S · kind: feature
- [x] channex-validation-limits — [TECH] **corregir en las specs lo que la validación con Channex puede y no puede hacer**. → changes/archive/2026-08-17-channex-validation-limits/
  completes: channex-staging-adapter · size: S · kind: tech
- [x] messaging-ai — [BE] Conversation + Message + MockAIAdapter + escalación (PRD §26.12, §13). → changes/archive/2026-08-17-messaging-ai/
  needs: pms-beds24-adapter
- [x] dashboard-web-frontend — [FE] dashboard FE (property cards, detalle, timeline) adelantado contra mocks/fixtures mientras dashboard-web (backend agregado) sigue su orden natural en el roadmap … → changes/archive/2026-08-01-dashboard-web-frontend/
- [x] access-notifications — [BE] AccessRecord + ManualAccessAdapter + NotificationAdapter/Log + SES.Hospedajes capa operativa (PRD §26.13-14, §15, §17). → changes/archive/2026-08-08-access-notifications/
- [x] guest-portal-api — [BE] API y seguridad del portal de huésped: token opaco, autorización por estancia/tenant, consulta de información, check-in, PII, auditoría e incidencias (PRD §§6, 7.6, 7.7, 17, 22, 23 … → changes/archive/2026-08-11-guest-portal-api/
  needs: access-notifications · size: M · kind: feature
- [x] guest-portal-web — [FE] página `/guest/[token]`, instrucciones, formulario de check-in, soporte, estados accesibles e i18n ES/EN (PRD §§23-24; capability original `guest-portal`) → changes/archive/2026-08-17-guest-portal-web/
  needs: guest-portal-api · size: M · kind: feature
- [x] auth-account-recovery — [BE] **opcional MVP**: recuperación de contraseña (`/forgot-password`, PRD §24) y cambio de contraseña por el propio usuario. → changes/archive/2026-08-11-auth-account-recovery/
- [x] frontend-auth-session — [FE] **el login real y la sesión en el frontend**, separado de `dashboard-web` el 2026-08-07 porque no depende de la API agregada y sí bloquea cualquier pantalla real. → changes/archive/2026-08-08-frontend-auth-session/
  needs: api-ingress-routing · size: M · kind: feature
- [x] dashboard-api — [BE] **la API agregada del dashboard**: `GET /properties/{id}/dashboard`, `GET /properties/{id}/state` y `GET /timeline/{property_id}` (PRD §26.15-17, §9, §23, §24). Separada de `dashboard-web` el 2026-08-08 por la costura BE/FE … → changes/archive/2026-08-09-dashboard-api/
  needs: properties-crud · size: M · kind: feature
- [x] dashboard-web — [FE] **el consumo real del dashboard**: `HttpDashboardSource` y el cambio del mock, que es una línea en un solo fichero. La UI ya existe desde `dashboard-web-frontend` … → changes/archive/2026-08-11-dashboard-web/
  needs: dashboard-api, frontend-auth-session · size: S · kind: feature
- [x] reservations-web — [FE] **la primera pantalla real de reservas … → changes/archive/2026-08-20-reservations-web/
  needs: reservations, frontend-auth-session · size: S · kind: feature
- [x] incidents-web — [FE] **la primera pantalla real de incidencias … → changes/archive/2026-08-20-incidents-web/
  needs: maintenance, frontend-auth-session · size: S · kind: feature
- [x] incident-triage-web — [FE] **las mutaciones del manager sobre la incidencia, que hoy sólo existen para el técnico y para la CLI** … → changes/archive/2026-09-10-incident-triage-web/
  needs: incidents-web, maintenance, tech-incident-context · size: S · kind: feature
- [x] approvals-web — [BE+FE] **la pantalla `/approvals`, hoy `RoutePlaceholder`, y la ruta de lista que necesita** … → changes/archive/2026-09-10-approvals-web/
  needs: maintenance, frontend-auth-session · size: M · kind: feature
- [x] properties-web — [FE] **la pantalla de listado de propiedades, `/properties` … → changes/archive/2026-08-22-properties-web/
  needs: properties-crud, frontend-auth-session · size: S · kind: feature
- [x] properties-create-web — [FE] **alta y edición de propiedad desde `/properties`**, que hoy es sólo lectura … → changes/archive/2026-09-12-properties-create-web/
  needs: properties-crud, properties-web · size: S · kind: feature
- [x] timeline-web — [FE] **la pantalla `/timeline`, que hoy es un placeholder sobre un backend entregado** … → changes/archive/2026-08-22-timeline-web/
  needs: dashboard-api, dashboard-web · size: S · kind: feature
- [x] api-ingress-routing — [INFRA] **APLAZADA con condición de disparo explícita** (revisada el 2026-08-02, al abrir su `/sdd:new` y cerrarlo sin proposal). → changes/archive/2026-08-08-api-ingress-routing/
  size: S · kind: infra
- [x] cleaning-manager-view — [FE] **la vista de limpieza del manager** … → changes/archive/2026-08-22-cleaning-manager-view/
  needs: cleaning, dashboard-web · size: S · kind: feature
- [x] cleaning-assign-preconditions — [FE+BE] **que asignar una limpieza deje de responder «esa tarea ya no admite un cambio de asignación» cuando quien bloquea es la vivienda** … → changes/archive/2026-08-23-cleaning-assign-preconditions/
  completes: cleaning-manager-view · size: S · kind: tech
- [x] cleaning-task-manage-web — [FE] **crear y validar una limpieza desde `/cleaning`**, y cancelarla desde ahí y no sólo desde la tarjeta de estancamiento del dashboard … → changes/archive/2026-09-09-cleaning-task-manage-web/
  needs: cleaning, cleaning-manager-view, cleaning-assign-preconditions · size: S · kind: feature
- [x] cleaning-stall-blocks-next-stay — [BE] **una limpieza sin cerrar congela la vivienda y se traga el check-in siguiente, y no aparece en ningún recuento** … → changes/archive/2026-08-24-cleaning-stall-blocks-next-stay/
  needs: cleaning · size: M · kind: tech
- [x] blocked-transition-response-ids — [BE] **extender `BlockedTransitionResponse` con dos ids opcionales** (`cleaning_task_id`, `incident_id`) para que el frontend de `blocked-transitions-web` pueda invocar las mutaciones de la tarjeta. … → changes/archive/2026-08-27-blocked-transition-response-ids/
  size: S · kind: feature
- [x] blocked-transitions-web — [FE] **pintar los desajustes donde el manager ya mira**: `GET /api/v1/blocked-transitions` existe desde `cleaning-stall-blocks-next-stay` y nadie lo consume, así que su R2 se cumple en el dato y no en la pantalla — un manager no lee JSON … → changes/archive/2026-08-29-blocked-transitions-web/
  needs: cleaning-stall-blocks-next-stay · size: S · kind: feature
- [x] cleaner-task-context — [BE] **el contexto que la limpiadora necesita para hacer la tarea, sin darle `READ_PROPERTIES` ni `READ_RESERVATIONS`** … → changes/archive/2026-08-19-cleaner-task-context/
  needs: cleaning, properties-crud, reservations · size: M · kind: feature
- [x] cleaner-incident-report — [BE] **que la limpiadora pueda reportar una incidencia desde su tarea**, que PRD §11 pone como botón propio de la UI y PRD §12 lista como fuente de creación («reporte de limpiadora durante checklist»). … → changes/archive/2026-08-22-cleaner-incident-report/
  needs: maintenance, cleaning · size: M · kind: feature
- [x] cleaner-photo-requirements — [BE] **qué fotos pide la tarea, dicho a quien tiene que subirlas** … → changes/archive/2026-08-24-cleaner-photo-requirements/
  needs: cleaning · size: S · kind: feature
- [x] cleaner-app — [FE] **la app de la limpiadora, mobile-first** … → changes/archive/2026-08-31-cleaner-app/
  needs: cleaning, cleaning-photos-storage, access-notifications, frontend-auth-session, cleaner-task-context, cleaner-incident-report, cleaner-photo-requirements · size: M · kind: feature
- [x] tech-incident-context — [BE] **a qué piso va el técnico y cómo entra, sin darle `READ_PROPERTIES`** … → changes/archive/2026-08-22-tech-incident-context/
  needs: maintenance, properties-crud · size: M · kind: feature
- [x] incident-photos — [BE] **las fotos de incidente, que tienen puerto y no tienen consumidor** … → changes/archive/2026-08-23-incident-photos/
  needs: maintenance, cleaning-photos-storage · size: M · kind: feature
- [x] tech-cycle-completion — [BE] **cerrar el ciclo del técnico donde PRD §6 y §12 lo dejan a medias** … → changes/archive/2026-08-23-tech-cycle-completion/
  needs: maintenance · size: M · kind: feature
- [x] tech-app — [FE] **la app del técnico, mobile-first** … → changes/archive/2026-08-30-tech-app/
  needs: maintenance, frontend-auth-session, tech-incident-context, incident-photos, tech-cycle-completion · size: M · kind: feature
- [x] conversations-inbox — [FE] **la bandeja de conversaciones**: `/conversations`, hilos con el huésped, respuesta de la IA y escalado humano para manager/owner (PRD §26.21, §24). … → changes/archive/2026-08-26-conversations-inbox/
  needs: messaging-ai, frontend-auth-session · size: M · kind: feature
- [x] notifications-inbox-web — [BE+FE] **la bandeja in-app, única entrega real que el producto tiene hoy y que no lee nadie** … → changes/archive/2026-08-29-notifications-inbox-web/
  needs: access-notifications, frontend-auth-session · completes: access-notifications · size: M · kind: feature
- [x] auth-session-generation-semantics — [FE] **dos grietas de semántica en `frontend/lib/auth/` que destapó la primera mutación optimista del frontend** … → changes/archive/2026-09-05-auth-session-generation-semantics/
  needs: frontend-auth-session · completes: frontend-auth-session · size: S · kind: tech
- [x] auth-session-persistence — [FE+BE] **la sesión no sobrevive a una pestaña nueva ni a un reload**, por diseño deliberado de `frontend-auth-session` … → changes/archive/2026-09-06-auth-session-persistence/
  needs: frontend-auth-session · completes: frontend-auth-session · size: M · kind: feature
- [x] notification-writers-gap — [BE] **nueve de los diecisiete tipos de notificación no los escribe nadie, y uno es un fallo de producto** … → changes/archive/2026-08-30-notification-writers-gap/
  needs: maintenance, cleaning, access-notifications · completes: access-notifications · size: M · kind: feature
- [x] rule11-guard-trigger-and-scope — [TECH] **el guardián de la propiedad de los sumideros de la regla 11 no se ejecuta en el commit que introduce el defecto, y sí en el siguiente que pase por `backend/**`** … → changes/archive/2026-09-02-rule11-guard-trigger-and-scope/
  completes: rule11-ownership-single-source · size: M · kind: tech
- [x] guest-portal-messaging — [BE+FE] **el huésped no puede escribir: hoy solo escribe *por* él un operador**, porque la única entrada de `messaging-ai` exige `MANAGE_CONVERSATIONS`. … → changes/archive/2026-09-02-guest-portal-messaging/
  needs: messaging-ai, guest-portal-web, rule11-guard-trigger-and-scope · completes: messaging-ai · size: M · kind: feature
- [x] notification-channel-routing — [BE] **el conmutador de canal existe, se guarda, se parchea y se audita … → changes/archive/2026-09-02-notification-channel-routing/
  needs: access-notifications, user-management · completes: access-notifications · size: M · kind: feature
- [x] smtp-delivery-adapter — [BE+INFRA] **el email real**, hoy un `logger.info` … → changes/archive/2026-09-03-smtp-delivery-adapter/
  needs: notification-channel-routing · completes: access-notifications · size: M · kind: feature
- [x] whatsapp-cloud-adapter — [BE] **WhatsApp real, salida *y* entrada**, sustituyendo `MockWhatsAppAdapter`. … → changes/archive/2026-09-04-whatsapp-cloud-adapter/
  needs: notification-channel-routing · completes: messaging-ai · size: L · kind: feature
- [x] human-reply-outbound-delivery — [BE] **la respuesta del manager se guarda y nunca sale**: `RecordHumanReplyUseCase` (`messaging/application/use_cases.py:642-732`) se construye con `conversations, messages, timeline, uow` y sin registry de canales, así que persiste el `Message`, escribe `HUMAN_RESPONSE_SENT` y hace `take_over` — y no llama a ningún `OutboundMessagePort`. Sólo la respuesta de la IA lo hace (:509-517, :542-550). Para `PORTAL` da igual (la fila es la entrega); para `WHATSAPP` y `EMAIL` el huésped recibe la IA y **nunca al humano**, con credenciales de Meta o sin ellas. R4 de `specs/messaging-ai.md:187-191` exige exactamente lo que el código hace, así que la suite está verde y ningún spec ni doc lo declara como límite. De paso: `outbound_registry` hardcodea `ConsoleEmailAdapter()` para `EMAIL` (`channels.py:265-267`) aunque haya SMTP (no está en el plan original, añadida el 2026-09-04 al auditar la comunicación con el huésped; hito «MVP operable» 2) … → changes/archive/2026-09-11-human-reply-outbound-delivery/
  needs: messaging-ai, whatsapp-cloud-adapter, smtp-delivery-adapter · completes: messaging-ai · size: S · kind: fix
- [ ] whatsapp-dev-credentials-render — [INFRA] **que el `.env` que el CD renderiza en la VM lleve las cinco `WHATSAPP_*`** …
  needs: whatsapp-cloud-adapter, app-deploy-dev, human-reply-outbound-delivery · size: S · kind: infra
- [x] staff-messaging — [BE] **el tramo que no existe en absoluto … → changes/archive/2026-09-03-staff-messaging/
  needs: cleaning, maintenance, access-notifications · size: L · kind: feature
- [ ] staff-messaging-web — [FE] **el hilo del personal donde ya se trabaja**: `/cleaner/tasks/[id]`, `/tech/incidents/[id]` y la vista del manager. Va detrás de `cleaner-app` y `tech-app`, que son las que estrenan esas páginas — hoy son `RoutePlaceholder` (no está en el plan original, añadida el 2026-08-28) …
  needs: staff-messaging, cleaner-app, tech-app · size: M · kind: feature
- [ ] guest-scheduled-comms — [BE] **lo que el sistema debe decirle al huésped por su cuenta y hoy no dice** …
  needs: notification-channel-routing, smtp-delivery-adapter, celery-jobs, access-notifications · completes: access-notifications · size: M · kind: feature
- [x] guest-link-delivery — [BE+FE] **el portal del huésped está entero y nadie le da el enlace** … → changes/archive/2026-09-08-guest-link-delivery/
  needs: guest-portal-api, reservations-web, smtp-delivery-adapter, notification-channel-routing · size: S · kind: feature
- [x] revenue-pricing — [BE] **pricing v1 determinista por reglas** … → changes/archive/2026-08-18-revenue-pricing/
  size: M · kind: feature
- [x] pricing-web — [FE] **la pantalla de precios: la cola de recomendaciones con aprobar/rechazar/marcar-como-publicado y las reglas que las producen en modo lectura**, consumiendo `GET`+`PATCH /api/v1/price-recommendations`, `POST … → changes/archive/2026-08-23-pricing-web/
  needs: revenue-pricing, frontend-auth-session · size: M · kind: feature
- [x] design-system-tokens — [FE] **la identidad visual del producto**, que hoy es un placeholder declarado por escrito en `frontend/app/globals.css` (*«Neutral placeholder palette only … → changes/archive/2026-08-24-design-system-tokens/
  needs: frontend-foundation · size: L · kind: feature
- [x] landing-public — [FE] **la página pública de producto en `/`**, que hoy es un `redirect("/dashboard")` y no existe en PRD §24. … → changes/archive/2026-08-25-landing-public/
  needs: design-system-tokens · size: M · kind: feature
- [x] visual-restyle-workspace — [FE] **aplicar los tokens nuevos a las pantallas ya entregadas**: solo piel, sin arquitectura de información ni datos ni endpoints. Deja fuera, con motivo escrito, la reducción del sidebar de 13 destinos a 6, la rejilla con foto de `/properties` y los cuatro bloques agregados del dashboard … → changes/archive/2026-09-04-visual-restyle-workspace/
  needs: design-system-tokens · size: L · kind: feature
- [x] reservation-amount-empty-render — [TECH] **la lista de reservas pinta un código de divisa suelto cuando no hay importe** … → changes/archive/2026-08-25-reservation-amount-empty-render/
  size: S · kind: tech
- [x] reservation-property-identity — [BE] **la lista de reservas identifica la vivienda con un UUID pelado**, porque `ReservationResponse` tiene 27 campos y de la propiedad solo `property_id` … → changes/archive/2026-08-30-reservation-property-identity/
  needs: reservations, properties-crud · size: M · kind: feature
- [x] dashboard-operational-kpis — [BE] **las tres tarjetas de KPI del dashboard rediseñado** (limpiezas de hoy, próximos check-ins, incidencias abiertas con su desglose de urgentes) … → changes/archive/2026-09-02-dashboard-operational-kpis/
  needs: dashboard-api, cleaning, maintenance, reservations · informs-from: visual-restyle-workspace · size: M · kind: feature
- [x] dashboard-occupancy-series — [BE] **la serie de ocupación semanal** del dashboard rediseñado … → changes/archive/2026-09-03-dashboard-occupancy-series/
  needs: dashboard-api, reservations · informs-from: visual-restyle-workspace · size: M · kind: feature
- [x] dashboard-activity-feed — [BE] **el feed de actividad cross-propiedad** del dashboard rediseñado: la lectura de timeline que ya existe, pero por tenant en vez de por propiedad. Ojo al radio de agregación que acota la regla 11 de `steering/security.md`. Salió de `visual-restyle-workspace` D4. → changes/archive/2026-09-04-dashboard-activity-feed/
  needs: dashboard-api, timeline-state-machine · informs-from: visual-restyle-workspace · size: M · kind: feature
- [ ] timeline-description-sink-census — [TECH] **`timeline_events.description` y `property_state_transitions.reason` no tienen fila en el censo de la regla 11 de `sdd/steering/security.md`**, que es la autoridad y el único sitio donde eso se declara. …
  size: S · kind: tech
- [ ] audit-changes-repository-guard — [BE] **cerrar `audit_logs.changes` en el repositorio, no solo en `ChangeSet`** …
  size: S · kind: tech
- [ ] validation-error-loc-redaction — [BE] **acotar el `loc` que el 422 de validación devuelve al llamante** …
  size: S · kind: tech
- [ ] template-identifier-in-readonly-errors — [TECH] **las lecturas de plantilla con `READ_CLEANING_TASKS` nombran la plantilla en el `422` de una fila que dejó de parsear** …
  size: S · kind: tech
- [ ] template-label-sink-census — [TECH] **el `label` de las dos columnas JSONB de plantilla no tiene fila en el censo de la regla 11** …
  size: S · kind: tech
- [x] photo-cache-control-assertion-bound — [TECH] **un test de `maintenance` es sensible al reloj y falla bajo carga de la máquina** … → changes/archive/2026-08-26-photo-cache-control-assertion-bound/
  size: S · kind: tech
- [x] demo-tenant-audit-retention — [TECH] **el `audit_logs` del tenant de demostración crece sin límite** … → changes/archive/2026-08-26-demo-tenant-audit-retention/
  needs: demo-user · size: S · kind: tech
- [ ] assignment-note-storable-text — [TECH] **`incidents.assignment_note` es el único sumidero de texto libre vivo de `maintenance` que no pasa por `storable_text`** …
  size: S · kind: tech
- [ ] plaintext-sink-encryption-at-rest — [TECH] **cifrado en reposo de las cuatro columnas de texto libre que pueden transportar un valor de la regla 3** …
  size: M · kind: tech
- [ ] test-session-per-request — [TECH] **la fixture de tests comparte una sola sesión de BD donde producción abre una por petición**, así que la suite no ejercita el modelo de sesión que sí tiene producción; separada de `rule11-ownership-single-source` …
  size: L · kind: tech
- [x] session-cache-purge-on-logout — [TECH] **la caché de consultas sobrevive al logout, así que un cambio de operador en la misma pestaña puede servir a un rol menos privilegiado los datos del anterior sin que salga ninguna petición** … → changes/archive/2026-08-26-session-cache-purge-on-logout/
  size: S · kind: tech
- [x] revenue-statements — [BE] **liquidaciones al propietario**: `OwnerStatement` + `Expense`, statement mensual por propiedad, export CSV de gastos, desglose financiero por reserva y PDF exportable (PRD §26.24, §20, §7.22-7.23). Sin facturación fiscal (no está en el plan original, separada de `revenue` el 2026-08-16) → changes/archive/2026-09-02-revenue-statements/
  size: M · kind: feature
- [ ] expense-approval-response — [BE] **`OwnerApproval(related_type=OTHER)` no tiene ninguna ruta por la que la propietaria pueda responderla** …
  needs: revenue-statements · size: S · kind: feature
- [ ] statements-web — [FE] **`/statements`, hoy `RoutePlaceholder` sobre un backend entregado** …
  needs: revenue-statements, frontend-auth-session · size: M · kind: feature
- [x] revenue-reviews — [BE] **gestión de reseñas**: `Review` + `ReviewResponseDraft`, análisis de sentimiento, detección de problemas recurrentes y borrador de respuesta, con aprobación humana y **sin posting automático en OTAs** (PRD §26.23, … → changes/archive/2026-09-02-revenue-reviews/
  needs: messaging-ai · size: M · kind: feature
- [ ] reviews-web — [FE] **`/reviews`, hoy `RoutePlaceholder` sobre un backend entregado** …
  needs: revenue-reviews, frontend-auth-session · size: M · kind: feature
- [x] public-zone-hardening — [FE] **endurecimiento de la zona pública tras el primer deploy** … → changes/archive/2026-08-26-public-zone-hardening/
  size: S · kind: fix
- [x] frontend-auth-role-routing — [FE] **endurecimiento del post-login y del routing por rol tras el primer deploy**, agrupando los cuatro ítems §Out of scope de `public-zone-hardening` para no abrir cuatro frentes … → changes/archive/2026-08-27-frontend-auth-role-routing/
  size: M · kind: feature
- [x] frontend-verification-fixes — [TECH] tres defectos que salieron al verificar `blocked-transitions-web` a mano y que no eran de su alcance … → changes/archive/2026-09-09-frontend-verification-fixes/
  size: M · kind: tech
- [ ] incident-list-property-projection — [BE] **que el listado de incidencias traiga su vivienda, en vez de que cada fila la vaya a buscar** …
  needs: tech-app · size: S · kind: tech
- [ ] cleaner-list-property-projection — [BE] **que el listado de tareas de limpieza traiga su vivienda, en vez de que cada fila la vaya a buscar** …
  needs: cleaner-app · size: S · kind: tech
- [ ] incident-status-tone — [FE] **la tabla estado-de-incidencia→`Tone` que no existe** …
  needs: tech-app · size: S · kind: tech
- [ ] shared-datetime-formatter — [TECH] **la sexta copia de `formatDateTime`** …
  needs: tech-app, cleaner-app · size: S · kind: tech
- [x] reservations-identity-web — [FE] **el backend ya sirve el nombre de la vivienda y del huésped, y la pantalla sigue pintando el UUID** … → changes/archive/2026-09-05-reservations-identity-web/
  needs: reservation-property-identity · size: S · kind: fix
- [x] reservation-manual-guest-resolution — [BE] **resolver la identidad del huésped al crear manualmente una reserva**, sin convertirlo en CRUD de Guests … → changes/archive/2026-09-10-reservation-manual-guest-resolution/
  needs: reservations, reservations-web, reservations-identity-web · size: M · kind: feature
- [x] reservation-create-web — [FE] **crear, modificar y cancelar una reserva desde `/reservations`**, que hoy es sólo lectura: `POST` (:90), `PATCH` (:154) y `DELETE` (:180) de `reservations/api/router.py` existen y `http-reservations-source.ts` sólo tiene los dos `GET`. Es la única forma de **empezar** un ciclo operativo nuevo desde el navegador sin OTA ni PMS: canal `DIRECT`/`MANUAL`, nace `PENDING`, y `check_in_date`/`check_out_date`/`status` son parcheables (`schemas.py:75-79`). Cierra el «Fuera de alcance» que `reservations-web` dejó escrito sin entrada de seguimiento. Va detrás de `reservations-identity-web` para no construir un formulario sobre una lista que aún pinta UUIDs (no está en el plan original, añadida el 2026-09-04 al auditar los flujos por rol; hito «MVP operable» 1) … → changes/archive/2026-09-11-reservation-create-web/
  needs: reservations, reservations-web, reservations-identity-web, reservation-manual-guest-resolution · size: S · kind: feature
- [x] shell-topbar-overflow-360 — [FE] **la cabecera compartida desborda a 360 px, en todas las superficies** … → changes/archive/2026-09-01-shell-topbar-overflow-360/
  needs: · size: S · kind: fix
- [x] tenant-settings-web — [FE] **`/settings`, hoy `RoutePlaceholder` … → changes/archive/2026-09-12-tenant-settings-web/
  needs: user-management, frontend-auth-session, frontend-auth-role-routing · size: M · kind: feature
- [ ] hardening-release — [CROSS] suite E2E Playwright, docker + README, DoD §28 completo (PRD §26.25-28). …
  needs: incident-triage-web, approvals-web, reservation-create-web, cleaning-task-manage-web, sim-advance · size: L · kind: tech
- [x] super-admin-identity — [BE] **el modelo de identidad del `SUPER_ADMIN` … → changes/archive/2026-09-02-super-admin-identity/
  needs: auth-tenancy · size: S · kind: feature
- [x] platform-admin-api — [BE] **las rutas de administración de plataforma que hoy no existen** … → changes/archive/2026-09-03-platform-admin-api/
  needs: super-admin-identity, user-management, auth-tenancy · size: M · kind: feature
- [x] super-admin-console — [FE] **la consola de plataforma del `SUPER_ADMIN`** … → changes/archive/2026-09-04-super-admin-console/
  needs: super-admin-identity, platform-admin-api, frontend-auth-role-routing · size: M · kind: feature
- [ ] saas-cross-tenant — [CROSS] **post-MVP, condicional**: visibilidad cross-tenant e impersonation auditada de `SUPER_ADMIN`.
- [x] ci-pr-gates-optimization — [INFRA] **generalizar el patrón de conditional gate al resto de los gates de PR** … → changes/archive/2026-09-08-ci-pr-gates-optimization/
  completes: ci-backend-tests-conditional-gate · size: M · kind: infra
