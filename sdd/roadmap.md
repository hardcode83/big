# Roadmap

<!-- Backlog ordenado de changes, agrupando los 28 pasos del PRD §26 por módulo.
     /sdd-new coge la siguiente entrada y la convierte en proposal just-in-time.
     Al empezar una entrada, /sdd-new añade "→ changes/<feature>/"; al archivarla,
     /sdd-archive la marca [x]. -->

- [ ] dev-environment — monorepo scaffold (/backend, /frontend, cada uno con su Dockerfile), docker-compose + Makefile, esqueleto mínimo ejecutable, git init (PRD §26.1, §25) → changes/dev-environment/
- [ ] domain-foundation — modelos de dominio + enums, esquema DB + Alembic, sobre el scaffold de `dev-environment` (PRD §26.2-3, §7)
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
