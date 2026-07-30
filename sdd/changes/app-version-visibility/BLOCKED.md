# Blocked — app-version-visibility

Dos entradas de la sección 7 (Verification), que exigen infraestructura inexistente en
local, **más los hallazgos del panel de `/sdd:review`** (2026-07-30, 7 reviewers), que dejó
el change en **NO verificado localmente**.

`/sdd:review` es report-only, así que nada de lo de abajo se ha arreglado. La entrada 3
recoge lo que hay que corregir antes de volver a revisar.

---

## 3. Hallazgos del panel de `/sdd:review` — el change NO está verificado localmente

- **Fase**: review
- **Tipo**: `deferred` — todo son correcciones concretas, no hay decisión pendiente salvo
  donde se indica
- **Comando de reanudación**: corregir lo de abajo y volver a lanzar
  `/sdd:review app-version-visibility`

Veredicto por reviewer: **PASS** tenancy, documentation, i18n · **FAIL** architect (7),
security (6), qa (2 bloqueantes + 2 anotados), cicd (2).

### 3a. Código — bloqueantes

1. **El panel sobre-retiene `commit` y `builtAt`.** `provenance-panel.tsx`: el bloque
   `{withheld ? null : …}` envuelve `pullRequest`, `commit`, `builtAt`, `runId` y `ref`,
   cuando R4.6 solo autoriza ocultar PR, SHA completo, `run_id`, `ref` y URL del repo. Hoy
   el panel muestra **solo** Frontend y Backend. Contradice R4.1, R4.6, R6.6 y el propio
   comentario de `provenance.ts` ("non-sensitive either way"). *(qa #1, security #6)*
   → **Arreglo**: sacar las filas `commit` y `builtAt` del bloque condicional.
2. **El test que debía protegerlo es ceremonial.** `provenance-panel.test.tsx`, test
   "renders the version rows but NOT the repository rows": solo comprueba ausencias, nunca
   afirma la presencia de "Commit" y "Construido". *(qa #1)*
3. **`builtAt` se serializa al cliente sin renderizarse** — el mismo patrón que este change
   eliminó para `commitFull`. Lo resuelve el arreglo de 3a.1. *(security #2)*
4. **La retención depende de un default posicional sin test en el call site.** Nada fija que
   `workspace-shell.tsx` no pase `true`; un cambio de una línea republica los cinco valores
   en 15 rutas anónimas con la suite verde. *(security #1)*
   → **Arreglo**: leer la constante dentro de `resolveProvenance`, o test sobre la salida
   renderizada de `WorkspeaceShell` que afirme la ausencia de los cinco valores.
5. **El portal de huésped recibe la identidad en el payload RSC** (`appVersion`,
   `buildCommitShort`) aunque el badge esté oculto. R3.7 decidió que no la tuviera.
   *(security #3)* → **Decisión necesaria**: acotar el snapshot en esa superficie, o
   enmendar R3.7 y el doc para decir que el badge se oculta pero el valor viaja.
6. **Sin deny-by-default para los `route.ts` del frontend.** `route-coverage.test.ts` solo
   recorre `page.tsx`, así que el próximo route handler será anónimo y alcanzable sin que
   ningún gate lo señale. El backend tiene `ANONYMOUS_ENDPOINTS` justo para eso.
   *(security #5)*
7. **`make version-check` no valida el formato `X.Y.Z`.** El guard existe solo en el job
   `provenance`, que corre tras el merge: un PR con `VERSION=0.1.0-rc1` coherente pasa el
   gate y luego bloquea todos los deploys. *(cicd #1)*

### 3b. Deriva del registro

8. `tasks.md` 7.5 está marcada `[x]` afirmando que el panel muestra los enlaces — el
   historial demuestra que ese check llegó **después** de la retractación de D11.
   *(architect #1)*
9. **D6 contradice a D11**: dice que los valores llegan al HTML "ya convertidos en `href`".
   *(architect #2)*
10. **D8** describe "commit corto y completo" y una forma incondicional; `commitFull` ya no
    existe. *(architect #3)*
11. **`sdd/roadmap.md` sigue afirmando que el panel enlaza al PR, al commit y al run.**
    *(architect #4)*
12. El **caché de 30s** del route handler no está registrado en `design.md`, cuando todos
    los demás hallazgos del panel sí lo están. *(architect #5, qa #3)*
13. **R4 tiene dos criterios numerados "7."** y ningún "9.", así que las citas `[R4.7]` de
    `tasks.md` son ambiguas. *(architect #7, qa #2)*
14. `docs/app-version-visibility.md` y `RUNBOOK §6.4` prometen filas de Commit y fecha que
    hoy no se renderizan. Se resuelve con 3a.1 o corrigiendo ambos docs. *(security #6)*
15. **R5 necesita un criterio que registre que `/deployment/version` relaya públicamente la
    versión del backend**, y la fila de riesgos de `design.md` que dice que `/version` solo
    es alcanzable por túnel SSH hay que corregirla. R5.2 dice literalmente lo contrario.
    *(security #4)*
16. Comentario factualmente falso en `backend-tests.yml`: los `services:` de Actions
    arrancan antes de cualquier step, así que poner `ci-checks` primero no ahorra montar
    Postgres. *(cicd #2)*

### 3c. Cuestión abierta para el usuario (no defecto)

17. `OPERATOR_SURFACE_IS_AUTHENTICATED` vive en `features/shell/components/provenance.ts`.
    El architect sostiene que una política de divulgación pertenece a `lib/config`. El
    referente que cita regula lecturas de `process.env`, y la constante no lee ninguna, así
    que queda como decisión de diseño, no como incumplimiento. *(architect #6)*

### 3d. Riesgo descartado

El pineado `actions/setup-python@5fda3b95…` **es correcto** (v7.0.0, SHA verificado contra
la API, y es la tag más reciente). El riesgo que anota la entrada 2 no se materializa.

---

## 1. Verificación de la identidad horneada sobre la VM (tarea 7.6)

- **Fase**: run (sección 7)
- **Tipo**: `deferred` — el flujo puede reanudarla, no necesita decisión humana
- **Qué y por qué**: R1.2/R1.4/R1.5/R2.1 piden comprobar sobre el entorno desplegado que
  `docker inspect` muestra los labels OCI en las **dos** imágenes, que `curl` a `/version`
  por túnel SSH devuelve el bloque, y que la cadena coincide con el badge de
  `https://autohostai.digitalsec.work`. Requiere un deploy real, que solo ocurre al mergear
  a `main`.

  **Lo verificable sin desplegar ya está hecho y consta en el registro de la sección 3**:
  build real de la imagen `prod` del backend con build-args (labels presentes, `ENV`
  horneadas, `GET /version` por HTTP devolviendo los seis campos), imagen construida sin
  build-args arrancando y devolviendo `null` en los seis, y build real del frontend `prod`
  confirmando que las server-only quedan en la imagen y que nada server-only aparece en
  `.next/static` ni en el HTML servido.

  Lo que **no** se puede saber hasta el deploy: que el job `provenance` alimenta de verdad
  a los dos builds en un run real de Actions, y que el badge en producción muestra la misma
  cadena que `/version`.
- **Comando de reanudación**: tras el merge y el deploy verde, `/sdd:review app-version-visibility`

---

## 2. El gate `backend-tests` en verde en el Pull Request (tarea 7.7)

- **Fase**: run (sección 7)
- **Tipo**: `deferred`
- **Qué y por qué**: R2.13 exige que el gate esté verde en el PR. Localmente se han
  reproducido **todos** sus pasos con éxito (`make ci-checks`, `alembic upgrade head`,
  `alembic check`, la suite completa: 1203 pasados / 35 saltados), pero el gate en sí solo
  corre cuando el PR existe.

  Un detalle a vigilar en ese primer run, porque es nuevo y no se puede probar en local: el
  step `actions/setup-python@5fda3b95…` (v7.0.0) que se añadió para garantizar `tomllib`.
  Si ese pineado fuese incorrecto, el gate fallaría en cada PR.
- **Comando de reanudación**: abrir el PR y comprobar el run; luego
  `/sdd:review app-version-visibility`
