# Blocked / pending — seed-data-demo-extension

Abierto por el panel de `/sdd:review` del 2026-08-17. El veredicto fue **FAIL**: no se
escribió `LOCAL_VERIFIED` ni `READY_FOR_PR`, y `STATE.md` sigue en `ACTIVE`.

La causa raíz de las tres primeras entradas es la misma: **la rama no tiene ni un commit y su
HEAD (`6c3feab`) es antecesor de `main`**, que ha avanzado 12 commits (`messaging-ai` y
`cleaning-completion-evidence-gatherer`). Todo lo verificado hasta ahora —suite en verde
incluida— se verificó contra una base que ya no es el objetivo de integración.

**Re-revisado el 2026-08-17 (segunda pasada, panel completo de siete revisores).** El estado no
se movió: HEAD sigue siendo `6c3feab` y la rama sigue sin commits. La distancia sí ha crecido
mientras esperaba: tras `git fetch`, `origin/main` está en **`b42ddec`** y HEAD es antecesor
suyo **13** commits por detrás (el decimotercero es el archivado de `messaging-ai`). Las
entradas 1-4 se confirmaron una a una, la 7 es nueva, y la 5 la contradicen dos revisores de
esta pasada. Lo que aporta la segunda pasada, y que conviene no volver a pagar:

- **La suite está verde y eso no acredita nada.** Medido en esta pasada: 6672 passed,
  39 skipped, 0 failed, y `alembic check` sin operaciones. Pero el contenedor del worktree
  monta el `backend/` de la rama, es decir el `cleaning/` de **antes** del refactor de
  `cleaning-completion-evidence-gatherer`. La suite verde es la prueba de la entrada 3, no su
  refutación: verifica el árbol contra la base vieja.
- **El panel no puede certificar esta rama, y no es culpa del panel.** Arquitectura, QA,
  tenancy, i18n y CI/CD dieron PASS y seguridad y documentación una constatación cada una
  — todos contra la base de la rama, que es lo único que hay en disco. Ninguno de esos PASS
  sobrevive al rebase sin repetirse, porque la entrada 1 rompe en rojo el ciclo de la limpieza.

**El problema es estructural y no textual, y por eso las entradas no se cierran una a una**: el
change se implementó y se verificó entero contra una base que ya no existe, y nunca se
commiteó. Las entradas 1, 2 y 3 son el mismo hecho visto desde tres sitios, y la 4 y la 7 son
deriva de `main` y del árbol que el rebase vuelve a poner sobre la mesa. El orden es
**rebasar → arreglar la firma → commitear → re-verificar → re-revisar**; atacar las entradas en
cualquier otro orden repite el trabajo.

---

## 1. `CompleteCleaningTaskUseCase` se llama con la firma que `main` ya no tiene

- **phase**: review
- **type**: deferred
- **what & why**: `cleaning-completion-evidence-gatherer` (en `main`, commit `73d3ae9`) cambió
  `CompleteCleaningTaskUseCase.__init__` a `(*, evidence: CompletionEvidenceGatherer, **kwargs)`
  y retiró los cuatro repositorios que antes recibía. `backend/app/cli/seed_demo.py:1184-1190`
  sigue pasando `completions=`, `templates=`, `photos=` e `incidents=`; caen en `**kwargs`, que
  `_TaskLifecycleBase.__init__` tampoco acepta. Al rebasar sobre `main` esto es un
  `TypeError` en el cierre de la limpieza de la demo, y con él caen en rojo al menos
  `test_the_cleaning_is_walked_by_the_cleaner_and_closes_with_its_evidence`,
  `test_a_second_run_uploads_no_seventh_photo` y los demás tests que recorren el ciclo completo.
  Verificado por dos revisores del panel de forma independiente y comprobado a mano contra
  `git show main:backend/app/cleaning/application/use_cases.py:896`. Afecta a R3.1 y R3.4.
- **exact resume command**: rebasar la rama sobre `main`, construir un
  `CompletionEvidenceGatherer(...)` y pasarlo como `evidence=`, y después
  `/sdd:review seed-data-demo-extension`

## 2. El change no tiene ningún commit

- **phase**: review
- **type**: deferred
- **what & why**: las ~2.300 líneas del change están sin commitear en el árbol de trabajo, y
  `sdd/changes/seed-data-demo-extension/` está sin seguir. `mark-local-verified` fija
  `implementation_sha = git rev-parse HEAD`, así que certificaría `6c3feab` —un commit que no
  contiene nada de este trabajo— y `mark-ready` heredaría ese ancla. Por eso el gate no se
  escribió. El commit tiene que existir **antes** de volver a pasar por review, y la revisión
  posterior al rebase es la que debe quedar anclada.
- **exact resume command**: commitear la implementación (`feat(seed-demo): …`) sobre la rama
  rebasada y después `/sdd:review seed-data-demo-extension`

## 3. La verificación de la sección 10 de `tasks.md` no acredita lo que dice

- **phase**: review
- **type**: deferred
- **what & why**: las casillas 10.1-10.6 están marcadas y la suite corre en verde en este
  worktree (6672 passed, 39 skipped, `alembic check` sin operaciones), pero contra la base
  antigua: el contenedor monta el `cleaning/` de antes del refactor. Nadie ha ejecutado
  `make bootstrap && make seed-demo` contra un stack que lleve
  `cleaning-completion-evidence-gatherer`, así que ni las nueve filas de
  `property_state_transitions` ni «la limpieza cierra» están acreditadas contra lo que se va a
  mergear.
- **exact resume command**: tras resolver la entrada 1, repetir 10.1-10.6 sobre el árbol
  rebasado y después `/sdd:review seed-data-demo-extension`

## 4. El censo de la regla 11 no nombra al seed como escritor de `incidents.title`/`description`

- **phase**: review
- **type**: decision
- **what & why**: el change añade un escritor a dos columnas censadas y no añade ninguna fila al
  censo (`git diff -- sdd/steering/security.md` no toca la tabla). D6 argumenta bien que el seed
  **no necesita la excepción 2** porque escribe constantes versionadas — pero «no necesita la
  excepción» no es «no necesita fila». En la base de la rama la fila delega los futuros creadores
  a la **excepción 2**, que es justo la que D6 dice que un escritor nuestro no puede invocar; y en
  `main`, `messaging-ai` **partió** esa fila por escritor y borró esa cláusula abierta, dejando
  `incidents.title` con contrato por escritor (`security.md:130-132`) y una advertencia explícita
  en `:118`: «una columna viva puede ganar escritores sin que la fila lo note, que es la forma
  silenciosa de que este censo mienta». Los tres títulos del seed no son miembros de
  `CONVERSATION_INCIDENT_TITLES`, así que su contrato es un tercero distinto: forma cerrada por
  constantes del módulo, no impuesta en código. **Necesita decisión de Jose**: declarar el
  contrato del seed como forma cerrada por disciplina (como `auth-account-recovery` con
  `STORED_RECOVERY_*`) o imponerlo en código en `ReportIncidentUseCase`, cuyo `title: str` hoy no
  restringe nada.
- **exact resume command**: decidir el contrato, añadir la(s) fila(s) al censo tras el rebase
  (y actualizar «Dieciséis columnas, dieciocho filas») y después
  `/sdd:review seed-data-demo-extension`

## 5. La ampliación de la excepción 4 de la regla 9 no se acota como sus hermanas

- **phase**: review
- **type**: deferred
- **what & why**: el párrafo que concede (`sdd/steering/security.md:73`) funda la ampliación en
  «es un comando de línea de órdenes», propiedad que **cualquier** CLI satisface, y —a diferencia
  de la segunda y la tercera excepción (`:57`, `:63`)— no incluye la frase «este razonamiento no
  es un criterio reutilizable». El párrafo de cierre (`:75`) sí prohíbe la inferencia, así que los
  dos están en tensión y quien cite `:73` tiene una auto-exención lista para cualquier comando de
  soporte. Sección 3 de `tasks.md`, que ningún panel de sección revisó.
- **exact resume command**: estrechar el fundamento a «no hay decisión humana detrás de *esta*
  clasificación» y añadir la frase de no-reutilización, y después
  `/sdd:review seed-data-demo-extension`

## 6. Barridos menores de redacción y cobertura

- **phase**: review
- **type**: deferred
- **what & why**: cuatro apuntes acotados, ninguno bloqueante por sí solo:
  **(a)** `design.md` D13 dice que la validación de zona horaria «va a `build_plan`»; está —
  correctamente, y por la razón que D10 da— en la fase de precondiciones de `apply_plan`
  (`backend/app/cli/seed_demo.py:628-639`). `build_plan` sigue sin tocar la base de datos, así que
  el código es coherente y lo que está obsoleto es la prosa de D13.
  **(b)** `docs/seed-demo.md` explica los objetos huérfanos y que nadie los limpia, pero no dice
  que `docker compose down -v` **no** los toca, que es lo que D11 declara y lo que un operador
  hará al buscar un borrón y cuenta nueva.
  **(c)** R1.6 («no escribir `incidents` por ninguna vía que no sea un caso de uso de
  `maintenance`») se cumple hoy sólo por auditoría de código: no hay test que se ponga rojo si
  alguien añade una segunda vía de escritura en el módulo.
  **(d)** R5.3 («fallar en voz alta si el actor no satisface lo que `AssignIncidentUseCase`
  exige») es hoy vacua: el propio docstring de `seed_demo.py:995-1000` dice que el caso de uso no
  exige nada del rol del actor, así que la rama negativa no es alcanzable ni testeable.
  (El panel de QA de la segunda pasada confirmó (d) por su cuenta.)
- **exact resume command**: `/sdd:review seed-data-demo-extension`

## 7. El runbook de dev sigue documentando el contrato de consola de cinco recuentos

- **phase**: review
- **type**: deferred
- **what & why**: hallazgo **nuevo** de la segunda pasada, del revisor de documentación y
  comprobado a mano. `infra/environments/dev/RUNBOOK-seed-demo.md` describe la salida del comando
  con **cinco** recuentos en tres sitios —«imprimiendo los cinco recuentos a cero» (`:32`), el
  ejemplo literal `seed-demo: created 2 users, 2 properties, 3 guests, 3 reservations,
  1 checklist_templates` (`:94`) y «Los cinco tipos se imprimen **incluso a cero**» (`:97`)—, y
  D12 lo sube a **ocho**. Es el procedimiento que un operador sigue en la VM de dev, es decir
  justo el camino `S3` que este change estrena, así que el ejemplo desactualizado se lee como
  «faltan recuentos» o «el comando no sembró». No lo cazó la sección 9 porque las tareas 9.1 y
  9.2 nombran `docs/seed-demo.md`, `.env.example` y el `README.md` de raíz, y este fichero vive
  en `infra/`. Su SQL de limpieza **sí** está bien: ya borra `incidents`, `cleaning_photos`,
  `cleaning_checklist_completions` y `property_state_transitions`. Afecta a R4.4 / D12.
- **exact resume command**: actualizar los tres sitios de
  `infra/environments/dev/RUNBOOK-seed-demo.md` a los ocho recuentos tras el rebase y después
  `/sdd:review seed-data-demo-extension`
