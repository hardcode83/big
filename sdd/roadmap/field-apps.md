# field-apps

[FE] apps mobile-first de limpiadora y técnico + bandeja de conversaciones (PRD §26.18-21, §24).

## Hereda de `access-notifications` una decisión de steering pendiente

**`access_records.notes` no está en la tabla de sumideros de texto en claro de la regla 11**
(`sdd/steering/security.md`), y este change es el que probablemente tendrá que meterla.

Qué hay hoy: `notes` es texto libre que un operador teclea en la **misma petición** que el código
de acceso (PRD §15 lo pone en la firma del propio adapter, así que no se puede quitar sin
divergir). `AccessRecord.register_manual_code` rechaza la petición cuando el código aparece en las
notas —normalizando caja y separadores, tras dos rondas del panel de seguridad—, lo que cierra el
caso del operador descuidado. Lo que **no** cierra, y ninguna comprobación dentro de la petición
puede cerrar, es que alguien escriba *otro* código en `notes` más tarde.

Por qué cae aquí: mientras `notes` solo lo vean el owner y el manager, el radio es el de quien ya
puede registrar el código. En cuanto la app de la limpiadora muestre accesos, la superficie crece
a un rol que hoy no tiene `READ_ACCESS_RECORDS` — y ahí el residual deja de ser aceptable.

Qué hacer entonces, según la propia regla 11 («con una entrada nueva y nombrada aquí, aprobada en
el design del change que la pida»): añadir `access_records.notes` a su tabla y decidir la forma —
cifrado en reposo, o exclusión de los listados, o ambas. La decisión la tomó Jose el 2026-08-08:
no en `access-notifications`, que no la necesita para cumplir su R2.6, sino aquí.

Precedente aplicable: `properties.access_notes` / `cleaning_notes` / `emergency_notes` están en la
misma situación —auditables pero no denylisted, con la disciplina en el caso de uso
(`properties-crud` design D7)—, así que la decisión debería cubrir las cuatro columnas a la vez o
decir explícitamente por qué no.
