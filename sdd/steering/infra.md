---
applies_to: ["infra/**"]
---

# Infra — AutoHostAI

Convención de despliegue remoto. Herramientas ya confirmadas: **Terraform** (IaC) + **GitHub Actions** (CI/CD). Proveedor cloud **aún sin elegir** — ver criterio de decisión abajo. Nada de esto sustituye al stack local (`docker-compose`/`Makefile`, ver spec `local-environment`).

## Convención de layout

`infra/environments/<entorno>/` — un root module de Terraform por entorno (`dev`, `staging`, `prod`), cada uno con su propio state. Esto es ortogonal al layout de código por dominio de `backend`/`frontend` (ver `architecture.md`): la infra no se organiza por dominio de negocio (`auth`, `cleaning`, `reservations`, ...), sino por entorno y tipo de recurso.

Cuando exista código compartido entre entornos (red, base de datos, DNS...), irá en `infra/modules/` (módulos Terraform reutilizables) — **no creado todavía**, se añade cuando haya un primer módulo real que compartir.

## Criterio de decisión de proveedor cloud

**Estado: pendiente de decisión.** Ningún proveedor elegido todavía. Candidatos y criterios a evaluar cuando llegue el momento de desplegar de verdad:

| Criterio | AWS | Google Cloud | Vercel | Railway |
|---|---|---|---|---|
| Coste a escala de 2 viviendas | por evaluar | por evaluar | por evaluar | por evaluar |
| Postgres/Redis gestionado | sí (RDS, ElastiCache) | sí (Cloud SQL, Memorystore) | no nativo (requiere addon/terceros) | sí (plugins nativos) |
| Migración desde imágenes Docker de `local-environment` | directa (ECS/EKS/Fargate) | directa (Cloud Run/GKE) | requiere adaptar a su modelo de build | directa (despliega imágenes Docker) |
| Integración CI/CD (GitHub Actions) | buena, requiere IAM/OIDC | buena, requiere Workload Identity | nativa, muy simple | nativa, muy simple |
| Vendor lock-in | medio-alto si se usan muchos servicios gestionados | medio | alto (modelo de plataforma propio) | medio-alto |
| Madurez del provider de Terraform | oficial, muy maduro | oficial, muy maduro | oficial pero parcial (proyectos/env vars, no toda la plataforma) | comunitario, poco maduro |

Ningún candidato tiene "veredicto" todavía — esta tabla es el punto de partida para cuando el negocio necesite desplegar de verdad, no una recomendación. Cualquier `.tf` real (para cualquier entorno) requiere su propio change vía `/sdd-new`, una vez elegido proveedor — no se escribe directamente sobre los placeholders de `infra/environments/`.

## Integración futura con CI/CD

Un workflow de **GitHub Actions** (`.github/workflows/`, no creado todavía) ejecutará `terraform plan`/`terraform apply` contra `infra/environments/<entorno>/`, parametrizado por entorno. El disparador exacto (qué rama/evento dispara qué entorno) queda sin decidir — es una decisión de un change futuro, cuando exista el pipeline real.
