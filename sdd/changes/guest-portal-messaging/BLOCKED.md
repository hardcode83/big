# Blocked — guest-portal-messaging

## El guardián de la regla 11 está rojo en `main`, y esta rama lo hereda

- **phase**: ship
- **type**: decision
- **what & why**: la sincronización de la base (merge de `origin/main@92de13da`, 48 commits) dejó
  la suite del backend con **un** fallo:
  `tests/test_rule11_ownership.py::test_no_block_outside_the_table_declares_who_writes_a_sink`,
  por tres bloques de `sdd/specs/access-notifications.md` (líneas 372, 525 y 689).

  **No lo trae este change, y está probado, no supuesto**: extraído `origin/main` con
  `git archive` y corrida sobre él la propia detección del guardián (`_offending_blocks` con
  `_is_excluded` y `DECLARED_EXCEPTIONS` aplicados), da **3 infractores en `main` puro y los mismos
  3 en esta rama**. Los introdujo el archivado de `notification-writers-gap` (`f86a83f`,
  2026-08-30). Ni `sdd/specs/access-notifications.md` ni `backend/tests/test_rule11_ownership.py`
  difieren de `main` en esta rama (comparado por hash de blob, no por `git diff --quiet`, que
  bajo `rtk` devuelve un veredicto falso).

  **Por qué `main` está verde en CI y rojo en local**: `backend-tests.yml` gatea la suite con
  `case "$f" in backend/* | .github/workflows/backend-tests.yml)`, y el guardián no lee nada de
  `backend/` — escanea `sdd/**` y `docs/**`. Un commit de archivado sólo toca prosa, así que la
  suite no corre. Run 33409418091 de `main`: `backend-tests-suite` **skipped**. El análisis
  completo y la salida propuesta quedan en `design.md` § Roadmap candidates.

  **Por qué bloquea a esta feature**: su PR **sí** toca `backend/**`, así que el gate sí correría
  y la PR saldría roja por un defecto ajeno. Abrirla así reparte el coste al azar y deja a quien
  revise creyendo que el rojo es de este change.

  **Decisión tomada con Jose el 2026-08-31**: parar el ship y **arreglar el guardián primero**, en
  vez de abrir la PR documentando el rojo. Esta feature espera.

  Estado en el que queda todo lo demás, para que nadie lo rehaga: el merge de la base está
  resuelto y **sin publicar** (`README.md`, `sdd/project.md` y `sdd/roadmap.md` resueltos a mano;
  los tres se quedaron con la versión de `main` salvo la cláusula del portal del README y una
  frase de medición en `project.md`). Se arregló además una colisión que git no marca como
  conflicto: `main` añadió la revisión `e5c9b1f47a28` y la nuestra (entonces `f3c7a2b81d54`, hoy `80ea2e544b36`) colgaba del
  mismo padre, dejando dos cabezas de Alembic y 6 tests de migración en rojo; re-encadenada la
  nuestra detrás de la de `main`, una sola cabeza. Verificación tras el merge: backend **9360
  pasan, 1 falla** (el heredado de arriba); frontend **1965 pasan, 1 falla** en los dos ficheros
  que `sdd/project.md` documenta como ENOENT de worktree y que no son de este change.

- **exact resume command**: arreglar el guardián (su propio workflow sin `paths:`, el patrón de
  `api-contract.yml`, más fijar forma y alcance) en un change aparte; después, aquí,
  `/sdd:review guest-portal-messaging` para recertificar sobre el merge ya resuelto y volver a
  `/sdd:ship guest-portal-messaging`.

## Las BD locales que aplicaron esta rama antes del 2026-08-31 hay que recrearlas

- **phase**: review
- **type**: deferred
- **what & why**: al sincronizar la base se re-encadenó esta migración detrás de `e5c9b1f47a28`
  (`main` colgó otra revisión del mismo padre y dos cabezas rompen `tests/test_migrations.py`), y
  en la misma operación **cambió de `revision`**: de `f3c7a2b81d54` a `80ea2e544b36`.

  El cambio de id no es cosmético y lo decidió el panel. La primera versión conservaba el id, y
  QA midió lo que eso provoca: una BD ya sellada con el id viejo le parece a Alembic que está en
  cabeza, así que `upgrade head` **no hace nada** y se salta para siempre el DDL de
  `e5c9b1f47a28` —comprobado sobre la BD de este worktree, sellada en el id viejo y sin
  `notification_logs.read_at` ni sus dos índices—. Ese fallo es **silencioso**, y el panel de
  arquitectura rechazó cerrarlo con documentación: quien no lee el docstring no se entera. Con el
  id nuevo la misma BD falla en alto (`Can't locate revision identified by 'f3c7a2b81d54'`) y obliga a
  recrearla.

  **Ni `main` ni `dev` están afectados** en ninguna de las dos variantes: nunca tuvieron esta
  revisión sellada y la rama no está desplegada. QA verificó sobre BD limpia que el ciclo
  `upgrade`/`downgrade`/`upgrade` pasa entero y en el orden correcto.

  No se recreó ninguna BD desde review porque es report-only y la operación destruye los datos de
  demostración sembrados para 12.6, que ya está hecha y registrada.

- **exact resume command**: en cada worktree que se bajara esta rama antes del 2026-08-31, antes
  de volver a usarla: `make down` borrando volúmenes, `make up`, `make bootstrap`, `make seed-demo`.
  QA dejó además una BD de sondeo `qa_migration_probe` en el postgres de este worktree; se puede
  borrar.
