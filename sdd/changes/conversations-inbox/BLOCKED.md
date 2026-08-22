# Blocked / pending — conversations-inbox

## 1. Dos especificaciones vivas para esta feature: la rama remota es de Marta

- **phase**: ship
- **type**: decision
- **what & why**: al ir a publicar, `origin/sdd/conversations-inbox` resultó **no ser
  el bootstrap de esta línea de trabajo**, sino una línea independiente de **Marta
  Reyes Ojeda**, con su propia especificación y sin implementar. No se publicó nada:
  el remoto sigue en `98815ac` y no existe ningún PR.

  **Los hechos, para que nadie los reconstruya a mano:**

  | | Línea local (esta) | Línea de Marta (remoto) |
  |---|---|---|
  | Commits | 17, ninguno publicado | 5, publicados |
  | `/sdd:new`, `design`, `tasks` | 2026-08-19 | 2026-08-22 |
  | `/sdd:run` | 2026-08-21 | — |
  | Requisitos | R1–R7 | R1–R6 |
  | Decisiones | D1–D22 | D1–D9 |
  | Tareas | 42, secciones en español | 36, secciones en inglés |
  | Estado | `READY_FOR_PR`, review aprobada | `ACTIVE` |
  | Implementación | 678 tests en verde, build limpio | ninguna |

  Sus commits incluyen correcciones de gate («CHANGES REQUESTED») en design y en
  tasks, así que su especificación pasó por sus puertas de revisión.

  **La causa raíz es de esta línea, no de la suya**: hizo tres días de planificación
  y uno de implementación **sin publicar nunca la reclamación de rama**. La regla 10
  compartida dice que la rama remota `sdd/<feature>` es la reclamación del equipo; al
  no existir, Marta no tenía forma de ver que la feature estaba en marcha y la
  arrancó de cero. Cualquier arreglo de proceso va ahí: publicar la rama al crear el
  change, no al publicar el PR.

  **Qué NO se hizo, y por qué queda para una persona:**
  - No se empujó: sería non-fast-forward (17 por delante, 61 por detrás).
  - No se forzó: `--force` habría borrado sus 5 commits.
  - No se rebasó sobre la suya: reconciliaría en silencio dos especificaciones
    distintas, y **el veredicto de review no transfiere** — verifica la
    implementación contra R1–R7/D1–D22, no contra R1–R6/D1–D9. Sobre sus requisitos
    habría que revisar de nuevo, y es previsible que aparezcan huecos reales porque
    el código no se escribió contra ellos.
  - No se renombró para publicar aparte: dejaría dos changes vivos para la misma
    entrada de roadmap.

  **Qué falta**: que Jose y Marta decidan cuál de las dos especificaciones se
  queda, y si la implementación local se reutiliza contra ella, se rehace, o se
  descarta. Es una decisión de producto y de equipo, no una fusión mecánica, y el
  change es de ella.

  **Nota sobre el estado local**: `STATE.md` dice `READY_FOR_PR` con
  `local_review: APPROVED`, y es cierto **de esta línea**: la implementación está
  verificada contra la especificación local. Lo que no es cierto es que sea *la*
  bandeja de conversaciones del proyecto. Este `BLOCKED.md` no vacío es lo que impide
  que `/sdd:ship` la publique, y el commit que lo añade invalida a propósito el
  sufijo autorizado del ancla: mientras esto no se resuelva, el change no es
  publicable.
- **exact resume command**: decisión humana; después, `/sdd:ship conversations-inbox`
  (si se queda esta línea) o `/sdd:review conversations-inbox` (si se reconcilia
  contra la especificación de Marta).

## 2. Dos límites declarados en D22 que sobreviven a esta revisión

- **phase**: review
- **type**: deferred
- **what & why**: quedan escritos en `design.md` (D22) y no resueltos, los dos con
  dirección de arreglo:
  1. La recuperación del borrador está acotada al montaje de la página: un 401 —o
     navegar a otra ruta del workspace y volver— desmonta `ConversationsView` y pierde
     el mapa, así que el compositor vuelve limpio. Pide sostener el estado por encima
     de `AuthGuard` o del cuerpo de la página: alcance de la superficie de sesión.
  2. **Puede llegarle al huésped**: si el envío falla en el cliente *después* de que el
     servidor escribiera (timeout), `onError` solo invalida en un 409, así que el hilo
     no se re-consulta, la respuesta entregada es invisible y la operadora reenvía. La
     premisa de D18 («de un 500 no hay nada nuevo que aprender») es cierta para un 500
     del servidor y falsa para un timeout. Pide clave de idempotencia en
     `POST /messages` o re-consultar ante cualquier fallo de envío.
- **exact resume command**: `/sdd:review conversations-inbox`

## 3. Hueco de la superficie de sesión, ajeno a este change

- **phase**: review
- **type**: decision
- **what & why**: el `QueryClient` es un singleton por navegador
  (`lib/query/query-client.ts`) y **nadie llama a `clear()` al hacer logout**
  (`lib/auth/auth-provider.tsx` descarta tokens y usuario, nada más). Un cambio de
  operador en la misma pestaña puede servir a un rol menos privilegiado los datos
  cacheados del anterior **sin ninguna petición**. Las claves llevan ámbito de tenant,
  así que la exposición es mismo-tenant/distinto-rol, no cruce de tenants.
  No lo introduce ni lo amplía este change.

  **Registrarlo como hueco de la superficie de sesión, no como deuda de
  `conversations-inbox`**: si se queda aquí, se archiva con esta feature y desaparece.
  No tiene regla que citar en `steering/security.md` (la de aislamiento es de backend),
  así que necesita casa propia: una entrada de roadmap o de spec contra la superficie de
  autenticación, nombrando el camino concreto.
- **exact resume command**: decisión humana sobre dónde registrarlo
