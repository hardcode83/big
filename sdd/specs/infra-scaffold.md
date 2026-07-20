# Convención de infraestructura remota

## Purpose

Convención de despliegue remoto para AutoHostAI: dónde vive el código de IaC, cómo se organiza (por entorno, no por dominio de negocio), qué herramientas se usan, y el proveedor cloud por entorno. **`dev` tiene ya Terraform real y un pipeline de CI/CD real** (ver spec `infra-dev-terraform`); `staging`/`prod` siguen siendo placeholders, sin proveedor elegido.

## Requirements

### Estructura de `/infra` por entorno

- `infra/` contiene `environments/dev/`, `environments/staging/` y `environments/prod/`, cada uno con un `README.md`.
- Ningún directorio de `infra/` se organiza por dominio de negocio (`auth`, `cleaning`, `reservations`, ...) — es ortogonal al layout hexagonal de `backend`/`frontend` documentado en `architecture.md`.
- WHEN exista código Terraform compartido entre entornos (red, base de datos, DNS...), THE SYSTEM SHALL alojarlo en `infra/modules/` — no existe todavía, se crea con el primer módulo real.

### Herramientas confirmadas, proveedor decidido para dev

- **Terraform** es la herramienta de IaC confirmada; **GitHub Actions** es el CI/CD confirmado.
- El proveedor cloud para **dev** está **decidido**: Oracle Cloud Infrastructure, VM única (Ampere A1, Always Free) + docker-compose — ver `docs/adr/0001-dev-hosting-provider.md` (justificación, alternativas consideradas y riesgos aceptados) y `sdd/steering/infra.md` (tabla comparativa completa de todos los candidatos investigados, mantenida como histórico).
- **Staging y prod siguen pendientes de decisión propia** — no heredan el veredicto de dev; cada entorno tiene su root module de Terraform independiente (ver "Estructura de `/infra` por entorno" arriba).

### Estado por entorno

- **`dev`**: Terraform real (red, cómputo, backend de state, presupuesto — ver spec `infra-dev-terraform`) y dos workflows de GitHub Actions reales (`.github/workflows/infra-dev.yml`, `.github/workflows/multiarch-build-check.yml`).
- **`staging`/`prod`**: siguen siendo placeholders — "sin proveedor elegido; sin Terraform real todavía". Cada `README.md` de entorno indica su propósito, su estado, y enlaza a `sdd/steering/infra.md`.
- IF se necesita IaC real para `staging`/`prod`, THEN THE SYSTEM SHALL requerir un change SDD propio (`/sdd-new`) una vez elegido proveedor — nunca escribirse directamente sobre esos placeholders. No heredan el veredicto de `dev`.

### Punto de conexión con CI/CD

- Para `dev`, el disparador real está decidido y en producción: `pull_request` (paths `infra/environments/dev/**`) ejecuta solo `fmt`/`validate`/`init -backend=false`, sin credenciales; `workflow_dispatch` con input `action` (`plan`|`apply`) es el único camino que puede tocar recursos reales — nunca automático en push/merge. Ver spec `infra-dev-terraform` para el detalle completo.
- Para `staging`/`prod`, el disparador sigue sin decidir — se fija cuando exista Terraform real para esos entornos.

## Key files

- `sdd/steering/infra.md` — convención completa, criterio de decisión de proveedor, tabla histórica de candidatos.
- `infra/README.md`, `infra/environments/{staging,prod}/README.md` — placeholders.
- `infra/environments/dev/` — Terraform real, ver spec `infra-dev-terraform`.
- `sdd/steering/architecture.md`, `sdd/project.md` — referencias cruzadas a `infra.md`.
