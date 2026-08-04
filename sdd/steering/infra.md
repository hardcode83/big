---
applies_to: ["infra/**"]
---

# Infra — AutoHostAI

Convención de despliegue remoto. Herramientas ya confirmadas: **Terraform** (IaC) + **GitHub Actions** (CI/CD). Proveedor cloud: **decidido para `dev`** (Oracle Cloud, VM única + docker-compose — ver `docs/adr/0001-dev-hosting-provider.md`); **staging/prod siguen sin elegir**, decisión propia y futura, no heredada de dev. Nada de esto sustituye al stack local (`docker-compose`/`Makefile`, ver spec `local-environment`).

## Norma innegociable: infraestructura como código (IaC-first)

**Toda la infraestructura y su configuración se define como código** — Terraform para el cloud (OCI), y para **GitHub** el provider `integrations/github` y/o ficheros versionados (workflows, scripts). **Prohibido configurar a mano** en las consolas de OCI o GitHub salvo el *bootstrap irreducible* de abajo. Cualquier paso que hoy no puedas codificar debe quedar como **script versionado** (p. ej. `runner-bootstrap.sh`) o documentado en el RUNBOOK — nunca configuración ad-hoc que solo viva en una consola.

**Bootstrap irreducible** (se hace una vez, a mano, y se **documenta**; no hay forma de codificarlo porque emite credenciales o crea la raíz):
- Crear la **organización** GitHub y la **cuenta**/tenancy cloud.
- Crear la **GitHub App** y generar su **clave privada** (la API de GitHub no permite crearla headless).
- La **API key raíz de OCI** del usuario de servicio y el **bucket del tfstate** (dependencia circular con su propio state).
- El **dominio y su zona DNS** (hoy `digitalsec.work` en Cloudflare): registrar y delegar nameservers establece propiedad, no es codificable.
- El **API token de Cloudflare** del provider, con permisos mínimos `Account | Cloudflare Tunnel | Edit` + `Zone | DNS | Edit` + `Zone | Zone Settings | Edit`, acotado a esa zona (ver `RUNBOOK.md` §7.1). **No se copia al Vault**: su radio de daño es amplio y es re-emitible en segundos, así que una copia solo ampliaría la exposición sin aportar recuperación (change `ingress-https-dev`, ADR 0003).

  **Radio de daño, y no es solo la zona** (corregido en `ingress-https-hardening`, 2026-08-04): además de reescribir DNS y bajar el TLS de toda `digitalsec.work`, el token permite **publicar en internet cualquier dirección alcanzable desde el contenedor `cloudflared`**, porque la configuración de ingress del túnel es **remota** (`config_src = "cloudflare"`) — sin abrir un puerto, sin `apply` y sin rastro en el `tfstate` hasta el siguiente `plan`. El aislamiento de redes del compose de deploy saca de ahí `postgres`, `redis`, `backend`, `worker` y `migrate`, pero **queda residual, y parte de él es grave**: incluye el servicio de metadatos de la instancia, y por tanto credenciales que dan acceso a los secretos del Vault — de modo que datos que el aislamiento de red pone fuera de alcance siguen siendo alcanzables por otra vía.

  **La enumeración completa y autoritativa del radio vive en un solo sitio: [ADR 0003](../../docs/adr/0003-https-ingress-dev.md) §Addendum 2026-08-04 §1.** Esta regla **no la reformula a propósito** — durante `ingress-https-hardening` esa enumeración se corrigió tres veces y ninguna corrección acertó en todos los sitios donde estaba copiada, así que aquí solo consta la consecuencia normativa: **no se decide dónde vive este token, ni cómo se acota, ni qué se cuelga del túnel, sin leer antes esa tabla**.

## Decisión estable: el `apply` de infra no se protege con GitHub Environment

**Los jobs `plan` y `apply` del workflow de infra están acotados a `main` (`github.ref`), con `concurrency` y `timeout-minutes`, y NO se protegen además con un GitHub Environment con revisores requeridos.** Revisado y decidido el 2026-07-29: con dos owners y un `apply` que solo se dispara por `workflow_dispatch` manual desde `main`, se considera control suficiente. `environment:` nunca llegó a existir en los workflows: la entrada de `infra-dev-hardening` en el roadmap afirmaba que sí, y se corrigió el 2026-07-29 para reflejar el descarte.

No es un hallazgo pendiente: **su ausencia es deliberada**, y no debe reabrirse en cada revisión. Lo que sí es requisito es el gating por rama de **ambos** jobs — `plan` también, porque desde `ingress-https-dev` recibe un token con control del DNS de toda la zona y `sensitive = true` no protege frente a código de una rama no revisada.

**Todo lo demás es código**, incluido lo GitHub-side: secrets y variables de Actions (`github_actions_secret`/`github_actions_variable`), instalación de la App, ajustes de repo, acceso a packages, policies. La clave privada de la App / secrets se **inyectan** por variable y se escriben al Vault/secret-store desde Terraform (ver `security.md` §8, excepción dev/test).

**Lección de `app-deploy-dev` (2026-07-29):** se hicieron varios pasos a mano en GitHub (crear/instalar la App, poner variables/secrets con `gh`, transferir el repo, tocar acceso de packages) que en su mayoría **eran codificables** con el provider `github`. De aquí en adelante, gestionar la parte GitHub con Terraform (`github` provider) igual que la de OCI; dejar a mano solo el bootstrap irreducible. Adoptar el provider `github` es un change futuro pendiente (ver roadmap).

## Convención de layout

`infra/environments/<entorno>/` — un root module de Terraform por entorno (`dev`, `staging`, `prod`), cada uno con su propio state. Esto es ortogonal al layout de código por dominio de `backend`/`frontend` (ver `architecture.md`): la infra no se organiza por dominio de negocio (`auth`, `cleaning`, `reservations`, ...), sino por entorno y tipo de recurso.

Cuando exista código compartido entre entornos (red, base de datos, DNS...), irá en `infra/modules/` (módulos Terraform reutilizables) — **no creado todavía**, se añade cuando haya un primer módulo real que compartir.

## Criterio de decisión de proveedor cloud

### Decisión (dev)

**Oracle Cloud Infrastructure, VM única (Ampere A1) + docker-compose.** Justificación completa, alternativas consideradas (incluyendo Kubernetes) y riesgos aceptados en **`docs/adr/0001-dev-hosting-provider.md`**. **Addendum 2026-07-21** (change `infra-dev-payg`): ante el bloqueo persistente de capacidad de la Always Free (incluso en Frankfurt), la tenancy pasó a **Pay-As-You-Go conservando la capa gratuita a $0** (prioridad de capacidad A1); la instancia quedó en **4 OCPU/24 GB/200 GB, AD-3**. La tabla comparativa de abajo se mantiene como histórico de la investigación original. Fallback operativo documentado si el free tier de Oracle deja de ser fiable: Hetzner Cloud (fallback primario) o AWS Lightsail (fallback secundario, provider Terraform en tier oficial) — mismo modelo, sin cambio de ADR.

**Staging/prod: pendientes de decisión propia**, no asumir que esta elección se extiende a ellos — el ADR es explícito en que su alcance es solo `dev` (root module de Terraform independiente por entorno, ver "Convención de layout" arriba).

### Tabla comparativa (histórico de la investigación de mercado de `dev-hosting-provider`)

Se mantiene íntegra como referencia — incluye todos los candidatos investigados, no solo el elegido. Escala: 🟢 favorable · 🟡 riesgo gestionable · 🔴 desfavorable.

| Modelo | Candidato | Coste (0€ perm.?) | Terraform | Migración Docker | GitHub Actions/IaC | Postgres/Redis | Lock-in | Gate |
|---|---|---|---|---|---|---|---|---|
| VM | **Oracle Cloud (Ampere A1, Always Free) — elegido dev** | 🟢 0€/mes permanente | 🟢 Partner, activo | 🟡 Alto; riesgo ARM64 a verificar | 🟢 Total | 🟢 Autoalojado | 🟡 Bajo-medio (home region fija) | ✅ |
| VM | Oracle Cloud (AMD micro, Always Free) | 🟢 0€/mes | 🟢 igual | 🟢 Sin riesgo | 🟢 Total | 🟢 Autoalojado | 🟡 igual | Descartado por tamaño |
| VM | **Hetzner Cloud — fallback primario** | 🟡 ~€5,49/mes | 🟢 Partner, activo | 🟢 Alto, sin riesgo | 🟢 Total | 🟢 Autoalojado | 🟢 Bajo | ✅ |
| VM | Scaleway | 🟡 ~€16,79/mes | 🟢 Partner-premier | 🟢 Alto | 🟢 Total | 🟢 Autoalojado | 🟢 Bajo | ✅ |
| VM | DigitalOcean | 🟡 $24/mes | 🟢 Partner | 🟢 Alto | 🟢 Total | 🟢 Autoalojado | 🟢 Bajo | ✅ |
| VM | **AWS Lightsail — fallback secundario** | 🟡 $24/mes (sin free tier perm., crédito con caducidad desde jul-2025) | 🟢 Oficial | 🟢 Alto | 🟢 Total | 🟢 Autoalojado | 🟡 Bajo-medio | ✅ |
| VM | AWS EC2 | 🟡 $12-30/mes (mismo crédito no perm.) | 🟢 Oficial | 🟢 Alto (x86)/🟡 (ARM) | 🟢 Total | 🟢 Autoalojado | 🟡 Bajo-medio | ✅ |
| PaaS | Render | 🟡 ~$35-45/mes | 🟢 Oficial | 🟡 Medio | 🟢 Total | 🟢 Nativo | 🟡 Medio | ✅ |
| PaaS | Railway | 🟡 ~$5-20+/mes | 🔴 Community, parcial | 🟡 Medio | 🟡 Parcial | 🟡 Parcial | 🟡 Medio | ✅ (riesgo Terraform) |
| PaaS | Fly.io | 🔴 ~$50-70/mes | 🔴 Provider archivado (2024) | 🟢 Alto | 🔴 Sin Terraform viable | 🟡 MPG/3º | 🟡 Medio | ❌ Excluido |
| PaaS | Vercel | N/A | 🟡 Solo config. proyecto | 🔴 Requiere reescritura | 🔴 No cubre despliegue | 🔴 Vía 3º (Marketplace) | 🔴 Alto | ❌ Excluido |
| Serverless | AWS Fargate (ECS) | 🔴 ~$68-106/mes | 🟢 Oficial | 🟡 Medio | 🟢 Total | 🟡 Gestionado (RDS+ElastiCache) | 🟡 Medio | ✅ |
| Serverless | AWS App Runner | 🟡 ~$37-40/mes + Fargate | 🟢 Oficial | 🔴 No cubre worker solo | 🟢 Total | 🟡 Gestionado | 🟡 Medio-alto | ✅ técnico, no cubre stack solo |
| Serverless | GCP Cloud Run (+Worker Pools) | 🟡 ~$62-70/mes | 🟡 Oficial, Worker Pool sin confirmar en TF | 🟡 Medio | 🟢 Total | 🟡 Gestionado (Memorystore caro) | 🟢 Bajo | ✅ (riesgo IaC a verificar) |
| Kubernetes | AWS EKS | 🔴 ~$150-220/mes | 🟢 Excelente | 🔴 Alto esfuerzo | 🟢 Total | 🟡 Gestionado/PVC | 🟡 Medio | Rechazado (complejidad/coste prematuros) |
| Kubernetes | GCP GKE | 🔴 ~$95-140/mes | 🟢 Excelente | 🔴 Alto esfuerzo | 🟢 Total | 🟡 Gestionado/PVC | 🟡 Medio | Rechazado (complejidad/coste prematuros) |

Detalle completo de cada fila (fuentes, riesgos, cifras exactas) en `docs/adr/0001-dev-hosting-provider.md`. Cualquier `.tf` real (para cualquier entorno) requiere su propio change vía `/sdd:new` — no se escribe directamente sobre los placeholders de `infra/environments/`; para `dev`, ese change parte de la decisión de este ADR (incluye verificar/añadir build multi-arch ARM64 en CI antes del primer `apply`, ver Consecuencias del ADR).

## Integración futura con CI/CD

Un workflow de **GitHub Actions** (`.github/workflows/`, no creado todavía) ejecutará `terraform plan`/`terraform apply` contra `infra/environments/<entorno>/`, parametrizado por entorno. El disparador exacto (qué rama/evento dispara qué entorno) queda sin decidir — es una decisión de un change futuro, cuando exista el pipeline real.
