# Design: frontend-docker-deps-autosync

## Context

El contenedor `frontend` (target `dev` de `frontend/devops/Dockerfile`) monta el código vía bind mount (`./frontend:/app`) y protege `node_modules` con un volumen nombrado `frontend_node_modules:/app/node_modules` (docker-compose.yml, patrón descrito en spec `local-environment`). La imagen instalaba las deps con `npm install` en la etapa `deps`. El volumen nombrado se llena **una sola vez** desde la imagen la primera vez que arranca el contenedor y luego persiste: reconstruir la imagen no refresca un volumen ya poblado, así que al añadir una dependencia (`@radix-ui/react-dialog`, usada por `frontend/components/ui/sheet.tsx`) el volumen se queda sin ella y la compilación falla con `Module not found`. Turbopack (Next.js 16) exige además que `node_modules` sea resoluble **dentro** del root del proyecto que compila.

## Decisions

### D1 — Entrypoint que sincroniza node_modules con el lockfile en cada arranque

**Chosen:** un `frontend/devops/docker-entrypoint.sh` (usado como `ENTRYPOINT` solo en el stage `dev`) compara `sha256sum package-lock.json` con un hash guardado en `node_modules/.lock-hash`; si difieren (o falta `node_modules`), ejecuta `npm ci` y reescribe el hash; si coinciden, no hace nada y arranca `next dev`. Resuelve la causa raíz sin tocar la topología de volúmenes: el volumen persistente sigue existiendo pero se mantiene al día automáticamente, y `node_modules` permanece en `/app` (compatible con Turbopack). Añadir/actualizar deps solo requiere `docker compose up`/`restart`.

Rejected: **mover `node_modules` a un directorio padre** (`/deps`, fuera del bind mount) — probado y descartado: Turbopack solo compila dentro del root del proyecto y no resuelve `node_modules` externos (`Next.js inferred your workspace root … files outside of the project directory will not be compiled`).
Rejected: **volumen anónimo + `docker compose up -V`** — sigue exigiendo recordar un flag manual; no cumple "cero intervención".
Rejected: **`npm install` en el entrypoint siempre** — más lento y no determinista; se prefiere `npm ci` condicionado por hash.

### D2 — `npm ci` en vez de `npm install`

**Chosen:** la etapa `deps` de la imagen y el entrypoint instalan con `npm ci` a partir de `package-lock.json` (build reproducible, falla si package.json/lock están desincronizados). La imagen guarda el hash del lockfile (`… > node_modules/.lock-hash`) tras `npm ci`, de modo que en el primer arranque el volumen poblado desde la imagen ya trae el hash y el entrypoint no reinstala de más.

Rejected: mantener `npm install` — resolución no determinista entre entornos, contrario a un CI/CD fiable.

### D3 — Alcance limitado al stage `dev`

**Chosen:** el `ENTRYPOINT` se define solo en el stage `dev`. El stage `prod` (imagen standalone sin bind mount ni volumen) ya hornea las deps y queda intacto — su comando sigue siendo `node server.js`.

Rejected: entrypoint común a dev y prod — innecesario en prod y añadiría arranque condicional inútil.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Imagen frontend (dev) | `frontend/devops/Dockerfile` | `npm install` → `npm ci`; guardar hash del lockfile; `COPY` del entrypoint + `chmod`; `ENTRYPOINT` en stage `dev` |
| Entrypoint dev | `frontend/devops/docker-entrypoint.sh` (nuevo) | script de sincronización por hash del lockfile |

No cambia `docker-compose.yml` (el volumen `frontend_node_modules` y los mounts ya eran correctos) ni `frontend/next.config.ts`.

## Data & interfaces

- Sin cambios de esquema ni de API. Sin nuevas variables de entorno.
- Nuevo artefacto interno: `node_modules/.lock-hash` (marcador en el volumen, no versionado).
- Sin nuevas dependencias npm (el fix es de tooling de contenedor).

## Risks & mitigations

- **Primer arranque tras el fix reinstala una vez** si el volumen viejo no trae `.lock-hash`: coste puntual aceptable; luego los arranques son instantáneos. Mitigación adicional: recrear el volumen (`docker volume rm …_frontend_node_modules`) parte de un estado limpio.
- **`npm ci` requiere lockfile en sync**: si alguien edita `package.json` sin regenerar el lockfile, el arranque falla explícitamente — comportamiento deseado (falla ruidosa > estado inconsistente).
- **Coste de arranque**: acotado por el hash-check; solo reinstala cuando el lockfile cambia (R3).

## Open questions

Ninguna — el enfoque quedó validado durante la implementación (arranque limpio a 200, y prueba de sincronización automática al invalidar el hash).
