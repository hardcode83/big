# Proposal: infra-scaffold

## Why

`local-environment` dejó el stack local (Docker Compose + Makefile) construido para ser portable a un entorno remoto, pero todavía no existe ningún sitio en el repo para el código de despliegue (IaC) en sí, ni un criterio documentado para elegir proveedor cloud. Ahora mismo no está decidido dónde se desplegará (AWS, Google Cloud, Vercel, Railway son candidatos), y forzar esa decisión hoy sería prematuro. Este change fija la convención de `/infra` (organizada por entorno, no por dominio de negocio) y el criterio de decisión de proveedor, para que cuando llegue el momento de desplegar de verdad no haya que reestructurar nada ni decidir la convención con prisa.

## What changes

Se crea `infra/` con un subdirectorio por entorno (`dev`, `staging`, `prod`), cada uno con un `README.md` placeholder que explica qué contendrá una vez se elija proveedor — sin código de IaC real todavía. Se crea `sdd/steering/infra.md` documentando la convención (por entorno, no por dominio — ortogonal al layout hexagonal de `backend`/`frontend`), el criterio para evaluar proveedor, y el punto de conexión futuro con CI/CD. No se elige proveedor ni se escribe Terraform/Pulumi/CDK ni pipeline real en este change.

## Requirements

### R1 — Estructura de `/infra` por entorno, no por dominio

**As a** developer, **I want** `infra/` organizado por entorno de despliegue (`dev`/`staging`/`prod`) en vez de por dominio de negocio, **so that** la infraestructura no acople artificialmente al monolito modular ni a los dominios (`auth`, `cleaning`, `reservations`, ...).

Acceptance criteria:

1. WHEN se crea `infra/`, THE SYSTEM SHALL contener `infra/environments/dev/`, `infra/environments/staging/` e `infra/environments/prod/` como subdirectorios de primer nivel.
2. THE SYSTEM SHALL NOT organizar ningún directorio de `infra/` por dominio de negocio.

### R2 — Steering doc con la convención y el criterio de decisión de proveedor

**As a** developer, **I want** un steering doc que documente la convención de `infra/` y el criterio para elegir proveedor cloud, **so that** la decisión futura sea informada y cualquier agente/dev sepa dónde va el código de IaC cuando se escriba.

Acceptance criteria:

1. WHEN se archive este change, THE SYSTEM SHALL tener `sdd/steering/infra.md` con `applies_to: ["infra/**"]`.
2. THE SYSTEM SHALL documentar en ese doc, como mínimo: criterios de evaluación de proveedor (coste a escala de 2 viviendas, disponibilidad de Postgres/Redis gestionado, facilidad de migración desde las imágenes Docker de `local-environment`, integración con CI/CD, nivel de vendor lock-in) y el estado actual de la decisión (pendiente, ningún proveedor elegido).

### R3 — Placeholders de entorno sin IaC real

**As a** developer, **I want** un README por entorno explicando qué contendrá una vez se elija proveedor, **so that** el layout esté visible desde ya sin comprometerse a herramientas o proveedor concretos.

Acceptance criteria:

1. WHEN se crea `infra/environments/<entorno>/`, THE SYSTEM SHALL incluir un `README.md` que enlace a `sdd/steering/infra.md` y explique el propósito de ese entorno.
2. THE SYSTEM SHALL NOT incluir código de IaC real (Terraform, Pulumi, CloudFormation, etc.) en este change.

### R4 — Punto de conexión con CI/CD documentado, no implementado

**As a** developer, **I want** que quede documentado dónde y cómo el pipeline de CI/CD futuro invocará `infra/`, **so that** cuando se escriba el pipeline real no haya que redecidir la convención.

Acceptance criteria:

1. WHEN se documenta la convención en `sdd/steering/infra.md`, THE SYSTEM SHALL indicar que el futuro pipeline de CI/CD invocará `infra/environments/<entorno>/` como paso de deploy.
2. THE SYSTEM SHALL NOT implementar ningún pipeline de CI/CD real en este change.

## Out of scope

- Elegir proveedor cloud concreto (AWS, Google Cloud, Vercel, Railway) — decisión futura, cuando el negocio necesite desplegar de verdad.
- Código de IaC real (Terraform, Pulumi, CDK, CloudFormation...) para cualquier entorno.
- Pipeline de CI/CD real (GitHub Actions, GitLab CI, etc.) — solo se documenta el punto de conexión.
- Secretos/credenciales de ningún proveedor.
- Re-evaluar la portabilidad de las imágenes Docker — ya se garantizó en `local-environment` (12-factor, targets `dev`/`prod`); este change no la reimplementa, solo la referencia como criterio de decisión.

## Affected specs

- `sdd/specs/infra-scaffold.md` (no existe aún — se creará al archivar este change).
