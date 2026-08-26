# Design: reservation-amount-empty-render

## Context

La lista (`features/reservations/components/list/reservations-view.tsx:166`) y el
bloque financiero de la ficha (`features/reservations/components/detail/reservation-detail-sections.tsx:124/130/136`)
muestran hoy `{amount ?? ""} {currency}`. Cuando el importe es `null`, la
concatenación deja `" EUR"` (espacio inicial + código suelto): el `?? ""` produce
un hueco vacío al que se le suma el código de divisa sin condición. Los cuatro
sitios usan exactamente el mismo patrón roto, y la convención ya existe en el
mismo fichero (`reservations-view.tsx:156` y `reservation-detail-sections.tsx:163/192/196`
ya renderizan `guestId`/`accessStatus`/`email`/`phone` como `?? "—"`), así que
la corrección es **eliminar el patrón roto y dejar el render explícito del
caso nulo** —no crear un helper ni un componente nuevo (R3.3).

`ReservationSummaryDto.grossAmount`, `ReservationDetailDto.netAmount`/`otaCommission`
y `GuestSummaryDto.email`/`phone` ya declaran los nulables en
`features/reservations/data/dto.ts`; el mapper HTTP no los cambia. El esqueleto
del subcomponente financiero (`DetailFinancialBlock`) ya está factorizado
aislando los tres importes en un solo sitio, y la lista renderiza un único
importe por fila; los dos cambios son ediciones puntuales en cuatro líneas.

## Decisions

### D1 — Sustituir el patrón roto por un condicional ternario en línea

**Chosen:** en los cuatro sitios donde se concatena importe con código de divisa,
sustituir `{amount ?? ""} {currency}` por
`{amount !== null ? \`${amount} ${currency}\` : "—"}`. Cuando el importe es
`null` se pinta la raya em y **no** se concatena el código de divisa con un
espacio previo (R1.1, R1.2); cuando está presente se concatena exactamente
como antes (R1.4).

Rejected:
- `{amount ?? "—"}` con el `{currency}` fuera del ternario — deja el código de
  divisa colgando al lado de `—` cuando el importe es `null`, contraviniendo
  R1.1 ("SHALL NOT concatenar el código de divisa con un espacio o carácter
  vacío previo").
- Extraer un helper `formatAmount(amount, currency)` o un componente
  `<AmountCell />` — explícitamente prohibido por R3.3 ("NOT introducir un nuevo
  componente, hook o helper dedicado al formato de importes"). Sólo son cuatro
  sitios en una sola feature.

### D2 — Raya em como literal `—`, sin nueva clave i18n

**Chosen:** el carácter `—` (U+2014) se escribe literal en el JSX, igual que ya
lo hace `guestId ?? "—"` en `reservations-view.tsx:156`. Cero cambios en
`locales/es/reservations.json` y `locales/en/reservations.json`.

Rejected:
- Añadir `fields.amountEmpty: "—"` a los dos locales — explícitamente prohibido
  por R4.1 ("SHALL usar el mismo carácter" en ambos) y R4.2 ("SHALL NOT añadir
  una nueva clave i18n para 'importe vacío'"). El em-dash no se localiza.
- Usar otro glifo como `–` (en-dash) o `·` (punto medio) — rompería la
  convención ya establecida por `guestId`/`accessStatus`/`email`/`phone`.

### D3 — Barrido R3 confinado a nulables del DTO de la feature

**Chosen:** el barrido `?? ""` cubre `ReservationSummaryDto`, `ReservationDetailDto`
y `GuestSummaryDto` (R3.2). Quedan **fuera** del barrido:

- `features/reservations/components/list/reservations-filters.tsx:48/81/105` —
  aplican `?? ""` a `ReservationFilters.status`/`dateFrom`/`dateTo`, que **no
  es un DTO** sino un objeto de entrada de filtros, y el `""` es el idiom
  canónico de React para "ningún valor seleccionado" en `<select>`/`<input>`
  controlados. Cambiar esto no es arreglar el patrón roto, es romper inputs.
- Las cuatro apariciones de `?? ""` en los dos `*.test.tsx` (`textContent ?? ""`
  defensivo al interrogar `screen.getByRole(...).textContent`) — son lectura
  segura de cadenas posiblemente nulas y no son render.
- `features/reservations/components/detail/reservation-detail-sections.tsx:124/130/136`
  ya están en alcance por R1 y dejan de tener el patrón tras D1.
- `internalNotes`, `specialRequests` (`DetailNotesBlock`) — ya usan un ternario
  sobre el bloque completo (`if (!internalNotes && !specialRequests) return null`)
  y renderizan o no el bloque; no usan `?? ""`.

Rejected:
- Sustituir también los inputs del filtro — rompe el binding controlado del
  formulario y no arregla ninguna pantalla rota.

### D4 — Cobertura de test del caso nulo explícita, en los dos archivos existentes

**Chosen:** añadir los casos de R2 como dos nuevos `it(...)` en los archivos
de test ya existentes, sin tocar la suite ni el runner. La forma exacta:

1. **`reservations-view.test.tsx`** — un `it` que mockea el hook con una fila
   de `grossAmount: null` (el resto del fixture `SAMPLE` se mantiene) y
   verifica: `screen.getAllByText("—")` contiene al menos una aparición en la
   celda de importe, y `document.body.textContent` no contiene `"EUR"`. La
   primera assert exige el em-dash del importe; la segunda exige que el código
   de divisa no se concatere con un espacio previo. El test existente
   `guestId null renders as an em-dash` sigue verde: su fixture ya tiene
   `guestId: null` y `grossAmount: "612.50"`, así que la assert `getByText("—")`
   matchea vía guest null; convivirá con el nuevo.
2. **`reservation-detail-view.test.tsx`** — un `it` que renderiza la ficha con
   `grossAmount: null`, `netAmount: null`, `otaCommission: null` (el resto de
   `FULL_DETAIL` se mantiene, incluido `guest` poblado) y verifica:
   `screen.getAllByText("—").length >= 3` (uno por cada importe nulo, sin
   contar el `accessStatus` ni el email/phone, que en el fixture están
   poblados) y `document.body.textContent` no contiene `"EUR"`. Los fixtures
   con importes presentes (el propio `FULL_DETAIL` y el caso de `otaCommission:
   null` ya existente) siguen verdes.

Rejected:
- Mover los tests a un archivo aparte (`reservations-empty-amount.test.tsx`) —
  R2.1 y R2.2 los quieren en los archivos de test ya existentes, no crea
  taxonomía nueva.
- Parametrizar la cobertura con `it.each` — el suite ya tiene tests planos;
  introducir `it.each` aquí sólo para dos casos no aporta legibilidad.

### D5 — Ningún cambio en mapper HTTP, DTO, hook, locales, CI, ni en la maqueta de Stitch

**Chosen:** la corrección vive entera en los dos componentes de presentación.
`HttpReservationsSource`, `useReservations`, `features/reservations/data/dto.ts`,
`frontend/locales/{es,en}/reservations.json`, los workflows de CI y los
fixtures se quedan como están.

Rejected:
- Cambiar `dto.ts` para que `grossAmount`/`netAmount`/`otaCommission`
  pasen de `string | null` a `string` con `""` como sentinela — el backend
  realmente puede no tener importe (no es 0, no es "") y el contrato
  `ReservationResponse.gross_amount: string | null` del OpenAPI es lo que la
  UI ya consume; camuflar el nulo como `""` reintroduce el mismo problema en
  la frontera del mapper.
- Añadir una clave i18n (R4.2 lo prohíbe).
- Actualizar la maqueta de Stitch (`docs/design/2026-08-23-stitch-export/`)
  porque ya está documentada como fuente del hallazgo y el cambio es del
  código, no del diseño.

## Changes by area

| Area | Files | Change |
|---|---|---|
| List view | `frontend/features/reservations/components/list/reservations-view.tsx` | Línea 165-167: la celda de importe sustituye `{row.grossAmount ?? ""} {row.currency}` por `{row.grossAmount !== null ? \`${row.grossAmount} ${row.currency}\` : "—"}`. |
| Detail financial block | `frontend/features/reservations/components/detail/reservation-detail-sections.tsx` | Líneas 122-138: cada uno de los tres `<dd>` financieros usa el mismo ternario. `accessStatus`, `email`, `phone` y `guestId` no se tocan (D3). |
| List test | `frontend/features/reservations/components/list/reservations-view.test.tsx` | Añadir `it("renders a row with grossAmount: null as an em-dash, with no stray currency code (R1.1)")`. Fixture: `SAMPLE` con `data[0].grossAmount = null`. Asserts: em-dash presente, `EUR` ausente en `document.body.textContent`. |
| Detail test | `frontend/features/reservations/components/detail/reservation-detail-view.test.tsx` | Añadir `it("renders null grossAmount/netAmount/otaCommission as three em-dashes with no currency code (R1.2)")`. Fixture: `FULL_DETAIL` con los tres importes nulos. Asserts: al menos tres em-dashes en el documento, `EUR` ausente. |

## Data & interfaces

None. El cambio es de render. Los DTOs (`features/reservations/data/dto.ts`) y
el contrato HTTP (`backend/openapi.json` ⇒
`frontend/lib/api/generated/openapi.d.ts`) ya declaran los nulables; no se
tocan. Las traducciones (`frontend/locales/{es,en}/reservations.json`) tampoco.

## Risks & mitigations

- **El test `guestId null renders as an em-dash` (lista) matchea `—` por guest
  null**, no por importe — y el nuevo test también. Riesgo: si los fixtures
  cambian durante el `run` no se pisen entre sí. Mitigación: el nuevo test usa
  `SAMPLE` pero **sobrescribe** `data[0].grossAmount` a `null`, dejando el
  resto igual; las dos asserts (`getAllByText("—")` con length ≥ 2 — uno del
  guest null original, otro del importe null) bastan para no depender del
  orden de `getByText`. Si el suite se reorganiza en paralelo, este test se
  resiste porque la assert `not.toContain("EUR")` es estricta.
- **Regresión silenciosa si el patrón se reactiva.** La presencia en el árbol
  de `?? ""` sobre un `string | null` volvería a colar el bug. Mitigación: la
  barra de R3 la quita del sitio correcto, no la prohíbe globalmente; el test
  R2.1 lleva el `not.toContain("EUR")` al verde, así que cualquier reintroducción
  local rompe el suite.
- **Worktree con `npm test` roto de fábrica (project.md).** Dos tests leen por
  encima de `/app` y dan `ENOENT` en worktree, sumando 2 ficheros rojos que no
  son del change. Mitigación: la verificación corre el script de Bootstrap
  documentado en `sdd/project.md` (mkdir + `docker compose cp` de los 9 ficheros)
  antes de invocar `npm test`, y compara el recuento de ficheros rojos con el
  de partida, no contra una cifra memorizada.
- **Maquetación `?? "—"` accessibility.** El em-dash literal es un carácter
  no-espacio legible para lectores de pantalla (lo leen como "em dash" o "guión
  largo") y conserva el contraste visual con cifras. La fila/cell no pierde
  contenido accesible — `—` no es aria-hidden, no necesita un `aria-label`
  alternativo.

## Resolved during the gate

- **`sdd/specs/reservations-web.md` no existe** y la propuesta lo cita como
  afectado. Resuelto: tratar la cita como error del proposal. El change no
  introduce nuevo contrato, sólo cambia presentación, y los tests ya citan
  R1-R5. La escritura del spec después de shipped, si alguna vez se quiere,
  es trabajo de otra entrada.
