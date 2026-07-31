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
0.1.0+a2f3c1d
```

`0.1.0` es la base (el fichero `VERSION` de la raíz) y `a2f3c1d` el commit corto. Aparece en
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
# org.opencontainers.image.version  → 0.1.0+2026-07-30.a2f3c1d  (con la fecha de build)
# org.opencontainers.image.revision → el SHA completo
# org.opencontainers.image.created  → cuándo se construyó
```

Las dos imágenes de un mismo despliegue llevan la **misma** cadena: la calcula un único job
del CD y la consumen los dos builds, así que no pueden desincronizarse.

## Para parear con un PR

El badge da el SHA corto; de ahí al Pull Request:

```bash
gh pr list --search a2f3c1d --state all
gh api /repos/autohostai-labs/AutoHostAI/commits/a2f3c1d/pulls --jq '.[0].number'
```

El pareo en un clic desde la propia pantalla está en el roadmap como entrada aparte
(`app-version-provenance`): exige que el frontend tenga autenticación antes, porque los
enlaces nombran el repositorio privado y hoy el HTML de todas las páginas es público.

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

## Cómo se mantiene la versión base

`VERSION`, en la raíz, es la fuente de la parte fija. Subirla es editar ese fichero. El CD
valida que tenga forma `X.Y.Z` antes de componer nada, y falla el build si no.

Hoy no hay ceremonia de release (ni git tags, ni CHANGELOG): fue una decisión explícita,
porque el CD despliega en cada push a `main` y el esquema `<base>+<fecha>.<sha>` ya
identifica cada despliegue sin ambigüedad. El hueco para adoptar SemVer está abierto y no
exige rediseñar nada.

`backend/pyproject.toml` y `frontend/package.json` declaran también un `version` por
convención de sus ecosistemas; **hoy nadie los usa y pueden divergir de `VERSION` sin que
nada avise**. Comprobarlo en CI está en la entrada de roadmap `app-version-provenance`.
