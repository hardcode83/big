# Draft de actualización — `sdd/specs/compose-ports.md`

> Preparado durante `/sdd:run` (sección 6, archive prep). **No se ha tocado ningún spec vivo.**
> `/sdd:archive ci-pr-gates-optimization` consume este borrador. **Decisión que el archive
> debe tomar** (ver abajo): `sdd/specs/compose-ports.md` **no existe** como fichero propio —
> todo el contenido vigente de esta guardia vive dentro de
> `sdd/specs/local-environment.md` § «Guardia de la postura de red» (líneas 347-451). Este
> borrador da el texto para las dos vías: (i) actualizar esa sección in situ (recomendado,
> preserva la estructura actual), o (ii) extraerla a un fichero `compose-ports.md` dedicado si
> el archive prefiere darle spec propia — como ya tienen `backend-ci.md`, `frontend-ci.md` y
> `rule11-ownership-guard.md` para sus respectivos workflows.

## (a) Estado actual del spec

No hay `sdd/specs/compose-ports.md`. El contrato vigente de `.github/workflows/compose-ports.yml`
está documentado en `sdd/specs/local-environment.md` § «Guardia de la postura de red»
(líneas 347-451), que describe:

- `make check-compose-ports` → `scripts/compose-ports.py`, que también corre en cada Pull
  Request vía `.github/workflows/compose-ports.yml` — descrito ahí como **un solo job**
  (implícito: no se menciona detección de área, ni jobs separados).
- "Estado del check" (líneas 354-360): no obligatorio hoy, mismo motivo de plan de GitHub que
  `backend-tests` y `frontend-tests` — cita ya `specs/backend-ci.md` §Estado.
- Las seis reglas de decisión por mapeo, la exención de los dos pares
  `backend:8000`/`frontend:3000`, la aserción positiva por igualdad de inventario, el fallo
  cerrado ante cualquier paso roto, y las limitaciones deliberadas (`::1` en rojo, valores
  interpolados en rojo).
- Al final de la sección (líneas 446-451): "Su suite **sí** la recoge un workflow —
  `compose-ports.yml`, con `uv run --no-project --with 'pytest==9.1.1' python -m pytest
  scripts/ -q`" — sigue siendo cierto, ese paso vive ahora en `compose-ports-suite`.

Nada de esto menciona el patrón de tres jobs, la puerta de área (`compose-ports-detect`) ni el
consolidador (`compose-ports`) que introduce `ci-pr-gates-optimization`.

## (b) Cambios que el archive debe aplicar

1. **Decisión previa**: elegir entre actualizar la sección existente de `local-environment.md`
   in situ, o extraerla a `sdd/specs/compose-ports.md` dedicado. Este borrador da el texto para
   ambas rutas en (c); la ruta (i) es la que menos rompe referencias existentes (otros specs y
   `steering/security.md` enlazan a `local-environment.md` § «Guardia de la postura de red»).
2. Documentar el patrón de tres jobs (`compose-ports-detect` / `compose-ports-suite` /
   `compose-ports`), igual que `backend-ci.md` y `frontend-ci.md`: sin `paths:` en `on:`,
   filtrado dentro del workflow, fail-open ante diff ambiguo, y el check `compose-ports`
   reportando siempre (`if: always()`).
3. Documentar el área que decide `compose-ports-detect` — las **diez** anclas del `case`
   on-disk (post-§11 de `tasks.md`, tabla D1/D1.1.b de `design.md`): **toda la familia de
   descubrimiento por defecto de Docker Compose** (`compose.yaml`, `compose.yml`,
   `compose.override.yaml`, `compose.override.yml`, `docker-compose*.yml`, `docker-compose*.yaml`,
   `docker-compose.worktree.yml`), más `scripts/*`, `Makefile` y el propio workflow. La familia
   `compose.*` se añade (SEC-1, §11) porque `scripts/compose-ports.py` corre `docker compose
   config` **sin `-f`** y Compose resuelve esos nombres —`compose.yaml`/`compose.yml` con
   **precedencia** sobre `docker-compose.yml`—, así que un PR que solo añadiera `compose.yaml` lo
   inspeccionaría el guard pero el detector lo omitía. Además, `compose-ports-detect` corre
   `python3 scripts/check-detect-surface.py compose` como **paso always-run** antes de decidir el
   skip: si la superficie de descubrimiento excede las anclas, el job falla y el consolidador
   reporta **fail-closed** (design D1.1.c). `scripts/*` y `Makefile` se añaden sobre el conjunto
   pre-§9 de 4 anclas porque
   `compose-ports-suite` corre `pytest scripts/ -q` (el árbol de tests de `scripts/` **entero**,
   no solo compose) además de `make check-compose-ports`; principio de `design.md` **D1.1**
   (`detect surface ⊇ suite dependency surface`) — anclar solo los ficheros de compose dejaba
   fuera el código de guard/tests que la suite ejecuta. A diferencia de `backend-tests-detect`,
   que mira `backend/**`, esto cubre justo el vacío que la cabecera de `compose-ports.yml`
   documenta: un PR que solo toca `docker-compose.yml` no habría ejecutado `backend-tests-suite`
   (cuyo alcance es `backend/**`), y por eso esta guardia necesita su propia detección de área,
   no reutilizar la de `backend-tests`.
4. **Preservar sin cambios** toda la descripción de la postura de red: las seis reglas de
   decisión, la exención de los dos pares, la aserción positiva por igualdad, el fallo cerrado,
   las limitaciones deliberadas y el "Qué NO es" frente a `make up`. Ninguna de ellas cambia
   con este change — `compose-ports-suite` ejecuta exactamente `make check-compose-ports` y la
   suite de pytest, igual que antes, solo que ahora condicionado a la detección de área.
5. Actualizar la frase final ("Su suite sí la recoge un workflow…") para nombrar
   `compose-ports-suite` en vez de un job único implícito.

## (c) Texto propuesto, listo para pegar

### Ruta (i) — actualizar `local-environment.md` § «Guardia de la postura de red» in situ

Insertar tras el primer párrafo (línea 352, tras "sale con código distinto de cero cuando hay
hallazgo.") y antes de "**Estado del check.**":

```markdown
**Tres jobs, no uno** (change `ci-pr-gates-optimization`). `compose-ports.yml` sigue sin
`paths:` en `on:` — mismo motivo que fija `specs/backend-ci.md`: un filtro de rutas a nivel de
disparador no produce check alguno en los PR que no lo tocan. El filtrado ocurre dentro del
workflow, en tres jobs: `compose-ports-detect` decide si el diff toca la configuración de
compose o el código que la suite ejecuta (la familia de descubrimiento de Compose —`compose.yaml`,
`compose.yml`, `compose.override.yaml`, `compose.override.yml`, `docker-compose*.yml`,
`docker-compose*.yaml`, `docker-compose.worktree.yml`—, `scripts/*`, `Makefile` o el propio
workflow), verifica su superficie always-run (`check-detect-surface.py compose`) y corre siempre en
segundos; `compose-ports-suite` ejecuta `make check-compose-ports` y la suite de pytest solo si
la detección dice que hace falta; `compose-ports` consolida y reporta con `if: always()`, así
que el check existe siempre aunque la suite se salte. Las anclas `scripts/*` y `Makefile`
cubren la superficie de dependencias de la suite (`design.md` D1.1: `detect surface ⊇ suite
dependency surface`) — `compose-ports-suite` corre `pytest scripts/ -q` sobre el árbol de
`scripts/` entero, no solo el guard de compose. La detección resuelve su propia área —
deliberadamente **no** reutiliza la de `backend-tests-detect` (`backend/**`): un PR que solo
toca `docker-compose.yml` no la tocaría, y es justo el PR donde esta guardia tiene que hablar.
Ante diff ambiguo o fallo de detección, decide a favor de ejecutar la suite (fail-open), igual
que el resto de detectores del repositorio.
```

Y sustituir, en el último párrafo de la sección (líneas 446-451), la frase:

> "Su suite **sí** la recoge un workflow —`compose-ports.yml`, con `uv run --no-project --with
> 'pytest==9.1.1' python -m pytest scripts/ -q`—"

por:

> "Su suite **sí** la recoge un workflow — el job `compose-ports-suite` de `compose-ports.yml`,
> con `uv run --no-project --with 'pytest==9.1.1' python -m pytest scripts/ -q`, ejecutado solo
> cuando `compose-ports-detect` afirma que el diff toca el área—"

### Ruta (ii) — crear `sdd/specs/compose-ports.md` dedicado

Si el archive decide darle spec propio (consistente con `backend-ci.md`/`frontend-ci.md`/
`rule11-ownership-guard.md`), el contenido es el mismo texto de § «Guardia de la postura de
red» de `local-environment.md` (líneas 347-451), con la inserción de la ruta (i) de arriba,
movido a un fichero propio con este `## Purpose`:

```markdown
# Postura de red del compose local

## Purpose

Esta capacidad comprueba en GitHub Actions, en cada Pull Request, que ningún servicio del
compose local publica un puerto en el host fuera de `127.0.0.1`, salvo los dos pares exentos
a propósito (`backend:8000`, `frontend:3000`, abiertos a la LAN porque el proyecto es
mobile-first). Existe porque el Redis del stack local guarda los contadores del throttle de
login y corre sin `requirepass`, y este bind es lo que sostiene la exención de
`POSTGRES_PASSWORD` de `steering/security.md` regla 8.
```

seguido del contenido íntegro de la sección de `local-environment.md`, con la inserción del
patrón de tres jobs de la ruta (i). En ese caso, `local-environment.md` sustituye su sección
§ «Guardia de la postura de red» por un enlace a `specs/compose-ports.md`, y sus referencias
cruzadas actuales (`rule11-ownership-guard.md`, `steering/security.md`) actualizan su cita al
nuevo fichero.
