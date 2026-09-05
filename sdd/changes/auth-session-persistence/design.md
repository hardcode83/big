# Design: auth-session-persistence

## Context

The frontend stores both access and refresh JWTs in the runtime-only
`session-store.ts` (`frontend/lib/auth/session-store.ts:7-10`) and sends the
refresh token in the body of `POST /api/v1/auth/refresh`
(`frontend/lib/auth/authenticated-client.ts:48-58`,
`backend/app/auth/api/router.py:80-91` reads it at
`backend/app/auth/api/schemas.py:23-26`). A reload, a new tab, or a new browser
instance therefore drops the refresh token and forces a manual login even when
the user still owns a valid session. The backend emits the refresh token in the
body of `POST /api/v1/auth/login` (`backend/app/auth/api/schemas.py:113-117`,
`backend/app/auth/application/use_cases.py:118-135`) and the cookie surface is
empty (`grep -rn "Set-Cookie\|set_cookie\|httpOnly" backend/app/` returns
nothing). CORS is **not** configured today: the production frontend reaches the
backend same-origin through `frontend/app/api/[...path]/route.ts`, and dev uses
`NEXT_PUBLIC_API_BASE_URL` directly to a different port — the cookie contract
makes both reach the backend with credentials, and the new attribute
`Secure` has to track the request scheme because dev is HTTP and prod is HTTPS.

This change moves the refresh token into a `httpOnly Secure SameSite=Lax`
cookie emitted by the backend, leaves the access token in memory, removes the
refresh from the body's contract (no dual period), and wires a silent
mount-refresh in `AuthProvider` so a reload resolves to the persisted
session.

## Decisions

### D1 — CORS is introduced for the first time, with `Allow-Origin` reflecting the request

**Chosen**: mount `CORSMiddleware` in `create_app()` with
`allow_origins` left empty, `allow_credentials=True`, `allow_origin_regex` set to
a configurable `BACKEND_CORS_ALLOWED_ORIGIN_REGEX`
(`Settings.backend_cors_allowed_origin_regex`, default
`^https?://(localhost|127\.0\.0\.1)(:\d+)?$|https://autohostai\.digitalsec\.work$`),
and `allow_methods=["*"]` / `allow_headers=["*"]` so the existing public API
and the cookie flow both work. Allowlist-driven origin reflection (regex match
on `Origin` if present, else no `Access-Control-Allow-Origin`) is the only
shape that co-exists with `allow_credentials=True`: a static `allow_origins`
list forces `*` semantics at the ASGI layer when credentials are on, which
browsers reject. R7.1 demands "Allow-Origin explícito, no `*`"; reflecting an
allowlisted origin meets that without enumerating every dev worktree's port.
**The default covers both dev (`localhost`/`127.0.0.1` with any `PORT_OFFSET`)
and the prod hostname; deploy compose writes the env var only when a new
origin is added — agreed at gate.**

Rejected: per-deploy static origin lists — `make up PORT_OFFSET=<n>` shifts
ports on every worktree (`sdd/project.md:96-100`), so a hardcoded list would
silently break every neighbour's worktree. Rejected: hardcoding the regex
without a setting — a future origin would force a code change. Rejected:
dropping the `httpOnly` cookie in favour of a SameSite=None token in the body
— that is the exact XSS-flavoured leak the proposal rejects in its opening
paragraph.

### D2 — `Secure` is decided by the request's **external** scheme, not the ASGI scheme

**Chosen**: in the auth handlers (`login`, `refresh`, `logout`), set
`Secure` on `Response.set_cookie(...)` iff the effective scheme of the
**client request** is HTTPS, resolved by `request.url.scheme == "https"`
alone.

**Corrected 2026-09-04** (the run panel's `sdd-security` found this
section's original premise factually wrong against the installed uvicorn
0.51.0 source): uvicorn's `ProxyHeadersMiddleware` rewrites **both**
`scope["client"]` (from `X-Forwarded-For`) **and** `scope["scheme"]` (from
`X-Forwarded-Proto`) under the exact same `--forwarded-allow-ips` trust
gate (`sdd/specs/auth-tenancy.md` §Identificación del cliente) — it was
wrong to claim the scheme rewrite doesn't happen. So `request.url.scheme`
is already proxy-aware and trust-gated, the same way `get_client_ip`
already trusts `scope["client"]` rather than reading `X-Forwarded-For`
itself. A second, manual `request.headers.get("x-forwarded-proto")` read is
redundant on the trusted path and, worse, ungated on the untrusted one: the
dev stage pins `--forwarded-allow-ips 127.0.0.1` in `backend/devops/Dockerfile`
— not its absence — so `docker-compose.yml` can publish `:8000` on every
interface and still trust nobody but the container's own loopback; a LAN
peer reaching the published port directly does not present as loopback, so
uvicorn never rewrites the scheme for it regardless of what header it
sends. A raw header read would bypass that gate entirely and let any LAN
peer force `secure=True` by spoofing it, breaking that
standing principle for exactly the header `get_client_ip`'s own docstring
warns against trusting unconditionally. `resolve_cookie_secure` therefore
reads `request.url.scheme` only.

Rejected: always emit `Secure` — breaks the local `make up PORT_OFFSET=<n>`
flow the project documents as the dev way to publish ports
(`sdd/project.md:96-100`), and any future non-TLS staging. Rejected: never
emit `Secure` — fails the prod path through Cloudflare and leaves the cookie
replayable on the wire. Rejected: a manual `X-Forwarded-Proto` header read —
the corrected premise above. **An operational override (`cookie_refresh_secure:
bool`) was considered and rejected at gate: a knob a deploy could set wrong
silently breaks dev and silently weakens prod, and the request-scheme
derivation covers both paths.**

### D3 — `RefreshRequest.refresh_token` is removed, no dual period

**Chosen**: drop the `refresh_token` field from `RefreshRequest`
(`backend/app/auth/api/schemas.py:23-26`) and the body argument from the
handler. The handler reads the token from `request.cookies.get(SESSION_REFRESH_COOKIE)`
directly. Tests migrate in the same change: `tests/auth/test_api.py:67,87,120`
and the call sites in `tests/auth/test_use_cases.py` go from passing
`body=RefreshRequest(refresh_token=...)` to using `TestClient` with
`cookies={SESSION_REFRESH_COOKIE: token}` (which `starlette.testclient.TestClient`
already supports). `LoginUseCase` stops including `refresh_token` in
`TokenPairResponse` (`backend/app/auth/api/schemas.py:113-117`) and emits the
cookie instead. `TokenPairResponse.refresh_token` is removed: the
schema regenerates, and the frontend types regenerate, and there is no client
of the field outside `frontend/lib/auth/authenticated-client.ts:51-57`.

Rejected: a deprecation window that keeps `RefreshRequest.refresh_token`
honoured — `R2.3` of the proposal explicitly forbids it, and the cost is real:
two cookie+body code paths to keep in sync until every caller migrates, plus
a fallback window in which the refresh token can leak through the very
channel the change exists to close.

### D4 — Cookie name and attributes live as a single `SESSION_REFRESH_COOKIE` constant

**Chosen**: a `SESSION_REFRESH_COOKIE` constant in
`backend/app/auth/api/schemas.py` (or a new
`backend/app/auth/api/cookies.py` of one constant — keep it small) with name
`autohostai.session.refresh` and an
`emit_refresh_cookie(response, value, max_age_seconds, secure)` helper that
encapsulates the full attribute set: `HttpOnly`, `SameSite=Lax`,
`Path=/api/v1/auth`, `Max-Age=<refresh_ttl_seconds>`, `Secure=<decision from D2>`.
The handler passes only the **value** (the token string) and the **secure
flag**; everything else is fixed. The constant `Path=/api/v1/auth` is the
mechanism that keeps the cookie off every other route: `/api/v1/users`,
`/api/v1/properties`, etc. never see it on the request and never try to
overwrite it on the response. Same-Site `Lax` is the only value that lets a
top-level navigation from an email link to `/login` carry the cookie back to
the backend through a `POST`; `Strict` would force a second click.

Rejected: `Path=/` — every request carries the cookie, including static asset
hits; the surface is wider than the contract. Rejected: `SameSite=Strict` —
breaks the reload-after-email-link path. Rejected: a separate cookie attribute
constants module — there is exactly one cookie and three callers.

### D5 — `RefreshTokenUseCase.execute` drops the `refresh_token` parameter

**Chosen**: the use case signature becomes
`execute(*, client_ip: str, now: datetime) -> TokenPair`. The router reads the
token from the cookie, validates presence and basic shape (non-empty string),
and hands the **string** to the use case; the use case stops touching the
transport. The throttle guard, the token decode, the family lookup, the
rotation and the reuse-detected branch are unchanged — they already work on a
string. The `client_ip` parameter is unchanged because R8 of
`api-ingress-routing` still applies (`backend/app/auth/application/use_cases.py:148-164`).

Rejected: keep the parameter optional and prefer the body when both arrive —
the same dual-period cost as D3. Rejected: move the cookie read into the use
case — leaks Starlette `Request` into a domain class and breaks the layering
test in `tests/test_layering.py`.

### D6 — `LogoutUseCase` is unchanged; the router is responsible for purging the cookie

**Chosen**: `LogoutUseCase` already revokes the family
(`backend/app/auth/application/use_cases.py:240-254`); the handler adds
`response.delete_cookie(SESSION_REFRESH_COOKIE, path="/api/v1/auth")` after a
successful revoke, and unconditionally on the "no-op" branch where there is
nothing to revoke (R3.2: logout is idempotent). The cookie deletion shares
`Path` with the emit helper so the browser's cookie jar picks it up.

Rejected: letting the use case take a `Response` — same layering concern as
D5. Rejected: deleting the cookie only on success — would leave a stale
cookie on a 5xx that the next reload would resurrect, defeating R3.2's
idempotence guarantee.

### D6a — `/auth/logout` accepts the refresh cookie as a credential when no Bearer is presented (added 2026-09-05, review: `sdd-security`, second round)

**Chosen**: a new dependency, `get_logout_subject`
(`backend/app/auth/api/dependencies.py`), resolves who to revoke: a Bearer
access token when one is presented (unchanged — same
`get_authenticated_request` every other endpoint uses), or, when none is
presented at all, the family named by the `SESSION_REFRESH_COOKIE` itself,
decoded directly (`codec.decode_refresh`, no repository round trip — revoking
a family is a no-op update either way, so there is nothing to gain from
checking the session row first). Tagged with `MANAGE_OWN_SESSION` for
`test_route_authorization.py`'s structural walk even though the cookie path
checks no role: that permission is in `_SELF_SERVICE`
(`app/auth/domain/policy.py`), held by every role there is, so there is no
identity a valid credential of either kind could resolve to that this would
ever refuse — authenticating by the cookie alone is equivalent to being
authorised here, unlike every other endpoint `require(...)` guards. No
`bind_session_to_tenant` call in the cookie branch, matching `/auth/refresh`
and `/auth/login` (also unauthenticated at this point): `revoke_family` takes
`tenant_id` as an explicit filter, not via the session-level marker. Returns
`None` — nothing to revoke, not an error — when there is no Bearer, no
cookie, or a cookie that fails to decode (expired, tampered, wrong
signature), so R3.2's idempotent 204 covers this case too instead of turning
a missing/invalid cookie into a new, distinguishable error surface.

**Why**: `use-logout-mutation.ts`'s empty-store case (no access token in
memory — a mount-refresh that never repopulated it, or a session-expired
reset) previously called `refreshSession()` first purely to obtain a Bearer
to present to `/auth/logout`. That rotated and re-extended the refresh cookie
by a fresh `jwt_refresh_token_days` window *before* attempting to revoke it —
so a `POST /auth/logout` that then failed (offline, 5xx, a retry racing
another empty-store path) left the browser holding a freshly-extended,
still-fully-valid session, worse than the one the user tried to end. Letting
the backend accept the cookie directly removes the refresh round trip, and
with it the window, entirely. `use-logout-mutation.ts` now always calls
`POST /api/v1/auth/logout` unconditionally (`needsCredentials` already sends
`credentials: "include"` for this path regardless of Bearer presence).

Rejected: keep the refresh-then-logout round trip and instead mitigate by
purging local state first — does not address the actual exposure, since the
server-side session (and its now-longer-lived cookie) survives regardless of
local state. Rejected: make `get_authenticated_request` itself accept the
cookie as a fallback — that function backs every `require(...)`-guarded
endpoint in the app, not just logout; doing so would silently open the whole
authenticated surface to cookie-only access, when the cookie's own `Path` is
deliberately scoped to `/api/v1/auth` alone.

### D6b — the cookie fallback also fires on a Bearer that fails to authenticate, not only on a missing one (added 2026-09-05, same day, review: `sdd-security`, second re-review of D6a itself)

**Chosen**: `get_logout_subject` now catches `InvalidTokenError` around the
Bearer branch and falls through to the cookie branch, instead of letting the
exception propagate as a 401. D6a's first version only fell back to the
cookie when NO Bearer was presented at all — a Bearer that IS presented but
fails to authenticate (expired, malformed, an unknown/inactive user or
tenant) still hit `get_authenticated_request` and raised.

**Why**: the common real case is an access token that expired without ever
being cleared from the store (the same "stale-but-present token" case
`client.ts`'s own logout comment already names). That request still reaches
`get_authenticated_request` with a Bearer, gets a 401, and falls into the
client's ordinary 401-recovery — which calls `refreshSession()` before
retrying, rotating and re-extending the refresh cookie by a fresh week
before any revoke is attempted. If that retry then failed, the browser was
left holding a freshly-extended, still-valid session: the exact failure
mode D6a exists to close, just reached through a different door (a stale
Bearer instead of an empty store). Falling through on a failed Bearer closes
that door too: whatever the Bearer's fate, revocation is attempted straight
off the cookie, and `/auth/logout` now effectively never answers 401 for an
auth reason — every combination of Bearer/cookie state resolves to either a
revoke-and-204 or a nothing-to-revoke-204 (R3.2). `PasswordChangeRequiredError`
is deliberately NOT caught alongside `InvalidTokenError`: `/auth/logout` is
on `PASSWORD_CHANGE_EXEMPT`, so `get_authenticated_request` never raises it
for this route, and catching it anyway would silently swallow a genuine bug
if that invariant ever changed.

Rejected: fix this on the frontend instead (retry logout with the
`Authorization` header dropped instead of refreshed) — leaves the backend
endpoint itself still capable of leaking a longer-lived session to any OTHER
caller that does not implement that specific retry shape (a future client, a
retry that never runs, a user who navigates away mid-recovery). Fixing the
endpoint closes the gap for every caller at once.

### D7 — `frontend/lib/auth/session-store.ts` keeps only the access token

**Chosen**: `SessionTokens` becomes `{ accessToken: string }` (no
`refreshToken`). `setSessionTokens({ accessToken })` advances the generation;
`getSessionTokens()` returns the new shape; `clearSessionTokens()` zeroes it.
The existing `auth-provider.tsx:151-154`, `useLogoutMutation` and
`refresh-coordinator.ts` are the three callers; each drops the `refreshToken`
field. The `RefreshTokens` callback in `refresh-coordinator.ts:10` becomes
`() => Promise<{ accessToken: string }>` — the cookie travels in the request
body and the backend never sees a `refresh_token` body field.

Rejected: keep `refreshToken` as an unused field for one release — a dormant
`refreshToken` in the store is exactly the surface a future XSS reaches for
(R1's argument).

### D8 — Silent mount-refresh in `AuthProvider`

**Chosen**: `status`'s initial value is `"loading"` whenever there is no
access token in memory at construction time, set via a **lazy `useState`
initializer** (`useState(() => getSessionTokens() ? "anonymous" :
"loading")`) — **corrected 2026-09-05** (the run panel's `sdd-architect`
found the original wording here, "a new `useEffect` on mount ... sets
`status` to `loading`", both self-contradictory with this section's own
preamble and actually unachievable: React commits child effects before
parent effects, so if `status` started at `"anonymous"` and an effect
flipped it to `"loading"` afterward, a nested `AuthGuard` would read
`"anonymous"` on the very first commit and fire a `/login` redirect before
the silent refresh ever got a chance to run — exactly the bug R5 exists to
prevent. Only a lazy initializer satisfies "before `useState` is read by
any consumer"). A `useEffect` on mount then:

1. Calls a new
   `POST /api/v1/auth/refresh` with `credentials: "include"` and **empty
   body**, routed through `authClient` (no `Authorization` header, no
   `refresh_token` body field).
2. On 200: reads the new access token from the JSON body, runs it through
   `setSessionTokens({ accessToken })`, then `GET /auth/me` with
   `credentials: "include"` and the new `Authorization` header, populates
   `user` and transitions `status` to `"authenticated"`.
3. On any other status (401, network): transitions `status` to
   `"anonymous"` with no visible error — the user only sees the login form
   when they navigate to a protected route.

Before installing the resolved access token in step 2, the effect
re-checks `getTokenGeneration()` (the token-identity counter, not
`getSessionGeneration()`'s cache-purge counter — see `session-store.ts`)
against the generation captured when the mount-refresh started, and drops
the result instead of calling
`setSessionTokens` if the generation has moved on — **added 2026-09-05**
(the run panel's `sdd-security` found the original implementation missing
this guard, unlike its sibling `refresh-coordinator.ts:46`'s
`SessionInvalidatedError` check on the same generation field: without it, a
mount-refresh still in flight when the user logs out, has their session
declared expired, or logs in as a different identity would land its
resolved access token into the shared, module-level session-store once the
network call completed, silently reinstating or clobbering credentials for
a session the app had already torn down or superseded).

The same guard applies a second time, symmetrically, around the failure
branch's cleanup: if step 2's own `setSessionTokens` succeeded but the
subsequent `GET /auth/me` then fails, the effect only calls
`clearSessionTokens()` when `getTokenGeneration()` still equals the
generation captured **after** installing this mount-refresh's own token —
**added 2026-09-05, same fix round** (both `sdd-architect` and
`sdd-security`, independently, found the first guard's mirror image
missing here: without it, a concurrent `login()` completing while this
mount-refresh's `/auth/me` call is still in flight — installing a newer
session's tokens and bumping the generation again — would have its live
tokens wiped by this cleanup, which has no way to tell "my own stale
token" from "a newer session that has nothing to do with me" without the
check). Judged in-scope for this change, not the pre-existing
`refresh-coordinator.ts` cracks `proposal.md`'s "Out of scope" section
already deferred to the separate `auth-session-generation-semantics`
roadmap entry (dated 2026-08-29, before `runMountRefresh` existed) — this
is a same-shaped race in code this change itself introduces, not one of
the two facts that entry catalogued.

Single-flighting is structural: the effect runs **once per provider
mount**, and React strict-mode's double-invoke in dev — along with any
other consumer mounting its own `AuthProvider`/`AuthGuard` in the same tick
— is absorbed by a **module-level** in-flight guard (D11), not a
component-local one. The `refresh-coordinator.ts` machinery still serves
the 401-recovery path within a session — the mount-refresh and the
401-recovery path are the two distinct callers and use different code
paths on purpose (mount starts from anonymous, recovery starts from
authenticated).

Rejected: re-using `refreshSession(...)` for the mount path — it requires
`getSessionTokens()` to return a refresh token, and we just removed that
field. The mount path is a new caller that talks to a new shape of the
endpoint (`credentials: include`, empty body).

### D9 — `auth-client` `apiClient` and the new `authClient` both send `credentials: "include"`

**Chosen**: in `frontend/lib/api/client.ts:200`, `doFetch(...)` is invoked with
`credentials: "include"` whenever the request is to a known auth endpoint
(`/api/v1/auth/login`, `/api/v1/auth/refresh`, `/api/v1/auth/logout`) —
path-only, not origin-based (see Rejected below). The decision lives in a single helper
`needsCredentials(path)` so the cookie is sent on login (so the response
cookie is stored), on refresh (so the request cookie is sent), and on logout
(so the request cookie is sent before the response purges it). For other
endpoints the helper returns `false` because access-token auth via
`Authorization` header is unchanged.

Rejected: sending `credentials: "include"` on every request — costs nothing
on the wire but means the browser sends the cookie on every endpoint, and
the `Path=/api/v1/auth` attribute already keeps the cookie off those routes.
Rejected: putting the decision in `apiBaseUrl` matching — `apiBaseUrl` is
opaque to the helper and same-origin requests still need credentials on the
auth endpoints.

### D10 — TestClient cookies replace body fields for refresh

**Chosen**: every existing test that calls `POST /auth/login` keeps reading
`access_token` from the JSON body (only `refresh_token` is removed from the
response). Every test that calls `POST /auth/refresh` now does
`client.post(..., json={})` (empty body) with
`cookies={SESSION_REFRESH_COOKIE: tokens["refresh_token"]}` set in the
client. The `tests/auth/test_use_cases.py:475-507` family of tests continues to
exercise `RefreshTokenUseCase.execute` directly with a `refresh_token` string
— that test exercises the use case, not the handler, and the use case
parameter `refresh_token` is still present as the **transport-decoded value**
(see D5: the parameter survives in the use case). Two parameters, same name,
different transport — the test surface is unchanged.

Rejected: rewriting every use-case test to inject a fake `Request` — turns a
fine use-case-level test into a handler-level test.

### D11 — Single-flight of the silent mount-refresh

**Chosen**: a module-level `inFlightMountRefresh: Promise<CurrentUser | null>
| null` in `frontend/lib/auth/auth-provider.tsx` — **corrected 2026-09-05**
(the run panel's `sdd-architect` found the original `Promise<void>` payload
insufficient for this section's own stated purpose: with a `void` payload
a joining component still has to make its own `GET /auth/me` call to learn
who's signed in, which is not "one network round-trip" — resolving the
identity itself is what lets every joiner skip a duplicate `/auth/me`, and
the "shares one mount-refresh round-trip" test asserts exactly one
`/auth/refresh` **and** one `/auth/me` call for two same-tick mounts, an
outcome a `void` payload would not by itself guarantee) — so multiple
components rendering in the same tick share one network round-trip.
The guard is "are we already in flight AND have we not yet resolved the
identity?" — once the promise resolves, the field is cleared. Components
mounting later in the same runtime (because StrictMode runs effects twice, or
because two routes both need identity) join the in-flight promise instead of
kicking a second one.

Rejected: per-component `useRef` — does not survive the navigation between
routes that each mount their own `AuthGuard`. Rejected: lifting to React
Context — the existing `AuthContextValue` is the **resolved** identity, not
the in-flight promise; the mount-refresh is a one-shot pre-state concern.

### D12 — `MarkSessionPresent()` and `ClearSessionPresent()` are unchanged

**Chosen**: the existing `autohostai.session.present` cookie at `Path=/`
(`frontend/lib/auth/session-presence-cookie.ts:21-27`) is unrelated to the new
refresh cookie. The landing page's Server Component keeps reading the
presence cookie to decide between landing and redirect (`sdd/specs/frontend-auth-session.md` §Login e identidad), and the new refresh cookie at
`Path=/api/v1/auth` does not collide with it. **Confirmed at gate**: moving
the presence cookie to `Path=/api/v1/auth` would break the root-page Server
Component, which reads it on `/` — different purpose, different reader, kept
where it is.**

Rejected: collapsing the two cookies — they answer different questions (root
render decision vs API authentication) and have different lifecycles.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Backend API | `backend/app/auth/api/router.py` | `login` adds `response: Response` and `set_cookie`; `refresh` removes `body: RefreshRequest`, reads `request.cookies`, returns `Response`; `logout` adds `response: Response` and `delete_cookie` (success and no-op branches) |
| Backend schemas | `backend/app/auth/api/schemas.py` | Remove `refresh_token` from `TokenPairResponse`; remove `RefreshRequest` (whole class) — the cookie is the only transport; add `SESSION_REFRESH_COOKIE` constant and `emit_refresh_cookie(response, value, secure)` helper |
| Backend use cases | `backend/app/auth/application/use_cases.py` | `RefreshTokenUseCase.execute` keeps `refresh_token: str` (the decoded value), unchanged; `LoginUseCase._start_session` keeps emitting the pair internally — only the **router** drops the body field and emits the cookie. `LogoutUseCase` unchanged |
| Backend config | `backend/app/core/config.py` | Add `backend_cors_allowed_origin_regex: str = r"^https?://(localhost\|127\.0\.0\.1)(:\d+)?$"`; add `cookie_refresh_secure: bool = False` (operational toggle, default off so dev works, set to True when behind a TLS-terminating proxy) — or compute `secure` from the request scheme and drop the setting |
| Backend wiring | `backend/app/main.py` | Add `CORSMiddleware` mount **after** `MaxBodySizeMiddleware`/`NoSniffMiddleware` in source order, so it ends up **outermost** (`add_middleware` inserts at position 0, the stack builds in `reversed()` order — corrected 2026-09-04 after the run panel's `sdd-architect` found the original "before" placement leaves CORS innermost, so a `413` from `MaxBodySizeMiddleware._refuse()` — which answers via the raw ASGI `send` without calling `self._app(...)` — never carries `Access-Control-Allow-*` headers, violating R7.1) |
| Frontend store | `frontend/lib/auth/session-store.ts` | Drop `refreshToken` from `SessionTokens`; `setSessionTokens`/`getSessionTokens`/`clearSessionTokens` updated |
| Frontend refresh | `frontend/lib/auth/refresh-coordinator.ts` | `RefreshTokens = () => Promise<{ accessToken: string }>`; the cookie travels with the request |
| Frontend client | `frontend/lib/api/client.ts` | `doFetch` accepts `credentials: "include"`; helper `needsCredentials(path)` decides |
| Frontend auth client | `frontend/lib/auth/authenticated-client.ts` | `refreshTokens` calls `/auth/refresh` with empty body and `credentials: include`; the API client also sends credentials on the auth endpoints |
| Frontend BFF proxy | `frontend/app/api/[...path]/route.ts` | `outboundHeaders()` re-signs `x-forwarded-proto: https` when the request carries `cf-connecting-ip` (added 2026-09-04, `sdd-review-cicd` HIGH): without it, `resolve_cookie_secure()` (D2) never sees HTTPS behind the Cloudflare tunnel in the deployed dev topology, so the refresh cookie would never carry `Secure` there. A client-supplied `x-forwarded-proto` is stripped first, same as every other client-controlled header this proxy re-derives |
| Frontend provider | `frontend/lib/auth/auth-provider.tsx` | New `useEffect` performs silent mount-refresh; `login()` no longer reads `refresh_token` from the response body; `logout()` remains unchanged (best-effort local purge + endpoint call) |
| Frontend hooks | `frontend/features/auth/hooks/use-logout-mutation.ts` | Reads `getSessionTokens()` only for the "is there a session" guard; no change in the endpoint call (logout still `POST`s); `clearSessionTokens` already works with the new shape |
| Frontend config | `frontend/lib/config/public.ts` | `apiBaseUrl` is unchanged — the cookie is sent via `credentials: include` regardless of host |
| Tests backend | `backend/tests/auth/test_api.py`, `test_use_cases.py`, `test_recovery_api.py`, `test_login_throttle_over_http.py`, `test_user_admin_api.py`, plus all suites that login | Migrate `refresh_token` body fields to cookies; assert `Set-Cookie` on login and logout; assert absence of `refresh_token` in login response |
| Tests frontend | `frontend/features/auth/auth-session.integration.test.tsx`, `frontend/lib/auth/auth-provider.test.tsx`, `frontend/lib/auth/session-store.test.ts`, `frontend/lib/auth/refresh-coordinator.test.ts`, `frontend/lib/api/client.test.ts` | New mount-refresh cases; update shape assertions; `refreshTokens` callback signature update |
| Specs | `sdd/specs/frontend-auth-session.md` | Replace "JWT solo en memoria" wording per proposal R4; add mount-refresh; remove `refresh_token` from the token-persistence prohibition and add the cookie transport |
| Specs | `sdd/specs/auth-tenancy.md` | Update `POST /auth/login` / `/refresh` / `/logout` contracts; add `autohostai.session.refresh` cookie attribute catalogue; add `X-Forwarded-Proto`-driven `Secure` rule |
| Specs | `sdd/specs/backend-http-posture.md` | Add CORS attribute set as a global posture requirement |
| Docs | `docs/auth-tenancy.md` | Operative note on cookie rotation and `Secure` flag in dev/prod |
| OpenAPI | `backend/openapi.json` | Regenerated; `TokenPairResponse.refresh_token` removed; `RefreshRequest` removed |
| Generated types | `frontend/lib/api/generated/openapi.d.ts` | Regenerated; `TokenPairResponse` and refresh request types update |

## Data & interfaces

- **Cookie**: `autohostai.session.refresh`, attributes:
  - `HttpOnly` — always
  - `SameSite=Lax` — always
  - `Path=/api/v1/auth` — always (kept off other routes)
  - `Max-Age=604800` (= `refresh_ttl_seconds` from `Settings.jwt_refresh_token_days=7`) — always
  - `Secure` — iff the external request scheme is HTTPS, derived as in D2
  - Value: the raw refresh JWT (same string the body used to carry), opaque to
    the browser because of `HttpOnly`
- **CORS attribute set** (issued on every response that carries `Origin`):
  - `Access-Control-Allow-Credentials: true`
  - `Access-Control-Allow-Origin: <reflected request origin>` (only if the
    origin matches `backend_cors_allowed_origin_regex`)
  - `Access-Control-Allow-Methods: GET, POST, PUT, PATCH, DELETE, OPTIONS, HEAD, TRACE`
  - `Access-Control-Allow-Headers: Authorization, Content-Type`
  - `Access-Control-Max-Age: 600` — preflight cache to avoid re-handshakes on
    every navigation
- **OpenAPI**:
  - `POST /auth/login` — `200` body: `{ access_token, token_type, expires_in }`
    (no `refresh_token`); `Set-Cookie` documented as a response header
  - `POST /auth/refresh` — `200` body: same; request **body**: empty; cookie
    required
  - `POST /auth/logout` — `204`; `Set-Cookie` with `Max-Age=0` documented
- **Env vars**:
  - `BACKEND_CORS_ALLOWED_ORIGIN_REGEX` (default above) — only added if we
    keep the configurable regex; otherwise the default covers dev worktrees
    (`PORT_OFFSET`) and the public hostname (`https://autohostai.digitalsec.work`)
    is added explicitly in the deploy `.env`
  - No new secret, no `.env.example` change beyond the optional regex

## Risks & mitigations

- **Cookie theft via XSS**: the cookie is `HttpOnly`, so JS cannot read it. The
  residual threat is a same-origin XSS that issues requests with `credentials`
  on the user's behalf; this change does not address that and the proposal
  marks it out of scope. Mitigation lives elsewhere (`frontend-foundation`,
  `frontend-dependency-security`).
- **CSRF**: `SameSite=Lax` blocks third-party-initiated `POST`s to `/auth/*`
  from foreign origins. The proposal's R1 says `SameSite=Lax` and the
  rationale is that the cookie's `Path=/api/v1/auth` is not exposed to
  third-party forms — Lax matches the threat model.
- **Cookie size on every request**: a refresh JWT is ~430 bytes. The browser
  attaches it on `/api/v1/auth/*` only because of `Path=/api/v1/auth`, so
  non-auth endpoints do not pay the cost. The auth endpoints themselves are
  already the throttle boundary (`auth-tenancy.md` §Protección de los
  endpoints).
- **Mount-refresh in `StrictMode`** double-invoking the effect: D11's
  in-flight promise absorbs the second call.
- **Concurrent rotations across tabs**: each tab keeps its own in-memory access
  token (R6.1); the cookie is the shared state. A rotation from tab A writes
  a new cookie; tab B's next `/auth/refresh` reads the rotated cookie and
  rotates it again. The backend's reuse-detected branch fires when two tabs
  race on the same `jti` — exactly the existing behaviour, unchanged.
- **`X-Forwarded-Proto` spoofing**: the same risk as `X-Forwarded-For`, and
  already mitigated by uvicorn's `--forwarded-allow-ips` in `deploy`
  (`auth-tenancy.md` §Identificación del cliente). Local dev sets
  `--forwarded-allow-ips 127.0.0.1`, so an attacker outside the box cannot
  forge the header. If a future deploy introduces a new proxy, it must be
  added to the allowlist.
- **Test surface erosion**: every test that used `refresh_token` in the body
  has to migrate. The `tests/auth/test_use_cases.py:475-507` family is
  preserved by D10 — the use case still takes the decoded value.
- **`local-environment` worktree tree**: in a worktree the cookie reaches
  the backend through the **direct** `NEXT_PUBLIC_API_BASE_URL`, which is a
  different port (`PORT_OFFSET`). Without CORS, the response cookie would be
  ignored and the refresh would fail. D1 closes this; the dev worktree flow
  is exercised by `make up` so the test of record is the integration test
  with `TestClient(cookies=…)`.
- **OpenAPI regen**: a breaking schema change (`refresh_token` removed from
  response, `RefreshRequest` removed) means the generated frontend types
  regenerate; `npm run api:generate` must be re-run inside the change
  (and the produced diff committed), and `npm run api:check` must remain
  green.

## Open questions

(None — all three resolved at gate: configurable CORS regex, request-scheme
derivation for `Secure`, `Path=/` preserved for the presence cookie.)
