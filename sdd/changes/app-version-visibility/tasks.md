# Tasks: app-version-visibility

<!-- Alcance recortado el 2026-07-30. Las tareas del panel de procedencia, la deriva y el
     gate de paridad se retiraron con su código; viven en `app-version-provenance`.
     Todo lo de abajo está implementado y verificado salvo donde se indica. -->

## 1. Identidad de build en el CD <!-- panel: PASS 2026-07-30 (cicd/security/qa, revisado en el alcance original) -->

- [x] 1.1 Job `provenance` que compone `<base>+<fecha>.<sha-corto>` una sola vez y la publica por `outputs`, leyendo la base de `VERSION`, validando forma `X.Y.Z` y existencia previa, y con **una sola lectura del reloj** para la fecha y el label `.created` — files: `VERSION`, `.github/workflows/deploy-dev.yml` [R1.1, R1.2]
- [x] 1.2 `ARG` + `ENV` `NEXT_PUBLIC_APP_VERSION` y `NEXT_PUBLIC_BUILD_COMMIT_SHORT` en la etapa `builder` del frontend, al final para no invalidar la caché de dependencias — files: `frontend/devops/Dockerfile` [R1.3]
- [x] 1.3 Los dos builds consumen el mismo job y emiten los labels OCI `{source,revision,version,created}` — files: `.github/workflows/deploy-dev.yml` [R1.5]
- [x] 1.4 Verificar que ni el `.env` que renderiza el job `deploy` ni `docker-compose.deploy.yml` ganan variable alguna de identidad, y que los tags y el pineado `${IMAGE_TAG}` quedan intactos — files: (comprobación) [R1.4, R1.7]
- [x] 1.5 Las dos `NEXT_PUBLIC_*` declaradas explícitamente en el servicio `frontend` de `docker-compose.yml`, con default que rinda `local` — files: `docker-compose.yml` [R1.6]
- [x] 1.6 Excluir `.env*` del contexto de build del frontend: un `.env.local` de una máquina de desarrollo entraría por `COPY . .` y `npm run build` inlinearía sus `NEXT_PUBLIC_*` en el bundle — files: `frontend/.dockerignore` [R1.3]

## 2. Badge de versión <!-- panel: PASS 2026-07-30 (i18n/architect/qa, revisado en el alcance original) -->

- [x] 2.1 `appVersion` y `buildCommitShort` en la allowlist de `PublicRuntimeConfig`, con fallback a vacío. Test de que el snapshot no gana nada más — files: `frontend/lib/config/public.ts`, `public.test.tsx` [R2.4]
- [x] 2.2 Slot `footer` en `ShellFrame`, moviendo el `pb-16 md:pb-0` del `main` a la columna para que en móvil quede por encima del `BottomNavigation` fijo. Tests: el footer se renderiza, queda **fuera** del landmark `main`, el `pb-16` está en la columna, y precede al nav fijo en orden de documento. Verificados por mutación: devolver el `pb-16` a `main` rompe 2 — files: `shell-frame.tsx`, `shell-frame.test.tsx` [R2.1]
- [x] 2.3 `VersionBadge` **síncrono**, que recibe sus strings como props (patrón de `Brand`/`SkipLink`; una versión async anidada suspende el árbol entero del shell), pinta `<base>+<sha-corto>` y no hace **ninguna** petición de red. `formatBuildVersion` devuelve `null` —no `""`— cuando la base queda vacía, para que el caller pueda localizar "desconocida" en vez de pintar un badge en blanco — files: `version-badge.tsx`, `shell-footer.tsx`, tests [R2.1, R2.3, R2.7]
- [x] 2.4 Slot `footer` desde `WorkspaceShell`, `PublicShell` (login, sin sesión), `CleanerShell` y `TechnicianShell`; **no** desde `GuestShell`. Tests de presencia en los cuatro y ausencia en huésped, más uno en `workspace-shell.test.tsx` porque es el único shell con `BottomNavigation` y por tanto el único con riesgo real de tapado — files: los cuatro shells, `field-public-guest-shell.test.tsx`, `workspace-shell.test.tsx` [R2.2, R2.6]
- [x] 2.5 Claves i18n en `locales/es/` y `locales/en/`, resueltas en servidor con `getServerT`. La parity test cubre claves anidadas (verificado mutando el catálogo) — files: `frontend/locales/{es,en}/common.json` [R2.5]

## 3. Documentación <!-- sección de documentación: el flujo no le pasa panel -->

- [x] 3.1 `RUNBOOK.md` §6.4: confirmar un rollback con el badge y con los labels OCI. §7: fila de diagnóstico para un badge atrasado, con el alcance real (página cacheada sí, chunks JS no) y para el badge en "desconocida" — files: `infra/environments/dev/RUNBOOK.md` [R3.2]
- [x] 3.2 `docs/app-version-visibility.md`: página de capacidad orientada a cómo se opera, incluidas las dos cosas que confunden (el SHA es el último commit que **disparó build**; el badge delata una página cacheada pero no un chunk JS) y la deuda de los manifiestos — files: `docs/app-version-visibility.md` [R3.3, R3.4, R3.5]
- [x] 3.3 README raíz al día. Sin variable de runtime nueva, así que `.env.example` y `.env.deploy.example` no cambian — files: `README.md` [R3.4]

## 4. Verification

- [ ] 4.1 Frontend en verde: `docker compose exec -T frontend npx vitest run`, `npm run typecheck`, `npm run lint` — **PENDIENTE**: el daemon de Docker se cayó justo tras el recorte y no se han podido re-ejecutar [R2]
- [ ] 4.2 Backend sin tocar: `docker compose exec -T backend uv run pytest -q` debe seguir en 1203/35 — **PENDIENTE**, mismo motivo. El recorte revirtió `main.py`, `config.py`, los dos tests y el Dockerfile del backend a `main`, así que no debería haber diferencia [R1]
- [ ] 4.3 Build de producción del frontend sin backend: `npm run build` — **PENDIENTE**, mismo motivo [R2.3]
- [ ] 4.4 Comprobación manual en local (`make up`): badge en `/login`, `/dashboard` y `/cleaner`; ausente en `/guest/<token>` — **PENDIENTE**, mismo motivo [R2.2, R2.6]
- [ ] 4.5 **BLOQUEADA — requiere un deploy real.** Tras el merge: `docker inspect` de las dos imágenes muestra los cuatro labels con idénticos valores, y la cadena coincide con el badge en `https://autohostai.digitalsec.work` [R1.5]
- [ ] 4.6 **BLOQUEADA — requiere el PR abierto.** El gate `backend-tests` en verde. El recorte revirtió ese workflow a `main`, así que el riesgo del pineado de `setup-python` desaparece [R1]
