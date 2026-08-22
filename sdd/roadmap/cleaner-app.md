# cleaner-app

[FE] la app de la limpiadora, mobile-first: `/cleaner` y `/cleaner/tasks/[id]` (PRD §26.19, §24).

> Esta nota se escribió para `field-apps`, que el 2026-08-18 se partió en cuatro
> (`cleaning-manager-view`, `cleaner-app`, `tech-app`, `conversations-inbox`).
> La decisión que describe es de la app de la limpiadora —es la que muestra accesos a un
> rol que hoy no los ve—, así que viaja aquí entera y no a las otras tres.

## Hereda de `access-notifications` una decisión de steering pendiente

**`access_records.notes` no está en la tabla de sumideros de texto en claro de la regla 11**
(`sdd/steering/security.md`), y este change es el que probablemente tendrá que meterla.

Qué hay hoy: `notes` es texto libre que un operador teclea en la **misma petición** que el código
de acceso (PRD §15 lo pone en la firma del propio adapter, así que no se puede quitar sin
divergir). `AccessRecord.register_manual_code` rechaza la petición cuando el código aparece en las
notas —normalizando caja y separadores, tras dos rondas del panel de seguridad—, lo que cierra el
caso del operador descuidado. Lo que **no** cierra, y ninguna comprobación dentro de la petición
puede cerrar, es que alguien escriba *otro* código en `notes` más tarde.

Por qué cae aquí (razonamiento original, escrito cuando la entrada era `field-apps`): mientras `notes` solo lo vean el owner y el manager, el radio es el de quien ya
puede registrar el código. En cuanto la app de la limpiadora muestre accesos, la superficie crece
a un rol que hoy no tiene `READ_ACCESS_RECORDS` — y ahí el residual deja de ser aceptable.

Qué hacer entonces, según la propia regla 11 («con una entrada nueva y nombrada aquí, aprobada en
el design del change que la pida»): añadir `access_records.notes` a su tabla y decidir la forma —
cifrado en reposo, o exclusión de los listados, o ambas. La decisión la tomó Jose el 2026-08-08:
no en `access-notifications`, que no la necesita para cumplir su R2.6, sino aquí.

Precedente aplicable: `properties.access_notes` / `cleaning_notes` / `emergency_notes` estaban en la
misma situación —auditables pero no denylisted, con la disciplina en el caso de uso
(`properties-crud` design D7)—, así que la decisión debería cubrir las cuatro columnas a la vez o
decir explícitamente por qué no.

**Y una de las cuatro ya está decidida, así que esta nota ya no describe la decisión entera.**
`tech-incident-context` (2026-08-21) amplió el público de `properties.access_notes` al rol
`TECHNICIAN` y con ello le tocó decidir su forma: entró en la tabla de la regla 11 con **excepción
6** y con su mecanismo implementado —las **tres** notas de `properties` salieron del listado
paginado—, y dijo explícitamente por qué las otras dos no ganan fila del censo: no las lee ninguna
proyección nueva, así que no ganan lector, y su propósito no es transportar un valor de la regla 3.
Es el «decir explícitamente por qué no» que el párrafo anterior pedía, resuelto para tres de las
cuatro.

Lo que queda de esta nota, entonces, son **dos cosas y no una**:

- **`access_records.notes` sigue siendo de aquí**, con el razonamiento de arriba intacto: su
  mitigación actual (`AccessRecord.register_manual_code` rechaza la petición cuando el código
  aparece en las notas) no es trasladable a `access_notes`, porque allí no hay código en claro
  almacenado contra el que comparar. El disparador sigue siendo el mismo: que la app de la
  limpiadora muestre accesos.
- **La mitad de cifrado en reposo dejó de ser de esta nota** y vive en
  `sdd/roadmap/plaintext-sink-encryption-at-rest.md`, que cubre las cuatro columnas juntas —las
  tres de `properties` y esta— porque la amenaza que responde (lectura offline de la base, de un
  backup o de una réplica) es idéntica para todas y no la mueve ningún change de audiencia.
  `tech-incident-context` la rechazó con su motivo escrito, no por olvido.
