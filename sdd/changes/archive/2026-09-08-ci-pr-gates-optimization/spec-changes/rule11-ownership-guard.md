# Draft de actualización — `sdd/specs/rule11-ownership-guard.md`

> Preparado durante `/sdd:run` (sección 6, archive prep). **No se ha tocado el spec vivo.**
> `/sdd:archive ci-pr-gates-optimization` consume este borrador y lo aplica a
> `sdd/specs/rule11-ownership-guard.md`.

## (a) Estado actual del spec

`sdd/specs/rule11-ownership-guard.md` describe el estado **anterior** a este change: el
workflow `rule11-ownership` como **un único job** que corre siempre, sin puerta de área "ni en
el disparador ni dentro del workflow" (línea 41-49), justificado explícitamente porque el
escaneo tarda ~1 segundo y "no había nada que ahorrar filtrando" (esa misma frase, ahora
desactualizada, es la que el propio `rule11-ownership.yml` cita en su cabecera como razonamiento
que "envejeció junto con el resto del repo"). Puntos concretos:

- "Disparador y alcance de ejecución" (líneas 34-52): afirma **explícitamente** "sin puerta de
  área de ninguna clase", con una nota extensa (líneas 44-49) explicando por qué se intentó
  anclar una puerta mecánicamente y no convergió, y remitiendo al candidato de roadmap del
  change `rule11-guard-trigger-and-scope`. Esta afirmación es la que el archive debe **revertir**:
  el change `ci-pr-gates-optimization` sí introduce una puerta de área (`rule11-ownership-detect`),
  resolviendo lo que esa nota declaraba pendiente.
- "El check run" (líneas 54-66): describe el check run como job único llamado igual que el
  workflow. Sigue siendo cierto que el nombre del check es `rule11-ownership`, pero ahora es el
  nombre del job **consolidador**, no del único job.
- "Independencia del entorno" (líneas 68-83): sigue siendo cierto para `rule11-ownership-suite`
  (sin PostgreSQL, Redis, `.env` ni secrets); no requiere cambios de contenido, solo de encaje
  estructural (ahora describe un job, no el workflow entero).
- "Alcance recorrido", "Fallo cerrado", "Qué es un sumidero para este guardián": sin relación
  con el disparador — describen el propio script `scripts/rule11-ownership.py`, no el workflow.
  No requieren cambios.
- "El coste declarado de vivir fuera de la suite" (líneas 85-89): sigue vigente, sin cambios.
- "Verification" y "Obligaciones sobre la Pull Request abierta, antes del merge"
  (líneas 162-254): la subsección "Las dos vías de diff" (líneas 195-221) ya documenta el
  contraste `backend-tests-suite` `skipped` frente a `rule11-ownership` sin puerta — ese
  contraste **cambia** con este change: ahora `rule11-ownership-suite` también puede salir
  `skipped` legítimamente, y hay que distinguir su omisión legítima (el check consolidador sigue
  verde) de la vieja alarma que motivó el workflow.

## (b) Cambios que el archive debe aplicar

1. Reescribir "Disparador y alcance de ejecución" para documentar el patrón de tres jobs
   (`rule11-ownership-detect` + `rule11-ownership-suite` condicional + `rule11-ownership`
   consolidador), retirando la afirmación "sin puerta de área de ninguna clase" y su nota
   extensa — el intento que no convergía queda resuelto: el patrón replicado de
   `backend-tests.yml` sí ancla la puerta mecánicamente, condicionando el **trabajo** en vez
   del **disparo**.
2. Documentar el área que decide `rule11-ownership-detect` — las **doce** anclas del `case`
   on-disk (post-§9 de `tasks.md`, tabla D1/D1.1 de `design.md`): `sdd/steering/*`,
   `sdd/specs/*`, `sdd/project.md`, `sdd/README.md`, `sdd/metrics.md`, `docs/*`,
   `backend/app/*`, `backend/alembic/versions/*`, `backend/tests/*`, `scripts/*`, `Makefile` y
   el propio workflow. Frente al conjunto pre-§9 de 6 anclas (que solo cubría
   `sdd/steering/*`, `sdd/specs/*`, `backend/app/*`, `backend/tests/*`, `docs/*` y el
   workflow), §9 añade `sdd/project.md`, `sdd/README.md`, `sdd/metrics.md` (los tres `.md`
   sueltos del censo prosa que el guardián también camina), `backend/alembic/versions/*`
   (censo código) y `scripts/*`/`Makefile` (el propio guard, su test y su target de Make, que
   la suite EJECUTA). Principio de `design.md` **D1.1** (`detect surface ⊇ suite dependency
   surface`): el censo exacto de árboles que el guardián recorre (`SCOPE` en
   `scripts/rule11-ownership.py`), para que la detección de área y el alcance del script no
   puedan discrepar en silencio (mismo principio que ya fija "Alcance recorrido").
3. Documentar la invariante machine-checked de `design.md` **D1.1.a**:
   `relevant-SCOPE-walked-surface(rule11) ⊆ detect-anchor-surface(rule11)`. `SCOPE` declara
   `sdd` como raíz recursiva (censo prosa), mientras el detector **enumera** las rutas de
   `sdd/` a propósito (anclar `sdd/*` recursivo dispararía la suite en cada PR de flujo SDD,
   que toca `sdd/changes/**` — fuera de `SCOPE` por exclusión `OUT_OF_CENSUS`). Esa elección
   deja una brecha latente si `SCOPE` crece (p. ej. un `sdd/adr/` nuevo) sin que el detector se
   actualice a la vez. La invariante la hace comprobable un test en
   `scripts/test_rule11_ownership.py` — `test_rule11_detect_surface_covers_walked_scope` y
   `test_rule11_detect_surface_invariant_catches_a_new_sdd_subtree` (change
   `ci-pr-gates-optimization`, §10.5) — **y, sobre todo, se ejecuta always-run** como paso de
   `rule11-ownership-detect` (`python3 scripts/check-detect-surface.py rule11`, §11/D1.1.c),
   antes de la decisión de skip: si `SCOPE` crece fuera de las anclas, el job `*-detect` falla y
   el consolidador reporta fail-closed **en el propio PR que abre la brecha**, no uno después
   (los tests de la suite condicional quedan como belt-and-suspenders). La invariante falla si
   aparece una ruta bajo `sdd/` que la guardia camina pero ninguna ancla activa cubre; la
   resolución correcta ante ese rojo es
   añadir la ancla explícita (o declarar la ruta `OUT_OF_CENSUS` en `SCOPE`), nunca ampliar a
   `sdd/*` ni recortar `SCOPE`.
4. Actualizar "El check run" para nombrar `rule11-ownership` como el job **consolidador**
   (`needs: [rule11-ownership-detect, rule11-ownership-suite]`, `if: always()`), distinto de
   `rule11-ownership-suite` donde vive la ejecución real del guardián.
5. Actualizar "Independencia del entorno" para nombrar `rule11-ownership-suite` como el job que
   ejecuta `make check-rule11-ownership` y la suite de pytest — el resto del contenido (sin
   servicios, Python ≥ 3.11 en local, `python3` de `ubuntu-latest`) no cambia.
6. Actualizar "Las dos vías de diff" (dentro de "Obligaciones sobre la Pull Request abierta"):
   el contraste que documentaba el defecto original —`backend-tests-suite` `skipped` mientras
   `rule11-ownership` no tenía puerta y por tanto siempre corría— sigue siendo la evidencia
   histórica del defecto (no se reescribe: es un hecho medido y fechado), pero hay que añadir
   una nota de que, **tras este change**, `rule11-ownership-suite` también puede salir
   `skipped` legítimamente cuando el diff no toca el censo — y que eso es distinto de la
   omisión indebida que el defecto original describía, porque ahora el consolidador
   `rule11-ownership` reporta siempre pase lo que pase con la suite.
7. **Preservar sin cambios**: "Alcance recorrido", "Fallo cerrado", "Qué es un sumidero para
   este guardián" (censo, `SCOPE`, meta-vocabulario, el párrafo de auto-referencia), "El coste
   declarado de vivir fuera de la suite", "Verification" (salvo la nota de arriba) y el resto de
   "Obligaciones sobre la Pull Request abierta" (las dos Pull Requests desechables, el
   `mark-recertified`, "Verde sobre la base fusionada").

## (c) Texto propuesto, listo para pegar

### Reemplazo de "Disparador y alcance de ejecución" (líneas 34-52)

```markdown
### Disparador y alcance de ejecución

- WHEN se abre o actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL ejecutar el
  workflow `rule11-ownership`.
- THE SYSTEM SHALL conseguirlo **sin `paths:` en `on:`**, por el motivo que
  [`specs/backend-ci.md`](backend-ci.md) fija para todo el repositorio: un filtro de rutas a nivel
  de disparador no produce check alguno en los PR que no tocan esas rutas.
- THE SYSTEM SHALL **reportar siempre un resultado del check `rule11-ownership`**, toque el diff
  el censo de la regla 11 o no — mismo invariante que `backend-tests` y `frontend-tests`.
- THE SYSTEM SHALL estructurarlo en tres jobs (change `ci-pr-gates-optimization`, revirtiendo la
  decisión "sin puerta de área de ninguna clase" que este spec fijaba antes de él):
  `rule11-ownership-detect` decide el área a partir del diff, `rule11-ownership-suite` corre el
  guardián y su suite **solo si** la detección dice que el diff toca el censo,
  y `rule11-ownership` publica el resultado con `if: always()`.
- THE SYSTEM SHALL anclar en `rule11-ownership-detect` las doce rutas siguientes (`design.md`
  D1.1: el detect debe ser un superconjunto de la superficie de dependencias de
  `rule11-ownership-suite` — tanto el censo que el guardián camina como el código de guard que
  la suite ejecuta): `sdd/steering/*`, `sdd/specs/*`, `sdd/project.md`, `sdd/README.md`,
  `sdd/metrics.md`, `docs/*`, `backend/app/*`, `backend/alembic/versions/*`,
  `backend/tests/*`, `scripts/*`, `Makefile` y el propio workflow.
- WHEN la detección concluye que el diff **no** toca ninguna de esas doce rutas, THE SYSTEM
  SHALL saltarse la suite y publicar el check en verde con el motivo.
- IF la detección falla o no puede determinar el área, THEN THE SYSTEM SHALL decidir a favor de
  ejecutar la suite (fail-open) — mismo criterio que el resto de detectores del repositorio.
- THE SYSTEM SHALL derivar el área de detección de las **mismas rutas** que gobierna `SCOPE` en
  `scripts/rule11-ownership.py` (ver § «Alcance recorrido»), para que la detección de área y el
  alcance real del guardián no puedan discrepar en silencio: una ruta que el guardián recorre
  pero que la detección no reconoce reproduciría exactamente el defecto original —un commit
  que toca esa ruta y no dispara la suite—, solo que ahora en un mecanismo nuevo.
- THE SYSTEM SHALL hacer esta relación **machine-checked** (`design.md` D1.1.a): un test en
  `scripts/test_rule11_ownership.py` (`test_rule11_detect_surface_covers_walked_scope`,
  `test_rule11_detect_surface_invariant_catches_a_new_sdd_subtree`) construye la superficie
  recorrida por la guardia (`prose_files` + `code_files` sobre `SCOPE`) y las anclas del `case`
  on-disk, y falla si aparece una ruta bajo `sdd/` que la guardia recorrería pero ninguna ancla
  cubre — la invariante `relevant-SCOPE-walked-surface(rule11) ⊆ detect-anchor-surface(rule11)`
  no puede degradarse en silencio cuando `SCOPE` crece.

**Por qué esto sí resuelve lo que la nota de este spec declaraba pendiente.** La sección
histórica de este spec explicaba que anclar una puerta de área mecánicamente "se intentó y no
convergió" en el change `rule11-guard-trigger-and-scope`. Lo que cambia con
`ci-pr-gates-optimization` no es esa conclusión sobre las tres vías que se probaron entonces,
sino el punto donde se aplica el filtro: condicionar el **trabajo** (dentro del workflow, sobre
la detección de un job previo) en vez del **disparo** (`paths:` en `on:`), que es precisamente
el patrón que `backend-tests.yml` ya usaba y que este change replica.
```

### Reemplazo de "El check run" (líneas 54-66)

```markdown
### El check run

- THE SYSTEM SHALL publicar el resultado como un check run **propio**, llamado `rule11-ownership`,
  distinto del de `backend-tests`. El nombre lo toma del job **consolidador**
  (`rule11-ownership`, `needs: [rule11-ownership-detect, rule11-ownership-suite]`,
  `if: always()`), no del workflow ni del job de detección o de suite — que se llaman
  `rule11-ownership-detect` y `rule11-ownership-suite` respectivamente.
- **Estado del check.** WHILE el repositorio no disponga de protección de rama compatible, THE
  SYSTEM SHALL ejecutar y reportar `rule11-ownership` **sin** configurarlo como check obligatorio
  para fusionar — igual que `api-contract`, `compose-ports` y `frontend-tests`, y por el mismo
  motivo de plan de GitHub ([`specs/backend-ci.md`](backend-ci.md) §Estado,
  [`docs/adr/0002-github-org-hosting.md`](../../docs/adr/0002-github-org-hosting.md)). Lo que
  sostiene esta guardia mientras tanto es un rojo **visible** en cada Pull Request, no una puerta
  que impida fusionar. El día que haya protección de rama, éste es de los checks que deben pasar a
  obligatorios.
```

### Reemplazo del primer bullet de "Independencia del entorno" (línea 70)

```markdown
- WHERE el guardián se ejecute en CI (job `rule11-ownership-suite`), THE SYSTEM SHALL no
  requerir PostgreSQL, Redis, `.env` ni ningún secret, y SHALL hacerlo **verificable leyendo el
  workflow**: sin `services:`, sin `env:` y sin ninguna referencia a `secrets`.
```

### Inserción tras "Las dos vías de diff" (tras línea 198, dentro de «Obligaciones sobre la Pull Request abierta»)

```markdown
  **Tras `ci-pr-gates-optimization`, un `rule11-ownership-suite` `skipped` deja de ser en sí
  mismo evidencia de defecto.** El contraste medido arriba —`backend-tests-suite` `skipped`
  mientras el guardián de la regla 11 no tenía puerta de área y por tanto siempre corría— sigue
  siendo el hecho histórico que motivó separar este workflow de `backend-tests.yml`; no se
  reescribe. Lo que cambia es que ahora `rule11-ownership-suite` también puede salir `skipped`
  legítimamente, cuando `rule11-ownership-detect` decide que el diff no toca el censo. La
  distinción con el defecto original: el consolidador `rule11-ownership` reporta siempre,
  `if: always()`, así que una omisión legítima de la suite sigue dejando un check verde con el
  motivo nombrado — nunca la ausencia de check que describía el defecto de origen.
```
