# BLOCKED: tech-app

## 1. Tres residuos de baja severidad tras dos rondas de arreglos en review

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

## 2. `e975a56` cierra dos hallazgos que ningún revisor ha visto todavía

- **phase**: review
- **type**: deferred
- **what & why**: la última pasada del panel sobre `29f2ac4` dio **6 PASS y 1 FAIL**
  (`architecture`, dos hallazgos), y el gate ejecutable lo confirmó:
  `gate: FAIL — reviewer did not pass: sdd-architect`. Los dos hallazgos, más un residuo que
  `security`, `tenancy` y `qa` señalaron por separado, se arreglaron en `e975a56`:

  1. el JSDoc de `useIncidentPhotos` afirmaba que una URL firmada no puede caducar en caché,
     cuando §Risks acepta justo ese caso como residual;
  2. `(D11)` resolvía a la D11 de este change en vez de a la de `frontend-foundation`;
  3. `design.md` D10 conservaba la premisa falsa del `staleTime` 0 en su origen.

  **Ese commit no está revisado.** La fase tiene un tope de dos rondas de arreglos y se pasó de
  largo —van cuatro—, así que se para aquí en vez de encadenar una quinta. Lo que falta para
  certificar es **una pasada del panel sobre `e975a56`**: si sale PASS, el gate pasa y siguen
  `mark-local-verified` → `mark-ready --base main` → `validate-ship`.

  Contexto para quien la lance: el código lleva limpio desde `7fd3ba7` —las siete lentes lo han
  certificado en varias rondas— y todo lo que ha fallado después han sido **afirmaciones mías en
  prosa que iban por delante de la evidencia**: seis hallazgos de esa misma clase en cuatro
  rondas. Merece la pena leer `e975a56` con esa sospecha concreta y no como un diff cualquiera.

- **exact resume command**: `/sdd:review tech-app` sobre `e975a56`.
