# Tasks: hardening-release

<!-- Markers: "hard" en un encabezado de sección escala esa sección a Opus;
     "manual" en una línea de tarea marca lo que solo un humano o un entorno
     inalcanzable desde el worktree puede hacer. -->

## 1. Infraestructura E2E (Playwright)

- [ ] 1.1 Añadir `@playwright/test` (misma major que la `playwright` ya fijada en `frontend/package.json`, `^1.62.1`) como devDependency; nuevo script `"test:e2e": "playwright test"`. [R1]
- [ ] 1.2 `frontend/playwright.config.ts`: proyecto Chromium, `testDir: './e2e'`, `use: { baseURL: 'http://localhost:3000' }`, timeouts razonables para flujos multi-página. Distinto de `vitest.config.ts` — no toca ese fichero. [R1]
- [ ] 1.3 `globalSetup` en `frontend/e2e/global-setup.ts`: petición HTTP a `http://localhost:8000/health` (backend directo, no vía proxy) antes de correr cualquier spec; si no responde, aborta con mensaje explícito ("stack no levantado — corre `make up` primero") en vez de dejar que cada test falle por timeout genérico. Referenciarlo desde `playwright.config.ts` (`globalSetup`). [R1.2]
- [ ] 1.4 Fixture compartida `frontend/e2e/fixtures/auth.ts`: helper que hace login por clic (navegar a `/login`, rellenar credenciales, enviar, esperar `/dashboard`) parametrizado por rol — inspeccionar `frontend/features/auth/components/login-form.tsx` para los selectores reales, no inventarlos. Reutilizada por los tres specs de flujo. [R1]
- [ ] 1.5 Fixture `frontend/e2e/fixtures/seed-context.ts`: helpers de API (autenticados) para crear por API el dato de partida que cada spec necesite más allá de `make seed-demo` (p. ej. una `CleaningTask`/incidencia en el estado exacto del test), documentando qué endpoint usa cada helper. [R1]

## 2. E2E: flujo de login [R2]

- [ ] 2.1 `frontend/e2e/login.spec.ts`: login válido → redirect a `/dashboard`; login inválido → error visible sin redirect; una petición autenticada representativa con un usuario `must_change_password` confirma el bloqueo `403 PASSWORD_CHANGE_REQUIRED` salvo `me`/`logout`/`change-password` (ver `docs/auth-account-recovery.md`). [R2]

## 3. E2E: ciclo de limpieza <!-- hard -->

- [ ] 3.1 `frontend/e2e/cleaning.spec.ts`: con una `CleaningTask` sembrada (fixture 1.5), el `PROPERTY_MANAGER` la reasigna desde `/cleaning` y el nuevo asignado se refleja. [R3.2]
- [ ] 3.2 Mismo spec: el rol `CLEANER` acepta la tarea desde `/cleaner`, abre `/cleaner/tasks/[id]`, completa el checklist y sube las fotos requeridas por categoría (ver `docs/cleaning.md`, `docs/cleaner-photo-requirements.md`); verificar que la tarea queda completada y que el estado operacional de la propiedad cambia según corresponda (`docs/dashboard.md`). [R3.1]

## 4. E2E: ciclo de incidencia <!-- hard -->

- [ ] 4.1 `frontend/e2e/incident.spec.ts`: crear una incidencia (por API o portal del huésped, según lo que el flujo real permita) y verificar que `MockAIAdapter` la clasifica; un manager la tría y asigna a un técnico desde `/incidents/[id]`. [R4.1]
- [ ] 4.2 Mismo spec: el técnico acepta y resuelve desde `/tech/incidents/[id]` con coste y materiales; verificar el cierre. Con severidad `CRITICAL`, verificar que la propiedad aparece en rojo en el dashboard mientras esté abierta. [R4.1, R4.2]
- [ ] 4.3 Mismo spec, variante con coste sobre el umbral del tenant: verificar que se genera un `OwnerApproval` visible en `/approvals` para su respuesta (`docs/maintenance.md`). [R4.3]

## 5. CI: workflow `e2e-tests` y detector

- [ ] 5.1 `.github/workflows/e2e-tests.yml`: patrón de 3 jobs (`e2e-tests-detect` / `e2e-tests-suite` / `e2e-tests` consolidador), copiando el fail-open/fail-closed y la superficie de detección de `frontend-tests.yml` (`backend/**`, `frontend/**`, `docker-compose.yml`, `Makefile`, `frontend/e2e/**`, este propio workflow). Runner `[self-hosted, dev]`, mismos SHA pineados que los otros workflows (`actions/checkout@11d5960a326750d5838078e36cf38b85af677262`, `actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020`, `astral-sh/setup-uv@c771a70e6277c0a99b617c7a806ffedaca235ff9` si hace falta `uv` para el bootstrap del backend). [R1.3]
- [ ] 5.2 El job `e2e-tests-suite` hace `make up`, espera salud (reutilizar o adaptar el healthcheck de 1.3), `make bootstrap` + `make seed-demo`, corre `npm run test:e2e` desde `frontend/`, y `make down` en un paso `if: always()`. [R1.3]
- [ ] 5.3 Añadir un detector `e2e` a `scripts/check-detect-surface.py` (mismo mecanismo que `frontend_surface()`) que lea la superficie del `case` de `e2e-tests-detect` contra lo que `e2e-tests-suite` ejecuta; extender `scripts/test_detect_surface.py` con su caso. Correr `python3 scripts/check-detect-surface.py e2e` y confirmar que pasa. [R1.3]

## 6. Auditoría del DoD §28 <!-- hard -->

- [ ] 6.1 Enumerar los directorios de dominio de negocio bajo `backend/app/` (excluir `cli`, `core`, `provenance`, `scheduler`) y, para cada uno con estado propio scopado por tenant, confirmar en `backend/tests/<dominio>/` que existe un test de aislamiento tenant A / tenant B. Añadir el test que falte donde el hueco sea real. [R5.1]
- [ ] 6.2 Enumerar las transiciones (válidas e inválidas) de `PropertyStateMachine` (`backend/app/properties/domain/state_machine.py`) contra `backend/tests/properties/test_state_machine.py`; añadir el caso que falte. [R5.2]
- [ ] 6.3 `docs/dod-audit.md`: tabla de los 20 ítems de PRD §28 con su evidencia (test/archivo/comando); detalle de las tablas de 6.1 y 6.2. `#28.20` (un solo `make up` levanta todo) se documenta con la corrida de 7.3 como evidencia — ya construido por `local-environment`/`infra-scaffold`, no se reconstruye aquí. Corregir la cifra de dominios desactualizada en `README.md:311` (dice 19, con un roster que ya no incluye `statements` ni `audit`) contra el recuento real de 6.1. Enlazar `docs/dod-audit.md` desde `README.md`. [R5.3]

## 7. Verificación

- [ ] 7.1 Backend: `docker compose exec backend uv run pytest` — verde, incluyendo los tests nuevos de 6.1/6.2.
- [ ] 7.2 Frontend: `cd frontend && npm run typecheck && npm run lint && npm test` — verde.
- [ ] 7.3 E2E local: en este worktree, `make up PORT_OFFSET=<n>` (publica puertos — necesario porque Playwright corre en el host, no en la red de compose; ver `sdd/project.md` §Worktree bootstrap) y `cd frontend && BASE_URL=http://localhost:<3000+n> npm run test:e2e` (o el equivalente que 1.2 documente si `baseURL` se parametriza por variable de entorno) — los tres specs (2.1, 3.1-3.2, 4.1-4.3) en verde.
- [ ] 7.4 `python3 scripts/check-detect-surface.py e2e` (5.3) — verde.

## Implementation Notes

<!-- Append-only: cada implementador de sección añade aquí lo que la siguiente necesita. -->
