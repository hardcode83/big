# Design: app-version-visibility

> **Alcance recortado el 2026-07-30.** Este design tenía 11 decisiones cubriendo el panel de
> procedencia, la detección de deriva y el gate de paridad. Al recortar el change a "ver la
> versión al abrir la app", quedan cinco. Las retiradas (D3 extracción del PR, D8 island de
> procedencia, D9 lectura fuera del render, D11 retención de enlaces, y la parte de gate de
> D1) se recuperan en `app-version-provenance`, que hereda su razonamiento.

## Context

El CD (`.github/workflows/deploy-dev.yml`) construye las dos imágenes `prod` arm64, las
etiqueta `sha-<commit>` + `dev`, y el job `deploy` pinea el compose con `${IMAGE_TAG}`.
Ninguna imagen lleva identidad dentro ni labels OCI.

En el frontend, `frontend/lib/config/` es la única frontera de configuración: `public.ts`
construye `PublicRuntimeConfig` desde una allowlist explícita y el layout raíz lo pasa por
`AppProviders`. El chrome del shell son Server Components que resuelven su texto con
`getServerT` y lo reciben como props (`Brand`, `SkipLink`). `ShellFrame` recibe slots
`skipLink`/`topbar`/`sidebar`/`bottomNavigation` y **no tenía slot de footer**.

## Decisions

### D1 — `VERSION` en la raíz como sitio de la base

**Chosen:** un fichero `VERSION` con la base en una línea. El CD lo lee y valida `X.Y.Z`
antes de componer nada. La versión del *producto* es un hecho de producto, no de componente:
ninguno de los dos manifiestos es naturalmente canónico, y hoy ambos declaran `0.1.0` sin
que nadie los use.

Rejected: `pyproject.toml` como canónico — obliga al frontend a parsear TOML por un dato que
no es del backend. Rejected: derivar los manifiestos de `VERSION` en build — dos generadores
por un string.

**Deuda conocida y documentada** (R3.5): los dos manifiestos pueden divergir de `VERSION`
sin que nada avise. Comprobarlo en CI necesita un target que corra en el host —el contenedor
de backend monta solo `./backend` y no ve `VERSION` ni `frontend/package.json`, verificado— y
eso va en `app-version-provenance` junto con el resto del gate.

### D2 — La identidad se calcula una vez en el CD y viaja como build-args

**Chosen:** un job `provenance` que la compone en un solo sitio y la publica por `outputs`;
los dos builds la consumen. Garantiza que las dos imágenes lleven idéntica cadena por
construcción en vez de por disciplina, y deja el cálculo en un único lugar auditable.

Una sola lectura del reloj alimenta la fecha de la versión y el label `.created`: con dos
invocaciones de `date`, un build que cruzase la medianoche UTC las dejaría con un día de
diferencia.

Rejected: calcularlo dentro de cada job de build — dos implementaciones del mismo string, que
es exactamente cómo se desincronizan. Rejected: calcularlo en el job `deploy` — llega tarde,
la identidad tiene que estar *dentro* de la imagen.

### D3 — Frontend: la cadena entra en `PublicRuntimeConfig`

**Chosen:** `NEXT_PUBLIC_APP_VERSION` y `NEXT_PUBLIC_BUILD_COMMIT_SHORT` se hornean en la
etapa `builder` y se leen en `buildPublicRuntimeConfig()`, que es la única frontera de
configuración que la spec de `frontend-foundation` permite.

**Alcance real frente al cachéo del edge, verificado y no supuesto:** el badge es un Server
Component (el chrome del shell lo es por spec), así que la cadena viaja en el **HTML
servido**, no inlineada en `.next/static`. Comprobado con un build real: `grep` en
`.next/static` no la encuentra, `curl` a `/login` sí. Por tanto delata que el edge sirve una
**página** cacheada antigua, pero **no** chunks JS antiguos con HTML fresco. Cubrir el
segundo caso exigiría hacer el badge client component, contradiciendo la convención del
shell por una cadena estática — se acepta no cubrirlo.

Lo que sí garantiza, y es el argumento de fondo: una identidad horneada **no puede mentir
sobre qué imagen corre**, mientras que una variable de compose reporta lo que compose cree.

### D4 — El badge es un slot `footer` nuevo en `ShellFrame`

**Chosen:** `ShellFrame` gana un slot `footer` opcional y cada shell decide si lo pasa.
Server Component puro, cero JS de cliente, una sola posición para las cinco superficies. El
`pb-16 md:pb-0` se mueve del `main` a la columna que lo contiene: reserva la altura del
`BottomNavigation` (`fixed inset-x-0 bottom-0 z-40 md:hidden`) de forma que el footer quede
**por encima** de la barra fija en móvil en vez de debajo.

Rejected: el slot `end` del `Topbar` — habría que reescribirlo en las cinco shells y compite
por un `h-14` que en móvil ya va justo. Rejected: renderizarlo en cada página — 21 sitios
donde olvidarlo.

### D5 — `VersionBadge` es síncrono y recibe sus strings como props

**Chosen:** el mismo patrón que `Brand` y `SkipLink`: el shell resuelve el texto con
`getServerT()` y lo pasa. Motivo empírico: la primera versión era un componente **async
anidado** dentro del footer, y eso **suspende el árbol entero del shell** — reventó los 11
tests de las cinco shells a la vez. El chrome no puede permitirse eso por un valor decorativo.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Base de versión | `VERSION` *(nuevo)* | La base, en una línea |
| CD | `.github/workflows/deploy-dev.yml` | Job `provenance` + build-args del frontend + labels OCI en ambas imágenes |
| Imagen frontend | `frontend/devops/Dockerfile` | `ARG`+`ENV` `NEXT_PUBLIC_*` en la etapa `builder` |
| Contexto de build | `frontend/.dockerignore` | Excluir `.env*`: un `.env.local` de una máquina de desarrollo entraría en el contexto y `npm run build` inlinearía sus `NEXT_PUBLIC_*` |
| Config frontend | `frontend/lib/config/public.ts` (+test) | `appVersion` y `buildCommitShort` en la allowlist |
| Shell | `shell-frame.tsx` (+test) | Slot `footer` + reubicación del `pb-16` |
| Shell | `version-badge.tsx`, `shell-footer.tsx` *(nuevos)* (+test) | Badge y pie |
| Shell | los cuatro shells operativos | Pasan el slot `footer`; `guest-shell.tsx` **sin cambios** |
| i18n | `frontend/locales/{es,en}/common.json` | `version.label`, `version.unknown` |
| Compose dev | `docker-compose.yml` | Las dos `NEXT_PUBLIC_*` explícitas (el servicio no tiene `env_file`) |
| Docs | `RUNBOOK.md` §6.4 y §7, `docs/app-version-visibility.md` *(nuevo)*, `README.md` | Operación |

## Data & interfaces

**Cadena canónica**: `0.1.0+2026-07-30.a2f3c1d`. Es la que llevan los labels OCI y
`docker inspect`. El badge muestra la forma corta `0.1.0+a2f3c1d`: con la fecha son ~24
caracteres y compiten por el espacio de un móvil.

**Labels OCI** en ambas imágenes: `org.opencontainers.image.{source,revision,version,created}`.

**Variables**: ninguna nueva en runtime de producción — la identidad se hornea. En build,
`NEXT_PUBLIC_APP_VERSION` y `NEXT_PUBLIC_BUILD_COMMIT_SHORT`. En dev local se declaran en
`docker-compose.yml` y degradan a `local`.

**Esquema de base de datos**: sin cambios. **Migraciones**: ninguna. **Backend**: sin tocar.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| Los manifiestos divergen de `VERSION` sin aviso | Deuda conocida, documentada en R3.5 y en `docs/`; el gate va en `app-version-provenance` |
| El badge parece atrasado respecto a `main` | Es correcto: el filtro de paths del CD hace que sea el último commit que **disparó build**. Documentado (R3.3) |
| Cachéo del edge sirviendo una **página** antigua | Es la funcionalidad: el badge del HTML la delata. El caso de **chunks JS** antiguos con HTML fresco queda fuera (D3) |
| La cadena de versión y el SHA corto viajan al portal de huésped | Aceptado y verificado (R2.6): `PublicRuntimeConfig` es un snapshot único que el layout raíz serializa en todas las superficies. Es la misma divulgación ya aceptada en `/login`; lo que se evita es *mostrárselo* al huésped |
| Una imagen construida sin build-args | Degrada a "versión desconocida" con texto localizado, nunca a un badge vacío (R2.7) |

## Open questions

Ninguna.
