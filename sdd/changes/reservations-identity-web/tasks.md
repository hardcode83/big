# Tasks: reservations-identity-web

## 1. DTO y mapper llevan los tres campos derivados <!-- panel: PASS 2026-09-05 -->

- [x] 1.1 En `frontend/features/reservations/data/dto.ts`, añadir `propertyName: string | null`,
      `propertyInternalCode: string | null` y `guestFullName: string | null` a
      `ReservationSummaryDto` (heredados automáticamente por `ReservationDetailDto`, que ya
      extiende de `ReservationSummaryDto`). Actualizar el comentario de cabecera del fichero si
      queda desactualizado. [R1]
- [x] 1.2 En `frontend/features/reservations/data/http/http-reservations-source.ts`, mapear
      `property_name → propertyName`, `property_internal_code → propertyInternalCode` y
      `guest_full_name → guestFullName` en `mapReservationSummary` (los tres ya están declarados
      como `string | null | undefined` opcionales en `ReservationResponse` de
      `openapi.d.ts:4077,4101,4103` — normalizar `undefined` a `null` con `?? null`).
      `mapReservationDetail` no necesita cambios propios: hereda los tres campos de
      `ReservationSummaryDto` pero su función de mapeo es independiente (no llama a
      `mapReservationSummary`), así que replicar las mismas tres líneas ahí, leyendo de
      `ReservationDetailResponse` (`openapi.d.ts:4169,4193,4195`). [R1]
- [x] 1.3 Extender `frontend/features/reservations/data/http/http-reservations-source.test.ts`:
      un caso con los tres campos presentes y otro con los tres `null`/ausentes, para
      `mapReservationSummary` (vía `listReservations`) y para `mapReservationDetail` (vía
      `getReservation`). Verificar que un campo ausente en el fixture de respuesta mapea a `null`,
      no a `undefined`. [R1, R6.1]

## 2. Columnas *Property* y *Guest* de la lista <!-- panel: PASS 2026-09-05 -->

- [x] 2.1 En `frontend/features/reservations/components/list/reservations-view.tsx`
      (`ReservationRow`), sustituir la celda `{row.propertyId}` (línea 172) por
      `row.propertyInternalCode ?? "—"`, y añadir `title={row.propertyName ?? undefined}` al
      mismo `<td>` (el atributo `title` no se pinta cuando es `undefined`). [R2]
- [x] 2.2 En la misma fila, sustituir `{row.guestId ?? "—"}` (dentro del `<Link>` de navegación,
      línea 169) por `row.guestFullName ?? "—"`, sin tocar el `href` (que sigue construyéndose
      con `row.id`, no con el guest). [R3]
- [x] 2.3 Extender `frontend/features/reservations/components/list/reservations-view.test.tsx`:
      un caso de fila con `propertyInternalCode`/`propertyName`/`guestFullName` presentes (verificar
      que la celda de Property no vuelve a pintar el UUID) y un caso con los tres `null` (verificar
      el em-dash en ambas celdas, sin fallback a `propertyId`/`guestId`). El test existente
      "guestId null renders as an em-dash, not the id" (línea 171) puede necesitar renombrarse o
      ampliarse si pasa a cubrir `guestFullName`. [R2, R3, R6.2]

## 3. Bloque de identidad de propiedad en el detalle <!-- panel: PASS 2026-09-05 -->

- [x] 3.1 En `frontend/features/reservations/components/detail/reservation-detail-sections.tsx`,
      añadir `DetailPropertyBlock({ propertyInternalCode, propertyName }: { propertyInternalCode:
      string | null; propertyName: string | null })`, con el mismo patrón `section`/`dl`/`dt`/`dd`
      que `DetailGuestBlock` y las demás; usar `aria-label={t("fields.property")}` (clave ya
      existente en `locales/{es,en}/reservations.json`, reutilizada — no crear una nueva salvo
      que el texto no encaje al implementar, en cuyo caso añadirla a **ambos** locales). Cada `dd`
      pinta el valor o el em-dash `—` si es `null`. [R4, R5]
- [x] 3.2 Añadir `property` al objeto que devuelve `composeDetailSections` (misma función,
      construido con `detail.propertyInternalCode`/`detail.propertyName`), y montar
      `{sections.property}` en `reservation-detail-view.tsx`, en un lugar razonable del flujo
      (junto a `sections.header`, antes de `sections.stay`). [R4]
- [x] 3.3 Añadir un test (en `reservation-detail-view.test.tsx` o un fichero nuevo colocado junto a
      `reservation-detail-sections.tsx` si el primero no es el sitio natural) que cubra el bloque
      de propiedad con ambos valores presentes y con ambos `null` (em-dash en los dos `dd`, bloque
      visible en ambos casos — a diferencia de `DetailGuestBlock`, este bloque no se oculta por
      completo cuando sus valores son `null`). [R4, R6.3]

## 4. Verification

- [x] 4.1 Full frontend test suite passes: `docker compose exec -T frontend npm test`.
      **Entorno**: 5 worktrees de otras features vivos en paralelo (`docker stats` — host de
      Docker en ~536 MB disponibles de 8 GB) hicieron que dos pasadas completas terminaran en
      `Killed` (OOM) o con fallos en ficheros ajenos a este change que **cambiaban de fichero
      entre pasadas** (`test/topbar-overflow.test.ts`, `test/theme-client-state.test.ts`,
      `test/color-tokens.test.ts`) — firma de contención de host, no de regresión
      ([[suite-flake-is-host-contention-not-regression]] en la memoria del proyecto). Verificado:
      los tres ficheros pasan limpios en aislado (`npx vitest run <fichero>` — 9/9, 14/14 —
      recuento estable en dos pasadas). La suite de la feature que este change toca
      (`docker compose exec -T frontend npx vitest run --maxWorkers=1 features/reservations/`)
      pasa **8/8 ficheros, 63/63 tests**, cero fallos. No se completó un `npm test` de árbol
      entero limpio de punta a punta por la contención descrita, no por ningún fallo atribuible a
      este change.
- [x] 4.2 Typecheck/lint. `npm run typecheck` de árbol entero (`tsc --noEmit`) muere con `Killed`
      en este worktree por el mismo motivo (memoria disponible < lo que exige el programa
      completo). Verificado en su lugar con un `tsconfig` temporal (no commiteado) que extiende
      `tsconfig.json` y acota `include` a los ficheros que este change toca
      (`features/reservations/**`, `lib/api/**`, `test/setup.ts` para los matchers de
      `jest-dom`): **0 errores**. `npm run lint` de árbol entero también muere por la misma razón;
      `npx eslint features/reservations/` (el scope de este change) da **0 problemas**, y
      `npx eslint app components lib` (una de las dos mitades que evitan el OOM, per memoria del
      proyecto) también da 0.
- [ ] 4.3 Comprobación manual: NO realizada. El navegador solo es alcanzable con
      `make up PORT_OFFSET=<n>`, y con el host ya al límite de memoria (5 stacks de otros
      worktrees vivos, ~536 MB disponibles de 8 GB) levantar puertos adicionales arriesgaba
      desestabilizar sesiones ajenas en vez de una mejora proporcional al riesgo. Documentado
      aquí en vez de omitido, tal como esta tarea anticipa.

## Implementation Notes

- Section 1 (dto.ts + http-reservations-source.ts): new DTO fields on `ReservationSummaryDto` are `propertyName: string | null`, `propertyInternalCode: string | null`, `guestFullName: string | null` — inherited as-is by `ReservationDetailDto`, no redeclaration needed.
- Mapper reads `value.property_name ?? null`, `value.property_internal_code ?? null`, `value.guest_full_name ?? null` in `mapReservationSummary`; `mapReservationDetail` composes via `...mapReservationSummary(value)` for all shared fields (fix-round from the panel's architect finding — `ReservationDetailResponse` is structurally assignable into `ReservationResponse`) instead of duplicating the field list.
- Row shape for section 2/3 consumers: `row.propertyName`, `row.propertyInternalCode`, `row.guestFullName` (camelCase, always `string | null`, never `undefined`).
- Test command used: `docker compose exec -T frontend npx vitest run features/reservations/data/http/http-reservations-source.test.ts` — 11/11 passed.
- Section 2 (reservations-view.tsx + its test): the *Guest* cell inside the row `<Link>` now renders `row.guestFullName ?? "—"`; the `href` is unchanged (still `/reservations/{row.id}`). The *Property* cell renders `row.propertyInternalCode ?? "—"` with `title={row.propertyName ?? undefined}` on the same `<td>`. `SAMPLE` in the test file was extended with `propertyName: null, propertyInternalCode: null, guestFullName: null` (matching the real DTO — always present, nullable, never `undefined`); the old "guestId null renders as an em-dash" test was renamed/expanded to assert 2 em-dashes (guest + property cells) and that the raw `propertyId`/`guestId` UUIDs never leak into the DOM; a new test covers all three fields present (asserts the code/name/full-name render, not the UUIDs, and the `title` attribute). Nothing here should matter to section 3 (different files), no new i18n keys were needed. Test command: `docker compose exec -T frontend npx vitest run features/reservations/components/list/reservations-view.test.tsx` — 14/14 passed.
- Section 3 (detail property block): `DetailPropertyBlock` reuses the existing `fields.property` key for its `section aria-label` (section header/column meaning, unchanged text "Propiedad"/"Property"), same as R5.1 anticipated. The two `dt` field labels inside the block needed new keys — neither `fields.property` nor `fields.fullName` fit (the latter is already the guest's full-name label, and reusing its value "Nombre"/"Name" caused a real `getByText` multiple-match test failure, confirming the collision). Added to **both** `frontend/locales/es/reservations.json` and `frontend/locales/en/reservations.json` under `fields`: `propertyCode` = ES "Código interno" / EN "Internal code", `propertyName` = ES "Nombre de la propiedad" / EN "Property name" (deliberately more specific than a bare "Código"/"Nombre" to avoid colliding with `fullName`'s text). Unlike `DetailGuestBlock`, `DetailPropertyBlock` never returns `null` — both `dd`s independently fall back to the literal em-dash `—` (not an i18n key), so the block and its labels stay visible even when both values are null (R4.2). `composeDetailSections` gained a `property` entry (built from `detail.propertyInternalCode`/`detail.propertyName`) mounted in `reservation-detail-view.tsx` as `{sections.property}` right after `{sections.header}` and before `{sections.stay}`. Test command: `docker compose exec -T frontend npx vitest run features/reservations/components/detail/` — 13/13 passed (11 pre-existing + 2 new).
