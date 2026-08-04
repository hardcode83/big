# BLOCKED — pms-beds24-spike

Una entrada. **La cuenta ya existe y la medición está hecha**, salvo un requisito que resultó
no ser medible en las condiciones que otro requisito impone.

---

## 1. R2 (latencia y orden de los webhooks) no es medible sin canales conectados

- **Fase**: run (tarea 7.3 de `tasks.md`)
- **Tipo**: `decision` — necesita una persona porque **es un conflicto entre dos requisitos del
  propio proposal**, no un fallo de implementación, y resolverlo cambia el alcance.
- **Comando para retomar**: no hay. Requiere la decisión de abajo.

### Qué pasa

R2 pide medir la latencia y el orden de los webhooks. Medido el 2026-08-04: Beds24 **solo
dispara webhooks para reservas de canal** — su documentación lo dice (*«when a booking is
created, modified or cancelled **by a channel**»*) y la medición lo confirma.

**R6.1 prohíbe conectar ningún canal OTA a esta cuenta**, porque REDES11 y PAJARITOS8 están
vendiendo y Airbnb admite un único channel manager por cuenta.

Medir R2 exigiría exactamente lo que R6.1 prohíbe. Los dos requisitos son correctos por separado
y no pueden satisfacerse a la vez.

### Qué se descartó antes de concluirlo

- El banco funciona: sink, túnel efímero, webhook configurado **por API**, camino verificado de
  punta a punta con un `POST` manual que llegó en **246 ms**.
- **Tres eventos reales** sobre una reserva de verdad —crear, modificar, cancelar— y **cero
  webhooks**. El túnel seguía vivo, comprobado después.
- **No falta habilitar nada**: la página Settings → Properties → Access muestra los mismos
  cuatro campos que escribe la API y ningún interruptor extra.
- `Additional Data` descartada como causa: sus valores son `None / CVC / Token / CVC and Token`
  — controla si el payload lleva datos de tarjeta, no si se envía.

### La decisión

**Opción A (recomendada): amender R2 en `proposal.md` y cerrar el change.** R2 pasa a estar
condicionado a la existencia de un canal conectado, y la medición se traslada a la **ventana de
corte de `pms-beds24-adapter`**, que es cuando los canales se conectan de verdad y no cuesta ni
una cuenta extra ni riesgo nuevo. Lo demás del spike está medido y entregado, incluido lo que
bloqueaba a `celery-jobs`.

**Opción B: dejar el change abierto** hasta poder medir R2. Significa mantenerlo vivo semanas,
con el trial caducando, para un dato que llegará igual con `pms-beds24-adapter`.

**Opción C: una segunda cuenta con un canal real.** Ningún proveedor evaluado salvo Channex da
sandbox de OTA (ADR 0006), así que «canal de test» significa un anuncio real en una OTA real.
Coste y riesgo propios, y no parece justificado por el dato que devuelve.

## Lo que sí quedó medido

Tareas 7.1, 7.2 (reserva; el mensaje no, misma causa), 7.4 y 7.5. Entre otras cosas:

- **Presupuesto de créditos**: ciclo de 8 créditos, cadencia máxima sostenible de un sync cada
  24 s por cuenta. Era la incógnita que bloqueaba `celery-jobs`.
- **Escrituras a 1,1 créditos** — coste fraccionario confirmado.
- **Fixture real de reserva**, 73 campos, anonimizado.
- **Cuatro contradicciones o hallazgos con peso arquitectónico**: los webhooks sí tienen API
  (ADR 0006 dice que no), el refresh token no rota, Beds24 responde `201` incluso cuando rechaza
  una escritura, y **puede enviarte el CVC en el webhook** si alguien toca un desplegable.
