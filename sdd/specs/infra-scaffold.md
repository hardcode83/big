# Convención de infraestructura remota

## Purpose

Convención de despliegue remoto para AutoHostAI: dónde vive el código de IaC, cómo se organiza (por entorno, no por dominio de negocio), qué herramientas se usan, y el criterio para elegir proveedor cloud cuando llegue el momento — sin comprometerse todavía a un proveedor concreto ni a código de IaC real.

## Requirements

### Estructura de `/infra` por entorno

- `infra/` contiene `environments/dev/`, `environments/staging/` y `environments/prod/`, cada uno con un `README.md`.
- Ningún directorio de `infra/` se organiza por dominio de negocio (`auth`, `cleaning`, `reservations`, ...) — es ortogonal al layout hexagonal de `backend`/`frontend` documentado en `architecture.md`.
- WHEN exista código Terraform compartido entre entornos (red, base de datos, DNS...), THE SYSTEM SHALL alojarlo en `infra/modules/` — no existe todavía, se crea con el primer módulo real.

### Herramientas confirmadas, proveedor pendiente

- **Terraform** es la herramienta de IaC confirmada; **GitHub Actions** es el CI/CD confirmado.
- El proveedor cloud (AWS, Google Cloud, Vercel, Railway) está **pendiente de decisión**. `sdd/steering/infra.md` documenta una tabla comparativa de 6 criterios (coste, Postgres/Redis gestionado, migración desde Docker, integración CI/CD, vendor lock-in, madurez del provider de Terraform) sin rellenar veredicto.

### Placeholders sin IaC real

- Cada `README.md` de entorno indica su propósito, su estado ("sin proveedor elegido; sin Terraform real todavía") y enlaza a `sdd/steering/infra.md`.
- IF se necesita IaC real para cualquier entorno, THEN THE SYSTEM SHALL requerir un change SDD propio (`/sdd-new`) una vez elegido proveedor — nunca escribirse directamente sobre los placeholders.
- No existe ningún fichero `.tf` ni `.github/workflows/*.yml` en el repo todavía.

### Punto de conexión con CI/CD

- `sdd/steering/infra.md` documenta que un futuro workflow de GitHub Actions ejecutará `terraform plan`/`terraform apply` contra `infra/environments/<entorno>/`, parametrizado por entorno.
- El disparador exacto (qué rama/evento dispara qué entorno) no está decidido — se fija cuando exista el pipeline real.

## Key files

- `sdd/steering/infra.md` — convención completa, criterio de decisión de proveedor, integración CI/CD futura.
- `infra/README.md`, `infra/environments/{dev,staging,prod}/README.md` — placeholders.
- `sdd/steering/architecture.md`, `sdd/project.md` — referencias cruzadas a `infra.md`.
