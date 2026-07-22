# Proposal: infra-dev-payg

## Why

La instancia Ampere A1 **Always Free** del entorno `dev` no se podía aprovisionar: Oracle devolvía `Out of host capacity` de forma persistente **incluso con la home region ya en Frankfurt** — es decir, dejó de ser un problema de región (la home region es inmutable sin recrear la cuenta, y ya estaba en la "buena") y pasó a ser la escasez de la cola de capacidad del free tier puro. Esto activa el **criterio de revisión #1 y #5 del `docs/adr/0001-dev-hosting-provider.md`**.

Se reabrió el debate de proveedor con **precios verificados a 2026-07-21** (no las cifras del ADR original): Hetzner subió precios dos veces en 2026 y renombró shapes — el tier de 8 GB es ahora **CX33 ~€9 neto** (no €5,49) más backend de state propio; AWS Lightsail 8 GB **~$44/mes** (no $24) y su free tier es crédito con caducidad; alternativas nuevas **Contabo ~€4-5/8 GB** y **Netcup ~€6-10**. La conclusión de la comparativa fue **quedarse en Oracle vía Pay-As-You-Go** en lugar de cambiar de proveedor: es la única opción a **$0/mes con cero reescritura** (reutiliza el Terraform `oci` ya escrito y su backend de state nativo) y ataca directamente el bloqueo real (capacidad), ya que PAYG da prioridad de aprovisionamiento A1. Hetzner/Contabo quedan documentados como fallback si Oracle deja de ser viable.

Este change **reconcilia el entorno `dev`** con esa decisión: formaliza el paso a PAYG, redimensiona la instancia ya desplegada, y ajusta el pipeline para que GitHub Actions gestione la infra a partir de ahora sin destruir la máquina conseguida.

## What changes

Tras este change, el entorno `dev` corre sobre una tenancy **Oracle PAYG** (conservando toda la capa gratuita a $0), con la instancia A1 redimensionada **in-place** a 4 OCPU / 24 GB / 200 GB de boot volume; el workflow `infra-dev.yml` fija el Availability Domain real de la máquina (AD-3) para no recrearla, quedando GitHub Actions como el único gestor de cambios de infra; y el repositorio queda blindado contra fuga de credenciales de backend y limpio de artefactos del bootstrap manual. La decisión queda registrada en el ADR 0001 (addendum del criterio de revisión #5), la spec de infra y el steering.

## Requirements

### R1 — Tenancy en PAYG conservando la capa gratuita a coste $0

**As a** responsable de infra, **I want** operar `dev` sobre una tenancy Pay-As-You-Go que conserve la capa gratuita, **so that** obtengo prioridad de capacidad A1 y protección frente a la reclamación de instancias ociosas sin dejar de pagar $0.

Acceptance criteria:

1. WHERE la tenancy está en PAYG, THE SYSTEM SHALL seguir disponiendo de todos los recursos Always Free (A1, block storage, IP pública, egress) sin cargo mientras el uso se mantenga dentro de los límites gratuitos.
2. WHEN el uso mensual del entorno `dev` se mantiene dentro de los límites Always Free, THE SYSTEM SHALL generar una factura de 0 €/$ por cómputo, storage, IP y egress.
3. THE SYSTEM SHALL documentar que el cambio a PAYG es de un solo sentido a nivel de tipo de cuenta (no hay downgrade a Always Free-only), con la única vía de "dejar de pagar" siendo terminar los recursos de pago y permanecer dentro de límites gratuitos.

### R2 — Instancia dev redimensionada in-place a 4 OCPU / 24 GB / 200 GB

**As a** responsable de infra, **I want** la instancia a 4 OCPU / 24 GB con 200 GB de disco, **so that** el stack completo (backend+worker+frontend+Postgres+Redis) tiene holgura, aprovechando el grant free que esta cuenta PAYG conserva a €0.

Acceptance criteria:

1. THE SYSTEM SHALL definir la instancia con `shape_config` de 4 OCPU y 24 GB y un boot volume de 200 GB (cupo free de block storage).
2. WHEN se aplica el cambio de tamaño sobre la instancia existente, THE SYSTEM SHALL hacerlo **in-place** (`terraform plan` reporta `0 to destroy`), nunca por destrucción y recreación.
3. WHERE el boot volume crece a 200 GB, THE SYSTEM SHALL documentar el paso de expansión de la partición en el SO (`oci-growfs`/`growpart`) requerido tras el `apply` para que el espacio sea usable.

### R3 — Reconciliación del pipeline y GitHub Actions como único gestor de infra

**As a** responsable de infra, **I want** que el pipeline opere la máquina existente sin moverla de Availability Domain, **so that** los cambios futuros no la destruyan reintroduciendo la ruleta de capacidad.

Acceptance criteria:

1. THE SYSTEM SHALL fijar el default de `ad_number` del workflow `infra-dev.yml` al AD real de la instancia (AD-3), documentando que cambiarlo fuerza destrucción + recreación.
2. WHEN se ejecuta el `workflow_dispatch` de `apply` con el `ad_number` por defecto sobre el estado remoto vigente, THE SYSTEM SHALL producir un plan sin destrucción de la instancia.
3. THE SYSTEM SHALL establecer GitHub Actions (`workflow_dispatch`) como la vía de cambios de infra a partir de este change; los `terraform apply` locales quedan reservados a bootstrap excepcional.

### R4 — Salvaguarda de facturación PAYG (alerta de presupuesto)

**As a** responsable de infra, **I want** una alerta de presupuesto activa, **so that** cualquier cargo por exceder los límites free se detecta de inmediato bajo PAYG.

Acceptance criteria:

1. THE SYSTEM SHALL desplegar un `oci_budget_budget` mensual con una `oci_budget_alert_rule` de tipo `ACTUAL` sobre el compartment de `dev`.
2. IF no se proporciona un destinatario de la alerta, THEN THE SYSTEM SHALL rechazar el `plan`/`apply`.

### R5 — Higiene de repositorio y secretos

**As a** responsable de infra, **I want** el repositorio blindado contra fuga de credenciales y limpio de artefactos del bootstrap manual, **so that** el bootstrap a mano no ensucia lo que el repo debe contener para operar por pipeline.

Acceptance criteria:

1. THE SYSTEM SHALL ignorar en git todo fichero `*.hcl` (incluidos typos como `backekn.hcl` que contendrían credenciales del backend) salvo `.terraform.lock.hcl`, además de `*.tfvars` (salvo `*.example`), `*.pem` y `*.log`.
2. THE SYSTEM SHALL eliminar del working tree los artefactos del bootstrap manual sin valor versionable (`oci_provision.log`, `backekn.hcl` duplicado).
3. THE SYSTEM SHALL mantener `apply_loop.sh` fuera del repositorio (gitignored), por ser una herramienta de bootstrap manual cuya re-ejecución sobre la máquina existente es destructiva.
4. THE SYSTEM SHALL garantizar que ninguna credencial real (`dev.tfvars`, `backend.hcl`, claves privadas) esté versionada en el historial.

### R6 — Registro de la decisión en la documentación

**As a** miembro del proyecto, **I want** la decisión reflejada en el ADR, la spec y el steering, **so that** el porqué del pivote a PAYG queda trazable y las specs no divergen del despliegue real.

Acceptance criteria:

1. THE SYSTEM SHALL añadir al `docs/adr/0001-dev-hosting-provider.md` un addendum fechado que registre la activación del criterio de revisión #5 (paso a PAYG), el resultado del debate reabierto (precios 2026 verificados, se mantiene Oracle) y la nueva configuración (4/24/200, AD-3).
2. THE SYSTEM SHALL actualizar la spec `sdd/specs/infra-dev-terraform.md` y el steering `sdd/steering/infra.md` de "2 OCPU/12 GB Always Free" a "4 OCPU/24 GB/200 GB en tenancy PAYG, AD-3", conservando la tabla comparativa como histórico.

## Out of scope

- **Staging/prod**: siguen sin decisión de proveedor propia; este change es solo `dev`.
- **Despliegue de la app por SSH** (`docker compose pull && up -d`): workflow futuro, fuera de alcance como en `infra-dev-terraform`.
- **Migración a otro proveedor** (Hetzner/Contabo): documentados como fallback en el ADR, no se implementan aquí.
- **El click de upgrade a PAYG en la consola de Oracle**: acción manual del usuario (ya realizada), no automatizable por Terraform.
- **Cambiar la home region / recrear la cuenta**: descartado (Frankfurt ya era la buena; PAYG es el fix, no la región).

## Affected specs

- `sdd/specs/infra-dev-terraform.md` — modificar (dimensionamiento 2/12→4/24, boot volume 200 GB, tenancy PAYG, AD-3 fijado, default de `ad_number`).
- `docs/adr/0001-dev-hosting-provider.md` — addendum (no es una spec de `sdd/specs/`, pero es el documento de decisión que este change actualiza; criterio de revisión #5).
- `sdd/steering/infra.md` — actualizar la decisión de `dev` (Always Free → PAYG) manteniendo la tabla comparativa histórica.
