# Tasks: frontend-verification-fixes

## 1. Backend · cadena de degradación de locale (D4) <!-- panel: PASS 2026-09-05 -->

- [x] 1.1 Test-first en `backend/tests/test_i18n.py`: casos de
      `resolve_locale(requested, stored) -> Locale` — pedido soportado gana sobre lo almacenado;
      pedido no soportado (incluye `es-ES`, listas con pesos tipo `es;q=0.9`, `None`) degrada a
      `Locale.resolve(stored)`; `stored` no soportado o `None` degrada a `es`. Seis combinaciones
      mínimas. [R1.2, R1.3]
- [x] 1.2 Implementar `resolve_locale` en `backend/app/core/i18n.py` (Python puro, sin FastAPI ni DB)
      hasta que 1.1 pase. [R1.2, R1.3]

## 2. Backend · cabecera `X-Locale` y las tres rutas <!-- hard --> <!-- panel: PASS 2026-09-05 -->

- [x] 2.1 En `backend/app/auth/api/dependencies.py`: constante `LOCALE_HEADER = "X-Locale"` y nueva
      dependencia `RequestLocaleDep` que depende de `AuthenticatedDep`, lee
      `request.headers.get(LOCALE_HEADER)` y devuelve
      `resolve_locale(header_value, authenticated.context.preferred_language)`. No añade ninguna
      consulta (reusa el `RequestContext` ya resuelto). `get_authenticated_request` no cambia. [R1.1,
      R1.4, R1.5]
- [x] 2.2 Docstring de `backend/app/auth/domain/context.py`: aclarar que
      `RequestContext.preferred_language` es la preferencia almacenada de la fila y no el idioma en
      el que se pinta la respuesta; apunta a `RequestLocaleDep` para lo segundo. Sin cambio de
      comportamiento. [R1]
- [x] 2.3 `backend/app/dashboard/api/router.py` (`GET /dashboard/properties` en `:100`,
      `GET /properties/{id}/dashboard` en `:139`) y `backend/app/timeline/api/router.py`
      (`GET /timeline/{property_id}` en `:109`): cambian `locale=authenticated.context.preferred_language`
      por un parámetro `locale: RequestLocaleDep` y `locale=locale`; actualizan las tres
      `description=` para decir de dónde sale ahora el idioma (D11). Las dos rutas que no componen
      texto (`operational-kpis`, `occupancy-series`) no cambian. [R1.1, R1.6, R1.7]
- [x] 2.4 Parametrizar en `backend/tests/dashboard/test_api.py` y `backend/tests/timeline/test_api.py`
      las cuatro combinaciones idioma-pedido × idioma-de-la-fila (`es`/`en` × `es`/`en`) sobre las
      tres rutas: el texto compuesto sale en el idioma pedido; `description` y los literales
      canónicos (`operational_state`, `event_type`, `actor_type`, `severity`) no se traducen; la
      columna `title` almacenada no se modifica. [R1.8, R1.6, R1.7]
- [x] 2.5 Guardia estructural (D5): test que recorre por AST `backend/app/*/api/*.py` y falla si
      alguno contiene un acceso de la forma `<algo>.context.preferred_language` (los cuatro
      serializadores legítimos que nombran la columna —`auth/api/user_schemas.py`,
      `auth/api/schemas.py`, `platform/api/schemas.py`, `reservations/api/schemas.py`— no encajan
      esa forma). Añadir a `backend/tests/test_layering.py` o fichero nuevo junto a él. [R1]
- [x] 2.6 `make openapi` desde la raíz: regenerar y commitear `backend/openapi.json`. Verificar que
      solo cambian las tres `description=` y que ninguna ruta gana un parámetro (confirma R1.5).
      [R1.5]

## 3. Frontend · publicación del locale activo (D6) <!-- panel: PASS 2026-09-05 -->

- [x] 3.1 Nuevo `frontend/lib/i18n/active-locale.ts`: `getActiveLocale(): Locale` /
      `setActiveLocale(locale: Locale)`, valor inicial `DEFAULT_LOCALE` (el que resolvería el
      servidor antes de que monte cualquier proveedor). [R1.4]
- [x] 3.2 Nuevo `frontend/lib/i18n/use-active-locale.ts`: `useActiveLocale()` implementado sobre
      `useTranslation()` (mismo patrón que ya usan los componentes con `i18n.language`), para que un
      cambio de idioma provoque re-render. [soporta R2.1]
- [x] 3.3 `frontend/lib/i18n/client-provider.tsx`: publica el locale de forma **síncrona** al crear
      la instancia (dentro del inicializador de `useState`, no en un efecto) y se suscribe al evento
      `languageChanged` de i18next para republicarlo. [R1.4]

## 4. Frontend · cabecera en peticiones y claves de consulta (D7, D8, R2) <!-- panel: PASS 2026-09-05 -->

- [x] 4.1 `frontend/lib/api/authenticated-client.ts`: `getHeaders` añade
      `X-Locale: getActiveLocale()`. Es el único punto de edición — cubre las nueve
      `features/*/data/index.ts` que pasan por el `ApiClient` autenticado. El cliente anónimo del
      portal del huésped no se toca. [R1.4]
- [x] 4.2 `frontend/features/dashboard/hooks/query-keys.ts`: el locale entra al **final** del
      `scope` en `cards`, `propertyDetail` y `propertyTimeline`
      (`['tenant', tenantId, resource, ...scope, locale]`), conservando la forma que
      `frontend-foundation.md:56` exige. [R2.1]
- [x] 4.3 `frontend/features/dashboard/hooks/use-dashboard-data.ts`: los tres hooks toman
      `useActiveLocale()` y lo pasan a su clave; ninguna de las tres consultas usa
      `placeholderData: keepPreviousData` (D8) — un cambio de idioma pasa por el estado de carga
      existente (`StatePanel`, `aria-busy`), no por el texto del idioma anterior. [R2.2, R2.3]
- [x] 4.4 Tests: `frontend/features/dashboard/hooks/query-keys.test.ts` — `dashboardKeys.cards(t,
      "en")` sigue empezando por `["tenant", t, "dashboard-cards"]` y
      `dashboardKeys.propertyTimeline(...)` por `["tenant", t, "property-timeline"]` (las dos
      invalidaciones por prefijo escritas a mano en `use-resolve-incident.ts` y
      `use-cancel-cleaning-task.ts` siguen casando para los dos idiomas); una clave sin locale
      falla (R2.4). `use-dashboard-data.test.tsx` — cambio de idioma produce clave nueva y refetch.
      `frontend/lib/api/authenticated-client.test.ts` (o `client.test.ts`) — la cabecera `X-Locale`
      viaja y su valor es el locale activo. [R1.4, R2.1, R2.2, R2.4]
- [x] 4.5 Regenerar el contrato del lado frontend: la secuencia de `docker compose cp` que
      `sdd/project.md` §Worktree bootstrap documenta, seguida de
      `docker compose exec -T frontend npm run api:generate`; commitear
      `frontend/lib/api/generated/openapi.d.ts` (solo cambian comentarios de `description`, D11).
      [D11]

## 5. Prosa · la redacción superada de "el idioma sale del usuario" (R1.9)

- [x] 5.1 `docs/dashboard.md:43-45` — el epígrafe «El idioma sale del usuario, no de
      `Accept-Language`» pasa a describir R1: el idioma que la petición declara, con degradación a
      `preferred_language` y a `es`. [R1.9]
- [x] 5.2 `sdd/roadmap/timeline-web.md:70` — misma corrección, en el contexto de la entrada del
      `title` de timeline. [R1.9]
- [x] 5.3 `sdd/specs/dashboard-api.md:487` (y la sección «Textos legibles en el idioma del usuario»,
      `:270-307`, si su redacción sigue afirmando lo contrario tras el cambio de código) — corregir.
      La reescritura completa de esta spec como `SHALL` la hace `/sdd:archive` tras el merge; esta
      tarea es la prosa que queda fuera de esa reescritura. [R1.9]
- [x] 5.4 `sdd/specs/revenue-statements.md:306` — corregir «ni mecanismo de traducción por
      `Accept-Language` o locale de usuario en el backend de este proyecto», ya falsa tras 2.1-2.3.
      [R1.9]

## 6. Verificación manual con Playwright (R3) y párrafo de hidratación (R4)

- [x] 6.1 Precondición: rellenar en el `.env` de este worktree `BOOTSTRAP_OWNER_PASSWORD` y
      `BOOTSTRAP_MANAGER_PASSWORD` con credenciales desechables (no commitear), y `make bootstrap`.
      [R3]
- [x] 6.2 `make up PORT_OFFSET=<n>` y una pasada headless con el **MCP de Playwright** contra
      `next dev`. Registrar: driver, `PORT_OFFSET`, `next dev` o build de producción, errores de
      consola, si aparecen claves `__react*` en el documento, y si un clic en el conmutador de
      idioma muta el DOM. Si `next dev` no responde, caer a
      `docker compose exec -T frontend npm run build` seguido de
      `docker compose run --rm --no-deps -p <puerto>:3000 frontend sh -c 'npx next start -p 3000 -H 0.0.0.0'`
      y registrar la condición exacta bajo la que falla, sin atribuirle causa. [R3.1, R3.2, R3.3]
- [x] 6.3 En esa misma pasada, verificar R1 y R2 a mano en las cuatro combinaciones rol × idioma
      (`TENANT_OWNER` y `PROPERTY_MANAGER`, únicos con `READ_PROPERTIES`, × `es`/`en`): la card del
      dashboard, el detalle de propiedad y el timeline muestran el texto compuesto en el idioma
      activo tras pulsar el conmutador, sin recarga manual del navegador. [R3.4, R1, R2]
- [x] 6.4 Reescribir el párrafo de hidratación de `sdd/project.md` en un solo sitio: qué probar
      primero, qué hacer si falla, y la fecha y condiciones de la medición de 6.2 (D9). Dejar
      `allowedDevOrigins` explícitamente como hipótesis no verificada — no declarada en
      `frontend/next.config.ts` (D10) — y conservar el aviso de credenciales en la URL de
      `login-form.tsx` sin hidratar, que sigue siendo cierto. Si 6.2 mide hidratación completa,
      cerrar el hallazgo 2 como falso con su fecha. [R4.1, R4.2, R4.3]
- [x] 6.5 `sdd/roadmap.md` (entrada `frontend-verification-fixes`) y
      `sdd/roadmap/frontend-verification-fixes.md` — corregir su redacción del hallazgo de
      hidratación para que apunten al párrafo de `sdd/project.md` en vez de repetir el veredicto
      (una sola casa por hecho). [R4.4]

## 7. Verification

- [x] 7.1 Suite backend completa: `docker compose exec backend uv run pytest` (incluye 1.1, 2.4,
      2.5, verdes). **10307 passed, 43 skipped, 0 failed** (726.99s). Requirió tres intentos: los dos
      primeros murieron con `EXIT_CODE=137` (el host tenía ~5 stacks de worktree simultáneos con
      load average >20 y memoria casi agotada — `incident-triage-web-frontend-1` solo llegó a
      288% CPU); parar el `frontend` de este worktree (`docker compose stop frontend`) antes del
      tercer intento fue lo que lo dejó terminar limpio.
- [x] 7.2 Estático backend: desde `backend`, `uv sync --frozen` y `uv run pyright .`. **907 errores,
      pre-existentes**: ninguno cae en un fichero que esta change toque o añada
      (`backend/app/core/i18n.py`, `backend/app/auth/domain/context.py`,
      `backend/tests/test_i18n.py`, `backend/tests/test_layering.py`,
      `backend/tests/dashboard/test_api.py`, `backend/tests/timeline/test_api.py`: cero errores en
      los seis). Los que sí caen en ficheros que esta change edita
      (`backend/app/auth/api/dependencies.py`, `backend/app/dashboard/api/router.py`,
      `backend/app/timeline/api/router.py`) están todos en líneas que el diff no toca —confirmado
      línea a línea contra `git diff`—, la mayoría del mismo patrón preexistente
      (`tenant_id: UUID | None` pasado a un parámetro `UUID`, y `SqlAlchemySessionRepository` vs
      `SessionRepository`). No se reporta como hallazgo de esta change.
- [x] 7.3 Guardia de propiedad de la regla 11: `make check-rule11-ownership` (host, sin Docker, sin
      stack levantado) — se toca prosa de `sdd/`, `docs/` y un docstring de `backend/app/**`.
      **Verde**: "ningún bloque fuera de la tabla de la regla 11 declara quién escribe un sumidero
      del censo" (106 ficheros markdown, 888 ficheros Python recorridos).
- [x] 7.4 Frontend: aplicar los `docker compose cp` de `sdd/project.md` §Worktree bootstrap y correr
      `docker compose exec -T frontend npm test`; comparar el **total** de ficheros/tests contra la
      pasada de partida de este worktree, no contra una cifra recordada. **205 ficheros / 2127
      tests; 204 ficheros y 2126 tests en verde, 1 test rojo**
      (`features/cleaning/components/cleaning-view.test.tsx` › "renders the page the source
      returned, and not the placeholder"). Re-ejecutado en aislamiento
      (`npx vitest run --project node features/cleaning/components/cleaning-view.test.tsx`): **39/39
      verde** — no del change (`features/cleaning/` no aparece en ningún diff de este change) y no
      reproduce fuera de la pasada completa bajo la misma contención de host que afectó a 7.1;
      fichero de contención, no regresión. Los dos `ENOENT` conocidos del worktree
      (`features/provenance/workflow-contract.test.ts`, `lib/config/build-identity-contract.test.ts`)
      pasan en verde gracias al `docker compose cp` previo — confirmados por nombre en el log.
- [x] 7.5 Frontend estático: `docker compose exec -T frontend npm run typecheck` y
      `docker compose exec -T frontend npm run lint`. **Los dos limpios**, sin salida de error.
- [x] 7.6 Contrato sin deriva: `docker compose exec -T frontend npm run api:check` (tras el `cp` de
      `backend/openapi.json` de 7.4). **"api: generated types are up to date."** Nota: el contenedor
      `frontend` se recreó entre 7.1 y 7.4 (parado y reiniciado para 7.1), lo que borra el symlink
      `/frontend → /app` que este comando necesita; hubo que rehacer
      `docker compose exec -T frontend ln -sfn /app /frontend` antes de que `api:check` encontrara el
      fichero. Anotado aquí porque es el mismo filo que `sdd/project.md` documenta y no estaba escrito
      que un `stop`/`start` de por medio también lo dispara.
- [x] 7.7 Pasada manual de extremo a extremo: la de la sección 6 (6.2-6.3) cubre el flujo completo —
      login real, conmutador de idioma, dashboard/detalle/timeline en las cuatro combinaciones
      rol × idioma. No se repite aquí.

## Implementation Notes

- Section 1: `resolve_locale(requested: str | None, stored: str | None) -> Locale`, in
  `backend/app/core/i18n.py`, alongside `Locale`/`Catalog` (no new file, no new import path).
- Signature order matters: `requested` first, `stored` second (matches the eventual
  `resolve_locale(header_value, authenticated.context.preferred_language)` call in task 2.1).
- Match rule for `requested`: `Locale(requested.strip().lower())` inside a `try/except
  ValueError` — same normalization `Locale.resolve` uses, but on failure it falls through to
  `stored` rather than defaulting to `es` directly (that distinction is why `resolve_locale`
  can't just be `Locale.resolve(requested) or Locale.resolve(stored)`).
- `requested=None` skips the try entirely and goes straight to `Locale.resolve(stored)`.
- Unsupported `requested` values (`es-ES`, `es;q=0.9`, `fr`, `""`, `"klingon"`, etc.) are
  never parsed/split — anything `Locale(...)` rejects just falls through. No
  `Accept-Language` quality-list parsing lives here; that stays out of scope for section 2 too
  unless the design says otherwise.
- Section 3: `Locale`/`DEFAULT_LOCALE` were already defined on the frontend at
  `frontend/lib/config/constants.ts` (`SUPPORTED_LOCALES`, `DEFAULT_LOCALE = "es"`,
  `isLocale`) — reused as-is, no duplicate type created.
- `frontend/lib/i18n/active-locale.ts` exports `getActiveLocale(): Locale` and
  `setActiveLocale(locale: Locale): void`, both importable as
  `import { getActiveLocale, setActiveLocale } from "@/lib/i18n/active-locale"`. Task 4.1
  needs `getActiveLocale` in `authenticated-client.ts`'s `getHeaders`.
- `frontend/lib/i18n/use-active-locale.ts` exports `useActiveLocale(): Locale` (default
  export none — named export only), `import { useActiveLocale } from
  "@/lib/i18n/use-active-locale"`. It returns `i18n.language` from `useTranslation()` (no
  namespace argument), matching the existing `i18n.language` pattern (e.g.
  `features/dashboard/components/property-card.tsx`) rather than `resolvedLanguage` — that
  distinction only matters for the synchronous publish path below. Task 4.3 needs this for
  the three dashboard query-key hooks.
- `frontend/lib/i18n/client-provider.tsx`: `createClientI18n` now calls
  `setActiveLocale((instance.resolvedLanguage ?? locale) as Locale)` synchronously right
  after `instance.use(initReactI18next).init(...)`, still inside the `useState(() =>
  createClientI18n(locale))` initializer — `init()` resolves synchronously here because
  resources are passed in-line (no async backend/detector), so `resolvedLanguage` is already
  set by the time `createClientI18n` returns. A `useEffect` in `I18nProvider` subscribes to
  `instance.on("languageChanged", ...)` and republishes with
  `instance.resolvedLanguage ?? instance.language`, unsubscribing via `instance.off(...)` on
  cleanup.
- Gotcha for section 4 tests: the `languageChanged` republish only fires once `I18nProvider`
  has mounted and its effect has run (React `act()`/an awaited state update in tests) — a
  synchronous read of `getActiveLocale()` right after calling `i18n.changeLanguage(...)` in a
  test, without an intervening flush, can still see the old value. The very first publish
  (at mount) is synchronous and needs no flush; only the *change* path is effect-based.
- `active-locale.ts` is plain module state (a `let` with getter/setter) — not a Zustand
  store and not TanStack Query state, per `sdd/steering/frontend.md`'s "no duplicar server
  state en stores": this isn't server state, it's a synchronous cross-boundary publication
  point.
- Verification for section 3: `docker compose exec -T frontend npx tsc --noEmit -p
  tsconfig.json` clean; `docker compose exec -T frontend npx vitest run lib/i18n` — the 2
  pre-existing test files (24 tests) still pass. Wrote and ran a throwaway
  `lib/i18n/_manual-check.test.tsx` (round-trip get/set, synchronous publish on mount,
  republish on `languageChanged` via a real `i18n.changeLanguage` call) — all 3 passed, then
  deleted before finishing; no test file was committed for this section (that's task 4.4).
- `Locale.resolve(stored)` is unchanged and already degrades `None`/unsupported `stored` to
  `Locale.ES` — `resolve_locale` just delegates to it for the second step, no duplicated logic.
- Tests added to `backend/tests/test_i18n.py` (existing file, not new) under a
  `# --- resolve_locale ---` section; import line updated to add `resolve_locale` alongside
  `Catalog, CatalogTemplateError, Locale`.
- Local run needed generating a `.env` (JWT_SECRET_KEY + ENCRYPTION_KEY) since the stack
  wasn't running yet; test invocation path inside the backend container is
  `tests/test_i18n.py` (not `backend/tests/test_i18n.py` — container workdir is `/app` mapped
  to `backend/`).
- Full `tests/test_i18n.py` (43 tests, after round 5's `requested`-side normalization pin)
  and `tests/test_layering.py` (1509 tests, after round 8's main catch-up) both green —
  `app/core/i18n.py` stays pure Python, no framework/DB import added.

### Section 2 (backend `X-Locale` + the three routes, plus a fourth on main catch-up)

- **Round 8, main catch-up**: `dashboard-activity-feed` merged into `main` after this change
  forked, adding a fourth route reading `preferred_language` directly —
  `GET /api/v1/timeline` (`list_tenant_activity`). Converting it to `RequestLocaleDep` +
  `Cache-Control` was not part of the original section 2 scope; it was done at review time
  (design.md D5's "third amendment") once the base-catchup merge brought that route in red
  against this change's own D5 guard. Its test coverage lives in
  `backend/tests/timeline/test_tenant_feed_api.py`, not in this section's original files.

- **Header name and import path** (what sections 3/4 must send): the constant is
  `LOCALE_HEADER = "X-Locale"` in `backend/app/auth/api/dependencies.py`, exported alongside
  `RequestLocaleDep` (`Annotated[Locale, Depends(get_request_locale)]`) from that same module.
  The frontend must send the header spelled exactly `X-Locale` with a bare locale value
  (`es` / `en`) — no quality list, no regional tag: `resolve_locale` does not parse `es-ES` or
  `es;q=0.9`, they simply fall through to the stored preference.
- Routers import it as
  `from app.auth.api.dependencies import AuthenticatedRequest, RequestLocaleDep, require`.
  The three handlers take a `locale: RequestLocaleDep` parameter and pass `locale=locale`;
  `get_authenticated_request` was not touched, and no route declares a header parameter.
- **Exact new `description=` wording** (section 5: grep for the OLD wording tree-wide — the
  phrase "in the authenticated user's language" and "arrive already composed in the
  authenticated user's language" are now gone from `backend/app/`):
  - `GET /dashboard/properties`: "... arrive already composed in the language the request
    states in its `X-Locale` header, falling back to the authenticated user's stored
    preference and then to Spanish."
  - `GET /properties/{id}/dashboard`: a NEW sentence was added (this description never had a
    language clause — D11's claim that all three said "in the authenticated user's language"
    is inexact): "Every composed label in the aggregate arrives in the language the request
    states in its `X-Locale` header, falling back to the authenticated user's stored
    preference and then to Spanish."
  - `GET /timeline/{property_id}`: "`title` arrives already composed in the language the
    request states in its `X-Locale` header, falling back to the authenticated user's stored
    preference and then to Spanish (PRD §10); `description` does not ..."
- **`openapi.json` moved by description text only.** `make openapi` produced a 3-line diff
  (3 insertions, 3 deletions), all three of them `description` strings on exactly those
  routes. Verified no route gained a parameter: the whole contract contains **zero**
  `in: header` parameters, and the only three `X-Locale` occurrences in the file are inside
  that prose. R1.5 holds as written. `frontend/lib/api/generated/` regeneration is task 4.5.
- `backend/app/auth/domain/context.py`: the docstring now separates the stored preference
  from the render locale and points at `RequestLocaleDep`; the "never from request input"
  sentence is untouched and still literally true (design D3). The PRD:205 citation was kept
  and marked superseded-on-this-point rather than deleted — section 5 may want to mirror that
  phrasing rather than claim PRD:205 is simply wrong.
- **Deviation from D5 (resolved — see design.md's D5 amendment).** The guard in
  `backend/tests/test_layering.py` bans the shape `<anything>.context.preferred_language`
  across `backend/app/*/api/*.py` as specified, but carries a one-entry allowlist
  `LOCALE_ROW_READERS = {("app/auth/api/dependencies.py", "get_request_locale")}` — because
  task 2.1's own mandated expression is that shape, inside that scope. D5's "sin lista blanca"
  rested on "`dependencies.py` la construye pero no la lee así", which task 2.1 makes false.
  The entry is keyed by (module, enclosing function), so a second reader anywhere — including
  elsewhere in `dependencies.py` — still fails; and `test_the_only_permitted_row_reader_still_exists`
  fails if the exempt function is renamed or deleted, so the exemption cannot go stale.
  Precedent for the shape of this allowlist: `CELERY_IMPORTERS` in the same file.
  The four serialisers named in D5 are untouched and were confirmed safe by construction
  (they read `user.preferred_language` / `guest.preferred_language`, a one-attribute chain).
- Both new test matrices were **falsified before being trusted**: reverting the dashboard
  collection route to the old expression turned exactly the two mixed rows
  (`asks-es-row-en`, `asks-en-row-es`) red, and reinstating that read made the AST guard fire
  with the offending file, line and function named. Both reverts were undone.
- The pre-existing `test_the_title_is_composed_in_the_users_language` (timeline) now documents
  that it sends **no** `X-Locale`, which is what keeps it the R1.3 fallback case.
- Test counts after section 2: `tests/dashboard/test_api.py` 56 (was 44), `tests/timeline/test_api.py`
  32 (was 24), `tests/test_layering.py` 1483 (was 1380 — the guard parametrizes over ~100 api
  modules plus 3 standalone tests). `tests/test_route_authorization.py` + `tests/auth` 899, green:
  adding a non-`require` dependency does not disturb the permission-tag route walk.
- Gotcha: `--maxWorkers=2` is a Jest flag; pytest rejects it. For the backend use `-n` (xdist)
  or nothing.
- **Fix round (QA panel finding, R1.8 coverage gap in the aggregate test).**
  `test_the_aggregate_composes_in_the_language_the_request_asked_for` only asserted
  `cleaning_status`, leaving `access.label`, `open_incidents[0].title` and
  `pending_approvals[0].label` — the other three fields `GetPropertyDashboardUseCase`
  composes through the same `locale` parameter — uncovered. `_seed_composed_text` now also
  seeds a live `ReservationModel` (bracketing `TODAY`, `access_status` left at its
  `ReservationAccessStatus.PENDING` default) and an `OwnerApprovalModel`
  (`related_type=OwnerApprovalRelatedType.OTHER`, `status` left at its `PENDING` default);
  `EXPECTED_LABELS` gained `access_label`/`incident_title`/`approval_label` per locale, and the
  aggregate test now asserts all three alongside `cleaning_status`. `open_incidents[0].title`
  needed no new seed — the incident `_seed_composed_text` already inserts has no explicit
  `category=`, which defaults to `IncidentCategory.OTHER`. Falsified the same way as the
  existing matrices: hardcoding `Locale.ES` at the three `use_cases.py` call sites turned the
  new assertions red on the two `asks-en-*` cases (the two `asks-es-*` cases stayed green,
  since ES was what was asked), then reverted clean. `test_the_collection_composes_...` and
  `test_the_requested_language_translates_no_canonical_literal` (the other two callers of
  `_seed_composed_text`) were unaffected by the added seeding. Full scope
  (`tests/dashboard/test_api.py` + `tests/timeline/test_api.py`) stayed at 88 passed.

### Section 4 (frontend header + query-key locale, D7/D8)

- `getHeaders` in `authenticated-client.ts` now sets `X-Locale: getActiveLocale()`
  unconditionally (before the `Authorization` check), so the header travels on every
  authenticated request — with or without a session. Import is
  `import { getActiveLocale } from "@/lib/i18n/active-locale";`.
- `dashboardKeys.cards`/`propertyDetail`/`propertyTimeline` all gained a **required**
  `locale: Locale` last parameter (no default) — the design's `[..., ...scope, locale]`
  shape. `propertyTimeline`'s `filters` parameter lost its `= {}` default in the process:
  TypeScript rejects a required parameter (`locale`) following an optional one
  (`filters: TimelineFilters = {}`) — `TS1016`. Every real caller already passes an actual
  filters object (`use-dashboard-data.ts`'s own hook still defaults `filters = {}` one layer
  up), so this has no runtime effect; it only moves the "optional" default one level out of
  `query-keys.ts`.
- **Both hand-written prefix invalidations verified to still match, both locales, after the
  key-shape change** — not just trusted from design.md: `use-resolve-incident.ts` (~line 87)
  and `use-cancel-cleaning-task.ts` (~line 96) both invalidate
  `["tenant", tenantId, "dashboard-cards"]` and `["tenant", tenantId, "property-timeline"]`
  as 3-element arrays; `dashboardKeys.cards(t, locale)` and
  `dashboardKeys.propertyTimeline(t, id, filters, locale)` both still produce that exact
  3-element prefix (`key.slice(0, 3)`) for `locale` = `"es"` and `"en"` — asserted directly in
  `query-keys.test.ts` (`.slice(0, 3)` parametrized over both locales), not by re-reading the
  design doc's claim. TanStack Query's `invalidateQueries` matches by prefix, so this is the
  contract that matters at runtime; both incident/cleaning hook files were read and confirmed
  untouched (read-only per the section's scope).
- `useActiveLocale()` (section 3's export, `lib/i18n/use-active-locale.ts`) is called inside
  all three hooks in `use-dashboard-data.ts`, after `useTenantId()`. No `placeholderData` or
  `keepPreviousData` was present in this file before the change and none was added — D8 was
  already satisfied by omission; verified by reading the full file, not assumed.
- **Falsified, not just written**: reverted `query-keys.ts`/`use-dashboard-data.ts` to their
  pre-section-4 shape (locale-less keys, `git stash`) and re-ran the new tests — 6 failed
  exactly as expected (`query-keys.test.ts`'s locale-suffix and R2.4-shape assertions; both new
  `use-dashboard-data.test.tsx` locale-change tests, which timed out waiting for a second
  `requestMock` call because a locale-less key doesn't change on `changeLanguage`). Restored
  (`git stash pop`) and confirmed green again (77/77). Likewise for the header: temporarily
  reset `getHeaders` to omit `X-Locale` and re-ran `authenticated-client.test.ts` — all 4 tests
  failed (`Received: null`); restored and confirmed green.
- New test file `frontend/lib/api/authenticated-client.test.ts` (none existed for this module
  before). Covers: header present with no session, header value tracks `setActiveLocale`
  across two requests on the same client instance (no need to recreate the client on a
  language change — `getHeaders` reads `getActiveLocale()` fresh per request), header
  coexists with `Authorization` when a session is present, and header still present with no
  `Authorization` when there is none. Uses `clearSessionTokens()`/`setActiveLocale(DEFAULT_LOCALE)`
  in `afterEach` to avoid cross-test module-state leakage (`active-locale.ts` and
  `session-store.ts` are both plain module-level state).
- `use-dashboard-data.test.tsx`'s locale-change tests wrap hooks in the real
  `I18nProvider` (not a mock) so `useActiveLocale()`'s `useTranslation()` sees a real i18next
  instance, and drive the switch with the same `i18n.changeLanguage(...)` call
  `LocaleSwitcher` makes (not touching `locale-switcher.tsx` itself, per the read-only
  constraint) via a second `useTranslation().i18n` read inside the same `renderHook`. The
  inline `request` mock had to move behind `vi.hoisted(...)` — a plain top-level
  `const requestMock = vi.fn(...)` referenced from `vi.mock("@/lib/api/authenticated-client", …)`
  throws `ReferenceError: Cannot access 'requestMock' before initialization`, because
  `vi.mock` factories run at hoisted-import time, before a same-file `const` initializer has
  executed.
- Task 4.5: ran the exact `sdd/project.md` §Worktree bootstrap sequence (`mkdir -p /backend` in
  the frontend container, `docker compose cp backend/openapi.json frontend:/backend/openapi.json`,
  `ln -sfn /app /frontend`, `npm run api:generate`) against the CURRENT `backend/openapi.json`
  in this worktree (already regenerated by section 2, so `make openapi` was not re-run here).
  `git diff --stat` on `frontend/lib/api/generated/openapi.d.ts`: **6 lines changed (3
  insertions, 3 deletions doubled — the file emits each route's description twice, once under
  `paths` and once under `operations`)**, all six are `@description` JSDoc comment text on the
  same three routes section 2 touched (`list_dashboard_cards…`, `get_property_dashboard…`,
  `get_property_timeline…`); no type, parameter, or schema line changed. `npm run api:check`
  passes clean (types up to date) after the regeneration, confirming there is no drift left.
  `npx tsc --noEmit` stayed clean before and after.
- Verification for section 4: `docker compose exec -T frontend npx vitest run --project node
  features/dashboard/hooks lib/api lib/i18n` — 9 files, 77 tests, all green (includes the
  pre-existing 2 ENOENT-affected files' absence from this scoped run — they are outside
  `features/dashboard/hooks`, `lib/api`, `lib/i18n` so this run doesn't touch them).
  `npx tsc --noEmit -p tsconfig.json` clean. `npx eslint` on the six touched/added files clean.
  No `git commit` was made — sections 1-3's code changes are likewise still uncommitted in this
  worktree (only `tasks.md`'s checkboxes and notes are being written); committing is left to the
  run/review step that follows this implementer, consistent with the rest of this change so far.
- Section 5 (prose-only, R1.9): `docs/dashboard.md:43-49` — rewrote the epigraph from "el idioma
  sale del usuario, no de `Accept-Language`" to "el idioma sale de lo que declara la petición, no
  de `preferred_language` a secas"; body now names the `X-Locale` header (frontend fills it from
  i18next's resolved locale) as the primary source, with degradation to stored
  `preferred_language` and then to `es`; canonical-literals-untranslated sentence kept verbatim.
- `sdd/roadmap/timeline-web.md:70` — the `title`-translation bullet's "en el idioma de
  `preferred_language` del usuario" became "en el idioma que declara la petición (cabecera
  `X-Locale` …), con degradación al `preferred_language` … y a `es` …"; the rest of the bullet
  (description untranslated verbatim, frontend doesn't re-translate titles) untouched.
- `sdd/specs/dashboard-api.md:272-275` (section «Textos legibles en el idioma del usuario», first
  bullet only) — the `SHALL renderizarla en el idioma de preferred_language...RequestContext`
  claim rewritten to `SHALL renderizarla en el idioma que declara la petición vía X-Locale
  (RequestLocaleDep)`, degrading to `preferred_language`/`RequestContext` and then `es`
  (`resolve_locale`, `backend/app/core/i18n.py`). Line 487's bare file-listing bullet
  (`RequestContext.preferred_language`) was read and left as-is — it correctly names the
  attribute as the stored-preference fallback, doesn't assert it's the sole/primary source, so
  it isn't false. No other bullet in the 270-307 section asserted the superseded claim; no
  further rewrite attempted (full `SHALL` rewrite is `/sdd:archive`'s job per this task).
- `sdd/specs/revenue-statements.md:301-312` — "no existe ningún módulo `backend/app/core/i18n/`
  ni mecanismo de traducción por `Accept-Language` o locale de usuario en el backend de este
  proyecto" replaced with an acknowledgment that `backend/app/core/i18n.py` (`Locale`, `Catalog`,
  `resolve_locale`) now exists and translates request-declared-locale text, but is scoped to
  dashboard/timeline composition and does not reach error messages in
  `app/statements/api/errors.py` or `app/pricing/api/errors.py` — preserving the paragraph's real
  conclusion (R7.7 was never implemented for errors). Added a parenthetical to the task-10.1
  sentence clarifying the module didn't exist yet when that task ran, so that sentence isn't
  read as still true today.

### Section 6 (manual Playwright pass, R3; hydration paragraph, R4)

- **Precondition (6.1) was bigger than the task text says**: `backend/app/cli/bootstrap.py`'s
  `build_plan()` requires all eleven `BOOTSTRAP_*` vars (tenant name/billing email, owner
  name/email/password, manager name/email/password, super-admin name/email/password), not just
  the two owner/manager passwords the task names — it raises `BootstrapConfigurationError`
  listing every missing one. Filled all eleven with disposable local values (`*.test` emails,
  12+ char passwords — `PASSWORD_MIN_LENGTH = 12` in
  `backend/app/auth/domain/password_policy.py`). `make seed-demo` additionally needed
  `SEED_CLEANER_*`/`SEED_TECHNICIAN_*` (three vars each) that weren't mentioned anywhere in the
  task/design either — filled those too. None of this is committed; `.env` stays gitignored
  (confirmed with `git check-ignore .env` before editing).
- **Gotcha for whoever re-runs this**: `docker compose exec` reads the *container's* env, baked
  in at container creation from `env_file: .env` — filling `.env` after the stack is already up
  does nothing until the affected container is recreated. `make bootstrap` failed once with
  "missing all eleven" even after filling them, until `make up PORT_OFFSET=77` (which recreates
  backend/worker/beat) or a plain `docker compose up -d --no-deps backend` ran.
- **6.2 measured verdict: hydrates, cleanly, under `next dev`.** Driver: MCP Playwright.
  `PORT_OFFSET=77` (frontend `:3077`, backend `:8077`). No fallback to production build was
  needed — `next dev` responded and hydrated on the first successful load. Evidence: on
  `/login`, `document.querySelectorAll('*')` found `__reactFiber$…`-prefixed keys on 82 of 116
  elements *before* authenticating; clicking the language switcher mutated the whole DOM (tab
  title, headings, dashboard card text, property-detail + timeline text) with no reload, every
  time it was tried. Only console error across the whole pass: `favicon.ico` 404 (dev-server
  noise, not app). `allowedDevOrigins` was **not** touched in `frontend/next.config.ts` per D10
  (a resolved OQ) — the paragraph states it as an unverified hypothesis regardless of this
  measurement.
- **One transient, unrelated hiccup worth recording for whoever runs this suite next**: mid-pass,
  `frontend-verification-fixes-frontend-1` restarted twice on its own (`RestartCount` 0→2) while
  `incident-triage-web-frontend-1` — a different, unrelated live worktree on the same host — was
  observed at 780-900% CPU via `docker stats`. One login attempt failed with
  `net::ERR_EMPTY_RESPONSE` on `/api/v1/auth/login` and `/login` 404'd for about a minute during
  the restarts. This is host CPU contention from a concurrent session's container, not a
  hydration or cross-origin issue — it went away on its own once that container's spike
  subsided, and is *not* part of the hydration verdict above (the verdict is from the clean,
  stable run before and after). Not written into `sdd/project.md`'s hydration paragraph because
  it isn't about hydration; noted here only so a future reader doesn't mistake a stalled
  container for a reproduction of the old symptom.
- **6.3 measured result: all four role × locale combinations pass.** `TENANT_OWNER` and
  `PROPERTY_MANAGER`, each × `es`/`en`: dashboard card, property detail, and its embedded
  timeline all showed text composed in the *active* locale (e.g. "Revisar incidencia"/"Review the
  incident", "Incidencia clasificada"/"Incident classified") immediately after clicking the
  language switcher, with no manual reload, in all four combinations. Login was by click through
  the real form each time (never `page.goto` on a protected route — confirmed the documented "session
  lives in memory" behavior when a stray `page.goto('/timeline')` dropped straight to `/login`).
- **Files changed for 6.4/6.5**: `sdd/project.md` §Worktree bootstrap (hydration paragraph
  consolidated into one passage with today's measurement, `allowedDevOrigins` as an explicit
  unverified hypothesis, the credentials-in-URL warning kept, one sentence acknowledging the
  paragraph flip-flopped before); `sdd/roadmap.md` (`frontend-verification-fixes` entry) and
  `sdd/roadmap/frontend-verification-fixes.md` (findings 1/2 merged into a pointer at
  `sdd/project.md`'s paragraph, finding 3 and the "NO es" section untouched).
- **Pointers for section 7**: the stack is up at `PORT_OFFSET=77` (frontend `:3077`, backend
  `:8077`) with bootstrap + seed-demo data already applied — 7.4's `docker compose cp` +
  `npm test`/7.5/7.6 can reuse this same stack, no need to re-bootstrap. `.env` now has real
  (disposable) values for all `BOOTSTRAP_*`/`SEED_CLEANER_*`/`SEED_TECHNICIAN_*` vars — leave
  them as-is, don't reset/blank them back out; they're gitignored and harmless. 7.3
  (`make check-rule11-ownership`) runs on the host without the stack, unaffected either way.
