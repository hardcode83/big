# BLOCKED — rule11-guard-trigger-and-scope

## 1. La sección 6 no puede ejecutarse en `/sdd:run`: sus evidencias exigen una Pull Request abierta

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
