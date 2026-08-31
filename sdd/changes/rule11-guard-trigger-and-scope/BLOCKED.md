# BLOCKED — rule11-guard-trigger-and-scope

## 1. La sección 4 no puede cerrarse: la suite del backend es inviable en esta máquina

- **Fase**: run
- **Tipo**: `deferred` — el flujo puede reanudarlo solo, no necesita decisión humana nueva
- **Reanudar con**: `/sdd:run rule11-guard-trigger-and-scope 4`

**Qué falta.** Las tareas 4.1 (borrar `backend/tests/test_rule11_ownership.py`), 4.2 (retirar los
dos bind mounts de `docker-compose.yml`) y 4.3 (las cuatro citas vivas de la ruta vieja). La 4.4 ya
está hecha: se adelantó a la sección 3 porque es el target nuevo lo que falsea sus recuentos.

**Por qué está parado, medido y no supuesto.** 4.1 exige medir la suite del backend antes y después
de borrar («misma cifra de partida menos ese fichero, sin fallos nuevos»), y en esta máquina la
suite no termina:

- Tres intentos de la suite completa. Uno lo colapsó el filtro de `rtk` a catorce puntos sin línea
  de resumen; otro murió al 7% al pasar a segundo plano; el tercero salió con **`EXIT=137`**
  (SIGKILL) tras compilar y antes de ejecutar un solo test.
- La causa es memoria, no la suite: `docker system info` da **8,2 GB** para **46 contenedores** de
  **8 proyectos de Compose**. Siete de esos stacks son de otras sesiones vivas y no se tocan
  (norma del proyecto: un worktree ajeno no se apaga).
- Con `frontend`, `worker` y `beat` de **este** stack parados —lo único que es nuestro— la suite
  vuelve a correr, pero a **155 tests en 11 min 48 s** (`tests/notifications`). Extrapolado, la
  suite completa son 2-3 horas por pasada, y 4.1 necesita dos.

**Cómo desbloquearlo.** Basta con que la máquina respire: parar algunos de los otros stacks
(`make down` en sus worktrees, desde sus propias sesiones) o subir la memoria de Docker. Después,
`/sdd:run rule11-guard-trigger-and-scope 4` retoma en 4.1 con las dos medidas que la tarea pide.

**Lo que NO hay que hacer mientras tanto**, porque rompería el árbol sin que ningún test lo diga:
adelantar 4.2. Los dos bind mounts son el único árbol de prosa que ve el guardián viejo desde
dentro del contenedor, así que retirarlos antes de borrarlo lo deja recorriendo nada y en rojo por
una causa que no es la suya. El orden 4.1 → 4.2 no es estético.

**Estado del stack de este worktree**: `frontend`, `worker` y `beat` quedaron **parados** a
propósito para liberar memoria. `make up` los devuelve. La tarea 7.5 (`make down && make up`) los
necesita levantados.

**Consecuencia viva mientras esto siga abierto**: `backend/tests/test_rule11_ownership.py` sigue
existiendo, y con él su entrada transitoria en `SCOPE` (la que se declara a sí misma como
`mientras conviven`). Las dos mueren juntas en 4.1, y hasta entonces la frase de alcance de
`sdd/steering/security.md` la nombra, porque el ancla de rutas lo exige en las dos direcciones.


## 2. La sección 6 no puede ejecutarse en `/sdd:run`: sus evidencias exigen una Pull Request abierta

- **Fase**: run
- **Tipo**: `deferred`
- **Reanudar con**: `/sdd:review rule11-guard-trigger-and-scope` tras `/sdd:ship`, que es lo que
  abre la PR y hace existir los runs

**Qué falta.** 6.1 (registrar el id de run del check sobre un diff de sola prosa y otro de sólo
`backend/**`), 6.2 (el rojo por cada forma que la guardia dice cazar, con su id de run) y 6.3 (verde
sobre la rama fusionada con `main`).

**Por qué no es posible ahora, y no es una excusa sino la forma del disparador.**
`.github/workflows/rule11-ownership.yml` dispara en `on: pull_request: {}` y `push: branches:
[main]`. Empujar la rama de la feature **no produce ningún run**: no hay PR todavía y la rama no es
`main`. Así que los ids que R4.1 y R4.2 piden no existen hasta que `/sdd:ship` abra la Pull
Request. Es un desajuste del `tasks.md`, no del diseño: la sección 6 está redactada como trabajo de
`run` cuando su evidencia sólo puede nacer después de `ship`.

**Lo que sí queda demostrado ya, y conviene no volver a demostrarlo**: que la *función* detecta las
dos formas —markdown y docstring o tirada de `#`— lo prueban las meta-pruebas, y que **el binario**
falla cerrado por sus ocho vías lo verificó el panel de la sección 5 ejecutándolas una a una. Lo que
falta es exclusivamente que **el check run** se ponga rojo y verde donde debe, que es lo que D10
distingue de lo anterior y la única parte que necesita GitHub.

**Orden correcto al retomar**: desbloquear la sección 4 → `/sdd:review` → `/sdd:ship` → registrar
los ids de 6.1-6.3 sobre la PR ya abierta → sección 7.
