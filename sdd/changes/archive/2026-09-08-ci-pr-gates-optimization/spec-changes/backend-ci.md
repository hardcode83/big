# Draft de actualización — `sdd/specs/backend-ci.md`

> Preparado durante `/sdd:run` (sección 6, archive prep). **No se ha tocado el spec vivo.**
> `/sdd:archive ci-pr-gates-optimization` consume este borrador y lo aplica a `sdd/specs/backend-ci.md`.

## (a) Estado actual del spec

`sdd/specs/backend-ci.md` ya documenta el patrón de tres jobs
(`backend-tests-detect` / `backend-tests-suite` / `backend-tests`) como el estado vigente de
`backend-tests.yml` — es el **origen** del patrón, no un consumidor de este change. Secciones
relevantes ya presentes:

- "Disparadores y alcance" (líneas 19-37): fija el invariante de reportar siempre el check
  `backend-tests`, la prohibición de `paths:` en `on:`, y la estructura en tres jobs.
- "Detección del área y camino corto" (líneas 39-62): describe la decisión booleana, el
  fail-open ante diff ambiguo, `core.quotePath=false` + `-z`, `--no-renames` y la comparación
  ruta a ruta con `case`.
- "Servicios de los que depende", "Pasos verificados", "Secretos y dependencias", "Aislamiento
  entre ejecuciones concurrentes", "Presupuesto de tiempo de la suite": sin relación con este
  change, no requieren edición.
- El spec **no menciona `pytest-cov`** en ningún punto — no había una afirmación previa que
  corregir sobre cobertura.

## (b) Cambios que el archive debe aplicar

1. Añadir una nota (probablemente en "Disparadores y alcance", o como nueva subsección breve
   tras ella) que registre que el patrón `*-detect` / `*-suite` / `*-tests` de este workflow
   —ya documentado aquí— se ha **replicado** durante `ci-pr-gates-optimization` a los otros
   tres workflows que antes no lo tenían: `frontend-tests.yml`, `compose-ports.yml` y
   `rule11-ownership.yml` (ver sus specs). `backend-ci.md` sigue siendo la referencia
   canónica del patrón; no se duplica su descripción en las otras tres specs, que enlazan
   aquí.
2. Añadir una nota explícita, en la sección "Pasos verificados" o en una nueva subsección
   corta, de que `pytest-cov` **no se invoca en CI**: `backend-tests.yml` ejecuta
   `pytest -q -rs` (línea 85 del spec) sin flags de cobertura, y este change (tareas 1.1/1.2)
   retiró `pytest-cov` de `backend/pyproject.toml` y regeneró `backend/uv.lock` sin dejar
   rastro transitivo. La nota debe dejar constancia de que **este change no introduce
   cobertura real** — no es una capacidad nueva, es la eliminación de una dependencia de dev
   que no se usaba en el pipeline.
3. Sin cambios en "Coste" ni "Estado": el presupuesto de tiempo, el runner de 2 vCPU y la
   limitación de protección de rama no se ven afectados por este change.

## (c) Texto propuesto, listo para pegar

### Inserción en "Disparadores y alcance" (tras la lista de bullets existente, línea 37)

```markdown
### Patrón replicado a otros workflows

- El patrón de tres jobs descrito arriba (`*-detect` / `*-suite` / `*-tests`) es el **origen**
  y la referencia canónica de esta forma en el repositorio. El change `ci-pr-gates-optimization`
  lo replicó a los tres workflows que antes ejecutaban su verificación completa en un único job
  o sin puerta de área: `frontend-tests.yml` (`specs/frontend-ci.md`), `compose-ports.yml`
  (`specs/compose-ports.md`) y `rule11-ownership.yml` (`specs/rule11-ownership-guard.md`). Cada
  spec describe su propia instancia del patrón; esta sección no se repite en las otras tres.
```

### Inserción en "Pasos verificados" (tras el bullet de `pytest -q -rs`, línea 88)

```markdown
- THE SYSTEM SHALL NOT ejecutar `pytest-cov` ni ningún flag de cobertura (`--cov`) en este
  workflow. `pytest -q -rs` corre sin instrumentación de cobertura, y el change
  `ci-pr-gates-optimization` retiró `pytest-cov` de `[dependency-groups].dev` en
  `backend/pyproject.toml` (no se invocaba en CI) y regeneró `backend/uv.lock` en consecuencia.
  Esta nota deja constancia de que **el change no introduce cobertura real**: es la eliminación
  de una dependencia de desarrollo sin uso en el pipeline, no una capacidad nueva.
```
