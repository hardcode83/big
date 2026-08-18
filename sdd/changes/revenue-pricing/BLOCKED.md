# Blocked — revenue-pricing

## 1. Antes de la sección 8 hay que rebasar sobre `main`

- **fase**: run (sección 8)
- **tipo**: deferred — el flujo lo reanuda solo
- **qué y por qué**:
  Dos motivos independientes, y el primero es el que muerde:

  1. **El `security.md` de este worktree está muerto.** Aquí dice «Trece columnas»; en `main`
     dice «Dieciséis columnas, veinte filas», con un párrafo nuevo que separa el recuento de
     columnas del de filas. Las tareas 8.1 y 8.2 citan la redacción vieja, así que escribirlas
     contra este árbol es parchear una copia que ya no existe.
  2. **La tarea 8.5 lo pedía explícitamente**: «rebasar sobre `main` después de que mergee»
     el PR #98 (`compose-stacks-diagnostic`), que toca el mismo `README.md`. #98 **mergeó el
     2026-08-17** (verificado con `gh pr view 98`: `MERGED`).

  Ojo al orden: el rebase exige el árbol limpio, así que **primero el commit de las secciones
  1-7** — que hace falta igualmente antes de `/sdd:review` por la lección
  `review-must-check-implementation-is-committed`.

- **comando de reanudación**: `/sdd:run revenue-pricing 8`
