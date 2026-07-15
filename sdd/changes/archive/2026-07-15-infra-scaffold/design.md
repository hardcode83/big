# Design: infra-scaffold

## Context

Hoy no existe ningún directorio `infra/` en el repo. `sdd/steering/architecture.md` describe el layout de código (`/backend`, `/frontend`, cada uno con `devops/Dockerfile`) pero no dice nada sobre despliegue remoto. `sdd/project.md` no menciona proveedor cloud ni entornos remotos — solo el stack local (`local-environment`). Este change no toca código: crea convención y placeholders de documentación.

**Herramientas ya confirmadas por el usuario** (aunque el proveedor cloud sigue abierto): **Terraform** para declarar la infra, **GitHub Actions** como CI/CD. Esto permite ser más concreto en varias decisiones de abajo sin ampliar el alcance del proposal (sigue sin elegirse proveedor, sigue sin escribirse `.tf` ni workflows reales).

## Decisions

### D1 — Estructura: `infra/environments/{dev,staging,prod}/`, no `infra/{dev,staging,prod}/` directo

**Chosen:** cada entorno vive bajo `infra/environments/<entorno>/`, no directamente en `infra/<entorno>/`. Con Terraform confirmado, esto sigue exactamente la convención estándar de un monorepo Terraform: `infra/environments/<entorno>/` (root modules, uno por entorno, con su propio state) + `infra/modules/` (módulos reutilizables entre entornos — red, base de datos, etc.). Se documenta la intención de `infra/modules/` en `infra.md`, pero **no se crea en este change** (no hace falta todavía sin proveedor elegido; evita inventar estructura sin uso real).

Rejected: `infra/{dev,staging,prod}/` sin el nivel `environments/` — funciona igual de bien con 3 entornos, pero deja peor sitio para lo compartido entre entornos el día que aparezca.

### D2 — `sdd/steering/infra.md`: `applies_to`, sin restricción de `phases`

**Chosen:** frontmatter `applies_to: ["infra/**"]`, sin campo `phases` (aplica a todas las fases) — seguimos el mismo patrón que `backend.md`/`frontend.md` y la recomendación explícita de `sdd/workflow/references/steering.md` para steering docs por componente.

Rejected: `phases: [new, design]` como `product.md` — el criterio de decisión de proveedor también es relevante en `tasks`/`run` (quien escriba el IaC real más adelante necesita leerlo), así que restringir fases no aporta nada aquí.

### D3 — Contenido del criterio de decisión de proveedor

**Chosen:** una tabla en `infra.md` con los candidatos (AWS, Google Cloud, Vercel, Railway) como columnas y **6** criterios como filas — los 5 del proposal (coste a escala de 2 viviendas, Postgres/Redis gestionado, facilidad de migración desde las imágenes Docker de `local-environment`, integración CI/CD, vendor lock-in) más uno nuevo: **madurez del provider de Terraform**. Este último es relevante ahora que Terraform está confirmado: AWS y GCP tienen providers oficiales maduros y completos; Vercel tiene un provider oficial pero centrado en proyectos/env vars (no cubre toda su plataforma); Railway solo tiene un provider comunitario, poco maduro. Se deja **sin rellenar veredicto/ganador** — solo la estructura de comparación y, donde ya se sepa algo objetivo, la celda correspondiente. Estado explícito: "pendiente de decisión".

Rejected: recomendar ya un candidato — el proposal excluye explícitamente elegir proveedor en este change; rellenar un "ganador" aquí sería decidirlo por la puerta de atrás. Rejected también: omitir el criterio de madurez de Terraform — dado que Terraform ya es una decisión firme, ocultar esta asimetría entre candidatos sería dejar fuera la información más relevante para la decisión futura.

### D4 — Plantilla fija para los README de entorno

**Chosen:** los 3 `infra/environments/<entorno>/README.md` siguen la misma plantilla mínima: propósito del entorno, estado ("sin proveedor elegido; aquí irán los `.tf` de este entorno — `main.tf`, `variables.tf`, `backend.tf` — una vez decidido"), y enlace a `sdd/steering/infra.md`. Consistencia entre los 3, sin contenido divergente que luego haya que reconciliar.

### D5 — Punto de conexión con CI/CD: GitHub Actions confirmado, solo prosa, sin workflow real

**Chosen:** una sección "Integración futura con CI/CD" dentro de `infra.md` que explica que un workflow de **GitHub Actions** (`.github/workflows/`, no creado en este change) ejecutará `terraform plan`/`terraform apply` contra `infra/environments/<entorno>/`, parametrizado por entorno. No se crea ningún fichero `.github/workflows/*.yml` — cumple R4 literalmente (documentado, no implementado). El disparador exacto (push a qué rama → qué entorno) queda sin decidir, es una decisión de un change futuro cuando exista el pipeline real.

Rejected: dejarlo genérico ("un pipeline de CI/CD, a definir") — ya no aporta nada de precisión ahora que el usuario ha confirmado la herramienta; nombrar GitHub Actions explícitamente no compromete nada que no esté ya decidido.

### D6 — `architecture.md` referencia cruzada a `infra.md`

**Chosen:** añadir una línea en `architecture.md` (sección "Forma del sistema" o "Monorepo") apuntando a `sdd/steering/infra.md` para quien lea la arquitectura de código sepa que existe una convención de despliegue documentada aparte. Un cross-reference de una línea, no una decisión de arquitectura nueva.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Raíz | `infra/README.md`, `infra/environments/dev/README.md`, `infra/environments/staging/README.md`, `infra/environments/prod/README.md` | Nuevos — placeholders, sin IaC real |
| Steering | `sdd/steering/infra.md` (nuevo) | Convención de layout (D1), criterio de decisión de proveedor (D3), punto de conexión CI/CD (D5) |
| Steering | `sdd/steering/architecture.md` | Una línea de referencia cruzada a `infra.md` (D6) |

## Data & interfaces

Ninguno — este change no toca código, esquema de datos ni contratos de API.

## Risks & mitigations

- **Los placeholders quedan obsoletos si tarda mucho la decisión de proveedor**: mitigado con el estado explícito "pendiente" en cada README/en `infra.md` — nadie debería leerlos como una decisión ya tomada.
- **Alguien empieza a meter IaC real sin pasar por un change SDD**: mitigado dejando explícito en `infra.md` que cualquier `.tf`/workflow real requiere su propio `/sdd-new` una vez elegido proveedor — no se escribe directamente sobre el placeholder.
- **Vercel/Railway tienen soporte Terraform mucho más débil que AWS/GCP** (D3): si finalmente se elige uno de ellos, parte de su infra probablemente se gestione mejor vía su propio dashboard/CLI que vía `.tf` — riesgo real que `infra.md` deja explícito en la tabla, no oculto, para que la decisión futura lo tenga en cuenta.

## Open questions

Ninguna — el proposal ya fija el alcance (solo convención, sin proveedor, sin IaC) y las decisiones de arriba son de redacción/estructura, no requieren que el usuario elija entre alternativas de producto.
