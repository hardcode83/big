# Convención de infraestructura remota

## Purpose

Convención de despliegue remoto para AutoHostAI: dónde vive el código de IaC, cómo se organiza (por entorno, no por dominio de negocio), qué herramientas se usan, y el proveedor cloud por entorno — decidido para `dev` (ver `docs/adr/0001-dev-hosting-provider.md`), pendiente para staging/prod — sin código de IaC real todavía en ningún entorno.

## Requirements

### Estructura de `/infra` por entorno

- `infra/` contiene `environments/dev/`, `environments/staging/` y `environments/prod/`, cada uno con un `README.md`.
- Ningún directorio de `infra/` se organiza por dominio de negocio (`auth`, `cleaning`, `reservations`, ...) — es ortogonal al layout hexagonal de `backend`/`frontend` documentado en `architecture.md`.
- WHEN exista código Terraform compartido entre entornos (red, base de datos, DNS...), THE SYSTEM SHALL alojarlo en `infra/modules/` — no existe todavía, se crea con el primer módulo real.

### Herramientas confirmadas, proveedor decidido para dev

- **Terraform** es la herramienta de IaC confirmada; **GitHub Actions** es el CI/CD confirmado.
- El proveedor cloud para **dev** está **decidido**: Oracle Cloud Infrastructure, VM única (Ampere A1, Always Free) + docker-compose — ver `docs/adr/0001-dev-hosting-provider.md` (justificación, alternativas consideradas y riesgos aceptados) y `sdd/steering/infra.md` (tabla comparativa completa de todos los candidatos investigados, mantenida como histórico).
- **Staging y prod siguen pendientes de decisión propia** — no heredan el veredicto de dev; cada entorno tiene su root module de Terraform independiente (ver "Estructura de `/infra` por entorno" arriba).

### Placeholders sin IaC real

- Cada `README.md` de entorno indica su propósito, su estado, y enlaza a `sdd/steering/infra.md`. Para `staging`/`prod` el estado sigue siendo "sin proveedor elegido; sin Terraform real todavía"; para `dev` el estado refleja el proveedor decidido (ver arriba) con enlace al ADR, también sin Terraform real todavía.
- IF se necesita IaC real para cualquier entorno, THEN THE SYSTEM SHALL requerir un change SDD propio (`/sdd-new`) una vez elegido proveedor — nunca escribirse directamente sobre los placeholders.
- No existe ningún fichero `.tf` ni `.github/workflows/*.yml` en el repo todavía.

### Punto de conexión con CI/CD

- `sdd/steering/infra.md` documenta que un futuro workflow de GitHub Actions ejecutará `terraform plan`/`terraform apply` contra `infra/environments/<entorno>/`, parametrizado por entorno.
- El disparador exacto (qué rama/evento dispara qué entorno) no está decidido — se fija cuando exista el pipeline real.

## Key files

- `sdd/steering/infra.md` — convención completa, criterio de decisión de proveedor, integración CI/CD futura.
- `infra/README.md`, `infra/environments/{dev,staging,prod}/README.md` — placeholders.
- `sdd/steering/architecture.md`, `sdd/project.md` — referencias cruzadas a `infra.md`.
