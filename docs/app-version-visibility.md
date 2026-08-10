# Versión desplegada

Cómo se **usa y se opera** la visibilidad de versión. El *qué hace* vive en las reglas EARS
de `sdd/specs/app-version-visibility.md` (la crea `/sdd:archive` al cerrar el change).

## Para qué existe

Antes, saber qué estaba desplegado exigía abrir un túnel SSH a la VM y leer `IMAGE_TAG` del
`.env`. Eso encarecía **confirmar un rollback** (que es manual, por SHA — `RUNBOOK §6.4`) y
**descartar el cachéo del edge** cuando la app parece atrasada.

## Cómo se lee

**Abriendo la app.** El pie de página muestra:

```
0.1.0+2026-07-31.5872022
```

`0.1.0` es la base (el fichero `VERSION` de la raíz), `2026-07-31` la fecha de build y
`5872022` el commit corto — la **misma** cadena que llevan los labels OCI de las imágenes, sin
recortar. Aparece en
el workspace, en las apps de campo y **también en `/login`, sin sesión** — que es justo
cuando más falta hace, porque si la app está rota puede que no puedas entrar. **No** se
pinta en el portal de huésped: la versión no le dice nada a un huésped.

> **Matiz que conviene saber si alguien pregunta.** El badge no se *muestra* ahí, pero la
> cadena **sí viaja en el HTML** de esa página, igual que en todas: la configuración pública
> es un único snapshot que el layout raíz serializa en cada superficie. No es una fuga
> nueva —quien alcanza `/guest/<token>` alcanza `/login` en el mismo origen y obtiene la
> misma cadena—, pero la respuesta honesta a "¿un huésped puede ver la versión?" es
> *"no en pantalla; sí en el código fuente de la página"*.

**Desde la VM**, la identidad que lleva la imagen dentro:

```bash
docker inspect ghcr.io/autohostai-labs/autohostai-backend:sha-<commit> \
  --format '{{json .Config.Labels}}'
# org.opencontainers.image.version  → 0.1.0+2026-07-30.a2f3c1d  (lo mismo que el badge)
# org.opencontainers.image.revision → el SHA completo (solo en el label OCI, no en el snapshot frontend)
# org.opencontainers.image.created  → cuándo se construyó, con hora
```

El label `.version` y el badge dicen ahora **exactamente lo mismo**, así que comparar la
pantalla con la VM es comparar dos cadenas idénticas. Lo que solo está en la VM es el SHA
completo y la **hora** del build.

Las dos imágenes de un mismo despliegue llevan la **misma** cadena: la calcula un único job
del CD y la consumen los dos builds, así que no pueden desincronizarse.

> **Un matiz si usas el badge para afirmar "esta imagen concreta".** El despliegue pinea por
> el tag `sha-<commit>`, que es mutable, no por dígest, así que un mismo commit puede
> construirse más de una vez y producir imágenes distintas con el mismo tag. El badge lleva
> la fecha, así que **separa builds de días distintos**; lo que no separa son **dos builds
> del mismo commit el mismo día** — y ese es justo el caso frecuente, porque un
> `workflow_dispatch` para recuperar un deploy fallido se lanza el mismo día. La fecha
> canónica tiene granularidad de día (`%Y-%m-%d`); la hora solo está en
> `org.opencontainers.image.created`. Para identificar una imagen sin ambigüedad, sigue
> siendo ese label el que hay que mirar.

## Para parear con un PR

El badge da el SHA corto; de ahí al Pull Request:

```bash
gh pr list --search a2f3c1d --state all
gh api /repos/autohostai-labs/AutoHostAI/commits/a2f3c1d/pulls --jq '.[0].number'
```

El badge sigue siendo únicamente identidad pública: `appVersion` y `buildCommitShort` pueden
viajar en el HTML de todas las superficies. El pareo autenticado con PR, commit completo y run
de Actions pertenece a `app-version-provenance`: se solicita bajo demanda desde el workspace
autenticado mediante `GET /api/v1/provenance`, y nunca forma parte del HTML público, `RootLayout`,
`PublicRuntimeConfig` ni los bundles.

## Dos cosas que confunden si no se saben

### La versión en pantalla no es el último commit de `main`

El CD está filtrado por rutas: solo dispara con cambios en `backend/**`, `frontend/**`,
`docker-compose.deploy.yml` o el propio workflow. Un merge que solo toque `sdd/` o `infra/`
**no despliega**. Es normal y correcto que el badge apunte a un commit de varios merges
atrás: es el último que *disparó build*.

### El badge delata una página cacheada, no un chunk JS cacheado

El badge se renderiza en el servidor, así que su valor viaja en el HTML. Si el edge sirve
una **página** antigua, el badge la delata. Si sirve **JavaScript** antiguo con HTML fresco,
no: el badge vendría del HTML nuevo. Para ese caso hay que mirar los nombres de fichero en
la pestaña Network del navegador.

### Si el badge dice "versión desconocida"

Puede significar dos cosas distintas, y conviene no confundirlas.

La imagen **no lleva identidad horneada**: en dev local es lo normal (el target `dev` nunca
ejecuta `npm run build`); en la VM significa que el job `provenance` no alimentó el build.

O la lleva pero **el frontend la ha rechazado**. La configuración pública solo admite
`X.Y.Z+YYYY-MM-DD.<7 hex>` —o el literal `local`— y el commit corto solo 7 caracteres hex;
cualquier otra cosa cae a vacío. Es deliberado: esa cadena viaja en el HTML de **todas** las
superficies, así que el límite prefiere no mostrar nada antes que mostrar algo sin vetar. Se
dispara si alguien ensancha `${GITHUB_SHA:0:7}`, cambia el formato de la fecha, o `VERSION`
deja de tener forma `X.Y.Z`.

Para separarlas, mira el label de la imagen: si `org.opencontainers.image.version` está
**vacío** es el primer caso; si lleva una cadena y el badge sigue diciendo "desconocida" es el
segundo, y hay que alinear el patrón de `frontend/lib/config/public.ts` con lo que el CD
compone —en el mismo Pull Request, porque el check `frontend-tests` ejecuta la verificación
de congruencia—.

## Cómo se mantiene la versión base

`VERSION`, en la raíz, es la fuente de la parte fija. Subirla es editar ese fichero. El CD
valida que tenga forma `X.Y.Z` antes de componer nada, y falla el build si no.

Hoy no hay ceremonia de release (ni git tags, ni CHANGELOG): fue una decisión explícita,
porque el CD despliega en cada push a `main` y el esquema `<base>+<fecha>.<sha>` ya
identifica cada despliegue sin ambigüedad. El hueco para adoptar SemVer está abierto y no
exige rediseñar nada.

`backend/pyproject.toml` y `frontend/package.json` declaran también un `version` por
convención de sus ecosistemas. El target host-side `make check-version-parity`, ejecutado en el
workflow de frontend y documentado en el README, falla si cualquiera de los tres valores falta,
está vacío o diverge de `VERSION`.
