# Tasks: reservation-amount-empty-render

## 1. Render: lista y ficha (R1) <!-- panel: PASS 2026-08-24 -->

- [ ] 1.1 Sustituir el patrón roto en la celda de importe de la lista.
  Fichero: `frontend/features/reservations/components/list/reservations-view.tsx`
  (líneas 165-167). Cambiar `{row.grossAmount ?? ""} {row.currency}` por
  `{row.grossAmount !== null ? \`${row.grossAmount} ${row.currency}\` : "—"}`.
  El caso poblado debe concatenarse exactamente como hasta ahora; el caso
  `null` debe pintar `—` sin código de divisa suelto. Cubre R1.1, R1.4 y la
  parte de R3.2 que toca `ReservationSummaryDto.grossAmount`.
- [ ] 1.2 Sustituir el patrón roto en los tres `<dd>` del bloque financiero
  de la ficha. Fichero:
  `frontend/features/reservations/components/detail/reservation-detail-sections.tsx`
  (líneas 122-138, dentro de `DetailFinancialBlock`). Aplicar el mismo
  ternario que en 1.1 a `grossAmount`, `netAmount` y `otaCommission`. El
  em-dash debe ser idéntico en los tres. `accessStatus`, `email`, `phone` y
  `guestId` **no** se tocan (D3). Cubre R1.2, R1.3, R1.4 y la parte de R3.2
  que toca `ReservationDetailDto.netAmount`/`otaCommission`.

## 2. Barrido R3: confirmar que no quedan `?? ""` sobre nulables del DTO (R3)

- [ ] 2.1 Verificar con `rg -n '?? ""' frontend/features/reservations/` que
  los únicos sitios donde `?? ""` se aplica a un campo `string | null` /
  `T | null` declarado en `frontend/features/reservations/data/dto.ts` son
  los cuatro ya cubiertos por la sección 1. Las apariciones restantes
  deben caer en (a) filtros de `reservations-filters.tsx` (`status`,
  `dateFrom`, `dateTo` — idiom de inputs controlados, no DTO) y (b) lecturas
  defensivas de `textContent ?? ""` en los `*.test.tsx`. Documentar el
  resultado en el commit (`grep` adjuntado al mensaje o nota en el diff).
  Cubre R3.1, R3.2 y R3.3 (el patrón no se prohíbe globalmente; los sitios
  correctos siguen usando `?? "—"` para `guestId`, `accessStatus`, `email`
  y `phone`).

## 3. Cobertura de test del caso nulo (R2) <!-- panel: PASS 2026-08-24 -->

- [ ] 3.1 Añadir un caso de prueba en
  `frontend/features/reservations/components/list/reservations-view.test.tsx`
  con título `"renders a row with grossAmount: null as an em-dash, with no
  stray currency code (R1.1)"`. Reutilizar el fixture `SAMPLE` sobreescribiendo
  `data[0].grossAmount = null` y dejando el resto igual (incluido
  `guestId: null`, para que la assert siga matcheando al menos dos em-dashes).
  Asserts: `screen.getAllByText("—").length >= 1` (uno del importe; el del
  guest puede coexistir) y `expect(document.body.textContent).not.toContain("EUR")`.
  El caso existente `guestId null renders as an em-dash` (línea 171) sigue
  verde porque su fixture deja `grossAmount: "612.50"`. Cubre R1.1, R2.1.
- [ ] 3.2 Añadir un caso de prueba en
  `frontend/features/reservations/components/detail/reservation-detail-view.test.tsx`
  con título `"renders null grossAmount/netAmount/otaCommission as three
  em-dashes with no currency code (R1.2)"`. Reutilizar el fixture
  `FULL_DETAIL` sobreescribiendo los tres importes a `null` (dejando `guest`
  poblado con `email`/`phone` presentes, y `accessStatus: "DELIVERED"`).
  Asserts: `screen.getAllByText("—").length >= 3` y
  `expect(document.body.textContent).not.toContain("EUR")`. Cubre R1.2, R2.2.
- [ ] 3.3 Confirmar que los fixtures con importes presentes siguen verdes:
  el `it` "renders one row per summary …" de `reservations-view.test.tsx`
  (`grossAmount: "612.50"`) y los casos de `reservation-detail-view.test.tsx`
  que renderizan `FULL_DETAIL` o el sub-caso `otaCommission: null` ya
  existente (que ahora debe seguir verde: la celda de OTA pasa de `""
  {currency}` a `—` y el resto no se toca). Cubre R2.3.
- [ ] 3.4 **No** tocar `use-reservations.test.tsx` (responsabilidad de
  mapeo DTO, no de DOM). Cubre R2.4 — comprobación por omisión al diff.

## 4. Locales intactos (R4)

- [ ] 4.1 Confirmar que `frontend/locales/es/reservations.json` y
  `frontend/locales/en/reservations.json` no se modifican: `git diff` sobre
  ambos devuelve vacío. La raya em es un literal `—` en el JSX, no una
  clave nueva (`grep -n '"—"' frontend/locales/{es,en}/reservations.json`
  debe seguir sin matchear; sólo `reservations-view.tsx` y
  `reservation-detail-sections.tsx` la contienen). Cubre R4.1, R4.2 y R4.3.

## 5. Verification

Comandos exactos de `sdd/project.md`. La cifra de referencia se mide contra
el `npm test` del propio worktree tras aplicar el bootstrap documentado, **no**
contra números memorizados.

- [ ] 5.1 Backend tests en verde (la suite del backend no cambia con este
  change, pero se corre para descartar regresiones laterales):
  `docker compose exec backend uv run pytest`. Resultado esperado: misma
  cifra de paso que la baseline del worktree principal.
- [ ] 5.2 Typecheck del frontend en verde:
  `cd frontend && npm run typecheck` (o `tsc --noEmit` si no hay script).
  Resultado esperado: 0 errores. El DTO y el mapper HTTP no se tocan, así
  que `tsc` no debe añadir hallazgos.
- [ ] 5.3 Lint del frontend en verde:
  `cd frontend && npm run lint`. Resultado esperado: 0 errores. Si no hay
  script `lint`, saltar.
- [ ] 5.4 Suite del frontend:
  `cd frontend && npm test`. Antes de correrlo, aplicar el bootstrap
  documentado en `sdd/project.md` (mkdir + `docker compose cp` de los
  nueve ficheros) para silenciar los `ENOENT` del worktree. El cambio
  añade dos `it` y modifica cuatro líneas de render — ningún fichero
  existente debería romperse. Comparar el recuento de ficheros rojos
  contra la baseline medida **en este mismo worktree** antes de aplicar
  los cambios: si la baseline era X rojos (los `ENOENT` que el bootstrap
  no resuelva), el resultado debe seguir siendo X; si el bootstrap deja la
  suite en verde, debe seguir en verde. Los dos `it` nuevos deben pasar.
- [ ] 5.5 Inspección visual en navegador (opcional, no bloqueante): si el
  worktree se levanta con `make up` y se quiere confirmar visualmente la
  pantalla, recordar la nota de `sdd/project.md` sobre `PORT_OFFSET`: sirve
  para alcanzar la API desde el host, **no** para una pasada visual
  (Next 16 bloquea orígenes cruzados sin `allowedDevOrigins`). Para una
  inspección visual fiable, abrir el worktree principal o `dev`. No es un
  gate del change — los tests de 5.4 ya cubren el comportamiento.
