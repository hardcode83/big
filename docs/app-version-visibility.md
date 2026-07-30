# Versión desplegada: cómo leerla y cómo parearla con un PR

Cómo se **usa y se opera** la visibilidad de versión. El *qué hace* vive en las reglas EARS
de `sdd/specs/app-version-visibility.md` (la crea `/sdd:archive` al cerrar el change); aquí
no se duplican.

## Para qué existe

Antes de este change, saber qué estaba desplegado exigía abrir un túnel SSH a la VM y leer
`IMAGE_TAG` del `.env`. Eso encarecía dos cosas que se hacen a menudo: **confirmar un
rollback** (que es manual, por SHA — `RUNBOOK §6.4`) y **descartar el cachéo del edge**
cuando la app parece atrasada.

## Las tres vías, de más barata a más profunda

**1. Abrir la app.** El pie de página muestra la versión desplegada:

```
0.1.0+a2f3c1d
```

`0.1.0` es la base (el fichero `VERSION` de la raíz) y `a2f3c1d` el commit corto. Aparece en
el workspace, en las apps de campo y **también en `/login`, sin sesión** — que es justo
cuando más falta hace, porque si la app está rota puede que no puedas entrar. **No** aparece
en el portal de huésped: la versión no le dice nada a un huésped.

**2. El panel de procedencia**, botón "Detalles" en el pie, solo en el workspace:

| Campo | Para qué sirve |
|---|---|
| Frontend / Backend | Las dos cadenas de versión. Si difieren, hay aviso de deriva |
| Commit | El SHA corto de lo que está corriendo |
| Construido | Fecha y hora UTC del build |

### Por qué el panel no enlaza (todavía) al PR

Los enlaces al PR, al commit y al run de Actions **están implementados pero retenidos**, y
conviene saber por qué antes de "arreglarlo".

El panel es un componente de cliente, así que **todo lo que recibe se serializa en el HTML
de la página, esté el panel abierto o no**. Y `/dashboard` hoy es tan anónimo como `/login`:
el frontend no tiene autenticación y el túnel enruta el hostname completo a `frontend:3000`.
Publicar ahí los enlaces significaría que cualquiera con

```bash
curl https://autohostai.digitalsec.work/dashboard
```

obtiene el nombre del repositorio privado, el número de PR y el SHA completo de lo
desplegado. Se decidió no hacerlo.

La retención es **una sola constante**, `OPERATOR_SURFACE_IS_AUTHENTICATED` en
`frontend/features/shell/components/provenance.ts`. Cuando el frontend gane autenticación
(entrada `dashboard-web` del roadmap), se invierte y los enlaces aparecen sin tocar nada más.

**Mientras tanto, el pareo con el PR es de dos pasos**, no de uno:

```bash
# 1. Leer el SHA corto del badge, p. ej. a2f3c1d
# 2. Buscarlo:
gh pr list --search a2f3c1d --state all      # el PR que lo contiene
gh api /repos/autohostai-labs/AutoHostAI/commits/a2f3c1d/pulls --jq '.[0].number'
git log --oneline -1 a2f3c1d                 # o simplemente el subject del commit
```

**3. Por línea de comandos**, sin abrir el navegador:

```bash
# Las dos cadenas de versión, desde fuera y sin credenciales
curl -s https://autohostai.digitalsec.work/deployment/version

# El bloque completo del backend (por túnel SSH, ver RUNBOOK §7.4)
curl -s http://localhost:8000/version

# La identidad que lleva la imagen DENTRO, desde la VM
docker inspect ghcr.io/autohostai-labs/autohostai-backend:sha-<commit> \
  --format '{{json .Config.Labels}}'
```

`/deployment/version` devuelve **solo** las dos cadenas de versión. Ni el PR, ni la URL del
repositorio, ni el `run_id`: el túnel de Cloudflare enruta a `frontend:3000`, así que ese
path es alcanzable desde internet.

## Tres cosas que confunden si no se saben

### La versión en pantalla no es el último commit de `main`

El CD está filtrado por rutas: solo dispara con cambios en `backend/**`, `frontend/**`,
`docker-compose.deploy.yml` o el propio workflow. Un merge que solo toque `sdd/` o `infra/`
**no despliega**.

Por tanto **es normal y correcto** que el badge apunte a un PR de varios merges atrás. No es
deriva ni un deploy atascado: es el último commit que *disparó build*.

### El pareo depende de la estrategia de merge

El número de PR se extrae del subject del commit
([`.github/scripts/extract-pr.sh`](../.github/scripts/extract-pr.sh)) y solo se reconocen
dos formas, ancladas a propósito:

```
Merge pull request #24 from autohostai-labs/sdd/x   → PR 24   (merge commit, la de este repo)
título del squash (#42)                             → PR 42   (squash)
fix: cierra #7 y #9                                 → sin PR  (#7 es un ISSUE, no un PR)
```

Ese último caso es el motivo de las anclas: un patrón laxo leería `#7` como PR y el badge
enlazaría al sitio equivocado, **que es peor que no enlazar**.

**Si algún día se cambia la estrategia a `rebase`, esto se rompe en silencio**: no habría
subject del que extraer nada y todos los despliegues dirían "push directo, sin PR". El plan
B es sustituir el script por una llamada a la API, que es independiente de la estrategia:

```bash
gh api "/repos/$GITHUB_REPOSITORY/commits/$GITHUB_SHA/pulls" --jq '.[0].number'
```

Cuesta un permiso más (`pull-requests: read`) y una dependencia de red en el build, que es
por lo que hoy no se usa. `make pr-extract-check` protege el comportamiento actual en cada
PR.

### El badge delata una página cacheada, no un chunk JS cacheado

El badge se renderiza en el servidor, así que su valor viaja en el HTML. Si el edge sirve una
**página** antigua, el badge la delata. Si sirve **JavaScript** antiguo con HTML fresco, no:
el badge vendría del HTML nuevo. Para ese caso hay que mirar los nombres de fichero en la
pestaña Network del navegador.

## Cómo se mantiene la versión base

`VERSION`, en la raíz del repo, es la **única fuente de verdad** de la base. `pyproject.toml`
y `package.json` la declaran también porque sus ecosistemas lo esperan, y `make version-check`
—que corre en el gate de CI de cada PR— falla si divergen.

Subir la base es editar `VERSION` y alinear los dos manifiestos. Hoy no hay ceremonia de
release (ni git tags, ni CHANGELOG): fue una decisión explícita, porque el CD despliega en
cada push a `main` y el esquema `<base>+<fecha>.<sha>` ya identifica cada despliegue sin
ambigüedad. El hueco para adoptar SemVer de verdad está abierto y no exige rediseñar nada.

`make ci-checks` agrupa las dos comprobaciones. Corren **en el host**, no en un contenedor:
los servicios `backend` y `frontend` montan solo su propio directorio y no ven la raíz.
