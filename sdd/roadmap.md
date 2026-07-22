# Roadmap

<!-- Backlog ordenado de changes, agrupando los 28 pasos del PRD §26 por módulo.
     /sdd:new coge la siguiente entrada y la convierte en proposal
     just-in-time. Al empezar una entrada, /sdd:new añade
     "→ changes/<feature>/"; al archivarla, /sdd:archive la marca [x]. -->

- [x] local-environment — monorepo scaffold (/backend, /frontend, cada uno con su Dockerfile), docker-compose + Makefile, esqueleto mínimo ejecutable, git init (PRD §26.1, §25) → changes/archive/2026-07-15-local-environment/
- [x] infra-scaffold — convención de /infra por entorno (no por dominio), criterio de decisión de proveedor cloud (AWS/GCP/Vercel/Railway), sin IaC real ni proveedor elegido todavía (no está en el PRD original, añadido tras `local-environment`) → changes/archive/2026-07-15-infra-scaffold/
- [x] dev-hosting-provider — cierra el criterio de decisión de proveedor cloud de `infra-scaffold` para el entorno dev: ADR (`docs/adr/0001-dev-hosting-provider.md`) comparando VM/PaaS/serverless/Kubernetes, decide Oracle Cloud (Ampere A1, Always Free) + docker-compose; staging/prod quedan pendientes (no está en el PRD original, añadido tras `infra-scaffold`) → changes/archive/2026-07-19-dev-hosting-provider/
- [x] infra-dev-terraform — IaC real de `infra/environments/dev/` según ADR 0001 (Oracle Cloud, Ampere A1 Always Free): VCN/security list/instancia vía Terraform (`oracle/oci`), backend de state nativo `oci`, pipeline GitHub Actions (`plan`/`apply` manual + validación en PR) y build multi-arch (arm64) verificado en CI; despliegue de la app vía SSH queda fuera de alcance (workflow futuro); `terraform apply` real pendiente de confirmación explícita del usuario (no está en el PRD original, añadido tras `dev-hosting-provider`) → changes/archive/2026-07-20-infra-dev-terraform/
- [x] infra-dev-payg — reconciliación del entorno dev con el pivote a Oracle Pay-As-You-Go (ADR 0001, criterio de revisión #5): la A1 Always Free daba "Out of host capacity" persistente incluso en Frankfurt; reabierto el debate de proveedor con precios verificados 2026 (Hetzner ya ~€9 CX33, Lightsail ~$44, Contabo/Netcup nuevos), se mantiene Oracle vía PAYG (único $0 con cero reescritura, prioridad de capacidad); tenancy PAYG conservando la capa gratuita a $0, resize in-place a 4 OCPU/24 GB/200 GB en AD-3, GitHub Actions como único gestor de infra, higiene de repo/secretos (no está en el plan original, añadido tras `infra-dev-terraform`) → changes/archive/2026-07-22-infra-dev-payg/
- [ ] frontend-foundation — Application Shell de Next.js App Router (layout, navegación responsive, i18n ES/EN, TanStack Query, Zustand limitado a UI, testing y convenciones frontend), sin lógica de negocio ni integración backend; bloqueado hasta que `infra-scaffold` esté en `main` (no está en el PRD original, propuesta/diseño/tasks ya aprobados y mergeados, implementación sin empezar) → changes/frontend-foundation/
- [x] frontend-docker-deps-autosync — fix: el contenedor `frontend` en dev sincroniza `node_modules` con el lockfile en cada arranque (entrypoint + `npm ci`), evitando el `Module not found` por volumen nombrado desactualizado al cambiar dependencias (no está en el plan original, añadido tras `frontend-foundation`) → changes/archive/2026-07-21-frontend-docker-deps-autosync/
- [x] domain-foundation-core — entidades + enums + esquema DB/Alembic de Tenant, TenantConfig, User, Property, PropertyStateTransition, TimelineEvent, Guest, Reservation — backbone de identidad/tenencia/propiedad/reserva (PRD §26.2-3, §7.1-7.8) → changes/archive/2026-07-17-domain-foundation-core/
- [x] domain-foundation-ops — entidades + enums + esquema DB/Alembic de CleaningTask, CleaningChecklistTemplate, CleaningChecklistCompletion, CleaningPhoto, Incident, Conversation, Message, AccessRecord — dominios operativos, sobre `domain-foundation-core` (PRD §26.2-3, §7.9-7.16) → changes/archive/2026-07-17-domain-foundation-ops/
- [ ] domain-foundation-financial — entidades + enums + esquema DB/Alembic de PricingRule, PriceRecommendation, OwnerApproval, Review, ReviewResponseDraft, OwnerStatement, Expense, NotificationLog, AuditLog, WebhookEvent — pricing/financiero + logs de sistema, sobre `domain-foundation-core`/`domain-foundation-ops` (PRD §26.2-3, §7.17-7.26)
- [ ] auth-tenancy — JWT + RBAC + middleware, tenant isolation con tests (PRD §26.4-5, §6, §22)
- [ ] timeline-state-machine — TimelineService central + PropertyStateMachine con todas las transiciones (PRD §26.6-7, §8, §10)
- [ ] celery-jobs — scheduler (checkin windows, checkouts, occupied_estimated) + SLA enforcement (PRD §26.8, §8.3, §14)
- [ ] reservations — CRUD + MockPMSAdapter + import CSV + webhook handling (PRD §26.9, §16, §7.7)
- [ ] cleaning — CleaningTask + checklist + fotos + StorageAdapter + validación (PRD §26.10, §11)
- [ ] maintenance — Incident + clasificación IA + OwnerApproval + flujo técnico (PRD §26.11, §12)
- [ ] messaging-ai — Conversation + Message + MockAIAdapter + escalación (PRD §26.12, §13)
- [ ] access-notifications — AccessRecord + ManualAccessAdapter + NotificationAdapter/Log + SES.Hospedajes capa operativa (PRD §26.13-14, §15, §17)
- [ ] dashboard-web — dashboard API agregado + FE: layout, auth, property cards, detalle + timeline (PRD §26.15-17, §9, §24)
- [ ] field-apps — apps mobile-first de limpiadora y técnico + bandeja de conversaciones (PRD §26.18-21, §24)
- [ ] revenue — pricing v1 por reglas + statements/exports + reviews (PRD §26.22-24, §18-20)
- [ ] hardening-release — settings/integraciones FE, seed data §27, suite E2E Playwright, docker + README, DoD §28 completo (PRD §26.25-28)
