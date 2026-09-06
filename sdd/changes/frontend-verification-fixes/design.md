# Design: frontend-verification-fixes

## Context

El backend compone texto legible en **exactamente tres rutas**, y las tres lo hacen leyendo
`authenticated.context.preferred_language`: `GET /dashboard/properties`
(`backend/app/dashboard/api/router.py:100`), `GET /properties/{id}/dashboard` (`:139`) y
`GET /timeline/{property_id}` (`backend/app/timeline/api/router.py:109`). Las otras dos rutas de
`dashboard` —`operational-kpis` (`:161`) y `occupancy-series` (`:191`)— devuelven sólo números y
no piden locale, así que el alcance de R1 es cerrado y medido, no estimado. El valor lo pone
`get_authenticated_request` (`backend/app/auth/api/dependencies.py:417`) con
`Locale.resolve(user.preferred_language)` sobre la fila que la revalidación acaba de releer.

En el frontend, el conmutador (`frontend/features/shell/components/locale-switcher.tsx:64-77`)
cambia i18next, el cookie `autohostai.locale` y `<html lang>`, y llama `router.refresh()`; nada de
eso toca las peticiones al backend. Las cabeceras de una petición autenticada las pone un solo
sitio, `getHeaders` de `createAuthenticatedClients`
(`frontend/lib/api/authenticated-client.ts:63-70`), por el que pasan los nueve `features/*/data/index.ts`.
El proxy de mismo origen (`frontend/app/api/[...path]/route.ts`, `outboundHeaders`) copia las
cabeceras entrantes salvo las de reenvío, las hop-by-hop y las `proxy-*`, así que una cabecera
nuestra llega al backend sin trabajo adicional. Las claves de consulta de las tres superficies
viven en `frontend/features/dashboard/hooks/query-keys.ts` sobre `tenantScopedKey`
(`frontend/lib/query/query-keys.ts:13`).

Un dato que el proposal no tiene y que condiciona R2: **dos hooks de mutación invalidan esas
claves por prefijo escrito a mano** —`["tenant", tenantId, "dashboard-cards"]` y
`["tenant", tenantId, "property-timeline"]` en
`frontend/features/incidents/hooks/use-resolve-incident.ts:85-90` y
`frontend/features/cleaning/hooks/use-cancel-cleaning-task.ts:95-99`—, de modo que dónde se
inserta el locale en la clave no es indiferente.

## Decisions

### D1 — El idioma pedido viaja en una cabecera propia, `X-Locale`, y no en `Accept-Language`

**Chosen:** una cabecera de producto, `X-Locale`, cuyo valor es un locale soportado (`es` | `en`).
La razón es que el navegador manda `Accept-Language` **solo**, con la preferencia del sistema
operativo, y el proxy la reenvía tal cual: reusar ese nombre significa que el idioma del texto
compuesto lo decidiría, en cualquier petición que no pase por el `ApiClient`, una cabecera que
nadie de nuestra interfaz escribió. Con un nombre propio, todo valor que llega ahí lo puso nuestro
código, y "el idioma que el cliente pide" es una afirmación comprobable en vez de una inferencia.
Además evita la segunda mitad del coste: `Accept-Language` es una lista con pesos (RFC 9110
§12.5.4) y honrarla de verdad pide un negociador, mientras que ignorar los pesos sería publicar una
cabecera estándar con semántica no estándar.

El prefijo `X-` está desaconsejado por RFC 6648 y se usa a propósito: marca la cabecera como
nuestra justo al lado de una estándar con la que se podría confundir.

Rejected: `Accept-Language` con negociación completa — un negociador de pesos y comodines para
elegir entre dos idiomas, y el navegador seguiría ganando en cualquier petición que el `ApiClient`
no emita.
Rejected: `Accept-Language` sin negociación (metiendo el valor crudo en `Locale.resolve`) — cumple
R1.3 al pie de la letra y a cambio ignora en silencio un `es-ES,es;q=0.9` perfectamente válido.
Rejected: un parámetro de query `?locale=` — R1.5 lo prohíbe explícitamente (crecería
`openapi.json` por ruta) y ensuciaría la clave de caché del servidor.

### D2 — La cabecera se lee del `Request`, nunca como parámetro de operación

**Chosen:** `request.headers.get("X-Locale")` dentro de una dependencia que declara `request: Request`.
Es lo que satisface R1.5: FastAPI publica en `openapi.json` los parámetros anotados con
`Header(...)`, y no publica nada de lo que se lea del objeto `Request`. Consecuencia comprobable:
las tres operaciones no ganan ningún parámetro.

Rejected: `Annotated[str | None, Header()]` — es la forma idiomática y es exactamente la que R1.5
descarta, porque añade el parámetro a las tres rutas y por tanto al contrato generado.

**Enmienda (review, ronda 6, 2026-09-06):** las tres rutas que leen `RequestLocaleDep`
(`list_dashboard_cards`, `get_property_dashboard`, `get_property_timeline`) ahora ponen
`Cache-Control: private, no-store` en la respuesta — mismo patrón que ya usa
`app/provenance/api/router.py:39`. (Una cuarta ronda de review, la 8, sumó `list_tenant_activity`
a este mismo tratamiento tras el catch-up con `main` — ver D5, tercera enmienda — así que hoy son
cuatro, no tres.) Su cuerpo depende de una cabecera de petición (`X-Locale`) que
ninguna caché compartida indexa; sin este encabezado, una respuesta cacheada por URL sola podría
servir el idioma de un lector a otro. Hoy no hay ruta de explotación real —el entorno dev sí vive
detrás de un Cloudflare Tunnel (`sdd/specs/ingress-https-dev.md`), pero su nivel de caché estándar
no cachea rutas de `/api/v1/...` sin extensión cacheable, y las tres exigen `Authorization`, que
RFC 9111 prohíbe almacenar a cualquier caché compartida— pero la respuesta no debe depender de una
topología que vive fuera de este fichero, y menos una que ya existe: `no-store` es lo que mantiene
esta respuesta fuera del edge de Cloudflare, no una precaución sobre un CDN hipotético. No hace
falta `Vary: X-Locale` además: `no-store` ya excluye la respuesta de cualquier caché, compartida o
privada.

### D3 — El locale efectivo **no** entra en `RequestContext`: vive en su propia dependencia

**Chosen:** una dependencia nueva `RequestLocaleDep` (en `backend/app/auth/api/dependencies.py`,
junto a `AuthenticatedDep`) que resuelve `X-Locale` → `users.preferred_language` → `es` y devuelve
un `Locale`. Las tres rutas cambian `locale=authenticated.context.preferred_language` por
`locale=locale`. `RequestContext.preferred_language` **se queda como está**: la preferencia
almacenada de la fila.

El motivo es una invariante que no conviene aflojar. `RequestContext` se documenta a sí mismo como
"built from verified token claims plus the current database state, **never from request input**"
(`backend/app/auth/domain/context.py:12-14`), y es el objeto sobre el que descansa el aislamiento
por tenant. Meter ahí un valor que llega en una cabecera obliga a reescribir esa frase en el objeto
cuya única razón de ser es que la frase sea verdad. Con la dependencia aparte, el valor no fiable
tiene su propio portador, su propio docstring y su propio test, y la frase sigue siendo cierta
literalmente. La spec no se opone a ninguna de las dos vías: su `SHALL` de aislamiento
(`sdd/specs/auth-tenancy.md:233-236`) prohíbe creer un `tenant_id` de una cabecera, no un locale.

Coste real: tres firmas de ruta ganan un parámetro. No cuesta consulta ninguna —la dependencia
depende de `AuthenticatedDep`, que FastAPI resuelve una sola vez por petición, así que reusa el
`RequestContext` ya construido y con él la preferencia de la fila que la revalidación releyó—, y
por tanto sigue cumpliendo el "no cuesta plumbing nuevo" que R1.5 pedía.

Rejected: sobrescribir `RequestContext.preferred_language` con el idioma pedido — un solo portador
y ningún parámetro nuevo, a cambio de que el objeto que promete no leer entrada de la petición pase
a leerla.
Rejected: un segundo campo `RequestContext.locale` junto al primero — mismo defecto que la anterior
(entrada de petición dentro del objeto) más dos campos de idioma que hay que distinguir en cada uso.

### D4 — La cadena de degradación es una función pura en `app/core/i18n.py`

**Chosen:** `resolve_locale(requested: str | None, stored: str | None) -> Locale`, junto a
`Locale.resolve`: devuelve el pedido si `Locale` lo reconoce, y si no `Locale.resolve(stored)` —que
ya degrada a `es`. Los tres escalones de R1.2/R1.3 quedan en una función de dos `str | None` a un
`Locale`, testeable sin FastAPI y sin base de datos, y `app/core/i18n.py` sigue siendo Python puro
como `tests/test_layering.py` exige (los módulos `domain/` lo importan).

La dependencia de D3 queda entonces en cuatro líneas: leer la cabecera, llamar a esta función,
devolver el resultado.

Rejected: la lógica dentro de la dependencia — mezcla la regla con el framework y obliga a montar
una petición para probar los seis casos de degradación.
Rejected: un `Locale.negotiate` como classmethod — el segundo argumento no es un locale sino la
columna cruda, así que no es una operación sobre el enum.

### D5 — Una guardia estructural impide que una ruta futura vuelva a leer la fila

**Chosen:** un test que recorre por AST los ficheros `backend/app/*/api/*.py` y falla si alguno
contiene un acceso de la forma `<cualquier cosa>.context.preferred_language`. Los sitios legítimos
que nombran la columna —`auth/api/user_schemas.py:167`, `auth/api/schemas.py:151`,
`platform/api/schemas.py:140`, `reservations/api/schemas.py:113`, que serializan la fila— no la
encajan porque leen la columna en una cadena de **un** atributo (`user.preferred_language`), no de
dos.

Existe porque D3 deja dos cosas alcanzables desde un router (la preferencia almacenada y el locale
pedido) y una de las dos es la equivocada para pintar. Prohibir la **forma** en el **conjunto de
ficheros** donde importa es lo que convierte R1 en una propiedad del árbol y no en una nota que hay
que recordar.

**Enmienda tras la implementación (run, sección 2, 2026-09-05):** la redacción original decía "sin
lista blanca, porque no hace falta", razonando que `auth/api/dependencies.py` "la construye pero no
la lee así". Eso era cierto antes de escribir D3 y falso en cuanto la tarea 2.1 se implementa: el
propio `get_request_locale` que D3 manda construir tiene que leer
`authenticated.context.preferred_language` como su escalón de degradación — es la forma exacta que
esta guardia prohíbe, dentro del fichero exacto que escanea. D3 obliga a D5 a exceptuar su propia
implementación.

La resolución adoptada, en vez de aflojar la forma o el alcance: una lista blanca de **una entrada**,
indexada por `(módulo, función que la contiene)` y no por módulo —
`LOCALE_ROW_READERS = {("app/auth/api/dependencies.py", "get_request_locale")}` en
`backend/tests/test_layering.py`—, acompañada de un test que falla si esa función se renombra o se
borra (`test_the_only_permitted_row_reader_still_exists`), para que la excepción no pueda quedar
huérfana ni ampliarse en silencio. Un segundo lector en el mismo fichero, incluso en
`auth/api/dependencies.py`, sigue dando rojo. La forma prohibida y el conjunto de ficheros que D5
pedía quedan intactos; lo que cambia es que la lista blanca que D5 daba por innecesaria resultó
necesaria por la propia implementación que D5 exige.

Rejected: un `grep` por el nombre `preferred_language` — se lo comen los cuatro serializadores
legítimos y obligaría a una lista blanca más ancha que ésta.
Rejected: no poner guardia — el modo de fallo es silencioso (una ruta nueva sirve el idioma de la
fila y nadie lo ve hasta que alguien mira una pantalla en inglés).
Rejected (en la enmienda): mover el escalón de degradación de `get_request_locale` fuera de
`backend/app/*/api/*.py` para que el alcance de la guardia nunca contenga un lector legítimo — movería
la dependencia fuera del sitio que D3 le asigna a propósito, junto a `AuthenticatedDep`, por una razón
que es de la guardia y no de la dependencia.

**Segunda enmienda (review, rondas 2-3, 2026-09-05):** la primera enmienda fijó la forma prohibida
en la cadena directa de dos atributos. Dos rondas de revisión encontraron sendas reescrituras de la
misma idea que el AST original dejaba pasar: un alias de `.context` ligado a un nombre local (en
cualquiera de sus formas — asignación simple o encadenada, anotada, walrus, desempaquetado de
tupla/lista) y un parámetro o atributo literalmente llamado `context`; después, `getattr(<owner>,
"preferred_language")` como llamada en vez de atributo. Las tres se añadieron a `_stored_locale_reads`
en `backend/tests/test_layering.py`, con un test que prueba que el detector dispara sobre cada una
(`test_the_locale_check_catches_the_shapes_it_claims_to`).

Encontrada la tercera forma, la decisión fue parar: `getattr(getattr(x, "context"),
"preferred_language")`, `x.context.__dict__[...]`, `operator.attrgetter(...)`, y cualquier otra vía de
Python para obtener un atributo sin escribir `.attr` forman una lista abierta que un AST por fichero
no puede enumerar — cada una necesita solo una capa más de indirección que la anterior. El docstring
de `_stored_locale_reads` (líneas 314-326) lo deja explícito: la guardia es una barrera contra las
formas a las que llega una edición ordinaria, no contra la ofuscación deliberada, y no se persigue esa
lista porque el coste de un fallo (una traducción en el idioma equivocado, no una fuga entre tenants ni
un fallo de autorización — ver D3) no lo justifica. Esta es la razón por la que D3 aísla el locale no
verificado de `RequestContext`: si la guardia D5 cede ante una reescritura no prevista, el radio del
fallo queda acotado a texto en el idioma incorrecto para el propio lector, nunca a un dato de otro
tenant ni a una decisión de permisos.

**Tercera enmienda (review, ronda 8, 2026-09-06 — catch-up con `main`):** `dashboard-activity-feed`
mergeó a `main` tras la bifurcación de este change y añadió `GET /api/v1/timeline`
(`list_tenant_activity`) leyendo `authenticated.context.preferred_language` directamente — la
misma forma que D5 prohíbe, en un fichero que la guardia ya escaneaba. El catch-up con `main`
(merge, no rebase — el mismo criterio que rige en ship) trajo esa ruta a este árbol con la guardia
en rojo. La resolución fue la misma que R1 aplica a las otras tres: convertir la ruta a
`RequestLocaleDep` y `Cache-Control: private, no-store`, no ampliar `LOCALE_ROW_READERS` — ensanchar
la lista blanca por una ruta ajena a este change habría sido la erosión que la propia guardia existe
para impedir. `sdd/specs/dashboard-api.md`'s SHALL de esta ruta (sección «Feed de actividad a nivel
de tenant») se corrigió a la vez, con la misma redacción que las otras tres.

### D6 — El idioma resuelto de i18next se publica en un módulo de `lib/i18n` que `getHeaders` lee

**Chosen:** `frontend/lib/i18n/active-locale.ts` con un `getActiveLocale(): Locale` y un
`setActiveLocale(locale: Locale)`; el único escritor es el proveedor
(`frontend/lib/i18n/client-provider.tsx`), que lo publica al crear la instancia y se suscribe a
`languageChanged` para republicarlo. `getHeaders` de `authenticated-client.ts` añade
`X-Locale: getActiveLocale()`.

Hace falta un mecanismo de publicación porque **la instancia de i18next es local al proveedor**:
`client-provider.tsx:10-22` la crea con `createInstance()` dentro de un `useState`, a propósito
para que SSR y cliente coincidan, así que no hay singleton de módulo que `lib/api` pueda importar —
y los nueve `features/*/data/index.ts` construyen su cliente en ámbito de módulo, fuera de React.
Con esto el valor que viaja **es** `i18n.resolvedLanguage`, que es lo que R1.4 pide, y no un
equivalente que hay que argumentar. Se publica de forma síncrona al crear la instancia (no en un
efecto) para que una consulta que arranque en el primer render ya lleve el valor bueno; antes de
que monte cualquier proveedor vale `DEFAULT_LOCALE`, que es lo que el servidor habría resuelto.

Un solo punto de edición cubre R1.4 para las nueve `features/*/data/index.ts` que construyen su
cliente a través de `createAuthenticatedClients`/`authenticated-client.ts`, porque `getHeaders` es
el sitio donde esas llamadas ponen la `Authorization`. El cliente anónimo del portal del huésped
(`features/guest-portal/data/index.ts`) no se toca: ese eje está fuera de alcance.

**Corrección (review, 2026-09-05):** la redacción original decía que `getHeaders` es "el único
sitio donde se pone la `Authorization`" en todo el frontend, lo cual es falso —
`features/provenance/provenance-panel.tsx:49-57` construye su propio `ApiClient` con un
`getHeaders` inline que también pone `Authorization` y no pasa por `authenticated-client.ts`, así
que no lleva `X-Locale`. Queda fuera de alcance de R1.4 a propósito y no por omisión: es
pre-existente (no lo toca este change) y `/api/v1/provenance` no compone ningún texto dependiente
de idioma — devuelve URL de repositorio, número de PR, SHA de commit, id de run y versión de app,
todos datos técnicos, no traducidos. La afirmación correcta es la de arriba: el punto de edición
cubre las nueve `data/index.ts` que sí pasan por el cliente autenticado compartido.

Rejected: leer el cookie `autohostai.locale` desde `getHeaders` — cero estado nuevo y funciona,
pero el valor que viajaría sería el del cookie y no el de i18next, que es el que R1.4 nombra.
Rejected: leer `document.documentElement.lang` — mismo reparo, y depende de que nadie toque el
atributo por otra razón.
Rejected: inyectar la cabecera en el proxy (`app/api/[...path]/route.ts`) desde el cookie — un solo
sitio y automático, pero entonces la petición del navegador no declara el idioma, así que una
llamada directa al backend (dev con `PORT_OFFSET`, Playwright contra `:80xx`) volvería al idioma
de la fila; y no es lo que R1.4 pide.
Rejected: convertir la instancia de i18next en singleton de módulo — toca la decisión de hidratación
de `frontend-foundation` por una razón que no es la nuestra.

### D7 — El locale entra al **final** del `scope` de la clave

**Chosen:** `['tenant', tenantId, resource, ...scope, locale]`:

```ts
cards:            (tenantId, locale)                     → [..., "dashboard-cards", locale]
propertyDetail:   (tenantId, propertyId, locale)         → [..., "property-detail", propertyId, locale]
propertyTimeline: (tenantId, propertyId, filters, locale)→ [..., "property-timeline", propertyId, filters, locale]
```

La posición no es cosmética: las dos invalidaciones por prefijo escritas a mano que el Context
enumera casan con `["tenant", tenantId, "dashboard-cards"]` y
`["tenant", tenantId, "property-timeline"]`, y sólo siguen funcionando —para **los dos** idiomas a
la vez, que es lo correcto— si el locale va detrás del recurso. Un locale insertado entre
`tenantId` y el recurso las rompería en silencio: la mutación dejaría de refrescar la card.
La forma `['tenant', tenantId, resource, ...scope]` que `frontend-foundation.md:56` exige se
conserva; el locale es un elemento más del `scope`, como los filtros del timeline
(`dashboard-web-frontend.md:221` es el precedente exacto).

El locale lo aportan los tres hooks a través de un `useActiveLocale()` nuevo en `lib/i18n`,
implementado sobre `useTranslation()` —el patrón que ya usan quince componentes con `i18n.language`—
para que el cambio de idioma provoque re-render, clave nueva y refetch sin tocar el conmutador
(R2.3 intacto: no se reordena nada ni se intercala ninguna escritura de red entre sus tres pasos).

Rejected: el locale delante del recurso — rompe las dos invalidaciones por prefijo.
Rejected: no tocar las claves y llamar `queryClient.clear()` en el conmutador — tira el caché
entero por un cambio que afecta a tres recursos, e intercala trabajo en la secuencia que R2.3
congela.

### D8 — Un cambio de idioma pasa por el estado de carga, no por el texto viejo

**Chosen:** sin `placeholderData: keepPreviousData` en las tres consultas. Al cambiar la clave, la
superficie pinta su estado de carga —ya existente y accesible (`StatePanel`, `aria-busy`)— y luego
el texto nuevo. Es lo que R2.2 pide leído literalmente ("la **siguiente** pintura … muestre el texto
compuesto en el idioma nuevo"), y la alternativa enseñaría durante el vuelo exactamente el defecto
que este change existe para cerrar.

Rejected: `keepPreviousData` — media pantalla en el idioma viejo mientras carga, que es el síntoma.

### D9 — La pasada de R3 se registra en un solo sitio: el párrafo de `sdd/project.md`

**Chosen:** la medición se hace en este worktree con el **MCP de Playwright** (el driver que
`sdd/project.md` §Context declara activado, y uno de los dos con los que se levantó el hallazgo 2),
contra `next dev` con `make up PORT_OFFSET=<n>` —el orden que el propio párrafo manda probar
primero—, y su veredicto se escribe **en el párrafo de hidratación de `sdd/project.md`**, que es
donde R4.1 obliga a que estén la fecha y las condiciones de la medición más reciente. La entrada de
`sdd/roadmap.md` y la nota `sdd/roadmap/frontend-verification-fixes.md` apuntan ahí en vez de
repetir el veredicto: una sola casa por hecho (regla 1).

Lo que la pasada declara, porque R3.1 lo enumera: driver, `PORT_OFFSET`, `next dev` o build de
producción, errores de consola, si hay claves `__react*` en el documento y si un clic en el
conmutador muta el DOM. Si `next dev` no responde, se cae al `next start` con su `build` delante
—los dos comandos y su filo (el volumen `frontend_next` compartido) ya están en `sdd/project.md`— y
lo que se registra es esa condición exacta, sin atribuirle causa (R3.3).

Precondición que hay que hacer explícita: `.env.example` no trae valor para
`BOOTSTRAP_OWNER_PASSWORD` ni `BOOTSTRAP_MANAGER_PASSWORD` (`:313-318`), así que `make bootstrap`
falla hasta rellenarlos en el `.env` local. Se rellenan con credenciales desechables y no se
commitean nunca; el aviso de las credenciales en la URL de `sdd/project.md` es la razón por la que
"desechables" no es retórica.

La misma pasada verifica R1 y R2 (R3.4) en las **cuatro** combinaciones rol × idioma, que son
`TENANT_OWNER` × {es, en} y `PROPERTY_MANAGER` × {es, en}: medido contra `ROLE_PERMISSIONS`
(`backend/app/auth/domain/policy.py:342-387`), esos dos roles son los únicos que llevan
`READ_PROPERTIES`, que es el permiso de las tres rutas.

Rejected: el skill `browser-automation` (patchright) como driver — es el otro que levantó el
hallazgo, pero R3 existe para cerrar el veredicto sobre la suite que `hardening-release` va a
montar, y ésa es de Playwright.
Rejected: un fichero de medición propio en el change — sería una segunda casa del mismo hecho, y al
archivar el change desaparece justo lo que hay que poder leer luego.

### D10 — `allowedDevOrigins` se queda escrito como hipótesis no verificada

**Chosen:** no se declara en `frontend/next.config.ts`; el párrafo pasa a decir explícitamente que
es una hipótesis que nadie ha medido. Es la segunda de las dos salidas que R4.2 autoriza, y se elige
porque la primera no se puede cumplir: "declararlo y registrar qué cambió" exige un antes y un
después observables, y el síntoma **no se reproduce** desde el 2026-08-29. Declararlo produciría una
línea de configuración cuyo efecto seguiría sin medir, que es exactamente lo que R4.2 prohíbe dejar
en el párrafo. Hay además un coste que sólo aparece al intentarlo: el desplazamiento de puertos es
distinto en cada worktree, así que la lista tendría que salir de una variable de entorno nueva y
arrastraría un cambio en `sdd/specs/local-environment.md` por una hipótesis.

Se somete al gate como OQ1: es la clase de decisión que el proposal deja abierta a propósito.

Rejected: declararlo con la lista fija de `localhost:3000` — no cubre ningún desplazamiento, que es
el único caso en el que el síntoma se vio.

### D11 — Las tres rutas cambian su `description`, así que el contrato se regenera

**Chosen:** los tres `description=` que hoy dicen "in the authenticated user's language"
(`dashboard/api/router.py:83-84`, `:112` y `timeline/api/router.py:74-75`) pasan a decir de dónde
sale el idioma ahora. Eso mueve los **bytes** de `backend/openapi.json` y los comentarios de
`frontend/lib/api/generated/openapi.d.ts` aunque no crezca ningún parámetro, así que el change
ejecuta `make openapi` y regenera el cliente por la vía del worktree que `sdd/project.md`
documenta (`docker compose cp` + `npm run api:generate`), y commitea los dos ficheros. `api:check`
en CI lo exige (`sdd/specs/api-contract.md:184-186`).

R1.5 se sigue cumpliendo tal y como está escrito —no crece un parámetro por ruta, y
`frontend/lib/api/generated/` no cambia *por ese motivo*—, pero decirlo así sin más se leería como
"no hay nada que regenerar", y no es cierto.

### D12 — Sin diagrama

**Chosen:** ninguno. Lo que este change añade es una cadena de degradación de tres escalones y una
clave de consulta con un elemento más; las dos se dicen enteras en una línea de texto cada una.
Generar un SVG que las dibuje añadiría un artefacto que hay que mantener y, por la regla 11, un
coste de contexto para quien lo abra, sin sustituir ninguna frase.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Backend · i18n | `backend/app/core/i18n.py` | Nueva `resolve_locale(requested, stored) -> Locale` (D4). Python puro, sin framework. |
| Backend · auth API | `backend/app/auth/api/dependencies.py` | Nueva constante `LOCALE_HEADER = "X-Locale"` y `RequestLocaleDep` (D2, D3). `get_authenticated_request` **no cambia**. |
| Backend · auth domain | `backend/app/auth/domain/context.py` | Sólo docstring: `preferred_language` es la preferencia almacenada y **no** el idioma en el que se pinta; apunta a `RequestLocaleDep`. |
| Backend · dashboard | `backend/app/dashboard/api/router.py` | Las dos rutas que componen texto toman `RequestLocaleDep` (`:100`, `:139`); `description=` actualizada (D11). |
| Backend · timeline | `backend/app/timeline/api/router.py` | Igual para `:109`; `description=` actualizada. |
| Backend · contrato | `backend/openapi.json` | Regenerado con `make openapi` (sólo descripciones). |
| Backend · tests | `backend/tests/test_i18n.py`, `backend/tests/dashboard/test_api.py`, `backend/tests/timeline/test_api.py`, `backend/tests/test_layering.py` (o test nuevo de guardia) | Unitarios de `resolve_locale`; R1.8 parametrizado en las 4 combinaciones pedido × fila sobre las tres rutas; guardia estructural de D5. |
| Frontend · i18n | `frontend/lib/i18n/active-locale.ts` (nuevo), `frontend/lib/i18n/use-active-locale.ts` (nuevo), `frontend/lib/i18n/client-provider.tsx` | Publicación y lectura del idioma resuelto (D6, D7). |
| Frontend · API | `frontend/lib/api/authenticated-client.ts` | `getHeaders` añade `X-Locale` (D6). Único punto de edición para R1.4. |
| Frontend · claves | `frontend/features/dashboard/hooks/query-keys.ts`, `frontend/features/dashboard/hooks/use-dashboard-data.ts` | Locale al final del `scope`; los tres hooks lo aportan (D7). |
| Frontend · contrato | `frontend/lib/api/generated/openapi.d.ts` | Regenerado (comentarios). |
| README | `README.md` | Estructura: nueva entrada para `backend/app/core/i18n.py` y ampliación de la de `frontend/lib/i18n/` con el mecanismo de publicación (D6). |
| Frontend · tests | `frontend/lib/api/client.test.ts` o `authenticated-client` nuevo, `frontend/features/dashboard/hooks/query-keys.test.ts`, `frontend/features/dashboard/hooks/use-dashboard-data.test.tsx` | Cabecera presente y = locale activo; R2.4 (clave sin locale = rojo) y prefijo de invalidación intacto; cambio de idioma → clave nueva → refetch. |
| Prosa viva · R3/R4 | `sdd/project.md`, `sdd/roadmap.md` (entrada), `sdd/roadmap/frontend-verification-fixes.md` | Párrafo de hidratación reescrito con el veredicto medido y la hipótesis marcada como tal (D9, D10); las tres casas del hallazgo corregidas (R4.4). |
| Prosa viva · consecuencia de R1 | `docs/dashboard.md:43-45`, `sdd/roadmap/timeline-web.md:70`, `sdd/specs/dashboard-api.md:487`, `sdd/specs/revenue-statements.md:306` | Cuatro casas más de la redacción superada, fuera de las tres que R4.4 nombra — ver OQ3. |
| Specs | `sdd/specs/auth-tenancy.md` (`:243-251`, `:542`), `sdd/specs/frontend-foundation.md` (`:50-56`) | Los actualiza `/sdd:archive` tras el merge, no este change. `sdd/specs/dashboard-api.md` (`:270-307`) no está aquí porque sí lo toca este change — tarea 5.3, ver la fila «Prosa viva» de arriba: la reescritura completa como `SHALL` queda para `/sdd:archive`, pero la corrección de la redacción que seguía afirmando lo contrario del código nuevo no espera. |

## Data & interfaces

- **Esquema de base de datos**: sin cambios. Ninguna columna nueva, ninguna migración, ningún
  valor persistido. `users.preferred_language` se sigue leyendo y **no** se escribe (R1.7 y la
  columna `title` almacenada quedan intactas: este change no toca ningún escritor).
- **Contrato HTTP**: una cabecera de petición nueva, `X-Locale: es | en`, opcional, no declarada
  como parámetro de operación (D2). Una cabecera de respuesta nueva en las tres rutas afectadas,
  `Cache-Control: private, no-store` (enmienda D2, ronda 6): el cuerpo varía con `X-Locale`, y
  `no-store` excluye la respuesta de toda caché —compartida o privada— sin necesitar `Vary`
  además (RFC 9111 §5.2.2.5).
- **Config / variables de entorno**: ninguna nueva. El nombre de la cabecera vive dos veces —una
  constante en `dependencies.py` y una en `lib/api`— porque son dos lenguajes; se anota como espejo,
  igual que `MAX_CLIENT_IP_LENGTH` entre el proxy y `dependencies.py`.
- **Seguridad**: el valor de la cabecera es entrada no autenticada y se trata como tal. Selecciona
  entre dos catálogos estáticos y nada más: no llega a ninguna consulta, no influye en el scope de
  tenant (D3 lo mantiene fuera de `RequestContext` justamente para que eso sea comprobable), no se
  persiste, no se registra en log y no entra en ninguna plantilla —`Catalog` valida sus plantillas
  al construirse y sólo interpola `metadata` de la lista blanca por tipo de evento—. No añade
  ninguna columna de texto ni JSON libre, así que no interviene en el censo de la regla 11 de
  `steering/security.md`. Las reglas 1 y 2 quedan como están: mismos permisos, mismo filtro global.

## Risks & mitigations

- **La forma de la clave de consulta cambia y dos invalidaciones la conocen de memoria.** El riesgo
  es que una mutación deje de refrescar la card y nadie lo note. Mitigación: D7 pone el locale al
  final y un test asserta que `dashboardKeys.cards(t, "en")` sigue empezando por
  `["tenant", t, "dashboard-cards"]`.
- **Una ruta futura que componga texto puede volver a leer la fila.** Mitigación: la guardia de D5.
- **`npm test` en un worktree da dos ficheros en rojo que no son del change** (`ENOENT` por el
  bind-mount) y `npm run api:check` literal no funciona desde aquí. Mitigación: los `docker compose cp`
  que `sdd/project.md` §Worktree bootstrap enumera, y comparar el **total** de ficheros y tests
  contra la pasada de partida, no contra una cifra recordada.
- **R3 puede volver a no reproducir el fallo.** No es un riesgo del change: es el resultado que R3.2
  contempla, y lo que hay que evitar es atribuirle causa (R3.3). El riesgo real es el opuesto —que
  la pasada falle y se dé por imposible la verificación manual—, y contra eso está el `next start`
  con su `build` delante.
- **Regenerar el contrato desde un worktree es la vía con más filos del repo.** Mitigación: la
  secuencia de cuatro comandos de `sdd/project.md`, y `make openapi` antes de ella.

## Verificación de las afirmaciones del proposal

Medidas en el código durante esta fase, porque nadie las revisa después:

1. **"seis vocabularios + los 47 `TimelineEventType`"** — cierto: los seis `Catalog` de
   `app/dashboard/domain/labels.py` y `TIMELINE_TITLES` de `app/timeline/domain/rendering.py`.
   Alcance real de R1: **tres rutas**, no más; `operational-kpis` y `occupancy-series` no componen
   texto.
2. **"cuatro combinaciones rol × idioma"** — cierto y ahora nombrado: `TENANT_OWNER` y
   `PROPERTY_MANAGER` son los únicos roles con `READ_PROPERTIES`.
3. **"`next.config.ts` no declara `allowedDevOrigins`"** — cierto (Next `^16.2.11`).
4. **"`openapi.json` no debería moverse"** — sólo si no se toca la prosa de las rutas. Se toca, así
   que se mueve; ver D11.
5. **"la dependencia ya tiene el `Request` en la mano, así que no cuesta plumbing nuevo"** — cierto,
   y sigue siéndolo con D3: la dependencia nueva reusa el `RequestContext` que FastAPI ya resolvió,
   sin consulta adicional.
6. **Casas de la redacción superada** — R4.4 nombra tres y hay **siete**: las cuatro extra son
   `docs/dashboard.md:43-45` (afirma «El idioma sale del usuario, no de `Accept-Language`», que es
   lo que R1 invierte), `sdd/roadmap/timeline-web.md:70`, `sdd/specs/dashboard-api.md:487` y
   `sdd/specs/revenue-statements.md:306` (cuya frase «ni mecanismo de traducción por
   `Accept-Language` o locale de usuario en el backend de este proyecto» ya es falsa hoy, y R1 la
   deja más falsa). Ver OQ3.
7. **La instancia de i18next no es un singleton de módulo** — es local al proveedor, y por eso R1.4
   necesita el mecanismo de publicación de D6 en vez de un import.

## Open questions

Las tres se resolvieron en el gate de `/sdd:design` del **2026-09-05**, con Jose, y las tres por la
opción recomendada. Se conservan enunciadas porque el motivo de cada una es lo que hay que poder
releer, no el resultado.

- **OQ1 — `allowedDevOrigins`: ¿declararlo o dejarlo escrito como hipótesis?** R4.2 autoriza las
  dos. **Resuelta: hipótesis** (D10), porque el síntoma no se reproduce y por tanto no hay efecto
  que registrar, y declararlo bien exigiría una variable de entorno nueva y un cambio en
  `sdd/specs/local-environment.md`.
- **OQ2 — nombre de la cabecera: `X-Locale` o `Accept-Language`.** **Resuelta: `X-Locale`** (D1).
  Es la elección que decide si "el idioma que el cliente pide" es algo que nuestro código escribió
  o algo que el navegador manda solo.
- **OQ3 — ¿el change corrige las cuatro casas extra de la redacción superada?** **Resuelta: sí, las
  siete, y la enmienda bajó a `proposal.md`** — R1.9 nueva para las cuatro casas de la redacción del
  idioma (`docs/dashboard.md:43-45`, `sdd/roadmap/timeline-web.md:70`,
  `sdd/specs/dashboard-api.md:487`, `sdd/specs/revenue-statements.md:306`) y R4.4 acotada a las tres
  del hallazgo de hidratación, que es de donde es cada una. La enmienda no se queda aquí a propósito:
  una OQ que enmienda un requisito y no baja al proposal acaba como `SHALL` falso en la spec viva.
