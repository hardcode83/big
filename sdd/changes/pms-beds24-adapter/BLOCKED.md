# Blocked — pms-beds24-adapter

## 1. Ejecuciones del banco de medición contra la cuenta de Beds24

- **Fase**: run (tareas 1.2 y 1.5)
- **Tipo**: `decision` — necesita un humano con la credencial
- **Qué y por qué**: no hay `BEDS24_REFRESH_TOKEN` en el entorno de la sesión, y `beds24_probe.py` lo lee **solo** del entorno por diseño (nunca por argumento, `specs/pms-beds24-spike.md`). El código del banco está escrito y verificado offline (92 tests), pero nadie ha ejecutado nada contra el proveedor. Falta medir:
  1. Que `modifiedFrom` existe, en qué formato lo acepta y cuánto cuesta.
  2. Si `/bookings` devuelve las canceladas sin pedirlas, y si admite un filtro de estado que excluya los bloqueos `black`.
  3. La ventana completa: crear → modificar → cancelar, con la reserva visible en las tres.
  4. La re-medición que respalda las cinco filas hoy transcritas del informe.
- **Cómo desatascarlo**: con la credencial en el entorno, desde `backend/`:

  ```
  BEDS24_REFRESH_TOKEN=... uv run python scripts/beds24_probe.py probe --out ../docs/beds24-request-cost.jsonl
  BEDS24_REFRESH_TOKEN=... uv run python scripts/beds24_probe.py window --room=<roomId> --confirm-writes --out ../docs/beds24-request-cost.jsonl
  BEDS24_REFRESH_TOKEN=... uv run python scripts/beds24_probe.py capture --out ../docs/beds24-request-cost.jsonl
  uv run python scripts/beds24_probe.py report --out ../docs/beds24-request-cost.jsonl
  ```

  `window` **escribe** en la cuenta (crea, modifica y cancela una reserva directa, sin canal), aprobado en OQ3 del design. Sus guardas siguen vigentes: exige `--confirm-writes`, verifica que la cuenta tiene exactamente una propiedad y que el room le pertenece, y aborta antes de modificar si la creación devuelve una forma no reconocida.
- **Comando de reanudación**: `/sdd:run pms-beds24-adapter 1`

## 2. Decisión pendiente: el «coste de un ciclo» deja de ser 8 créditos

- **Fase**: run (consecuencia de la tarea 1.1, se materializa al ejecutar 1.5)
- **Tipo**: `decision`
- **Qué y por qué**: las formas `modifiedFrom` entran en `CATALOGUE`, que es lo que `report()` considera «un ciclo de sync» — y con razón, porque es la consulta que el adapter real va a emitir. Pero eso cambia la cifra publicada de **8 créditos por ciclo → un sync cada 24 s**, que no es un número cualquiera: la citan `specs/pms-beds24-spike.md`, `specs/pms-provider-resolution.md`, la entrada del roadmap y la justificación de la **regla 9 de `steering/security.md`** (el volumen de filas de `AuditLog` que la excepción de granularidad existe para evitar). Hay dos salidas y no son equivalentes:
  1. **Republicar** la cifra nueva y propagarla a los cuatro sitios que la citan (más honesto: es lo que el sync hará de verdad).
  2. **Separar** en el informe «ciclo de validación» de «ciclo de sync real», dejando 8 como está.
- **Cómo desatascarlo**: decidir con Jose al ver la medición real, antes de tocar `docs/beds24-spike.md`.
- **Comando de reanudación**: `/sdd:run pms-beds24-adapter 1`

## 3. Decisión de diseño: `special_requests` se persiste sin pasar por el scrubber

- **Fase**: run (panel de seguridad de la sección 2, hallazgo 3)
- **Tipo**: `decision` — amplía o acota D9, y no debe decidirse en silencio
- **Qué y por qué**: el scrubber protege `raw_payload`, que **no se persiste** (vive en memoria y ninguna columna lo almacena), y no toca `special_requests`, que **sí**: los dos mapeos lo llenan con texto libre del proveedor (`notes` en Channex, `comments` en Beds24) y de ahí va a `ingest.py` → columna `reservations.special_requests` → respuesta de la API. La regla 13(a) dice «eliminarlos en el adapter… antes de que nada pueda **persistirlos**, loguearlos o reenviarlos», así que el texto alcanza literalmente el verbo que la regla nombra. La regla 11 no lo cubre: ella misma se acota a «un valor de la regla 3», y los datos de tarjeta no están en la regla 3 — eso es justo lo que motivó que la 13 existiera.
- **Lo que NO está medido, y conviene decirlo**: no hay ninguna observación en este repositorio de dígitos de tarjeta dentro de `notes`/`comments`. Es texto que teclea un huésped o un agente, así que es plausible, no demostrado. El hallazgo medido (`raw_message`) ya está corregido.
- **Las dos salidas, y ninguna es gratis**:
  1. **Filtrar por valor** el texto libre que se promueve a un campo del DTO: exige detectar un PAN dentro de una cadena (Luhn + rachas de dígitos), con falsos positivos reales — una referencia de reserva de 16 dígitos — sobre un campo que el personal de limpieza lee.
  2. **Declarar en D9** que el texto libre persistido queda fuera de la frontera de la regla 13, y por qué. Es la opción barata, y deja constancia en vez de dejarlo por omisión, que es como estaba.
- **Cómo desatascarlo**: decidir con Jose. Si es la 1, es trabajo de esta sección; si es la 2, es un párrafo en `design.md` y una nota en la spec al archivar.
- **Comando de reanudación**: `/sdd:review pms-beds24-adapter`

## 4. Dónde excluir los bloqueos de calendario (D10, enmendada)

- **Fase**: run (panel de arquitectura de las secciones 3-5)
- **Tipo**: `deferred` — el flujo lo reanuda cuando la 1.2 mida
- **Qué y por qué**: D10 elegía excluir los `status: black` **en la consulta** y dejaba el descarte en el adapter como plan B. Lo que se entrega es el plan B, incondicionalmente, porque la medición que decidía entre los dos está bloqueada. El design ya está enmendado para decirlo. Lo pendiente es solo la optimización: si `/bookings` admite un filtro de estado, mover la exclusión ahorra traerse filas que se tiran. Con dos propiedades no se nota; a escala SaaS sí.
- **Cómo desatascarlo**: al ejecutar la 1.2, comprobar si el filtro existe y decidir. No bloquea el merge.
- **Comando de reanudación**: `/sdd:run pms-beds24-adapter 1`

## 5. Fixtures de reserva modificada y cancelada

- **Fase**: run (tarea 1.4 producida, 4.1 consumidora)
- **Tipo**: `deferred` — el flujo lo reanuda solo en cuanto exista la credencial
- **Qué y por qué**: `bookings_modified.json` y `bookings_cancelled.json` los produce el subcomando `window`, que está bloqueado por lo de arriba. Sin ellos, el mapeo de `cancelTime` y de un `status` distinto de `confirmed` se prueba con **variantes derivadas del fixture real** en lugar de con capturas del proveedor, que es evidencia de peor calidad y así queda marcado en los tests. **No se inventan fixtures**: las variantes se construyen modificando explícitamente el payload real capturado y el test dice que eso es lo que son.
- **Comando de reanudación**: `/sdd:run pms-beds24-adapter 1` y después re-verificar la sección 4.
