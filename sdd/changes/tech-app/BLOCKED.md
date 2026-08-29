# BLOCKED: tech-app

## 2. La comprobación visual del flujo (9.5) y la de 360 px (9.6) siguen pendientes

- **phase**: run
- **type**: deferred
- **what & why**: las dos tareas piden mirar la aplicación de verdad: recorrer
  `ASSIGNED → ACCEPTED → IN_PROGRESS → RESOLVED` con un usuario `TECHNICIAN`, subir una foto
  `BEFORE` y otra `AFTER`, cerrar con coste y materiales, comprobar en la pestaña de red que abrir
  una fila no vuelve a pedir su contexto, y revisar a 360 px que no hay desplazamiento horizontal.

  No se han hecho. Este worktree está enlazado y **no publica puertos**, así que no hay UI
  alcanzable desde el host; y con `make up PORT_OFFSET=<n>` la página se sirve pero **no hidrata**
  (`sdd/project.md`, medido en `cleaning-assign-preconditions` el 2026-08-23: submit nativo del
  formulario, el conmutador de idioma muerto y ninguna prop de React en el `<form>`), de modo que
  ni los botones del ciclo ni el formulario de cierre responderían — que es exactamente lo que hay
  que probar. La salida documentada es el **worktree principal** o `dev`, y el principal lo están
  usando otras sesiones vivas, así que no se le toca el stack.

  Lo que sí está verificado y no sustituye a lo anterior: la suite completa del frontend en verde
  (163 ficheros / 1653 tests), typecheck y lint limpios, y 75 tests propios de `features/tech` que
  cubren por composición cada criterio de R1–R6. **Un test de componente no es una pasada visual**:
  no dice nada del desplazamiento horizontal real ni de si los objetivos táctiles son cómodos con
  el pulgar.

- **exact resume command**: `/sdd:review tech-app` (desde el worktree principal, o contra `dev`)

## 3. Tres residuos de baja severidad tras dos rondas de arreglos en review

- **phase**: review
- **type**: deferred
- **what & why**: `/sdd:review tech-app` (2026-08-29) dio FAIL con 19 hallazgos en cuatro lentes.
  Se arreglaron en dos rondas y **las cuatro lentes vuelven PASS** (`architect`, `qa`, `i18n`,
  `documentation`; `security`, `tenancy` y `cicd` ya pasaban en la primera). Suite completa
  **164 ficheros / 1705 tests** en verde (163/1653 de partida), `tsc --noEmit` y lint limpios,
  paridad de catálogos exacta 94/94 sin huérfanas. QA verificó por **mutación** que los arreglos
  de la paginación, la navegación del `reject` y los estados de la galería matan a sus mutantes.

  Quedan tres cosas que **no** se arreglaron, por el tope de dos rondas de la propia fase:

  1. **F1 (bajo, R6.2)** — el test del estado vacío de la galería
     (`tech-incident-detail-view.test.tsx`, «an empty photo list renders the shared EmptyState»)
     comprueba sólo que aparece la cadena `photos.empty.title`, no la estructura del primitivo.
     Demostrado por mutación: sustituir `<EmptyState/>` por un `<p>` con la misma clave deja la
     suite en verde. Sus dos hermanos (el `aria-busy` de la carga y el `role="alert"` del error)
     sí matan a su mutante. Arreglo: afirmar lo que sólo `EmptyState` aporta (su descripción o el
     rol del contenedor), como hacen los otros dos.
  2. **Comentario caduco (informativo)** — el JSDoc de `useUploadIncidentPhoto` en
     `frontend/features/incidents/hooks/use-incident-cycle.ts` todavía dice que «el único motivo
     alcanzable es `out-of-order` y los otros dos mensajes son cadenas muertas», que describe el
     diseño de tres cadenas *anterior* a la enmienda de D8. El comportamiento que documenta es
     correcto; la frase no. El JSDoc del propio componente sí cuenta el contrato colapsado.
     Levantado por la lente de arquitectura, que lo marcó explícitamente como no bloqueante.
  3. **F2 (bajo, R4.1/R4.5)** — `validateFinalCost("5,00")` devuelve `required` («Indica el coste
     final.»), no un mensaje de formato, porque el `!Number.isFinite` de la línea 21 se adelanta a
     la comprobación de forma. Es la misma clase de defecto que la rama `format` arregló para
     `"5."`: un mensaje que nombra una regla que el técnico no ha roto, y en una UI en español el
     teclado numérico ofrece coma. **Matiz**: el input es `type="number"`, así que el navegador
     real puede saneárselo antes de que la cadena llegue al estado; QA verificó la función pura,
     no el recorrido de teclado. **En la pasada de certificación QA lo rebajó todavía más**: el
     input es `type="number" step="0.01"`, y el algoritmo de saneado de HTML entrega `""` para una
     cadena que no es un número válido, así que por el teclado real llega `""` y `required` es el
     mensaje **correcto**. Sólo es alcanzable por un camino que se salte el saneado.

  Ninguno de los tres se arregló: la fase tiene un tope de dos rondas de arreglos y se alcanzó.
  Las siete lentes los conocen y aun así certificaron.

- **exact resume command**: los tres son de una o dos líneas; que los recoja quien toque
  `tech-resolve-form.tsx`, `tech-incident-detail-view.test.tsx` o `use-incident-cycle.ts` la
  próxima vez, o `/sdd:review tech-app` si se prefiere cerrarlos antes de mergear.
