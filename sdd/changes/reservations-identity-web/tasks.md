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

## 3. Bloque de identidad de propiedad en el detalle

- [ ] 3.1 En `frontend/features/reservations/components/detail/reservation-detail-sections.tsx`,
      añadir `DetailPropertyBlock({ propertyInternalCode, propertyName }: { propertyInternalCode:
      string | null; propertyName: string | null })`, con el mismo patrón `section`/`dl`/`dt`/`dd`
      que `DetailGuestBlock` y las demás; usar `aria-label={t("fields.property")}` (clave ya
      existente en `locales/{es,en}/reservations.json`, reutilizada — no crear una nueva salvo
      que el texto no encaje al implementar, en cuyo caso añadirla a **ambos** locales). Cada `dd`
      pinta el valor o el em-dash `—` si es `null`. [R4, R5]
- [ ] 3.2 Añadir `property` al objeto que devuelve `composeDetailSections` (misma función,
      construido con `detail.propertyInternalCode`/`detail.propertyName`), y montar
      `{sections.property}` en `reservation-detail-view.tsx`, en un lugar razonable del flujo
      (junto a `sections.header`, antes de `sections.stay`). [R4]
- [ ] 3.3 Añadir un test (en `reservation-detail-view.test.tsx` o un fichero nuevo colocado junto a
      `reservation-detail-sections.tsx` si el primero no es el sitio natural) que cubra el bloque
      de propiedad con ambos valores presentes y con ambos `null` (em-dash en los dos `dd`, bloque
      visible en ambos casos — a diferencia de `DetailGuestBlock`, este bloque no se oculta por
      completo cuando sus valores son `null`). [R4, R6.3]

## 4. Verification

- [ ] 4.1 Full frontend test suite passes: `docker compose exec -T frontend npm test` (o
      `docker compose cp` de los ficheros que `sdd/project.md` §Worktree bootstrap documenta si
      aparecen los dos `ENOENT` conocidos del worktree — no son de este change). Comparar el
      recuento de partida (antes de esta sección) contra el final: no debe bajar ningún test que
      no sea de los ficheros tocados aquí.
- [ ] 4.2 Typecheck/lint pasan: `docker compose exec -T frontend npm run typecheck` y
      `docker compose exec -T frontend npm run lint`.
- [ ] 4.3 Comprobación manual (si el navegador es alcanzable en este worktree —
      `make up PORT_OFFSET=<n>`, ver `sdd/project.md` §Worktree bootstrap): `/reservations` en dev
      muestra el código interno de la propiedad y el nombre del huésped del seed en vez de UUIDs,
      el detalle también muestra la identidad de la propiedad, y una reserva sin huésped enlazado
      o cuya propiedad no resuelva muestra `—` en las celdas/campos correspondientes. Si el
      navegador no es alcanzable, documentarlo aquí en vez de omitir la tarea.

## Implementation Notes

- Section 1 (dto.ts + http-reservations-source.ts): new DTO fields on `ReservationSummaryDto` are `propertyName: string | null`, `propertyInternalCode: string | null`, `guestFullName: string | null` — inherited as-is by `ReservationDetailDto`, no redeclaration needed.
- Mapper reads `value.property_name ?? null`, `value.property_internal_code ?? null`, `value.guest_full_name ?? null` in `mapReservationSummary`; `mapReservationDetail` composes via `...mapReservationSummary(value)` for all shared fields (fix-round from the panel's architect finding — `ReservationDetailResponse` is structurally assignable into `ReservationResponse`) instead of duplicating the field list.
- Row shape for section 2/3 consumers: `row.propertyName`, `row.propertyInternalCode`, `row.guestFullName` (camelCase, always `string | null`, never `undefined`).
- Test command used: `docker compose exec -T frontend npx vitest run features/reservations/data/http/http-reservations-source.test.ts` — 11/11 passed.
- Section 2 (reservations-view.tsx + its test): the *Guest* cell inside the row `<Link>` now renders `row.guestFullName ?? "—"`; the `href` is unchanged (still `/reservations/{row.id}`). The *Property* cell renders `row.propertyInternalCode ?? "—"` with `title={row.propertyName ?? undefined}` on the same `<td>`. `SAMPLE` in the test file was extended with `propertyName: null, propertyInternalCode: null, guestFullName: null` (matching the real DTO — always present, nullable, never `undefined`); the old "guestId null renders as an em-dash" test was renamed/expanded to assert 2 em-dashes (guest + property cells) and that the raw `propertyId`/`guestId` UUIDs never leak into the DOM; a new test covers all three fields present (asserts the code/name/full-name render, not the UUIDs, and the `title` attribute). Nothing here should matter to section 3 (different files), no new i18n keys were needed. Test command: `docker compose exec -T frontend npx vitest run features/reservations/components/list/reservations-view.test.tsx` — 14/14 passed.
