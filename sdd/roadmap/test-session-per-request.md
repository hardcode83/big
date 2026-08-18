# test-session-per-request

[TECH] **la fixture de tests comparte una sola sesión de BD donde producción abre una por
petición**, y mientras siga así la suite no ejercita el modelo de sesión que sí tiene
producción. `backend/tests/conftest.py` sustituye `get_db_session` por **una única**
`db_session` para todo el test; producción abre una por petición. Consecuencia medida: un test
que autentica —lo que marca la sesión con un tenant— y después golpea una ruta anónima ejecuta
una lectura no scoped sobre una sesión ya marcada, cosa que en producción no ocurre nunca.
`backend/tests/auth/test_recovery_api.py` ya lo documenta como divergencia conocida.

**Por qué es una entrada propia y no trabajo de `rule11-ownership-single-source`** (que se topó
con ello al introducir `require_unmarked_session`, 2026-08-18): el arreglo obliga a revisar el
`commit` de **toda** la suite, no solo de los tests de las lecturas no scoped. Aquel change lo
dejó fuera de alcance a propósito y no lo puso en `BLOCKED.md` —no era trabajo pendiente suyo—
sino aquí.

**Las dos formas fieles se midieron y las dos cuestan más de lo que dan**, que es el dato que
esta entrada arrastra y no hay que volver a pagar:

1. **Una sesión por petición sobre su propia conexión** deja invisibles las filas de setup sin
   commitear: **249 rojos** solo en `auth` y `cleaning`.
2. **Todas las sesiones sobre una conexión compartida** conserva visibles esas filas, pero
   `join_transaction_mode` convierte el `commit()` de cada caso de uso en la liberación de un
   savepoint —un cambio de significado de toda la suite— y rompió tests de concurrencia y
   atomicidad en `scheduler`, `messaging`, `notifications` e `integrations`: **40 rojos**, en
   sitios que no tienen nada que ver con ninguna lectura no scoped.

Así que el alcance honesto no es «cambiar la fixture» sino **decidir qué significa `commit()` en
la suite** y revisarlo módulo a módulo. De ahí `size: L`.

**Lo que NO es la salida**: eximir del guard a las sesiones «de test». Un guard con una puerta
de test no es un guard, y `rule11-ownership-single-source` lo rechazó explícitamente (su D13).
Los tests que hoy conviven con la divergencia lo hacen desmarcando la sesión **en el test**,
nunca en `app/` —`backend/tests/test_session_marking.py` lo prohíbe ahí—, porque en producción
la petición ya habría terminado y la siguiente tendría una sesión nueva.

Valor al cerrarlo: la suite pasaría a ejercitar la sesión-por-petición real, y la divergencia
documentada en `test_recovery_api.py` dejaría de existir en vez de estar anotada.
