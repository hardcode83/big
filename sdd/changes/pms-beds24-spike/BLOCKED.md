# BLOCKED — pms-beds24-spike

Una entrada. El banco de medición está construido, probado y commiteado; lo que falta es la
cuenta contra la que medir, y eso no lo puede resolver un agente.

---

## 1. Falta la cuenta de desarrollo de Beds24

- **Fase**: run (sección 7 de `tasks.md`)
- **Tipo**: `decision` — necesita una persona: hay que registrarse, poner una tarjeta y
  arrancar un reloj de 14 días.
- **Comando para retomar**: `/sdd:run pms-beds24-spike 7`

### Qué hay que hacer

1. Dar de alta una cuenta de desarrollo en Beds24 (trial de 14 días, ~€15,50/mes después).
   **Sin conectar ningún canal OTA** — es la regla dura de R6.1, y con REDES11 y PAJARITOS8
   vendiendo no es una formalidad: Airbnb admite un único channel manager por cuenta.
2. Obtener el refresh token (código de invitación → refresh token) y exportarlo:
   `export BEDS24_REFRESH_TOKEN=...`
3. Tener `cloudflared` disponible para el túnel efímero de la medición de webhooks.
4. Reservar una hora seguida: la medición de webhooks necesita provocar hechos y esperarlos.

El runbook completo, paso a paso, está en [`docs/beds24-spike.md`](../../../docs/beds24-spike.md).

### Por qué está bloqueado y no simplemente pendiente

Los criterios de aceptación de este change **son mediciones** (R1.1-R1.4, R2.1-R2.5, R3.1,
R4.2, R5.1). No hay forma de satisfacerlos sin la cuenta, así que el change no puede alcanzar
`READY_FOR_PR`: no es que falte pulir algo, es que la mitad del entregable no existe todavía.

Esto **estaba previsto** desde el diseño (D10) y es el motivo del orden que eligió el roadmap.
El trial de 14 días empieza a contar al registrarse, así que el banco se construye **antes** de
abrir la cuenta para que los 14 días vayan íntegros a medir y no a escribir herramientas. Es la
misma razón por la que esta entrada se separó de `channex-staging-adapter`.

### Qué está hecho y no hay que rehacer

Secciones 1-6 de `tasks.md`, todas verificadas con la suite en verde (2479 passed, 35 skipped):

- `backend/scripts/anonymise.py` — el anonimizador fail-closed, extraído y compartido con el
  probe de Channex, con el invariante de orden fijado por test.
- `backend/scripts/beds24_probe.py` — canje de token, allowlist de host, autolimitación de
  ritmo, registro de coste por petición y subcomando `report`.
- `backend/scripts/beds24_webhook_sink.py` — receptor sellado en UTC, anonimización antes de
  disco, latencia por `booking_ref` y detección de desorden.
- `docs/beds24-spike.md` — runbook y hallazgos, cada medida marcada *no medido*.
- `.env.example`, `docs/README.md` y la regla 8 de `sdd/steering/security.md`.

### Espera dos negativas del script en la primera ejecución, y son correctas

El banco se escribió sin cuenta, así que lleva **cinco supuestos** sobre la API V2 marcados
como `ASSUMPTION`. El paso 0 del runbook los enumera en una tabla y hay que confirmarlos contra
la especificación OpenAPI publicada **antes** de la primera llamada autenticada. Dos de ellos
provocan un rechazo deliberado hasta que los confirmes:

1. **`provoke` exige `--confirm-writes`.** Es la única subcomanda que escribe: crea, modifica y
   cancela una reserva.
2. **El guardia de canales falla cerrado.** Antes de escribir lee `/properties` y, si no
   reconoce ninguna clave de canales en la respuesta, **se niega**. No es un bug: la forma de
   esa respuesta es un supuesto, y «no entendí la respuesta» no puede significar «la cuenta
   está limpia» cuando al otro lado hay dos viviendas vendiendo y Beds24 no tiene staging. La
   salida correcta es mirar la respuesta real y añadir el nombre de clave, no esquivar el
   chequeo.

Los otros tres —el host, los nombres de cabecera del flujo de token y las claves que llevan la
identidad de la reserva— fallan de forma más silenciosa, y por eso conviene confirmarlos antes
de gastar créditos. Si alguno falla, el arreglo es de una línea.
