# BLOCKED — notification-writers-gap

## 1. `test_rule11_ownership.py` está en rojo en `main`, y no es de este change

- **phase**: run (medido al tomar la cifra de partida de la tarea 8.1, 2026-08-29)
- **type**: decision

**Qué y por qué.** Antes de tocar una sola línea, la suite de partida da **un fallo**:
`backend/tests/test_rule11_ownership.py::test_no_block_outside_the_table_declares_who_writes_a_sink`.
El infractor único es `sdd/roadmap.md:187`, la entrada `guest-scheduled-comms`, que nombra
un sumidero de la regla 11 («Aquí la regla 11 muerde: llevan código de acceso») y a la vez
declara quién lo escribe («sus tres tipos **no tienen escritor**») — las dos cosas en el
mismo bloque, que es exactamente lo que el guardián prohíbe fuera de la tabla de
`sdd/steering/security.md`.

**No lo introduce este change, y se comprobó**: `sdd/roadmap.md` está sin modificar en este
worktree (`git status` limpio para ese fichero); la línea entró el 2026-08-28 en el commit
`0537b69` («docs(sdd): nueve entradas de roadmap para la comunicación de campo»); y
`origin/main` —que ya va un commit por delante de esta rama, `46a3658`— **sigue conteniendo
la misma línea sin corregir**, así que `main` está rojo en este test ahora mismo. El
`sdd/changes/` de esta feature no interviene: `EXCLUDED_DIRECTORIES` lo excluye
(`test_rule11_ownership.py:161`) y hay un test que lo fija (`:475`).

**Por qué importa aquí y no se puede ignorar sin decirlo.** La tarea 6.3 de este change
manda «comprobar que `backend/tests/test_rule11_ownership.py` pasa» tras añadir
`pricing/domain/notifications.py` a la fila del contrato vivo, y la 8.1 pide la suite
entera en verde. Con este fallo heredado, ninguna de las dos puede cumplirse literalmente.
Lo que este change **sí** puede demostrar, y hará, es que la lista de infractores sigue
siendo **exactamente esa una** después de sus cambios — es decir, que su edición de la
tabla de la regla 11 no añade ninguno.

**Fuera de alcance de este change**: la entrada de roadmap es de `guest-scheduled-comms`,
que es precisamente la feature a la que este change deriva los tres recordatorios al
huésped (ver «Out of scope» de `proposal.md`). Arreglar la redacción es una edición de una
línea de docs, pero pertenece a quien posea esa entrada, y tocarla desde aquí sería
reescribir el roadmap fuera de `/sdd:archive` (regla compartida 1).

**Decisión que hace falta**: si se corrige la línea 187 en un change/commit propio de docs
antes de que este entre, o si este change hereda el rojo y lo documenta en su Verification.

**Resume command**: `/sdd:review notification-writers-gap`


## 2. El panel de la sección 4 murió por límite de uso y se relanza acotado

- **phase**: run (2026-08-29)
- **type**: deferred

**Qué pasó.** Los **siete** revisores de la sección 4 terminaron con `status: failed`
(`rate_limit`, HTTP 429, «session limit») sin devolver veredicto. Ninguno de sus textos
finales es un resultado: son la frase en la que se cortaron, que es justo el modo de fallo
que hay que mirar en `status` y no en `result`.

**Qué se hizo al reanudar.** Se relanzaron **cinco**: `sdd-architect`, `sdd-security`,
`sdd-qa` (los tres del núcleo, obligatorios) y los de proyecto `sdd-review-tenancy` (la
sección escribe filas dirigidas a una persona, con tres operaciones acotadas por tenant) y
`sdd-review-documentation` (la sección añade docstrings largas, y ese revisor ya encontró
afirmaciones falsas en secciones anteriores).

**Los dos que quedan, y por qué no es un salto silencioso**: `sdd-review-i18n`
(`applies_to: frontend/**`) y `sdd-review-cicd` (`applies_to: infra/**`) no tienen superficie
en esta sección — no se toca ni un fichero bajo `frontend/`, `locales/`, `.github/`, `infra/`
ni `backend/alembic/versions/`. La única comprobación de la sección que sí era del revisor de
CI/CD —barrer el repo por sitios de construcción de `ClassifyIncidentUseCase` que se hubieran
quedado sin los puertos nuevos, porque uno olvidado es un `TypeError` en una ruta de Celery
que la suite podría no alcanzar— **se hizo a mano y consta**: los cuatro sitios reales
(`maintenance/api/dependencies.py:119`, `scheduler/tasks.py:168`, `cli/seed_demo.py:1243`,
`tests/maintenance/conftest.py:106`) pasan ambos puertos, y `tests/scheduler` (57) y
`tests/cli` (201) los ejercitan en verde.

**Resume command**: `/sdd:review notification-writers-gap` — cubre los dos revisores que
faltan a escala de feature, que es la vía que el propio skill señala para un panel
interrumpido.

