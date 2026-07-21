# Proposal: frontend-docker-deps-autosync

## Why

Al desplegar el frontend en el stack de dev aparece `Module not found: Can't resolve '@radix-ui/react-dialog'` (lo usa `components/ui/sheet.tsx`, añadido en `frontend-foundation`), aunque la dependencia **sí** está declarada en `package.json` y en `package-lock.json`. Causa raíz: el volumen nombrado `frontend_node_modules` (spec `local-environment`, sección "Stack local vía Docker Compose") se pobló una sola vez desde la imagen y **persiste desactualizado**: al añadir una dependencia, ni reconstruir la imagen refresca el volumen ya poblado, y `node_modules` queda sin el paquete nuevo. Esto rompe el arranque cada vez que cambian las dependencias del frontend y obliga a un `npm install`/`npm ci` manual dentro del contenedor — fricción que contradice el objetivo de que `docker compose up` "simplemente funcione". Fix pedido directamente por el usuario (no está en el plan original, añadido tras `frontend-foundation`).

## What changes

El contenedor `frontend` en target `dev` sincroniza automáticamente `node_modules` con el `package-lock.json` en cada arranque: un entrypoint compara el hash del lockfile con el de lo instalado y ejecuta `npm ci` solo cuando difieren. La imagen pasa a instalar con `npm ci` (determinista) en vez de `npm install`. Resultado: añadir o actualizar dependencias del frontend no requiere ningún paso manual ni reconstruir la imagen — basta `docker compose up`/`restart`. No cambia la imagen `prod` (ya hornea las deps sin bind mount) ni la topología de volúmenes de compose.

## Requirements

### R1 — Dependencias de dev siempre resueltas tras un cambio

**As a** desarrollador, **I want** que el contenedor frontend tenga instaladas las dependencias declaradas aunque hayan cambiado desde la última imagen, **so that** `docker compose up` compile sin errores de módulo no encontrado ni pasos manuales.

Acceptance criteria:

1. WHEN el `package-lock.json` del frontend difiere de lo instalado en el volumen `node_modules` y arranca (o se reinicia) el contenedor `frontend` en target `dev`, THE SYSTEM SHALL instalar las dependencias del lockfile antes de ejecutar `next dev`, sin intervención manual ni reconstrucción de la imagen.
2. IF una dependencia declarada en `package-lock.json` (p.ej. `@radix-ui/react-dialog`) no está presente en el volumen `node_modules`, THEN THE SYSTEM SHALL instalarla en el arranque de modo que su import se resuelva en la compilación.

### R2 — Instalación determinista y reproducible

**As a** equipo, **I want** que la instalación de dependencias sea reproducible a partir del lockfile, **so that** imagen y contenedor de dev resuelvan siempre las mismas versiones (CI/CD fiable).

Acceptance criteria:

1. THE SYSTEM SHALL instalar las dependencias del frontend con `npm ci` (a partir de `package-lock.json`), tanto al construir la imagen como en la sincronización automática de dev.
2. IF `package.json` y `package-lock.json` están desincronizados, THEN THE SYSTEM SHALL fallar el arranque de forma explícita (comportamiento propio de `npm ci`) en vez de resolver versiones arbitrarias.

### R3 — Sin coste cuando no hay cambios

**As a** desarrollador, **I want** que el arranque no reinstale dependencias si nada cambió, **so that** el ciclo de desarrollo siga siendo rápido.

Acceptance criteria:

1. WHILE el `package-lock.json` no cambie entre arranques del contenedor `frontend`, THE SYSTEM SHALL NOT reinstalar `node_modules` (arranque rápido), determinándolo por comparación de hash del lockfile.

## Out of scope

- La imagen `prod` del frontend: ya instala las deps en build sin bind mount ni volumen; no se toca.
- El mismo patrón para el `.venv` de `backend`/`worker`: es la misma clase de problema pero queda fuera de este fix (candidato a entrada de roadmap aparte si se materializa).
- Mover `node_modules` fuera de `/app` (patrón "parent node_modules"): descartado por incompatibilidad con el root de compilación de Turbopack — ver `design.md`.

## Affected specs

- `sdd/specs/local-environment.md` — amplía el requisito de hot-reload en target `dev` (sección "Stack local vía Docker Compose") para documentar la sincronización automática de dependencias frontend contra el lockfile.
