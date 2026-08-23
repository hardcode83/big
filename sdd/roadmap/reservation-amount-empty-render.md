# reservation-amount-empty-render

[TECH] **una reserva sin importe pinta un código de divisa suelto.** No es un bug de datos:
`gross_amount` es legítimamente nulable en el contrato y el render del caso vacío está mal.

Descubierto analizando el export de Stitch del 2026-08-23: su maqueta de reservas —la de
mayor fidelidad de las seis, hecha sobre la pantalla real— pinta `EUR` sin cifra en **tres
de sus cuatro filas**, porque lo copió de la pantalla. Ver
`docs/design/2026-08-23-stitch-export/README.md`.

## Los cuatro sitios

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

Los cuatro producen `" EUR"` —con espacio inicial— cuando el importe es nulo. El detalle
es peor que la lista: puede enseñar **tres** divisas huérfanas seguidas en la misma ficha.

## Por qué esto no se discute: el fichero ya sabe hacerlo bien

`reservations-view.tsx:156`, **diez líneas antes** del sitio roto:

```tsx
{row.guestId ?? "—"}
```

Mismo fichero, mismo componente, mismo tipo de campo nulable, idioma correcto. No hay que
inventar convención ni negociar copia: la raya em ya es el vacío de esta tabla. Lo único
que hay que decidir es si el vacío se localiza (clave i18n) o es el mismo guion literal
que ya usa `guestId` — y por coherencia con el vecino, es lo segundo.

## La causa raíz está en los tests, y es la parte que importa

**Ningún test renderiza el caso nulo.** Los cuatro render tests fijan un importe presente:

- `reservations-view.test.tsx:35` → `grossAmount: "612.50"`
- `reservation-detail-view.test.tsx:35` → `grossAmount: "612.50"`
- `http-reservations-source.test.ts:69,178` → `grossAmount: "612.50"`

El único `grossAmount: null` del árbol está en `use-reservations.test.tsx:69`, que es un
test de **hook**: comprueba el mapeo del DTO y no pinta ninguna celda. Así que la rama
`?? ""` de los cuatro sitios tiene **cobertura cero**, y por eso se entregó.

Consecuencia para el alcance: arreglar los cuatro `??` sin añadir el test del caso nulo
deja el agujero abierto para el siguiente campo nulable. El entregable son las dos cosas,
y el test es el que impide la recaída.

## Ojo: `grossAmount` no es el único nulable de la fila

`features/reservations/data/dto.ts` declara nulables `grossAmount`, `guestId` y —en el
detalle— `netAmount` y `otaCommission`. `guestId` ya está cubierto. Al pasar por aquí
conviene barrer los nulables del DTO **una vez** y comprobar que cada uno tiene un render
de vacío explícito, en vez de arreglar solo los cuatro que este análisis encontró: el
patrón `?? ""` es el que hay que erradicar, no sus instancias conocidas.

## Fuera de alcance

- **El UUID de la columna Property** (`reservations-view.tsx:159`). Es el otro defecto que
  la misma maqueta destapó, pero no es de presentación: el backend no tiene nombre que
  dar. Tiene entrada propia, `reservation-property-identity`.
- **Formato y localización de importes.** Hoy se concatena la cadena cruda del backend con
  el código de divisa, sin `Intl.NumberFormat` ni separadores por locale. Es una decisión
  de producto más grande —y afecta a `pricing` y a `statements` igual— así que no se
  resuelve de rebote aquí. Si se quiere, es su propia entrada.
