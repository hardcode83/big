# frontend-auth-role-routing

[FE] agrupar los cuatro ítems §Out of scope de `public-zone-hardening` para no abrir cuatro frentes y para que la decisión de qué entra en `cleaner-app` / `tech-app` (donde también podrían vivir dos de ellos) se tome con el código a la vista.

## Por qué existe

`public-zone-hardening` cierra los cinco síntomas de UX observados el 2026-08-26 sobre `autohostai.digitalsec.work`, y al hacerlo deja cuatro huecos documentados como explícitamente fuera de su alcance (proposal § §Out of scope). Son trabajos necesarios para el DoD §28 de `hardening-release` —la suite E2E no puede firmar sin bypass si los guards no discriminan por rol—, pero son lo bastante heterogéneos para no caber en un solo change de un solo tipo.

La decisión ahora es **agrupar o separar** — y la regla 1 de la docs/adr/0001-roadmap-structure-and-concurrency ("roadmap como fuente única de dependencias y progreso") se cumple siempre que la entrada tenga un solo nombre. Aquí se opta por agrupar para evitar la fragmentación que ya vimos en `field-apps` (partida en cuatro el 2026-08-18 porque mezclaba cuatro superficies sobre tres dominios y dos roles nuevos); el riesgo opuesto —un change demasiado grande para un único PR— se mitiga cuando llegue el momento con tareas pequeñas y un panel de review que se aplica por sección (visto funcionar en `public-zone-hardening`).

## Lo que entra

**(1) `AuthGuard` por rol** — `frontend/features/auth/components/auth-guard.tsx` acepta hoy a cualquier usuario autenticado; la separación por rol vive en el sidebar y en el backend (que ya discrimina por permisos). Endurecer el guard a `/cleaner` y `/tech` exige revisar el `Sidebar` para no esconder rutas a quien no debería verlas y el flujo de invitaciones, y pertenece de forma natural a `cleaner-app`/`tech-app` — pero como aquí también se cierra (2) y la lógica del guard es del shell, agrupar evita reabrir el AuthGuard dos veces.

**(2) Mini-landing autenticada post-login** — una pantalla con CTA directo a `/cleaner` o `/tech` para usuarios de campo en dispositivos de un solo uso. Es la evolución amable de R4 de `public-zone-hardening` (que ya redirige por rol; aquí se sustituye el redirect directo por una pantalla con un botón). Mismo camino que (1): podría vivir en `cleaner-app`/`tech-app`, pero el routing post-login es del shell, no de cada app, y aquí se cierra con un solo componente.

**(3) `auth-provider.logout` a TanStack Query mutation** — refactor de organización, no de comportamiento. Hoy `auth-provider.tsx:119-135` llama al cliente HTTP de `lib/api/authenticated-client`. Mudar a una mutation cacheable tiene sentido (caché, invalidación, retry, testabilidad), pero es ortogonal a los tres anteriores. La razón de meterlo aquí es que (1) endurece el guard y (3) endurece el logout, y abrir dos changes separados para dos caras del mismo AuthProvider duplica la revisión de seguridad.

**(4) `RootPage` server-side que distinga cookie stale pero JWT revocado** — defensa en profundidad del síntoma que R3 de `public-zone-hardening` ya elimina en el camino feliz (logout real). El backend ya marca el JWT como revocado por familia (`auth-tenancy.md:140-145`); el frontend hoy no puede detectar ese estado si la cookie `autohostai.session.present` sigue viva un año. Una `RootPage` que hable con el backend en cada visita rompe el modelo «server decide sin red» del landing actual — por eso la propuesta de `public-zone-hardening` lo rechazó como cosmético. La pregunta a resolver en este change es si vale la pena el coste (una petición extra por visita a la raíz) frente al riesgo residual.

## Lo que NO entra

- Nada de backend. El cambio es 100% frontend — sin migraciones, sin esquema, sin nuevos endpoints, sin variables de entorno.
- Reescritura de `AuthGuard` para más de los tres roles MVP (`TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`). Si entra `SUPER_ADMIN` (`docs/adr/0006-pms-channel-manager-provider.md`), su ruta queda para `saas-cross-tenant`.
- Migrar el `LocaleSwitcher` a un `Select` para más de dos idiomas — sigue siendo un solo botón (D1 de `public-zone-hardening` lo dejó así).

## Cómo se decide qué entra en `cleaner-app`/`tech-app`

Al archivar este change, su Out of scope debe nombrar explícitamente qué piezas (si las hay) se delegan a `cleaner-app` / `tech-app` — la regla 1 ("un cambio, una responsabilidad") se aplica tanto al descomprimir como al agrupar. La lectura por defecto es **todas las piezas van aquí**: es donde el shell ya vive y donde la lógica de routing por rol tiene un solo consumidor.

## Bloqueo

Bloquea a `hardening-release` (suite E2E Playwright, DoD §28): sin los guards endurecidos y sin la mini-landing, los tests E2E no pueden断言 «este usuario, a esta ruta, sin bypass». Si `hardening-release` se acerca antes que esta entrada, el camino corto es mover DoD §28 a un follow-up y firmar el resto.

## Dependencias

- `public-zone-hardening` (archivado 2026-08-26, listo para archivar — el PR #132 cubre R1–R5): provee el `UserMenu`, el `roleHome()` helper, el redirect por rol en `LoginForm`, y el `Logout` que (3) refactoriza.
- `frontend-foundation` (archivado 2026-07-21): provee el Application Shell, el `AuthGuard` actual, los namespaces `auth` y `navigation` en ES y EN.
- `frontend-auth-session` (archivado 2026-07-31): provee `AuthProvider`, `session-presence-cookie`, y el contrato de `/auth/logout` y `/auth/me`.