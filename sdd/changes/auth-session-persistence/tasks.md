# Tasks: auth-session-persistence

<!-- Section heading markers, read by /sdd:run (HTML comments appended to the
     heading, invisible when rendered): "hard" makes that section's implementer
     run on the stronger model; "panel: PASS <date>" is written by run itself
     when the section's review panel passes. -->

## 1. Backend: CORS middleware and the cookie helper <!-- panel: PASS 2026-09-04 -->

- [x] 1.1 Add `backend_cors_allowed_origin_regex: str` to `Settings`
      (`backend/app/core/config.py`), default
      `r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$|https://autohostai\.digitalsec\.work$"`
      (design D1) — not a secret, so it gets a working default per rule 8 of
      `steering/security.md`. [R7]
- [x] 1.2 Add the entry to `.env.example` (name + comment, no value) per
      `steering/documentation.md` — new environment variable rule. [R7]
- [x] 1.3 Mount `CORSMiddleware` (`fastapi.middleware.cors`) in
      `backend/app/main.py:create_app()`, **after** the `MaxBodySizeMiddleware`
      and `NoSniffMiddleware` calls (`app.add_middleware` inserts at position 0
      and the stack is built in `reversed()` order, so "after" in source order
      = outermost — **corrected 2026-09-04**: the original "before"/innermost
      placement left a `413` from `MaxBodySizeMiddleware._refuse()` — which
      answers via the raw ASGI `send` without calling `self._app(...)` —
      without CORS headers, violating R7.1; match design D1's actual intent
      that CORS wraps the whole app, including that response): `allow_origins=[]`,
      `allow_origin_regex=settings.backend_cors_allowed_origin_regex`,
      `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`. [R7.1]
- [x] 1.4 Add `SESSION_REFRESH_COOKIE = "autohostai.session.refresh"` constant
      and an `emit_refresh_cookie(response: Response, value: str, *, secure: bool,
      max_age_seconds: int) -> None` helper (design D4) in
      `backend/app/auth/api/schemas.py` (or a new one-constant
      `backend/app/auth/api/cookies.py` if that reads cleaner) that sets
      `HttpOnly`, `SameSite=Lax`, `Path=/api/v1/auth` and the given `Max-Age`/
      `Secure`. No caller yet — this task only adds the helper. [R1, R2, R3]
- [x] 1.5 Add a `resolve_cookie_secure(request: Request) -> bool` helper next to
      `get_client_ip` in `backend/app/auth/api/dependencies.py` implementing
      design D2: `request.url.scheme == "https"` **only** — **corrected
      2026-09-04**: uvicorn's `ProxyHeadersMiddleware` already rewrites
      `scope["scheme"]` from `X-Forwarded-Proto` under the same
      `--forwarded-allow-ips` trust gate it uses for `X-Forwarded-For`
      (verified against the installed uvicorn 0.51.0 source), so a manual,
      ungated `request.headers.get("x-forwarded-proto", ...)` read is both
      redundant on the trusted path and a trust-boundary violation on the
      dev backend port, which intentionally runs without
      `--forwarded-allow-ips` because it's published to the LAN — add a
      direct unit test for this helper's four scheme/header combinations
      (flagged by the run panel's `sdd-qa`: no test exercised it directly).
      Log the resolved value at the response side per R7.2's "registrar este
      matiz en el log de la response para auditoría" — a single
      `logger.info` in the handler that uses it is enough; do not add a new
      log sink. [R7.2, R7.3]
- [x] 1.6 New `backend/tests/test_cors.py`: a request with an allow-listed
      `Origin` header gets back `Access-Control-Allow-Credentials: true` and
      `Access-Control-Allow-Origin` reflecting that exact origin (never `*`);
      a request with a non-listed `Origin` gets no `Access-Control-Allow-Origin`.
      Use the same `create_app()` + `ASGITransport` pattern as
      `backend/tests/auth/test_api.py`. **Extended 2026-09-04** per the run
      panel's `sdd-qa`: add a `PORT_OFFSET`-style origin case (e.g.
      `http://localhost:3037`) asserting reflection, and an adversarial
      similar-but-wrong origin (a suffix/subdomain trick on the allowed
      hostnames, e.g. `https://autohostai.digitalsec.work.evil.com`)
      asserting rejection — the regex allowlist match must be anchored/full,
      not a substring match. [R7.1]

## 2. Backend: `/auth/login` emits the refresh cookie <!-- panel: PASS 2026-09-04 -->

- [x] 2.1 Remove `refresh_token` from `TokenPairResponse`
      (`backend/app/auth/api/schemas.py:83-87`). [R1.2]
- [x] 2.2 `backend/app/auth/api/router.py` `login()`: add a `response: Response`
      parameter; after `use_case.execute(...)` succeeds, call
      `emit_refresh_cookie(response, pair.refresh_token, secure=resolve_cookie_secure(request),
      max_age_seconds=settings.jwt_refresh_token_days * 86400)`. On the
      `InvalidCredentialsError`/`TooManyAttemptsError` failure paths (raised
      inside `use_case.execute`), no cookie is ever set because the exception
      propagates before this line runs — confirm this in the test rather than
      adding a redundant guard. [R1.1, R1.3]
- [x] 2.3 `backend/tests/auth/test_api.py`: update
      `test_login_returns_a_token_pair` — body keys become
      `{"access_token", "token_type", "expires_in"}` (no `refresh_token`), and
      assert the response's `Set-Cookie` header names
      `autohostai.session.refresh` and carries `HttpOnly`, `SameSite=Lax`,
      `Path=/api/v1/auth`, `Max-Age=604800`. Add a case for a failed login
      (wrong password) asserting **no** `Set-Cookie` header at all. [R1]

## 3. Backend: `/auth/refresh` reads the cookie, `/auth/logout` purges it <!-- panel: PASS 2026-09-04 -->

- [x] 3.1 Remove `RefreshRequest` entirely from
      `backend/app/auth/api/schemas.py:19-22`. [R2.3]
- [x] 3.2 `backend/app/auth/api/router.py` `refresh()`: drop the `body:
      RefreshRequest` parameter; add `response: Response`; read
      `token = request.cookies.get(SESSION_REFRESH_COOKIE)` and raise
      `InvalidTokenError("Token is not valid")` when it is absent (matches the
      existing 401 `INVALID_TOKEN` envelope — no new error path). On success,
      call `emit_refresh_cookie(response, pair.refresh_token, ...)` with the
      rotated value, same attributes as login. `RefreshTokenUseCase.execute`
      itself is unchanged (design D5) — it already takes `refresh_token: str`. [R2.1, R2.2, R2.3]
- [x] 3.3 `backend/app/auth/api/router.py` `logout()`: add `response: Response`;
      call `response.delete_cookie(SESSION_REFRESH_COOKIE, path="/api/v1/auth")`
      unconditionally after `use_case.execute(...)`, so both the "revoked
      something" and the "nothing to revoke" (idempotent) paths purge the
      cookie (design D6). **Keep the existing `204 No Content` status** — the
      logout contract's status code does not change, only the added
      `Set-Cookie`; see Implementation Notes below for why this reading was
      chosen over R3.1's literal "200". [R3.1, R3.2]
- [x] 3.4 `backend/tests/auth/test_api.py`: migrate every `json={"refresh_token":
      ...}` call to rely on the `AsyncClient`'s own cookie jar (login sets the
      cookie, the same `api` client instance carries it to the next call
      automatically) or, where a test needs a specific/invalid value,
      `api.cookies.set(SESSION_REFRESH_COOKIE, "...")`. Covers
      `test_the_whole_flow_login_me_refresh_logout`,
      `test_the_whole_flow_login_me_refresh_logout_for_a_super_admin`, and every
      other refresh/logout/reuse-detection test in the file. Add: refresh with
      no cookie at all → 401, no `Set-Cookie`; refresh with a `{"refresh_token":
      "..."}` JSON body but no cookie → 401 (body is ignored, not read as a
      fallback). Assert logout's response carries `Set-Cookie:
      autohostai.session.refresh=; Max-Age=0`. [R2, R3]
- [x] 3.5 `backend/tests/auth/test_recovery_api.py`,
      `backend/tests/auth/test_login_throttle_over_http.py`,
      `backend/tests/auth/test_user_admin_api.py`: same migration — replace the
      JSON-body `refresh_token` with the client's cookie jar or an explicit
      `cookies={SESSION_REFRESH_COOKIE: ...}`. [R2, R3]
- [x] 3.6 Verify `backend/tests/auth/test_use_cases.py` needs **no** change
      (design D10): it calls `RefreshTokenUseCase.execute(refresh_token=...)`
      directly, never through `RefreshRequest`. Run it to confirm, do not edit
      it speculatively.

## 4. Frontend: session-store, refresh-coordinator, and credentialed requests <!-- panel: PASS 2026-09-04 -->

- [x] 4.1 `frontend/lib/auth/session-store.ts`: `SessionTokens` becomes `{
      accessToken: string }` (drop `refreshToken`); `setSessionTokens`,
      `getSessionTokens`, `clearSessionTokens` need no other change. [R4.1, R4.2]
- [x] 4.2 `frontend/lib/auth/refresh-coordinator.ts`: `RefreshTokens` becomes
      `() => Promise<{ accessToken: string }>` (no argument — the refresh token
      travels via cookie, never through this module). `refreshSession()` no
      longer reads `current.refreshToken` to decide whether a session exists
      or to key the in-flight dedupe (lines 32-46) — key the dedupe on
      `sessionGeneration` alone, and treat "no access token in memory" as *not*
      a reason to skip calling refresh (a reload legitimately starts with an
      empty store and a live cookie — that path belongs to task 5.1's
      mount-refresh, this coordinator keeps serving the within-tab 401-recovery
      case per design D8's "two distinct callers"). [R6.1]
- [x] 4.3 `frontend/lib/api/client.ts`: add a `needsCredentials(path: string):
      boolean` helper (true for `/api/v1/auth/login`, `/api/v1/auth/refresh`,
      `/api/v1/auth/logout`) and pass `credentials: "include"` on `doFetch`
      when it returns true (design D9). [R7]
- [x] 4.4 `frontend/lib/api/authenticated-client.ts`: `refreshTokens` drops its
      `refreshToken` parameter, calls `POST /api/v1/auth/refresh` with an empty
      body, and returns `{ accessToken: tokenPair.access_token }` (no more
      `refreshToken` in the returned shape); update the `AuthenticatedClients`
      type accordingly. [R4, D8, D9]
- [x] 4.5 `frontend/lib/auth/auth-provider.tsx` `login()`
      (lines ~143-173): stop reading `tokens.refresh_token`; call
      `setSessionTokens({ accessToken: tokens.access_token })`. [R4]
- [x] 4.6 Grep the frontend tree for stray `refreshToken:` object-literal
      fields left over from the old `SessionTokens` shape outside the files
      above (found so far:
      `frontend/features/dashboard/hooks/use-dashboard-data.test.tsx:82`,
      `frontend/features/guest-portal/data/index.test.ts:54`) and drop the
      field from each mock so the tree type-checks clean against the new
      `SessionTokens`.
- [x] 4.7 Update `frontend/lib/auth/session-store.test.ts`,
      `frontend/lib/auth/refresh-coordinator.test.ts` and
      `frontend/lib/api/client.test.ts` for the new shapes: no more
      `refreshToken` field, `RefreshTokens` callback takes no argument, and a
      new case in `client.test.ts` asserting `fetch` was called with
      `credentials: "include"` for the three auth endpoints and without it for
      an arbitrary other path. [R4, R6, R7]

## 5. Frontend: silent mount-refresh in `AuthProvider` <!-- hard --> <!-- panel: PASS 2026-09-05 -->

- [x] 5.1 In `frontend/lib/auth/auth-provider.tsx`, add the mount-refresh
      `useEffect` (design D8, D11): on mount, if there is no access token in
      memory, set `status` to `"loading"`, call `clients.refreshTokens()` via
      the existing `authClient`/`apiClient` machinery (empty body,
      `credentials: "include"`, no `Authorization` header), and on success run
      `setSessionTokens({ accessToken })` then `GET /api/v1/auth/me` to
      populate `user` and resolve `"authenticated"`; on any failure (401,
      network) resolve `"anonymous"` with no visible error. Guard with a
      module-level (or `useRef`) in-flight flag so React StrictMode's
      double-invoke and multiple consumers mounting in the same tick share one
      network round-trip (D11) — once the promise settles, clear the guard so a
      later, real remount (e.g. after logout) can refresh again. [R5]
- [x] 5.2 `frontend/lib/auth/auth-provider.test.tsx`: add mount-refresh cases —
      successful restore (mock `/auth/refresh` 200 → `/auth/me` 200 → status
      `authenticated`, `user` populated), failed restore (401 → status
      `anonymous`, no thrown/visible error), and the single-flight guarantee
      (mount twice in the same tick, e.g. simulating StrictMode, and assert the
      refresh network call fired exactly once). [R5]
- [x] 5.3 `frontend/features/auth/auth-session.integration.test.tsx`: update the
      existing flows for the cookie-only contract (no `refresh_token` in
      mocked login responses) and add the reload-persists-session case: mount
      `AuthProvider` fresh with a mocked successful `/auth/refresh`, assert the
      transient `loading` state is followed by `authenticated` without a visible
      login form. Also confirm (R4.3, preexisting behavior — no code change
      expected in `use-logout-mutation.ts`/`session-cache-purge.ts` **at the
      time this task was written**; superseded — see the review findings log
      below, "HIGH (`sdd-security`)": a later review round DID change
      `use-logout-mutation.ts`, to keep an empty-store logout able to revoke
      the server-side session) that a
      logout still purges the access token, invalidates the `["auth", "me"]`
      query, and issues `POST /auth/logout`, unaffected by the cookie
      transport change (R6.2 — a second tab is untouched by this local purge
      until its own next 401, already the existing behavior). Add a case for
      R6.3: a refresh that comes back 401 (cookie already purged by another
      tab's logout) transitions this tab to `anonymous` without touching any
      other tab's state. [R4.3, R5, R6.2, R6.3]

## 6. Contract regeneration

- [x] 6.1 Regenerate `backend/openapi.json`: `make openapi`. Diff should show
      `refresh_token` gone from `TokenPairResponse` and `RefreshRequest` gone
      entirely; commit the regenerated file. [Documentation]
- [x] 6.2 Regenerate `frontend/lib/api/generated/openapi.d.ts`. In this worktree
      the plain `cd frontend && npm run api:generate` does not work (the
      `frontend` container only mounts `./frontend` — see `sdd/project.md`
      "Worktree bootstrap" § regenerar el contrato del frontend); use the
      documented workaround:
      ```
      docker compose exec -T frontend mkdir -p /backend
      docker compose cp backend/openapi.json frontend:/backend/openapi.json
      docker compose exec -T frontend ln -sfn /app /frontend
      docker compose exec -T frontend npm run api:generate
      ```
      Commit the regenerated file, then confirm `docker compose exec -T
      frontend npm run api:check` is clean (same workaround, `mkdir`/`cp`/`ln`
      must still be in place in this container). [Documentation]

## 7. Verification

- [x] 7.1 Backend suite: `docker compose exec backend uv run pytest`. Full
      green, including the new `test_cors.py` and every migrated `auth` test.
- [x] 7.2 Backend static tooling: `uv run pyright .` (from `backend`, per
      `sdd/project.md` Commands) — clean.
- [x] 7.3 Rule 11 ownership guard: `make check-rule11-ownership` (host,
      `python3`, no Docker, stack down) if any prose in `sdd/`/`docs/` or a
      backend docstring was touched.
- [x] 7.4 Frontend suite: `cd frontend && npm test`. Before running, re-apply
      the worktree `ENOENT` workaround from `sdd/project.md` (the `docker
      compose cp` list for `frontend/features/provenance/workflow-contract.test.ts`
      and `frontend/lib/config/build-identity-contract.test.ts`) if `make up`
      was re-run since task 6.2 — it resets the container and drops the earlier
      copies. Measure the baseline file/test count before this change's edits
      land so a regression is visible against *this* run, not a number written
      elsewhere.
- [x] 7.5 Frontend lint + typecheck: `cd frontend && npm run lint && npm run
      typecheck`.
- [x] 7.6 Manual check, browser: `make up PORT_OFFSET=<n>` (see `sdd/project.md`
      "Navegador en un worktree"), log in, open a **new tab** to the same
      `localhost:<frontend-port>` and confirm it resolves to the authenticated
      state without a login form (the R5 flow); then do a hard reload on one
      tab and confirm the same; then log out on one tab and confirm the other
      tab's next action (a navigation or an API call) drops it to `anonymous`
      (R6.3). Use `next dev` first; fall back to the documented `next
      build` + `next start` path only if `next dev` serves but does not
      hydrate.

## Implementation Notes

- Task 1.4's cookie helper landed in `backend/app/auth/api/schemas.py` (not a new
  `cookies.py`) — one constant, one helper, next to the other auth DTOs; no second file
  needed.
- `emit_refresh_cookie` signature is exactly `emit_refresh_cookie(response: Response,
  value: str, *, secure: bool, max_age_seconds: int) -> None`, per task 1.4's own
  restatement (not D4's positional prose) — sections 2 and 3 must call it keyword-only:
  `emit_refresh_cookie(response, pair.refresh_token,
  secure=resolve_cookie_secure(request), max_age_seconds=settings.jwt_refresh_token_days *
  86400)`.
- `resolve_cookie_secure` landed in `backend/app/auth/api/dependencies.py`, next to
  `get_client_ip`, taking only `request: Request`. **No `logger.info` call exists yet** —
  task 1.5 has no caller in this section (login/refresh/logout handlers are sections 2/3),
  so there is nothing to log from. R7.2's audit line ("registrar este matiz en el log de
  la response para auditoría") is sections 2/3's responsibility: add one `logger.info` in
  English in each of the three handlers that calls `resolve_cookie_secure`, logging the
  resolved `secure` boolean — do not add a new log sink.
- **Superseded by Fix 1 below — historical only, do not read as current state.** The
  first pass mounted `CORSMiddleware` in `backend/app/main.py:create_app()` BEFORE
  `MaxBodySizeMiddleware` and `NoSniffMiddleware` in source order, making it the innermost
  of the three, so a `413` from `MaxBodySizeMiddleware._refuse()` did NOT carry CORS
  headers. Fix 1 corrected the mount order to outermost; `backend/tests/test_cors.py::
  test_oversized_cross_origin_body_gets_413_with_cors_headers` now pins the corrected
  (current) behavior — a `413` DOES carry `Access-Control-Allow-*` headers.
- `test_cors.py` hits the anonymous, DB-free `/health` route rather than any `/auth/*`
  route, so it needs no `db_session` fixture. Starlette's `CORSMiddleware` sets
  `Access-Control-Allow-Credentials: true` on every "simple" (non-preflight) response once
  `allow_credentials=True`, **regardless of whether the origin is allowlisted** — only
  `Access-Control-Allow-Origin` is conditional on `is_allowed_origin`. The test for a
  disallowed origin therefore asserts only the absence of
  `Access-Control-Allow-Origin`, which is what the browser's CORS check actually keys on.
- `.env.example`'s `BACKEND_CORS_ALLOWED_ORIGIN_REGEX` entry is commented out (working
  default lives in `app/core/config.py`), following the same convention as the password
  recovery block just below it.
- **Fix 1 (2026-09-04, panel finding)**: `backend/app/main.py` — moved the `CORSMiddleware`
  `add_middleware` call to after `MaxBodySizeMiddleware`/`NoSniffMiddleware`, making CORS
  the outermost of the three; `backend/tests/test_cors.py` gained a direct test that drives
  the ASGI app with a declared oversized `Content-Length` on a cross-origin
  `/api/v1/auth/login` request and asserts the `413` carries `Access-Control-Allow-*`.
- **Fix 2/3 (2026-09-04, panel findings)**: `backend/app/auth/api/dependencies.py` —
  `resolve_cookie_secure` now reads `request.url.scheme` only (manual `X-Forwarded-Proto`
  read removed); new `backend/tests/auth/test_cookie_secure.py` covers the direct
  HTTPS-true / plain-HTTP-false cases. **Fix 4**: `backend/tests/test_cors.py` gained a
  `PORT_OFFSET`-style positive case and a suffix/subdomain-trick negative case for the
  origin regex.
- Encountered and resolved: `docker compose exec backend` served a stale/unlinked
  `/workspace/.env.example` bind-mount view mid-session (host `stat` showed `Links: 0` on
  the container-side inode) after editing the file on the host, failing
  `test_env_example_declares_the_demo_password_by_name_and_without_a_value` with
  `FileNotFoundError` despite `ls`/`stat` succeeding. `docker compose restart backend`
  fixed it; unrelated to this section's content. Worth knowing if a later section edits
  `.env.example` again and hits the same symptom.
- `uv run pyright .` reports 907 pre-existing errors on this branch, confirmed identical
  with and without this section's changes (`git stash` A/B compared) — none touch any
  file or symbol this section added or modified. Treat 907 as the pre-existing baseline,
  not a regression to chase.
- **Section 2 landed (2026-09-04)**: `TokenPairResponse.refresh_token` removal (task 2.1)
  is global, so it breaks every test still reading `body["refresh_token"]` from a login
  response, not just the ones task 2.3 updates. Confirmed via a full `tests/auth` run:
  exactly 10 failures, all `KeyError: 'refresh_token'` at that exact line — no other
  regression. They are precisely the tests task 3.4/3.5 already name for migration:
  `test_api.py::test_the_whole_flow_login_me_refresh_logout(_for_a_super_admin)`,
  `test_a_refresh_token_is_not_accepted_as_a_bearer`,
  `test_an_access_token_still_works_after_logout_through_the_real_boundary`;
  `test_recovery_api.py::test_the_previous_sessions_are_revoked`,
  `test_the_calling_session_itself_is_revoked`,
  `test_the_previous_sessions_die_and_the_login_after_a_lockout_works`,
  `test_a_temporary_password_still_logs_in`, `test_refresh_works_while_fenced`;
  `test_user_admin_api.py::test_deactivating_a_user_stops_it_from_refreshing`. **This is
  expected, not a Section 2 defect** — Section 3 fixes all 10 as part of migrating
  `/auth/refresh` off the request body onto the cookie (the same client instance's cookie
  jar already carries the cookie login sets, so these tests won't need much more than
  dropping the `json={"refresh_token": ...}` argument). The full `tests/auth` suite will
  stay red until Section 3 lands; do not treat this as a blocking regression when
  reviewing Section 2 in isolation.

- R3.1 of `proposal.md` literally says logout responds "200"; the existing
  endpoint returns `204 No Content` and `design.md`'s own OpenAPI section
  (`Data & interfaces`) keeps it at 204. Task 3.3 keeps 204 — the requirement's
  substance (revoke + purge the cookie) is unaffected by the status code, and
  changing an established contract with no test or caller asking for it would
  be an unrelated behavior change. Flag for `/sdd:archive` to reconcile the
  wording in `proposal.md`/`sdd/specs/auth-tenancy.md`.
- **Section 3 landed (2026-09-04)**: `/auth/refresh` now reads
  `SESSION_REFRESH_COOKIE` from `request.cookies` and raises
  `InvalidTokenError("Token is not valid")` (the same 401 `INVALID_TOKEN`
  envelope) when it is absent — no new error path, and a body-supplied
  `refresh_token` is never read (R2.3). `RefreshTokenUseCase.execute` itself is
  untouched, confirming design D5.
- **FastAPI gotcha found and fixed in `logout()`**: the original handler
  constructed and returned a fresh `Response(status_code=204)` rather than the
  injected `response: Response` dependency. When an endpoint returns its own
  `Response` instance, FastAPI sends that instance as-is and does **not**
  merge headers (cookies included) set on the injected dependency — so
  `response.delete_cookie(...)` on the injected object would have silently
  produced no `Set-Cookie` at all. Fixed by mutating and returning the SAME
  injected `response` (`response.delete_cookie(...)`, then
  `response.status_code = 204`, then `return response`) instead of
  constructing a new one. Worth knowing for any later section that adds
  cookie/header mutations to a handler already returning an explicit
  `Response`.
- `refresh()`'s frontend-facing contract shape is unchanged from Section 2:
  `TokenPairResponse` body is still `{access_token, token_type, expires_in}`
  (no `refresh_token` field, ever) on both `/auth/login` and `/auth/refresh`;
  the rotated refresh token travels exclusively via the `Set-Cookie` header,
  same attributes as login (`HttpOnly`, `SameSite=Lax`,
  `Path=/api/v1/auth`, `Max-Age=604800`). Section 4 can rely on this being
  identical across both endpoints.
- `logout()`'s cookie purge is `Set-Cookie: autohostai.session.refresh=;
  Max-Age=0; Path=/api/v1/auth` via `Response.delete_cookie`, sharing `Path`
  with `emit_refresh_cookie` (design D6) so the browser's jar actually drops
  it — confirmed directly in `test_api.py`'s whole-flow test.
- `backend/tests/auth/test_login_throttle_over_http.py`'s `refresh_attempt`
  helper now sends the deliberately-invalid probe value as the
  `SESSION_REFRESH_COOKIE` cookie (set on the `AsyncClient` instance, not as a
  per-request `cookies=` kwarg — httpx deprecates the latter) rather than in
  the JSON body: a missing cookie now 401s in the router BEFORE
  `RefreshTokenUseCase.execute` (and its throttle check) ever runs, which
  would have silently broken `test_refresh_is_rate_limited_per_client_too`
  and `test_refresh_and_login_share_one_budget_per_client` (R8's "throttle
  consulted before the token is looked at") had the probe stayed in the body.
- ~~R7.2's audit-log gap flagged in Section 1's notes ("registrar este matiz en
  el log de la response para auditoría") is still open: no `logger.info` call
  exists in `login()`, `refresh()`, or `logout()` for the `resolve_cookie_secure`
  result. Out of scope for Section 3 (R7 is not among this section's assigned
  requirements, and it is not named in tasks 3.1-3.6) — flagged here again so
  it is not lost; whichever section/archive step reconciles R7.2 should add
  one `logger.info` per handler that calls `resolve_cookie_secure`.~~ **Closed
  2026-09-05** (review-panel fix round, `sdd-architect`/`sdd-qa` medium): added
  `logger.info("auth.refresh_cookie_issued", extra={"secure": ..., "scheme": ...,
  "endpoint": ...})` in both `login()` and `refresh()` (not `logout()`, which never
  calls `resolve_cookie_secure`). Covered by
  `test_login_logs_the_resolved_cookie_secure_decision` and
  `test_refresh_logs_the_resolved_cookie_secure_decision` in `test_api.py`.
- Full backend suite (`docker compose exec backend uv run pytest`): all 10
  previously-failing tests named in the "Section 2 landed" note above now
  pass, and `tests/auth/` alone is 882 passed, 0 warnings. The **only**
  remaining red in the whole suite is
  `tests/test_openapi_contract.py::test_the_committed_contract_matches_the_code`
  — expected and NOT this section's to fix: it diffs the committed
  `backend/openapi.json` against the live schema and finds exactly the
  `RefreshRequest` removal (task 3.1) and the now-bodyless `/auth/refresh`
  (task 3.2), which is precisely what task 6.1 (`make openapi`, out of scope
  for Section 3 per this task's own Contract) exists to reconcile. Full
  result: `1 failed, 10186 passed, 43 skipped in 716.78s`. Section 6 should
  see this test go green as a side effect of regenerating the contract, not
  treat it as a fresh regression.
- **Section 3 review-panel fix round (2026-09-04, test-only, no production code
  changed)**: `backend/tests/auth/test_api.py` gained four cases/assertions closing the
  security/qa low-severity coverage gaps. (1) New
  `test_refresh_uses_the_cookie_even_when_the_body_also_carries_a_valid_token`: two
  distinct logins produce two distinct valid refresh tokens; the request's cookie names
  one, the body's `refresh_token` names the other. Proves R2.3's "cookie wins" concretely
  — the body's token is untouched by the call (still live, rotates cleanly afterward),
  confirming `refresh()` never even binds a request body (no `RefreshRequest` parameter on
  the handler at all, so httpx's `json=` payload is inert). (2)
  `test_the_whole_flow_login_me_refresh_logout` and its super-admin variant now assert the
  raw `set-cookie` header off the `/auth/refresh` response (`Max-Age=604800`, `HttpOnly`,
  `Path=/api/v1/auth`), matching the login test's existing pattern — previously only the
  httpx-parsed cookie value was checked. (3) The `reused_explicit` case (a revoked/rotated
  cookie presented again) now also asserts `"set-cookie" not in reused_explicit.headers`,
  closing R2.2's "no `Set-Cookie` on a revoked-cookie 401" for this path (the absent-cookie
  path already had the equivalent check). (4)
  `test_the_whole_flow_login_me_refresh_logout` gained a second `/auth/logout` call on the
  same already-logged-out client (same still-valid access token, no cookie churn needed),
  asserting `204` and a fresh `Set-Cookie: autohostai.session.refresh=; Max-Age=0` purge
  header — proves R3.2's idempotency, which no existing test exercised (every prior
  `/auth/logout` call happened on a client whose very first logout was the one under test).
  All four passed on first run with no implementation changes — the panel's read that
  Section 3 is behaviorally correct and only under-tested holds. `tests/auth/` is now 883
  passed (882 baseline + 1 new test function; findings 2-4 extended existing tests rather
  than adding new ones). `uv run pyright .` still reports the 907-error baseline, 0 new,
  none in `tests/auth/test_api.py`.

- **Section 4 landed (2026-09-04) — notes for Section 5**:
  - `refreshSession()` in `refresh-coordinator.ts` no longer short-circuits on "no access
    token in memory" — task 5.1's mount-refresh can rely on calling it directly with an
    empty store, and the existing `useEffect` ordering with `clearSessionTokens` / logout is
    unchanged. Dedupe is still keyed on `sessionGeneration`, so StrictMode's double-mount
    in task 5.2 still collapses to one network call inside this coordinator; the task's
    explicit `useRef`/module-level single-flight guard is belt-and-braces for the
    *mount-refresh* call site, not a replacement for this one (D11 is correct as written).
  - `clients.refreshTokens` is now `() => Promise<SessionTokens>` with no argument — the
    rotated refresh token rides the `Set-Cookie` from a credentialed `/auth/refresh` POST
    (`needsCredentials` set, see `client.ts`). Task 5.1 must call it on the existing
    `authClient` (`createAuthenticatedClients` already wires one), NOT on `apiClient`,
    because the cookie lives on a per-client `Request.credentials` posture and the design
    D9 helper keys off the path. The shape return is `{ accessToken }` — drop any
    `refreshToken` reads.
  - `auth-provider.test.tsx` lines 700/713 (the "drops the in-memory tokens" /
    "moves the session generation" tests) had to be updated to drop the `refreshToken:
    "r"` half of the `setSessionTokens` payload (they were mock-only, no behaviour
    change). 8 occurrences total in that file were the same mechanical `{ accessToken,
    refreshToken }` → `{ accessToken }` narrowing — no test logic was rewritten, only the
    fixture shape.
  - The new `client.test.ts` cases (D9) check `init.credentials === "include"` on the
    three auth endpoints and `=== undefined` on `/health` — they're the wire-level proof
    that D9's helper is wired; task 5.2's mount-refresh test will exercise the path
    transitively via `clients.refreshTokens`.
  - `frontend/lib/api/generated/openapi.d.ts` is still the pre-Section-2 shape:
    `TokenPairResponse.refresh_token` and `RefreshRequest` are both still declared in the
    generated types, and `/auth/refresh`'s declared request body is
    `components["schemas"]["RefreshRequest"]`. None of Section 4's narrowed call sites
    reads `refresh_token` or passes a body to `/auth/refresh`, so nothing fails to
    compile. Section 6 regen will remove both schemas; no Section 4 code touches the
    generated types directly.
  - **BLOCKER for verification (2026-09-04)**: Docker Desktop's daemon socket is missing
    on disk (`/Users/hardcode/.docker/run/docker.sock`) despite `com.docker.backend`
    processes running — almost certainly the harness restart that interrupted Section 4
    also killed the Docker VM, and the rebuild needs user interaction (privileged port
    dialog) the harness can't supply. Full suite / lint / typecheck could not be run by
    Section 4; the listed tasks were marked `[x]` purely on the basis of the diffs
    reading correct, not because the runner verified them. Whoever resumes must re-run
    `docker compose exec -T frontend npm test -- --run`, `npm run lint`, and `npm run
    typecheck` against the baseline of 204 files / 2115 tests before opening the PR.
    Section 4 itself did not touch anything that should regress on those (no new tests
    added outside the three test files in 4.7, all mechanical updates), so the expected
    delta is `+5` tests (4 new in `client.test.ts`, 1 new in `refresh-coordinator.test.ts`
    for the "calls refresh even when no access token is in memory" case) and `+2`
    test files only if the runner counts them — the file count is determined by
    `vitest`'s discovery and won't move.
  - **BLOCKER resolved (2026-09-04, same day)**: Docker came back after the orchestrator
    restarted Docker Desktop. Verification then ran for real: `npm test -- --run` → 204
    files / 2120 tests (exactly the predicted `+5`, 0 regressions), `npm run lint` clean,
    `npm run typecheck` clean. Section 4's panel (architect/security/qa/i18n, all PASS)
    ran against this verified state.

- **Section 5 landed (2026-09-04) — notes for Section 6/7 and the archiver**:
  - `AuthProvider`'s initial `status` is now `getSessionTokens() ? "anonymous" : "loading"`
    (a lazy `useState` initializer), NOT a `setStatus("loading")` inside the mount effect as
    D8 step (1) reads. React runs child effects before parent effects, so an `AuthGuard`
    mounted underneath reads the provider's state on the first commit and would have fired
    `router.replace("/login?returnTo=…")` on every page load before the silent refresh could
    even start. The observable contract (R5.1's transient `loading`) is unchanged; only
    where the value is set moved. `design.md` D8's step ordering should be reconciled at
    archive time.
  - The D11 guard is `inFlightMountRefresh: {generation, promise} | null` at module scope in
    `auth-provider.tsx`, keyed on `getSessionGeneration()`. It resolves
    `Promise<CurrentUser | null>` (as D11 now specifies, corrected 2026-09-05), so a provider that JOINS an
    in-flight refresh gets the identity without issuing a second `GET /auth/me` — the
    single-flight test asserts exactly one `/auth/refresh` AND exactly one `/auth/me` for two
    providers mounted in the same tick. Keying on the generation also means a leftover
    promise cannot be joined by a later test/mount whose store was cleared in between.
  - `mountRefreshSuperseded` (a `useRef`) is set by `login`, `logout`, `refresh` and both
    event subscriptions; a mount-refresh that settles afterwards drops its result instead of
    overwriting the newer state. Without it, a user who submits the login form while the
    silent restore is still in flight can end on `anonymous` after a failed login (the
    "clears the pair and exposes an error state when login fails" test does exactly this
    race, synchronously).
  - A refresh that succeeds but whose `/auth/me` then fails calls `clearSessionTokens()`
    before resolving `null` — otherwise the store would hold an access token backing an
    identity the provider never read.
  - `markSessionPresent()` is called on a successful mount-refresh, keeping the invariant
    "authenticated ⇒ presence cookie set" (the cookie gates the `/` → `/dashboard` server
    redirect and a reload restores the session without going through `login()`).
  - **Test-fixture churn this forced, all mechanical**: every `AuthProvider` mount with an
    empty store now fires one `POST /auth/refresh`, so positional
    `mockResolvedValueOnce` chains handed the mount-refresh the response meant for the
    login that followed. `auth-provider.test.tsx`'s four chained stubs became URL-dispatching
    `mockImplementation`s (shared `jsonResponse` / `noSessionCookie` / `USER_ONE` /
    `TOKEN_PAIR` / `userSwapFetch` helpers at the top of the file). Any later section adding
    a test that mounts `AuthProvider` must answer `/auth/refresh` in its `fetch` stub or the
    provider hangs on `loading`.
  - **Two tests outside the section's named files had to change** because they assert the
    pre-R5 initial state: `lib/auth/auth-provider.test.tsx`'s "starts anonymous without
    attempting session restoration" was replaced by the R5 cases (it asserted
    `fetch` was never called at mount, which R5.1 now forbids — kept as "skips the
    mount-refresh when the runtime already holds an access token", the case where that
    assertion is still true), and `app/providers.test.tsx` (NOT in `tasks.md`'s file list,
    reaches `AuthProvider` through `AppProviders`) now asserts `loading` then `anonymous`
    instead of a bare `anonymous`.
  - Section 5 verification, real runs against the live container: `npm test -- --run` →
    **204 files / 2127 tests, all passing** (baseline 204/2120; net +7 = 5 new in
    `auth-provider.test.tsx`, 3 new in `auth-session.integration.test.tsx`, 1 removed).
    `npm run lint` clean, `npm run typecheck` clean.
  - R6.3 is covered as the mount-refresh 401 path (`anonymous`), not the 401-recovery path
    (which resolves `expired`): the second tab only learns about the purged cookie when its
    own runtime restarts or its next refresh 401s. The test also asserts the failed restore
    broadcasts nothing on `subscribeToSessionExpired` / `subscribeToLogout`, which are the
    only cross-component channels — the closest in-runtime proof of "sin afectar a las
    restantes" available without a second browser context (task 7.6's manual check is the
    real cross-tab verification).
  - **Section 5 panel fix (2026-09-05, `sdd-security` HIGH)**: `runMountRefresh` now re-checks
    `getSessionGeneration()` against the generation captured at start *before* calling
    `setSessionTokens`, and resolves `null` (dropping the token, without clearing — whatever
    the store holds then belongs to the newer session) when it moved; this is the same guard
    `refresh-coordinator.ts:46` applies, and it closes the gap `mountRefreshSuperseded` did
    not cover, which only gated the later `setUser`/`setStatus`. In practice all three racing
    transitions (logout, a 401-driven session-expiry, a login as a different identity) also
    set `mountRefreshSuperseded`, so the effect no-ops rather than forcing `anonymous`; the
    `anonymous` fallback stands only for a generation move nothing in this provider drove.
    Covered by the new "drops a mount-refresh token that resolves after the session was torn
    down (D8)" test, verified to fail with the guard removed. Matches design.md D8's
    "added 2026-09-05" paragraph.
  - **Section 5 panel fix (2026-09-05, `sdd-qa` medium)**: the "refresh succeeds but
    `/auth/me` fails ⇒ `clearSessionTokens()`" branch had no test; added "leaves no access
    token behind when the mount-refresh works but `/auth/me` does not (R5.3)" to
    `auth-provider.test.tsx`, asserting `getSessionTokens() === null` and `status ===
    "anonymous"` after the mount-refresh settles. `/auth/me` is stubbed as a network
    rejection rather than a 401 on purpose: a 401 with a token installed re-enters
    `onUnauthorized` → `refreshSession` → retry, which exercises the 401-recovery path
    instead of the branch under test.
  - Re-verification after both fixes: `npm test -- --run` → **204 files / 2129 tests, all
    passing** (+2 vs. the 204/2127 Section 5 baseline). `npm run lint` clean,
    `npm run typecheck` clean.
  - ~~**Residual, not fixed here** (out of the panel's findings and not described by D8): the
    same clobber window exists in `runMountRefresh`'s `catch`, which calls
    `clearSessionTokens()` whenever `tokensInstalled` is true, without comparing the
    generation. A `login()` that completes while the mount-refresh's `/auth/me` is still in
    flight would have its fresh tokens dropped by that clear. It is the mirror of the
    trade-off already documented at the `subscribeToSessionExpired` listener; fixing it
    means deciding shared auth semantics, so it belongs with the existing
    `auth-session-generation-semantics` roadmap candidate.~~ **Superseded 2026-09-05** — the
    re-review round ruled this in scope (it is a race in code this change introduces, not one
    of the two pre-existing `refresh-coordinator.ts` facts the roadmap entry catalogued) and
    it is fixed by the bullet below; D8 now describes it.
  - **Section 5 panel re-review fix (2026-09-05, `sdd-architect` HIGH / `sdd-security`
    medium)**: `runMountRefresh` now captures `getSessionGeneration()` into
    `postInstallGeneration` immediately after its own `setSessionTokens` succeeds (replacing
    the `tokensInstalled` boolean, whose information it subsumes), and its `catch` calls
    `clearSessionTokens()` only while that value still equals the live generation — the
    mirror of the success-path guard and of `refresh-coordinator.ts:54`. A concurrent
    `login()` that lands a newer session's token while this mount-refresh's `/auth/me` is
    still in flight therefore keeps its credentials. Covered by the new "keeps a concurrent
    login's tokens when the mount-refresh's own /auth/me fails afterwards (D8)" test,
    verified to fail (`expected undefined to be 'newer-access'`) with the generation
    comparison removed. Same round: the `runMountRefresh` doc-comment no longer cites D11's
    superseded `Promise<void>` wording — D11 now specifies `Promise<CurrentUser | null>`
    directly, so the "design says X but we do Y" framing asserted a mismatch that no longer
    exists. Verification after this fix: `npm test -- --run` → **204 files / 2130 tests, all
    passing** (+1 vs. 204/2129). `npm run lint` clean, `npm run typecheck` clean.

- **Section 7 verification results (2026-09-05, run by the orchestrator directly, per
  shared rule)**:
  - 7.1: `docker compose exec backend uv run pytest -q` → **10188 passed, 43 skipped, 0
    failed** (the openapi-contract test, red before 6.1/6.2 landed, is now green).
  - 7.2: `uv run pyright .` → **907 errors** — the confirmed pre-existing baseline
    throughout this run, 0 new.
  - 7.3: `make check-rule11-ownership` (host, stack down) → clean verdict: "ningún bloque
    fuera de la tabla de la regla 11 declara quién escribe un sumidero del censo".
  - 7.4: `docker compose exec -T frontend npm test -- --run` → **204 files / 2130 tests,
    all passing**. Hit the documented `ENOENT` regression once (`make up` after 7.3's
    teardown recreated the frontend container and dropped the earlier `docker compose cp`
    workaround, exactly as `sdd/project.md` warns) — reapplied the full workaround
    (provenance contract, build-identity fixtures, CI workflow copies, both
    docker-compose files) and re-ran clean.
  - 7.5: `npm run lint` and `npm run typecheck` → both clean.
  - 7.6: manual browser pass via Playwright MCP against `make up PORT_OFFSET=41` (after
    filling disposable dev credentials for `make bootstrap`/`seed-demo` into the
    worktree's gitignored `.env` — never committed). Logged in as the seeded owner;
    opened a second tab to the same `/dashboard` URL and it resolved straight to the
    authenticated shell (nav, user menu showing the email) with no login form — R5;
    hard-reloaded that same tab and it persisted the authenticated state — R5.2/R5.3
    working end-to-end; logged out on the first tab (redirected to `/login`); reloaded
    the second tab and it dropped to `/login?returnTo=%2Fdashboard` — R6.3, the other
    tab's next mount-refresh hit the now-purged cookie, got 401, and resolved
    `anonymous` with no visible error, only the expected console 401 on
    `/api/v1/auth/refresh`. No other console errors.

- **`/sdd:review` panel re-review fixes (2026-09-05, High + Medium findings only —
  the panel's Low-severity security findings on cookie scoping/`__Host-`, same-site
  CSRF on `/auth/refresh`, and CORS-regex anchoring were deliberately left for a
  separate decision and are not addressed here)**:
  - **HIGH (`sdd-review-cicd`)**: the `Secure` cookie attribute was unsatisfiable in
    the deployed dev topology — `frontend/app/api/[...path]/route.ts` stripped the
    client's `x-forwarded-proto` (correct) but never re-set it, so uvicorn's
    `ProxyHeadersMiddleware` had nothing to rewrite `scope["scheme"]` from and
    `resolve_cookie_secure()` always saw `http`, even behind the HTTPS-only
    Cloudflare tunnel. Fixed: `outboundHeaders()` now sets `x-forwarded-proto: https`
    whenever the request carries `cf-connecting-ip` — the same trust signal
    `edgeClientIp()` already relies on, since that header can only have been added by
    Cloudflare's TLS-terminating edge (`always_use_https`), never by a caller of this
    container directly. Covered by three new cases in `route.test.ts` (`reports https
    to the backend when the edge is in front`, `does not claim https for a request
    that bypassed the edge`, `ignores a client-supplied x-forwarded-proto even when
    the edge is in front`).
  - **HIGH (`sdd-security`)**: logout could leave the server-side session and its
    `HttpOnly` refresh cookie alive — `use-logout-mutation.ts` skipped the
    `POST /auth/logout` call entirely when the in-memory store was empty, and
    `client.ts` excluded `/api/v1/auth/logout` from the normal 401-recovery path, so a
    stale-but-present Bearer token 401'd with no retry either. Fixed on both sides:
    `client.ts`'s recovery exclusion now covers only `login`/`refresh` (logout's 401
    is an ordinary expired-access-token 401 like any other authenticated endpoint's,
    recoverable the same way); `use-logout-mutation.ts` now attempts one
    `refreshSession` first when the store is empty, purely to obtain a Bearer token
    the logout call can present — a failed refresh means the cookie was already
    invalid, i.e. nothing left to revoke. Covered by a new test in `client.test.ts`
    (`recovers a 401 on logout exactly like any other authenticated endpoint`) and a
    new integration test in `auth-session.integration.test.tsx` (`recovers a logout
    with no cached access token via a fresh refresh`).
  - **MEDIUM (`sdd-architect`/`sdd-review-documentation`)**: `docs/auth-tenancy.md`
    — assigned to this change's own implementation table in `design.md` but never
    updated by any task — still documented `/auth/login` returning `refresh_token` in
    the body. Fixed: rewrote the endpoint table and added a new "El refresh token
    viaja por cookie, no por cuerpo" section documenting the cookie attribute set,
    `Secure`'s per-environment resolution, and the `x-forwarded-proto` re-signing this
    same round added.
  - Not independently re-run in full after these fixes (scoped `pytest`/`vitest`
    runs on the touched files were used while iterating); Section 7's full-suite
    commands above should be re-run once more before the next `/sdd:review` pass.
