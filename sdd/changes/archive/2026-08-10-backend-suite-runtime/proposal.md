# Proposal: backend-suite-runtime

## Why

El check `backend-tests` tarda hoy **16m 11s** cuando el diff toca el backend, y el **96 %** es un
solo paso: `pytest -q -rs` = **15m 34s** (medido el 2026-08-09 sobre el run `31336428305`; los tres
`alembic`, el checkout, `uv sync` y el arranque de containers suman 37s entre todos). La cifra que
`sdd/specs/backend-ci.md` declara —«~6m15s la suite, ~7m05s el workflow», fechada el 2026-08-03— está
**obsoleta por 2,5×** en seis días.

Eso no es una degradación puntual, es una tendencia con causa medible: la nota de roadmap contó
**201** funciones de test pidiendo la fixture `test_engine` el 2026-08-03, y hoy hay **397** funciones
que piden `db_session`/`test_engine` directamente más **487** fixtures que dependen de ellas, sobre
2 258 definiciones de test. La fixture es *function-scoped* y hace `create_all` + `drop_all` del
esquema **completo** en cada test (`backend/tests/conftest.py:75-96`), así que el coste crece
linealmente con cada test que toca base de datos — y quedan por delante `maintenance`, `messaging-ai`
y `revenue`, que son módulos enteros de dominio.

**Medición preliminar en local (2026-08-09, este worktree, `pytest -q --durations=25`)**, que apunta en
la misma dirección y acota lo que `/sdd:design` tiene que buscar: **5 329 pasados + 35 omitidos en
606,71s (10m 06s)** — los 2 258 `def test_` se parametrizan a 5 364 casos, a ~113ms de media. Y **no
hay ningún test caliente**: el más lento tarda 3,81s y los 25 más lentos suman ~35s, el **5,8 %** del
total. El tiempo está repartido finito entre miles de tests, que es la forma de un **coste fijo por
test** y no la de unos pocos tests lentos; varias entradas de ese top-25 son `setup` de fixture
(0,75s–1,87s), que es donde corre el `create_all`. Es una sola ejecución y por eso no sustituye a R1,
pero ya descarta la hipótesis «hay tres tests que se llevan la tarde». El runner de GitHub es ~1,5×
más lento que esta máquina (15m 34s frente a 10m 06s).

Hay además un límite duro a la vista: el job declara `timeout-minutes: 20`, así que al ritmo de los
últimos seis días el propio tope se alcanza en semanas y el gate empieza a reportar rojo por reloj y
no por defecto. El margen actual es de **4m 26s**.

Esta es, como dice la entrada del roadmap, **la única palanca que ayuda en los PR que sí tocan
backend**: el gate condicional de `ci-backend-tests-conditional-gate` (ya archivado) solo ahorra en
los que no.

Entrada de roadmap: `backend-suite-runtime` · nota larga en `sdd/roadmap/backend-suite-runtime.md`.

## What changes

Después de este change la suite del backend se ejecuta en CI en una fracción del tiempo actual, sin
recortar lo que verifica y sin debilitar el aislamiento por proceso que `specs/backend-ci.md` exige;
el repositorio lleva un **presupuesto de tiempo versionado** que hace visible la reincidencia en el
propio check en lugar de descubrirla seis días tarde; y la cifra de coste de la spec vuelve a ser una
medición fechada y reproducible. El **cómo** —dejar de crear y tirar el esquema por test (esquema una
vez + rollback por test), paralelizar con `pytest-xdist`, o ambas— lo decide `/sdd:design` con la
medición de R1 en la mano, no este proposal: hoy no sabemos cuánto del tiempo es esquema y cuánto son
los tests, y elegir remedio antes de saberlo es exactamente lo que produjo la cifra obsoleta.

## Requirements

### R1 — Saber en qué se va el tiempo antes de tocar nada

**As a** responsable del pipeline, **I want** un reparto medido del tiempo de la suite por causa,
**so that** el remedio se elija sobre datos y no sobre el sospechoso más plausible.

Acceptance criteria:

1. WHEN se inicia la implementación, THE SYSTEM SHALL producir una medición **fechada** del tiempo
   de la suite en CI y en local, obtenida con un procedimiento descrito en el change y repetible por
   cualquiera.
2. THE SYSTEM SHALL atribuir ese tiempo a causas nombradas —como mínimo: creación/borrado de esquema
   por test, ejecución de los tests propiamente dicha, y arranque/parada de la sesión— y cuantificar
   cada una.
3. IF la medición no consigue atribuir al menos el 80 % del tiempo a causas nombradas, THEN THE
   SYSTEM SHALL registrar esa laguna y no dar por elegido ningún remedio hasta cerrarla.

### R2 — La suite baja de tiempo en CI, y se demuestra

**As a** desarrollador que abre un PR que toca backend, **I want** la señal del gate en pocos
minutos, **so that** la revisión no se planifique alrededor de un cuarto de hora de espera.

Acceptance criteria:

1. WHEN el diff toca el backend y la suite se ejecuta completa en CI, THE SYSTEM SHALL completar el
   paso `pytest` en **≤ 5m 00s**, medido como mediana de **3 ejecuciones consecutivas** sobre la
   misma referencia.
2. THE SYSTEM SHALL registrar la cifra alcanzada, fechada y con el paso dominante identificado, en
   `sdd/specs/backend-ci.md`, sustituyendo la de 2026-08-03.
3. IF el objetivo de 5m 00s no se alcanza, THEN THE SYSTEM SHALL registrar el techo medido y su causa
   y **no** declarar el requisito cumplido — la cifra objetivo se renegocia con el usuario, no se
   redondea a la baja.

### R3 — Lo que la suite verifica y su aislamiento quedan intactos

**As a** quien confía en el check como evidencia, **I want** que la suite acelerada verifique
exactamente lo mismo, **so that** el ahorro no se pague con cobertura o con inestabilidad.

Acceptance criteria:

1. WHEN la suite se ejecuta después del change, THE SYSTEM SHALL recolectar y pasar el **mismo
   conjunto de tests** que antes: mismo recuento de recolectados y mismo recuento de omitidos, con
   los motivos que `-rs` ya deja en el log.
2. THE SYSTEM SHALL conseguirlo **sin** marcar tests como `skip`/`xfail`, sin reducir parametrizaciones
   y sin excluir ficheros: recortar lo verificado no es acelerar.
3. THE SYSTEM SHALL conservar el aislamiento que `specs/backend-ci.md` exige — bases de datos
   desechables por ejecución (`<db>_test_<pid>`, sufijo fijable con `PYTEST_DB_SUFFIX`) y borradas al
   cerrar la sesión — también cuando **dos ejecuciones concurren sobre el mismo PostgreSQL**, que es
   el caso real de dos worktrees con sus stacks levantados.
4. WHERE la solución introduzca paralelismo entre procesos, THE SYSTEM SHALL dar a **cada worker** su
   propia base de datos desechable y demostrar que ningún test depende del orden ni del worker que le
   toque.
5. THE SYSTEM SHALL demostrar estabilidad con **3 ejecuciones consecutivas verdes**, sin fallos de
   tipo `attached to a different loop` ni `another operation is in progress` — los que el docstring de
   `test_engine` documenta que el diseño actual evita y que cualquier cambio de ámbito puede
   reintroducir.

### R4 — Un presupuesto de tiempo que hace visible la reincidencia

**As a** responsable del pipeline, **I want** que superar el tiempo acordado se vea en el propio
check, **so that** la próxima deriva no tarde seis días y 2,5× en descubrirse.

Acceptance criteria:

1. THE SYSTEM SHALL declarar el presupuesto de tiempo de la suite como **dato versionado en el
   repositorio**, no como una cifra en prosa ni como un ajuste de la UI de GitHub.
2. WHEN la suite se ejecuta en CI, THE SYSTEM SHALL comparar su duración con ese presupuesto y, si lo
   supera, emitir una señal **visible y no ignorable** en el resultado del check, nombrando la cifra
   medida y la declarada.
3. IF la duración no se puede medir, THEN THE SYSTEM SHALL decirlo explícitamente en el resumen del
   check y no degradar a un verde silencioso.
4. THE SYSTEM SHALL respetar el invariante de `specs/backend-ci.md`: el check `backend-tests` se
   **sigue reportando siempre**, y el presupuesto no puede introducir ninguna ruta en la que deje de
   publicarse.

> Queda para `/sdd:design`, y se anota aquí para que no se decida por omisión: si superar el
> presupuesto pone el check **en rojo** o solo emite un aviso destacado en el resumen. Rojo es un gate
> de verdad pero convierte una regresión de rendimiento en un bloqueo de merge; aviso no bloquea pero
> se ignora. La decisión es del usuario.

### R5 — El guardián de orden de errores que hoy no guarda nada

**As a** quien depende de que un error de dominio devuelva su status HTTP, **I want** que el test que
protege el orden de `_MAPPING` compruebe la implicación correcta, **so that** deje de ser un test
vacío que aparenta cobertura.

Acceptance criteria:

1. WHEN se evalúa `backend/tests/cleaning/test_errors.py::test_subclasses_come_before_their_base`,
   THE SYSTEM SHALL comprobar que **ninguna fila posterior de `_MAPPING` es clase base de una
   anterior** — es decir, que ninguna subclase queda después de su base, que es lo que la resolución
   *primera coincidencia gana* exige. Hoy comprueba la implicación al revés y por eso es vacío.
2. THE SYSTEM SHALL demostrar el test **en rojo** con una fila construida a propósito (una subclase
   colocada después de su base) antes de darlo por bueno, según la regla 13(c) de
   `steering/security.md`.

## Out of scope

- **Los 37s restantes del workflow** (containers, checkout, `uv sync`, los tres `alembic`). Son el
  4 % y optimizarlos antes que el 96 % es ruido.
- **Tocar el gate condicional** de `ci-backend-tests-conditional-gate` (detección de área, camino
  corto, consolidación). Está archivado y verificado; este change acelera la suite, no rediseña el
  gate.
- **Hacer obligatorio el check** `backend-tests`: sigue bloqueado por el plan de GitHub del
  repositorio privado (`403: Upgrade to GitHub Pro`), ya documentado en `specs/backend-ci.md` §Estado.
- **Runners más grandes o de pago**: la palanca de este change es el trabajo que hace la suite, no el
  hardware que lo ejecuta.
- **La suite del frontend** (`frontend-tests`, `specs/frontend-ci.md`), que tiene su propio workflow y
  su propio coste.
- **Reescribir tests por calidad, cobertura o estilo**: solo se toca lo que el rendimiento exija, más
  el caso puntual de R5 que la nota de roadmap dejó apuntado para este momento.
- **E2E de Playwright**, que ni existe todavía ni corre en este workflow (llega con
  `hardening-release`).

## Affected specs

- `sdd/specs/backend-ci.md` — modificar: §Coste (cifra fechada nueva y procedimiento de medición),
  §Aislamiento entre ejecuciones concurrentes (si el modelo de fixtures o el paralelismo cambian lo
  que ahí se garantiza), y un requisito nuevo para el presupuesto de R4.
- `sdd/steering/testing.md` — posible: la convención de fixtures compartidas en `conftest.py` si el
  modelo de aislamiento por test cambia (esquema una vez + rollback en lugar de `create_all`/
  `drop_all` por test). Se decide en `/sdd:design`.
