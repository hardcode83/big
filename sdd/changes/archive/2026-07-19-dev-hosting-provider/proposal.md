# Proposal: dev-hosting-provider

## Why

`sdd/steering/infra.md` (change `infra-scaffold`) ya fijó la convención de `/infra` por entorno y confirmó Terraform + GitHub Actions como herramientas, pero dejó el **proveedor cloud pendiente de decisión**, con una tabla inicial de solo 4 candidatos (AWS, Google Cloud, Vercel, Railway) sin veredicto. Antes de escribir cualquier `.tf` real para `infra/environments/dev/` hace falta cerrar esa decisión con un análisis de mercado más amplio y una justificación documentada (ADR), priorizando madurez del provider de Terraform (el equipo es experto en Terraform) y ajuste con el stack Docker ya existente (`local-environment`: backend+worker Celery+frontend+Postgres+Redis).

## What changes

Se investiga el mercado de hosting/cloud para contenedores Docker a través de tres modelos de despliegue (VM única + docker-compose, PaaS con deploy nativo de contenedores, contenedores serverless gestionados), se evalúan los candidatos relevantes de cada modelo con criterios objetivos, y se documenta la decisión en un ADR nuevo (se introduce la convención `docs/adr/` en el repo, que no existía). `sdd/steering/infra.md` y `sdd/specs/infra-scaffold.md` se actualizan para reflejar el veredicto y enlazar el ADR. La decisión es exclusiva del entorno **dev** — no condiciona staging/prod, que tendrán su propia decisión cuando el negocio lo requiera. No se escribe Terraform real: eso queda para un change posterior, tal como ya indica `infra.md`.

## Requirements

### R1 — Barrido de mercado por modelo de despliegue

**As a** propietario técnico del proyecto, **I want** un barrido de proveedores agrupado por modelo de despliegue, **so that** la comparación no se limite a los 4 candidatos iniciales ni a un único modelo.

Acceptance criteria:

1. WHEN se investigue el modelo "VM única + docker-compose", THE SYSTEM SHALL incluir al menos  Oracle (con su capa gratuita incluida), Hetzner Cloud, Scaleway, DigitalOcean y AWS Lightsail/EC2 como candidatos evaluados.
2. WHEN se investigue el modelo "PaaS con deploy nativo de contenedores", THE SYSTEM SHALL incluir al menos Railway, Render y Fly.io como candidatos evaluados, además de Vercel (evaluando explícitamente su ajuste real con un stack backend+worker+Postgres+Redis, no solo su propuesta de marketing).
3. WHEN se investigue el modelo "contenedores serverless gestionados", THE SYSTEM SHALL incluir al menos AWS Fargate/App Runner y GCP Cloud Run como candidatos evaluados.
4. THE SYSTEM SHALL registrar, para cada candidato descartado en una primera pasada (p. ej. por falta de soporte a Postgres/Redis o por ausencia de provider de Terraform oficial), el motivo del descarte en el ADR — ningún candidato desaparece sin rastro.
5. THE SYSTEM SHALL identificar y documentar explícitamente las capas gratuitas ("free tier") de cada candidato relevante, distinguiendo **always-free permanente** (p. ej. Oracle Cloud Always Free — VMs ARM Ampere, hasta 4 OCPU/24 GB — o GCP Always Free e2-micro) de **crédito de prueba con caducidad** (p. ej. créditos iniciales de AWS, Railway, Render, Fly.io), dado que un entorno de dev de larga duración solo se beneficia de las permanentes.

### R2 — Evaluación con criterios ponderados

**As a** propietario técnico del proyecto, **I want** cada candidato evaluado contra un conjunto fijo de criterios, **so that** la decisión sea comparable y defendible, no una preferencia subjetiva.

Acceptance criteria:

1. THE SYSTEM SHALL evaluar cada candidato en, como mínimo: coste mensual estimado a la escala actual — incluyendo si ese coste puede quedar en 0€ usando su capa gratuita permanente (documentado, no eliminatorio por sí solo) —, madurez y cobertura del provider oficial de Terraform, ajuste de migración desde las imágenes Docker de `local-environment`, soporte de Postgres/Redis (gestionado o autoalojado en contenedor), integración con GitHub Actions, vendor lock-in, y carga operativa esperada.
2. THE SYSTEM SHALL ponderar, por encima del coste puro y de forma explícita en el ADR: la madurez del provider de Terraform, el ajuste de migración desde las imágenes Docker de `local-environment` (encajar con el sistema de desarrollo local actual, no forzar un repaquetado radical de la app), y la compatibilidad con un pipeline de GitHub Actions que ejecute `terraform plan`/`apply` de forma directa contra su infraestructura.
3. IF un candidato no tiene provider de Terraform oficial o community con mantenimiento activo, THEN THE SYSTEM SHALL señalarlo como riesgo explícito en su evaluación, no descartarlo automáticamente.
4. IF un candidato exige reescribir la aplicación a un modelo propietario incompatible con los contenedores Docker de `local-environment` (backend, worker Celery, frontend, Postgres, Redis), o no permite que un pipeline de GitHub Actions ejecute `terraform plan`/`apply` contra su infraestructura de forma razonable, THEN THE SYSTEM SHALL excluirlo como veredicto final para dev — permanece documentado en la tabla comparativa con el motivo, pero no puede ganar el ADR.
5. THE SYSTEM SHALL evaluar el vendor lock-in de cada candidato en términos de portabilidad real: si su código Terraform y sus imágenes Docker podrían migrarse a otro proveedor sin reescritura mayor, y usarlo como criterio de desempate explícito cuando dos candidatos queden empatados en el resto de criterios — el objetivo es no "secuestrar" la capacidad de cambiar de proveedor a futuro.

### R3 — Kubernetes evaluado y descartado con criterio de reconsideración

**As a** propietario técnico del proyecto, **I want** que Kubernetes se evalúe formalmente en vez de omitirse, **so that** quede constancia de por qué no se usa todavía y cuándo tendría sentido reconsiderarlo.

Acceptance criteria:

1. THE SYSTEM SHALL incluir Kubernetes gestionado (EKS/GKE) como alternativa evaluada en el ADR, con su comparación de coste/complejidad frente a los tres modelos priorizados.
2. THE SYSTEM SHALL documentar el motivo del descarte para esta fase (complejidad y coste prematuros a escala de 2 viviendas) y un criterio explícito de cuándo reconsiderarlo (p. ej. umbral de nº de tenants/viviendas o de tráfico).

### R4 — ADR publicado con convención nueva en el repo

**As a** cualquier futuro colaborador del proyecto, **I want** la decisión documentada como ADR en una ubicación estándar, **so that** quede trazabilidad de alternativas consideradas y motivo de la elección, reutilizable para decisiones de infraestructura futuras.

Acceptance criteria:

1. THE SYSTEM SHALL crear `docs/adr/` con un primer documento (`0001-<slug>.md`) siguiendo formato ADR estándar (Contexto, Decisión, Estado, Alternativas consideradas con motivo de rechazo, Consecuencias).
2. THE SYSTEM SHALL registrar en el ADR una decisión final única para el entorno dev (proveedor + modelo de despliegue), no una lista abierta de opciones igualmente válidas.
3. WHEN el ADR se publique, THE SYSTEM SHALL dejarlo enlazado desde `sdd/steering/infra.md`.

### R5 — Steering y specs de infra actualizados con el veredicto

**As a** propietario técnico del proyecto, **I want** que `infra.md` y la spec `infra-scaffold` dejen de decir "pendiente de decisión" para dev, **so that** el estado documentado del proyecto sea veraz.

Acceptance criteria:

1. WHEN se apruebe la decisión, THE SYSTEM SHALL sustituir la tabla "pendiente de decisión" de `sdd/steering/infra.md` por el proveedor y modelo elegidos para dev, manteniendo la tabla comparativa completa (todos los candidatos evaluados) como referencia histórica.
2. THE SYSTEM SHALL actualizar `sdd/specs/infra-scaffold.md` (sección "Herramientas confirmadas, proveedor pendiente") para reflejar que el proveedor de dev ya está decidido, enlazando al ADR.
3. THE SYSTEM SHALL dejar explícito que staging/prod siguen pendientes de su propia decisión, sin asumir que el veredicto de dev se extiende a ellos.

## Out of scope

- Escribir código Terraform real (`.tf`) para desplegar en el proveedor elegido — change futuro, posterior a esta decisión.
- Decidir el proveedor/modelo para staging o prod — decisión propia, futura, no arrastrada por esta.
- Definir el pipeline de GitHub Actions (`terraform plan`/`apply`) — ya anotado como pendiente en `infra.md`, no se resuelve aquí.
- Migrar datos o desplegar de verdad el stack actual — este change solo produce la decisión y su documentación.

## Affected specs

- `sdd/specs/infra-scaffold.md` — se actualiza la sección de proveedor cloud (pasa de "pendiente" a decidido para dev).
- Nuevo: `docs/adr/0001-<slug>.md` *(no existe aún — se crea al archivar; primer uso de la convención ADR en el repo)*.
