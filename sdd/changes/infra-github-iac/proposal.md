# Proposal: infra-github-iac

## Why

Hoy, varios ajustes del lado GitHub del repo `autohostai-labs/AutoHostAI` viven solo en la consola — se ponen a mano con `gh secret set` o haciendo clic en *Settings*: secrets/variables de Actions (credenciales OCI, `GH_APP_PRIVATE_KEY`, el token de pull de GHCR, etc.), instalación de la GitHub App sobre el repo, acceso a packages (GHCR), y ciertos settings del repo (descripción, topics, rama por defecto). Cuando entra un operador nuevo o rota un secret, el único camino es `gh secret set ...` contra el repo vivo, sin revisión, sin diff, sin manera de detectar drift. `app-deploy-dev` pagó ese coste en 2026-07-29, y la norma IaC-first de `steering/infra.md` ya lo declara: *"todo lo demás es código, incluido lo GitHub-side"*. Este change lo hace real: el mismo Terraform que aprovisiona la VM, el Vault y los secrets ahora también aprovisiona la superficie GitHub-side del repo, cerrando el objetivo explícito del feature — *"poder desplegar de 0 todo usando terraform"*. El bootstrap irreducible (crear la org, crear la GitHub App, generar su clave privada) sigue siendo un paso manual único documentado, porque la API de GitHub no permite crearlos headless.

`fuente:` `sdd/roadmap/infra-github-iac.md` (entrada de roadmap) + `sdd/steering/infra.md` (norma IaC-first + bootstrap irreducible) + `docs/adr/0002-github-org-hosting.md` (consecuencias Free-tier).

## What changes

Un nuevo root module de Terraform `infra/github/`, ortogonal a los módulos por entorno en `infra/environments/<env>/` (siguiendo la convención de layout de `steering/infra.md`), que usa el provider `integrations/github` para declarar la superficie GitHub-side como código: settings del repo (descripción, topics, rama por defecto, visibilidad), secrets/variables de Actions (reflejando la tabla de `infra/environments/dev/README.md` §"Secrets de GitHub Actions esperados" y las variables de `app-deploy-dev`), instalación de la GitHub App sobre el repo, acceso a packages (GHCR) y branch protections (best-effort dentro del techo Free de `ADR 0002`). La autenticación del provider usa la **misma GitHub App** que ya existe en la org y que `infra/environments/dev/cloud-init.yaml.tftpl` usa para mintear el installation token del runner — la App tiene los permisos que el provider requiere, y no se introduce un mecanismo de auth nuevo. El módulo se valida en CI con un workflow `pull_request` sobre `infra/github/**` (mismo patrón que `.github/workflows/infra-dev.yml`). El bootstrap irreducible (org, GitHub App, clave privada) se condensa en una sección única del nuevo `infra/github/RUNBOOK.md`, y `infra/environments/dev/RUNBOOK.md` §6 pasa a referenciarlo.

## Requirements

### R1 — Declarar el módulo Terraform para la parte GitHub-side

**As a** operador del proyecto, **I want** un módulo Terraform separado en `infra/github/` que gestione los recursos GitHub como código, **so that** la superficie GitHub-side quede en el mismo flujo de revisión y `apply` que el resto de la infra, y se pueda detectar drift con un `terraform plan`.

Aceptación:

1. WHEN se ejecuta `terraform plan`/`apply` en `infra/github/`, THE SYSTEM SHALL declarar el provider `integrations/github` autenticado por la GitHub App existente (la misma App que usa `infra/environments/dev/cloud-init.yaml.tftpl` para mintear el installation token del runner — sus `app_id` y `installation_id` llegan por variable, y la clave privada se lee del Vault por instance principal igual que en el deploy actual).
2. THE SYSTEM SHALL situar el módulo como un nuevo root module paralelo a `infra/environments/<env>/`, **no dentro** de ninguno, porque la superficie GitHub-side es por-organización y no por-entorno — coherente con la convención de layout de `steering/infra.md`.
3. THE SYSTEM SHALL parametrizar el nombre del owner/organization y el nombre del repo (`autohostai-labs/AutoHostAI`) por variable, no por literal, para que el módulo sea reusable si en el futuro hay otro repo que compartir.
4. THE SYSTEM SHALL generar `terraform plan` reproducible (sin timestamps en atributos que los produzcan, sin `name` derivados de la hora), de modo que el PR del módulo muestre solo el diff real y no ruido de planificación.
5. IF la GitHub App de autenticación no tiene los permisos que el provider `integrations/github` requiere para los recursos que el módulo declara (típicamente `repository: read/write`, `members: read`, `packages: read/write` cuando aplique), THEN THE SYSTEM SHALL hacer fallar el `plan` nombrando el permiso ausente, **no** continuar y dejar un `apply` a medias.

### R2 — Gestionar los settings del repo como código

**As a** operador del proyecto, **I want** que la descripción, los topics, la rama por defecto, la visibilidad y el resto de settings del repo vivan en Terraform, **so that** un cambio de setting sea un PR revisable, no un clic en la consola.

Aceptación:

1. THE SYSTEM SHALL declarar los settings del repo (`description`, `homepage` cuando exista, `topics`, `visibility = "private"`, `default_branch = "main"`, `has_issues`, `has_projects`, `has_wiki`, `archived`, y los flags de merge que el repo enforce hoy) como recursos del provider `integrations/github` en su versión vigente.
2. WHEN el módulo se aplica sobre el repo ya existente en `autohostai-labs`, THE SYSTEM SHALL producir un `plan` con diff **vacío** sobre esos settings — el módulo los modela, no los reconfigura; verificable con `terraform plan` contra el estado real.
3. THE SYSTEM SHALL NOT incluir la **creación** del repo en Terraform (eso es bootstrap irreducible — ver R6): el módulo asume el repo ya transferido a `autohostai-labs` y solo gestiona sus settings a partir de ahí.

### R3 — Gestionar los secrets y variables de Actions como código

**As a** operador del proyecto, **I want** que los secrets y variables que el CD y el pipeline de infra consumen estén declarados en Terraform, **so that** añadir un secret nuevo, rotar uno existente o detectar drift sea `terraform plan` + PR, no `gh secret set` contra la consola.

Aceptación:

1. THE SYSTEM SHALL declarar como `github_actions_secret` los secretos listados en `infra/environments/dev/README.md` §"Secrets de GitHub Actions esperados" (`OCI_TENANCY_OCID`, `OCI_USER_OCID`, `OCI_FINGERPRINT`, `OCI_REGION`, `OCI_PRIVATE_KEY`, `OCI_COMPARTMENT_OCID`, `TFSTATE_NAMESPACE`, `TFSTATE_BUCKET`, `ALLOWED_SSH_CIDRS`, `ALLOWED_SSH_CIDRS_WIDE`, `SSH_PUBLIC_KEYS`, `GH_APP_PRIVATE_KEY`), con valores leídos de variables Terraform **marcadas sensibles** y nunca impresos en `output`.
2. THE SYSTEM SHALL declarar como `github_actions_variable` las variables no sensibles que el CD y el pipeline de infra consumen explícitamente: las de `app-deploy-dev` (`GH_APP_ID`, `GH_APP_INSTALLATION_ID`, `NEXT_PUBLIC_APP_ENV`, `PUBLIC_HOSTNAME`), más cualquier otra variable que aparezca en `vars:` o `env:` de los workflows de `.github/workflows/` (verificable con `gh variable list` + lectura de los YAML).
3. THE SYSTEM SHALL NO copiar valores al `tfstate` plano cuando un secret venga de otra fuente ya aprovisionada (Vault, `oci_vault_secret`): el módulo **referencia** el valor por nombre de secreto en el Vault o por atributo de otro recurso, nunca inline. Es el mismo principio que `infra-dev-terraform` §"Almacén de objetos de medios" sigue con los cuatro secretos de medios.
4. THE SYSTEM SHALL NO duplicar en `github_actions_secret` los secretos que ya viven en el Vault y que la aplicación lee por instance principal (los `oci_vault_secret` de runtime — `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, los cuatro de medios, los seis `SMTP_*`, el token del túnel, `DEMO_ACCOUNT_PASSWORD`): la fuente de verdad de qué va al Vault es `infra-dev-terraform` y `app-deploy-dev`, y duplicarlos en Actions abriría una superficie de drift adicional sin valor.
5. WHEN un secret se declare con valor sensible, THE SYSTEM SHALL garantizar que su valor no aparece en `output` ni en el `tfplan` — los recursos `github_actions_secret` del provider lo gestionan; verificable con `terraform show -json | jq '.planned_values'` y comprobando que el campo está enmascarado.

### R4 — Gestionar la instalación de la GitHub App y el acceso a packages (GHCR) como código

**As a** operador del proyecto, **I want** que la GitHub App quede instalada en el repo y el acceso a packages (GHCR) gestionado desde Terraform, **so that** un repo recién transferido o una reinstalación del runner no exijan clics en la consola.

Aceptación:

1. THE SYSTEM SHALL declarar la instalación de la GitHub App sobre el repo con el recurso equivalente del provider `integrations/github` (`github_app_installation_repositories` en la versión vigente del provider), referenciando la App por su `app_id` y el repo por su nombre completo (`autohostai-labs/AutoHostAI`).
2. THE SYSTEM SHALL declarar los permisos del repo sobre packages (GHCR) con el recurso del provider `integrations/github` que corresponda, de modo que el CD (`deploy-dev.yml`) pueda hacer `docker push` a `ghcr.io/autohostai-labs/*` desde el runner self-hosted — verificable con un push de prueba ejecutado por un workflow `pull_request` que use una imagen de prueba con etiqueta efímera y la borre al terminar.
3. THE SYSTEM SHALL NO crear la GitHub App desde Terraform (bootstrap irreducible — la API de GitHub no lo permite headless); el módulo asume que la App existe y se identifica por `app_id`/`installation_id` aportados como variables.
4. THE SYSTEM SHALL NO crear la organización desde Terraform (bootstrap irreducible — `ADR 0002`); el módulo asume que `autohostai-labs` existe y que el repo está transferido.

### R5 — Declarar las branch protections como código, dentro del techo del plan Free

**As a** revisor del proyecto, **I want** que las reglas de protección de rama que el plan Free permita estén declaradas en Terraform, **so that** el "PR revisado antes de merge" del RUNBOOK quede anclado a un recurso versionado y no a una convención oral.

Aceptación:

1. THE SYSTEM SHALL declarar `github_branch_protection` (o el recurso equivalente del provider vigente) sobre `main` con las reglas que el plan Free soporte: required status checks (los checks que `infra-dev.yml`, `deploy-dev.yml` y los demás workflows relevantes expongan en `permissions`/`checks`), required linear history, y la prohibición de bypass por administradores si el provider/API lo permite en el tier Free.
2. WHERE la API de GitHub rechace alguna regla por el límite del plan Free (documentado en `ADR 0002` §"Consecuencias": branch protection con required reviewers requiere Pro/Team), THE SYSTEM SHALL dejar constancia del rechazo en el `plan` (no fallar) y reflejarlo en una sección del RUNBOOK que diga exactamente qué reglas quedan enforced técnicamente y cuáles siguen siendo solo convención.
3. THE SYSTEM SHALL NO sustituir el gate de aprobación humano por reglas automáticas — el gate sigue siendo "review del PR + apply manual desde main" según `RUNBOOK.md` §0; este R solo automatiza lo automatizable.

### R6 — Documentar el bootstrap irreducible en un único RUNBOOK

**As a** operador nuevo o que rota credenciales, **I want** un único RUNBOOK que liste los pasos irreducibles a mano (org, App, clave privada) y los pasos que Terraform ya cubre, **so that** nadie tenga que recombinar lo que vivía disperso entre `RUNBOOK.md` §6 (App, runner), la nota de `steering/infra.md` (org) y lo que se asumía implícito.

Aceptación:

1. THE SYSTEM SHALL mantener `infra/github/RUNBOOK.md` (nuevo) con tres secciones numeradas — *"Bootstrap irreducible (a mano, una vez)"*, *"Lo que Terraform ya cubre"*, *"Rotación"* — cubriendo: creación de la organización, creación de la GitHub App con sus permisos (`administration: write` para registrar runners; los permisos extra que requiera el provider `integrations/github` para los recursos de R2–R5: `repository: read/write`, `members: read`, `packages: read/write` cuando aplique), generación de la clave privada `.pem` (y rotación), y dónde se inyectan `GH_APP_ID`/`GH_APP_INSTALLATION_ID`/`GH_APP_PRIVATE_KEY` como variables de Terraform.
2. THE SYSTEM SHALL mantener `infra/environments/dev/RUNBOOK.md` §6 con la **misma información operativa que tiene hoy** — el comportamiento del runner, registro, rollback, dependencias con el Vault — y añadir solo una referencia cruzada al nuevo `infra/github/RUNBOOK.md` para que la fuente única de los pasos irreducibles sea el nuevo. La fuente de verdad de "cómo se opera el runner" no cambia de sitio.
3. THE SYSTEM SHALL NO incluir ningún valor real de credencial, OCID, fingerprint ni clave privada en el RUNBOOK; los placeholders apuntan a los `secret`/`variable` ya aprovisionados (R3).

### R7 — Validación automática en CI + verificación "deploy from zero"

**As a** revisor, **I want** que cualquier cambio en `infra/github/**` se valide en CI y que exista una verificación end-to-end de que se puede desplegar todo desde cero con Terraform, **so that** el cambio cumpla la norma IaC-first y el objetivo explícito del feature.

Aceptación:

1. WHEN se abre/actualiza un PR que toca `infra/github/**`, THE SYSTEM SHALL ejecutar un job `check` (`terraform fmt -check`, `init -backend=false`, `validate`), sin ningún secret, en `ubuntu-latest` (no necesita el runner self-hosted — no toca nada real), siguiendo el patrón del job `check` de `.github/workflows/infra-dev.yml`.
2. WHEN se dispara `workflow_dispatch` con `action: plan`/`apply` sobre el workflow de `infra/github/`, THE SYSTEM SHALL ejecutarlo en el runner self-hosted `[self-hosted, dev]` (mismo runner que `infra-dev.yml` y `deploy-dev.yml`, según `app-deploy-dev` y `ci-runner-self-hosted`), **solo desde `main`**, con `concurrency` (serializa applies) y `timeout-minutes`, igual que `infra-dev.yml`.
3. THE SYSTEM SHALL producir un run documentado de "deploy from zero" como artefacto del change: un run del workflow `infra/github` con `apply` real contra la org/repo, seguido de un `terraform plan` posterior que muestre **diff vacío** sobre todos los recursos gestionados en R2–R5. El run se enlaza desde la sección "Estado" de las specs que se modifiquen al archivar.
4. THE SYSTEM SHALL NO permitir un `apply` desde una rama que no sea `main` (gate `if: github.ref == 'refs/heads/main'`) — `ingress-https-dev` añadió este gate al `plan` y se mantiene para el `apply`, porque desde `app-deploy-dev` el `apply` recibe credenciales con control del DNS y del repo.

## Out of scope

- **Creación de la organización, la GitHub App y su clave privada** — bootstrap irreducible, no codificable por la API de GitHub. Va al RUNBOOK (R6), no a Terraform.
- **Gestión de runners self-hosted** — viven acoplados al ciclo de vida de la VM (su registro se destruye con la VM y se re-crea en el siguiente `cloud-init`); viven en `infra/environments/dev/`. Moverlos a `infra/github/` crearía un acoplamiento de orden entre los dos módulos sin un beneficio claro, y la cantidad de runners por VM es un ajuste del módulo dev, no de la org.
- **`staging`/`prod`** — cada entorno tiene su propio root module por convención; cuando se decida proveedor cloud para ellos, su GitHub-side (si difiere) entra en su propio change.
- **Branch protection con required reviewers** — límite del plan Free documentado en `ADR 0002`. R5 automatiza hasta donde se puede; el resto sigue siendo convención.
- **Migración de los secrets ya creados a mano a Terraform** — R3 los declara, pero la primera aplicación es una **importación**: el `plan` mostrará `create` para cada secret hasta que se ejecute `terraform import` (o el equivalente del provider). El procedimiento exacto se fija en `design.md` y se ejecuta en `/sdd:run`, no ahora.
- **Adopción del provider `cloudflare` adicional al ya en uso** — fuera de scope; `infra/environments/dev/main.tf` ya lo usa.

## Affected specs

- `sdd/specs/infra-scaffold.md` — añadir referencia al nuevo root module `infra/github/` y a su convención de layout (paralelo a `environments/<env>/`, no dentro).
- `sdd/specs/infra-dev-terraform.md` — añadir a "Pendiente" que el lado GitHub vive ahora en `infra/github/`, no en este módulo; referenciar el change desde aquí. La spec no pierde requisitos propios (la tabla de secrets de `README.md` sigue siendo la fuente de la lista que R3 importa), pero queda apuntando al módulo nuevo para evitar confusión.
- `sdd/specs/app-deploy-dev.md` — la **declaración** de qué secrets/variables de Actions existen pasa a `infra/github/`; este spec mantiene el comportamiento de cómo se consumen en runtime (Vault, instance principal, GitHub App en el cloud-init), pero la fuente de verdad del inventario se desplaza. El cambio se refleja en la sección "Estado" al archivar.
- `sdd/steering/infra.md` — añadir una nota bajo "Lección de `app-deploy-dev`" confirmando que el provider `github` ya está adoptado (la nota de "cambio futuro pendiente" queda obsoleta al archivar este change).