# Blocked / pending — conversations-inbox

## 1. Reconciliación pendiente con la línea de Marta (entrega paralela hecha)

- **phase**: ship
- **type**: decision
- **what & why**: `origin/sdd/conversations-inbox` **no es el bootstrap de esta línea**
  sino una línea independiente de **Marta Reyes Ojeda**: 5 commits del 2026-08-22 con
  proposal, design y tasks propios y correcciones de gate, en `ACTIVE` y sin
  implementar. Esta línea planificó el 19-ago e implementó el 21-ago contra otra
  especificación.

  | | Esta línea | La de Marta |
  |---|---|---|
  | Requisitos | R1–R7 | R1–R6 |
  | Decisiones | D1–D22 | D1–D9 |
  | Tareas | 42 (español) | 36 (inglés) |
  | Implementación | 678 tests en verde | ninguna |

  **La causa raíz es de esta línea**: hizo todo el trabajo sin publicar nunca la
  reclamación de rama, que es lo que la regla 10 usa para que el equipo vea una feature
  en marcha. Sin ella, Marta no podía saberlo.

  **Acuerdo tomado (Jose ↔ Marta, 2026-08-22)**: Jose entrega en paralelo y Marta
  reconcilia cuando cierre inbox, cogiendo lo mejor de cada línea. Hecho:

  - Rama **`sdd/conversations-inbox-jose`**, empujada. La de Marta **no se tocó**
    (sigue en `98815ac`); no se forzó nada.
  - PR **https://github.com/autohostai-labs/AutoHostAI/pull/111** contra `main`,
    titulado como implementación paralela y con el cuerpo escrito para reconciliar:
    las dos tablas de especificación, lo verificado, y qué piezas son reutilizables
    con independencia de qué especificación gane.

  **La evidencia de PR del lifecycle NO se registra, y es deliberado.** `STATE.md`
  sigue en `READY_FOR_PR` con `head_branch: sdd/conversations-inbox`, y el `head` de
  ese PR es otro: `record-pr` valida la identidad contra lo registrado y debe fallar.
  Este PR no es el PR canónico del change. Registrarlo aquí sería afirmar que esta
  línea *es* `conversations-inbox`, y eso es justo lo que está por decidir.

  **Qué falta**: que Marta rebase o entresaque contra el PR 111 al cerrar inbox, y que
  entre las dos líneas quede **una** especificación. Después, quien se quede conduce el
  ship canónico sobre `sdd/conversations-inbox`.
- **exact resume command**: tras la reconciliación, `/sdd:review conversations-inbox`
  sobre la especificación que sobreviva (el veredicto actual verifica R1–R7/D1–D22 y
  **no transfiere** a R1–R6/D1–D9).

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
