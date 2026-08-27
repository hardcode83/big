# Proposal: reservation-amount-empty-render

## Why

La lista de reservas y su detalle pintan, cuando el importe es nulo, un **código de
divisa suelto** — `" EUR"` con espacio inicial. No es un bug de datos: `gross_amount` es
legítimamente nulable en el contrato (`ReservationResponse.gross_amount: string | null`,
mapeado en `features/reservations/data/dto.ts`), y el render del caso vacío está mal.

Descubierto el **2026-08-23** analizando el export de Stitch de la maqueta de reservas
—la de mayor fidelidad de las seis, hecha sobre la pantalla real—: tres de sus cuatro
filas pintaban `EUR` sin cifra porque **se copió literalmente de la pantalla**.
Documentado en `docs/design/2026-08-23-stitch-export/README.md`.

Cuatro sitios producen el resultado incorrecto:

```
features/reservations/components/list/reservations-view.tsx:166
    {row.grossAmount ?? ""} {row.currency}
features/reservations/components/detail/reservation-detail-sections.tsx:124   (bruto)
    {grossAmount ?? ""} {currency}
features/reservations/components/detail/reservation-detail-sections.tsx:130   (neto)
    {netAmount ?? ""} {currency}
features/reservations/components/detail/reservation-detail-sections.tsx:136   (comisión)
    {otaCommission ?? ""} {currency}
```

La ficha de detalle es peor que la lista: puede enseñar **tres** divisas huérfanas
seguidas —bruto, neto y comisión—, todas con el mismo hueco vacío.

**La causa raíz está en los tests, y es la parte que importa.** Ningún test renderiza
el caso nulo: los cuatro render tests fijan un importe presente
(`grossAmount: "612.50"` en `reservations-view.test.tsx:35`,
`reservation-detail-view.test.tsx:35`, `http-reservations-source.test.ts:69,178`). El
único `grossAmount: null` del árbol está en `use-reservations.test.tsx:69`, que es un
**test de hook**: comprueba el mapeo del DTO y no pinta ninguna celda. La rama `?? ""`
de los cuatro sitios tiene **cobertura cero**, y por eso se entregó.

La convención ya existe en el propio fichero. Diez líneas antes del sitio roto de la
lista (`reservations-view.tsx:156`), `guestId` se renderiza como `{row.guestId ?? "—"}`:
mismo fichero, mismo componente, mismo tipo de campo nulable, idioma correcto. La raya
em es el vacío de esta tabla. No hay que inventar convención ni negociar copia.

## What changes

Después de este change, una reserva sin importe enseña una raya em en lugar de un
código de divisa suelto, **tanto en la lista como en la ficha de detalle**, y los
tests cubren explícitamente el caso nulo. La pauta `?? ""` deja de usarse para los
nulables del DTO de la feature, así que el siguiente campo nulable que se añada no
hereda el mismo agujero.

No se tocan el render de la columna Property (UUID pelado — su propia entrada,
`reservation-property-identity`), ni el formato o la localización de importes (`Intl`,
separadores por locale) —afecta a `pricing` y a `statements` igual y merece su propio
recorrido.

## Requirements

### R1 — Un importe nulo se pinta como raya em, no como código suelto

**As a** operadora que mira la lista o la ficha de una reserva, **I want** que un
importe ausente se vea vacío de forma reconocible, **so that** la pantalla no me haga
leer `EUR` como si fuera un precio.

Acceptance criteria:

1. WHEN una fila de la lista de reservas tiene `grossAmount: null`, THE SYSTEM SHALL
   renderizar la celda de importe como `—` y SHALL NOT concatenar el código de
   divisa con un espacio o carácter vacío previo.
2. WHEN una ficha de detalle tiene `grossAmount: null`, `netAmount: null` o
   `otaCommission: null`, THE SYSTEM SHALL renderizar la celda correspondiente como
   `—` y SHALL NOT pintar el código de divisa junto a esa celda.
3. THE SYSTEM SHALL usar el mismo carácter (`—`) para los tres importes en la ficha,
   para que la ausencia sea leíble como una sola convención, no como tres variantes.
4. IF todos los importes están presentes, THE SYSTEM SHALL seguir concatenando cifra y
   código como hasta ahora —no se cambia el render del caso poblado—.

### R2 — El caso nulo tiene cobertura de test explícita

**As a** quien mantiene esta pantalla, **I want** que añadir un campo nulable nuevo no
pueda volver a abrir el mismo agujero en silencio, **so that** la regresión que motivó
este change se detecte en CI.

Acceptance criteria:

1. THE SYSTEM SHALL añadir, en `frontend/features/reservations/components/list/reservations-view.test.tsx`,
   al menos un caso que renderice la lista con una fila de `grossAmount: null` y
   verifique que la celda contiene `—` y no contiene `EUR` como texto independiente.
2. THE SYSTEM SHALL añadir, en `frontend/features/reservations/components/detail/reservation-detail-view.test.tsx`,
   al menos un caso que renderice la ficha con `grossAmount`, `netAmount` y
   `otaCommission` nulos y verifique que aparecen tres rayas em y ningún código de
   divisa suelto.
3. THE SYSTEM SHALL mantener los fixtures existentes con importes presentes, y esos
   casos SHALL seguir verdes.
4. THE SYSTEM SHALL NOT modificar el test de hook `use-reservations.test.tsx` para
   añadir un assert de render: su responsabilidad es el mapeo DTO, no el DOM.

### R3 — El patrón `?? ""` deja de usarse para nulables del DTO de la feature

**As a** autora de esta pantalla, **I want** que el patrón roto no sea la opción
cómoda cuando llegue el próximo campo nulable, **so that** la causa que originó este
change se corrija una vez y no se propague.

Acceptance criteria:

1. THE SYSTEM SHALL barrer `frontend/features/reservations/` en busca de la cadena
   `?? ""` aplicada a un campo declarado `string | null` o `T | null` en
   `frontend/features/reservations/data/dto.ts`, y SHALL dejar cada uno de esos sitios
   con un render explícito del caso vacío (`—` cuando encaje con la convención de la
   tabla, el literal que ya use el sitio análogo si lo tiene, o el que el componente
   decida si no tiene vecino).
2. THE SYSTEM SHALL cubrir, como mínimo, los nulables de
   `ReservationSummaryDto` (`grossAmount`), `ReservationDetailDto` (`netAmount`,
   `otaCommission`; el resto ya se renderiza sin el patrón roto) y `GuestSummaryDto`
   (`email`, `phone`).
3. THE SYSTEM SHALL NOT introducir un nuevo componente, hook o helper dedicado al
   formato de importes: la corrección es del patrón, no de la presentación.

### R4 — El vacío es el mismo en ambos locales y no crea clave i18n

**As a** usuaria que cambia el idioma de la UI, **I want** que el vacío de un importe
se vea igual en español y en inglés, **so that** la convención no dependa de la
traducción.

Acceptance criteria:

1. THE SYSTEM SHALL usar el mismo carácter (`—`) para el vacío de importe en los dos
   locales (`locales/es/reservations.json` y `locales/en/reservations.json`).
2. THE SYSTEM SHALL NOT añadir una nueva clave i18n para «importe vacío»: la raya em
   no se localiza.
3. THE SYSTEM SHALL respetar la convención existente del fichero (`guestId ?? "—"` en
   `reservations-view.tsx:156`): mismo carácter, mismo tratamiento en ambos locales.

## Out of scope

- **El UUID de la columna Property** (`reservations-view.tsx:159`). Es el otro defecto
  que la misma maqueta de Stitch destapó, pero no es de presentación: el backend no
  tiene nombre que dar. Tiene entrada propia, `reservation-property-identity`.
- **Formato y localización de importes.** Hoy se concatena la cadena cruda del
  backend con el código de divisa, sin `Intl.NumberFormat` ni separadores por locale.
  Es una decisión de producto más grande —afecta a `pricing` y a `statements`
  igual— y no se resuelve de rebote aquí. Si se quiere, es su propia entrada.
- **Render de nulables que no usan `?? ""`** en la feature (`accessStatus`,
  `internalNotes`, `specialRequests`, `guest`, `checkInTime`, `checkOutTime`, etc.).
  Ya se renderizan sin el patrón roto; barrerlos aquí es trabajo de otro change.

## Affected specs

- `sdd/specs/reservations-web.md` — render de la lista y la ficha, y la cobertura de
  test del caso nulo.
- `sdd/specs/frontend-api-contract-consumer.md` — solo si la corrección obliga a
  tocar el mapper HTTP; no se espera, porque el DTO ya declara los nulables.