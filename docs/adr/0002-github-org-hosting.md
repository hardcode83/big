# 0002 — Hosting del repositorio en una organización GitHub propia

## Estado

Aceptado — 2026-07-29.

## Contexto

El repositorio `AutoHostAI` se creó bajo la **cuenta personal de Marta (`mreyesojeda`)**, con Jose (`hardcode83`) como colaborador con permiso `push`. Al implementar el CD del change `app-deploy-dev` (runner self-hosted + GitHub App + GHCR), varias operaciones requerían ser **admin del repo** (instalar la GitHub App, registrar runners self-hosted, gestionar packages). En un repositorio de **cuenta personal** GitHub no ofrece rol admin para colaboradores — admin es exclusivo del dueño de la cuenta —, así que Jose no podía administrar el CD sin depender de Marta para cada paso.

Esto choca con la norma que el equipo adoptó a raíz de este flujo (ver `sdd/steering/infra.md`, "infraestructura como código, sin cambios a mano"): el objetivo es poder **operar y redesplegar la infra sin depender de acciones manuales de terceros**.

Es un proyecto **de dos** (Marta tuvo la idea y creó el repo; Jose lo desarrolla): ambos deben tener el mismo poder sobre él.

## Decisión

**Crear una organización GitHub en plan Free (`autohostai-labs`) con Marta y Jose como owners, y transferir el repo a `autohostai-labs/AutoHostAI`.**

- El rol **Admin** granular (que no existe en repos de cuenta personal) sí está disponible en repos de organización, incluido el plan **Free**.
- Ambos owners → ambos pueden instalar Apps, registrar runners y gestionar packages: **sin dependencia unidireccional**.
- La transferencia la inició Marta (dueña original); GitHub mantiene un redirect de la URL antigua. Las imágenes GHCR pasan al namespace `ghcr.io/autohostai-labs/*` (el workflow usa `github.repository_owner`, se adapta solo); se actualizaron `github_repo` (default), el remote y las docs.

## Alternativas consideradas

- **Dejarlo en la cuenta personal de Marta** — statu quo; imposible que Jose sea admin (limitación de repos personales). Rechazada.
- **Transferir a la cuenta personal de Jose (`hardcode83`)** — invierte el problema: Marta quedaría como mera colaboradora `push`, sin admin. Rechazada (proyecto de dos).
- **Org `indivi`** (existe) — sería el hogar "institucional" si el proyecto fuera de la empresa, pero Jose no es miembro con acceso y no es (aún) un proyecto de indivi. Rechazada por ahora.
- **Org `Arch-tech-io`** (Jose es *member*, no owner) — cambiaría la dependencia de Marta por la del owner de esa org. Rechazada.

## Consecuencias

- **Positivas:** ambos son admin; el CD y futuros entornos se operan sin pasos manuales ajenos; el plan Free no recorta cuotas relevantes vs. cuenta personal (Actions 2.000 min/mes privado, Packages 500 MB — iguales; runners self-hosted ilimitados). Base para gestionar la parte GitHub-side como código (provider `github`).
- **Bootstrap irreducible (a mano, documentado):** crear la org y la GitHub App + su clave privada siguen siendo pasos manuales one-time (GitHub no permite crearlos headless) — ver `sdd/steering/infra.md`.
- **A vigilar:** branch protection / required reviewers en repos privados sigue necesitando plan de pago (igual que antes; el gate sigue siendo review de PR + apply manual). Si el proyecto pasa a ser de empresa, se puede transferir el repo a la org de indivi o renombrar.
- **Marca:** existe una empresa homónima "Autohost/AutohostAI" en GitHub (handle `autohostai` ocupado) — de ahí el sufijo `-labs`; a tener en cuenta para el naming del producto a futuro.

## Trazabilidad

Ejecutado durante `app-deploy-dev` (archivado en `sdd/changes/archive/2026-07-29-app-deploy-dev/`). No tuvo su propio ciclo SDD por ser una decisión de hosting/ownership que surgió a mitad de ese change; se registra aquí como ADR, en línea con `0001-dev-hosting-provider.md`.
