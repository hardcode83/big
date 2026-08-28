# staff-messaging

[BE] **el tramo de comunicación que no existe en absoluto: limpiadora↔manager y técnico↔manager**.

**El hecho medido (2026-08-28)**, y son cuatro comprobaciones independientes que apuntan al mismo sitio:
`MessageSenderType` tiene cinco miembros —`GUEST`, `OWNER`, `MANAGER`, `AI`, `SYSTEM`— y **ninguno de campo**;
`ROLE_PERMISSIONS` da a `CLEANER` exactamente `_SELF_SERVICE | _CLEANING_EXECUTE` y a `TECHNICIAN`
`_SELF_SERVICE | _INCIDENT_EXECUTE`, de modo que las siete rutas de `/conversations` les contestan `403`;
`policy.py` lo argumenta por escrito —*"`CLEANER` and `TECHNICIAN` get neither — a guest's conversation is
not part of doing a cleaning or a repair"*—; y no hay ninguna otra tabla, ruta ni entidad de mensajes entre
personal. La comunicación con la limpiadora y con el técnico es hoy **estrictamente unidireccional**: filas
`NotificationLog` que el sistema les escribe, sin vía de respuesta.

**Lo que decide, y es la razón de que esto necesite `/sdd:design` propio**: `Conversation` es del huésped
**por contrato**, no por casualidad. Ensancharla —añadir dos `sender_type`, abrir `READ_CONVERSATIONS` a dos
roles y meter un concepto de participantes— revienta la afirmación de `policy.py`, obliga a filtrar la
bandeja del manager para que la limpiadora no vea hilos de huéspedes, y convierte una entidad con
escalación, intents y umbral de confianza en dos cosas distintas con el mismo nombre.

**Recomendación de entrada** (a validar en design, no dada por cerrada): un hilo **acotado a la tarea o a la
incidencia** —`CleaningTaskMessage` / `IncidentMessage`, o una sola entidad con `related_type`/`related_id`
como ya hace `NotificationLog`—, porque:

- la autorización **ya existe y está probada**: `restrict_to_cleaner_id` y `restrict_to_technician_id`
  derivados del token, nunca de un campo de la petición, que es el patrón que `cleaning`, `maintenance`,
  `cleaner-task-context` y `tech-incident-context` aplican los cuatro;
- el alcance de lectura es el que esos roles ya tienen (su tarea, su incidencia), así que no estrena
  permiso de lectura sobre nada que hoy no vean;
- no toca `messaging`, así que la IA, la escalación y el umbral de confianza se quedan donde están y no hay
  que decidir si el técnico habla con un modelo.

**Lo que hay que decidir igualmente**: (1) si el mensaje del personal genera `TimelineEvent` —el timeline es
append-only y no se puede redactar, así que meter texto libre ahí es una decisión de la regla 11, no una
comodidad—; (2) si genera notificación al otro extremo, que es lo que lo hace útil y lo acopla a
`notifications-inbox-web`; (3) el sumidero de texto: `content` es texto libre de dos roles nuevos y necesita
`storable_text` como los de `maintenance`, con su fila en el censo de la regla 11 de `steering/security.md`;
(4) si el manager puede escribir a una tarea ya cerrada.

**Fuera de alcance a propósito**: huésped↔limpiadora y huésped↔técnico. Nadie lo ha pedido, PRD §11 y §12 no
lo contemplan, y abriría la identidad del personal a un portador anónimo.
