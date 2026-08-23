# Proposal: incident-photos

## Why

`sdd/specs/file-storage.md` nombra a `maintenance` (fotos de incidente) como uno de sus dos
siguientes consumidores, y esa es la **razón declarada** de que la capability de almacenamiento
viva en `app/integrations/` y no colgando de `cleaning`. Hoy ese consumidor no existe: no hay
entidad, no hay ruta, y `IncidentPhoto` / `incident_photos` no aparece en ninguna línea del
backend (verificado el 2026-08-22 sobre todo `backend/`). Mientras tanto PRD §6 le concede al rol
`TECHNICIAN` «subir fotos (antes y después)» y PRD §12 lo pide dos veces —«fotos del incidente» y
«subir fotos finales»—, y el flujo de §12 dibuja literalmente «Técnico sube fotos y coste final».

Es una de las tres entradas `[BE]` que salieron de cerrar el `/sdd:new` de `tech-app` **sin
proposal** el 2026-08-19: de las once cosas que PRD §12 pide, el rol `TECHNICIAN` solo podía
llamar cuatro. El censo entero está en `sdd/roadmap/tech-app.md`, y `tech-app` declara
`needs: … incident-photos …`. Las otras dos hermanas ya están cerradas
(`tech-incident-context`, 2026-08-22) o son independientes (`tech-cycle-completion`).

Lo que este change **no** decide, porque ya está decidido: proveedor, esquema de claves, detección
de formato y esquema de firma los cerraron `cleaning-photos-storage` y
`object-storage-provisioning` (`sdd/specs/file-storage.md`, [ADR 0008](../../../docs/adr/0008-object-storage-provider-dev.md)).
Decide **entidad, rutas, quién puede llamarlas y qué distingue una foto de llegada de una de
cierre**.

## What changes

Aparece la entidad `IncidentPhoto` (tabla `incident_photos`) y, sobre ella, tres rutas: la subida
y el listado de las fotos de una incidencia —autenticadas, bajo los permisos que `maintenance` R8
ya reparte, y acotadas por fila a la incidencia asignada al llamante cuando su rol es
`TECHNICIAN`— y la ruta de servido local firmada que los tenants con `storage_type = LOCAL`
necesitan para que un `<img src>` funcione. Cada fila declara su etapa en un enum cerrado de dos
valores, `BEFORE` / `AFTER`, que es exactamente lo que PRD §6 concede al rol. Todo el
almacenamiento va por el puerto compartido de `app/integrations/`, sin tocarlo: este change es su
segundo consumidor, no su modificación.

Es el calco deliberado de `specs/cleaning.md` §Fotos de la limpieza, con **una diferencia
estructural que hay que nombrar**: una tarea de limpieza tiene plantilla, y su plantilla declara
los `photo_type` admisibles; una incidencia no tiene plantilla, así que el conjunto de etapas
admisibles es un enum del dominio y no una consulta.

## Requirements

### R1 — La entidad de la foto de incidente

**Como** sistema, **quiero** una fila por foto de incidente con su etapa y su clave de
almacenamiento, **para que** exista el consumidor que `specs/file-storage.md` lleva nombrando
desde que se escribió.

Criterios de aceptación:

1. THE SYSTEM SHALL persistir una entidad `IncidentPhoto` en la tabla `incident_photos` con al
   menos `id`, `tenant_id`, `incident_id`, `uploaded_by`, `stage`, `storage_key` y `created_at`,
   siguiendo la convención de `steering/backend.md` (UUID PK, `tenant_id` en toda entidad,
   `TIMESTAMPTZ`).
2. THE SYSTEM SHALL declarar `stage` como enum cerrado de **dos** valores, `BEFORE` y `AFTER`, y
   NEVER SHALL admitir un tercer valor ni un campo de texto libre de tipo de foto: no hay plantilla
   que lo acote y un texto del llamante sería un sumidero nuevo de la regla 11 de
   `steering/security.md` sin pantalla que lo muestre.
3. THE SYSTEM SHALL llevar `tenant_id` en la propia fila —y no solo derivarlo por la incidencia—,
   de modo que la tabla sea alcanzable por el filtro global de tenant y admita su propio test de
   aislamiento (regla 1 de `steering/security.md`). `cleaning_photos` **no** lo tiene y su
   aislamiento se demuestra por la tarea; esta decisión se aparta del precedente a propósito y el
   diseño debe confirmarla o revertirla explícitamente.
4. THE SYSTEM SHALL admitir **varias fotos de la misma etapa** para una misma incidencia, sin
   restricción de unicidad: un técnico fotografía dos ángulos de la misma avería.
5. THE SYSTEM SHALL NOT persistir el `Content-Type` detectado ni el nombre de fichero que envía el
   cliente en ninguna columna, coherente con `file-storage.md` (el `Content-Type` de servido se
   deriva de la extensión de la clave, y el nombre del cliente no toca la clave).
6. `ASSUMPTION`: la entidad **no está en el PRD**. PRD §7.13 `Incident` no tiene columna de fotos y
   PRD §7 solo define `CleaningPhoto` (§7.12). Esta entidad extiende el modelo del PRD y SHALL
   quedar marcada como `ASSUMPTION` donde se declare, igual que la desviación que `cleaning`
   registró para sus plantillas.

### R2 — Subir una foto a una incidencia

**Como** técnico asignado, **quiero** subir la foto de llegada y la de cierre desde la incidencia,
**para que** quede la evidencia que PRD §6 y §12 me atribuyen.

Criterios de aceptación:

1. WHEN el técnico asignado solicita `POST /api/v1/incidents/{incident_id}/photos` con un fichero
   y una etapa `BEFORE` o `AFTER`, THE SYSTEM SHALL almacenar el fichero por el puerto compartido,
   persistir la fila de `IncidentPhoto` y responder `201` con la foto y su URL firmada.
2. THE SYSTEM SHALL exigir `EXECUTE_INCIDENTS` para subir, sin crear permiso nuevo, y SHALL
   permitirlo por tanto al técnico asignado y a `PROPERTY_MANAGER` —que `maintenance` R6 ya
   autoriza a conducir todo el ciclo del técnico «para desatascar»— y a nadie más.
3. THE SYSTEM NEVER SHALL permitir la subida a un técnico que no sea el asignado, y esa negativa
   SHALL ser indistinguible de «no existe», derivando la restricción del **rol del token** y nunca
   de un campo de la petición (`maintenance` R8; el mismo `restrict_to_technician_id`).
4. THE SYSTEM SHALL admitir la subida únicamente con la incidencia en `IN_PROGRESS` o
   `WAITING_EXTERNAL_PARTS` —los dos estados en los que el trabajo del técnico está en curso—, y
   IF está en cualquier otro estado THEN SHALL responder `409` sin escribir nada: ni fila ni objeto
   en el almacén.
5. IF la incidencia está en `AWAITING_OWNER_APPROVAL`, THEN THE SYSTEM SHALL rechazar la subida con
   el mismo error que `maintenance` R1 reserva para ese caso, distinguible de una transición fuera
   de orden.
6. IF la incidencia está en un estado terminal (`RESOLVED`, `CANCELLED`), THEN THE SYSTEM SHALL
   rechazarla con el error de incidencia ya cerrada de `maintenance` R1, y NEVER SHALL modificar
   nada.
7. THE SYSTEM SHALL escribir el objeto en el almacén **antes** de insertar la fila y borrarlo en
   *best effort* si la transacción falla: una fila que apunte a un objeto inexistente es un `GET`
   roto para siempre; un objeto sin fila es basura recuperable.
8. IF la escritura en el almacén falla, THEN THE SYSTEM SHALL responder `502` con código
   `BAD_GATEWAY` y no dejar fila (`specs/api-contract.md`, el código que introdujo
   `cleaning-photos-storage`).
9. IF el contenido no es una imagen de la allowlist, THEN THE SYSTEM SHALL responder `422`; IF
   supera el tope de tamaño, THEN `413`. El formato SHALL decidirse por los **bytes** y nunca por
   el `Content-Type` declarado (regla 6 de `steering/security.md`).
10. IF la etapa recibida no es `BEFORE` ni `AFTER`, THEN THE SYSTEM SHALL responder `422`, y no
    `404`: a diferencia del `photo_type` de limpieza, el conjunto admisible no depende de ninguna
    fila y por tanto no hay nada cuya existencia se pueda filtrar.

### R3 — Listar las fotos de una incidencia

**Como** manager o propietaria, **quiero** ver las fotos de una incidencia, **para que** la
evidencia del trabajo sea legible sin pedírsela al técnico.

Criterios de aceptación:

1. WHEN se solicita `GET /api/v1/incidents/{incident_id}/photos`, THE SYSTEM SHALL devolver las
   fotos de esa incidencia de la más antigua a la más reciente, cada una con su etapa y una URL
   firmada **acuñada para esa respuesta**.
2. THE SYSTEM SHALL exigir `READ_INCIDENTS` para listar —leer la evidencia es lo que hacen el
   manager y la propietaria, subirla es del técnico— y SHALL aplicar el mismo acotamiento por fila
   que el resto del módulo: WHERE el solicitante es `TECHNICIAN`, solo las fotos de incidencias que
   tiene asignadas.
3. THE SYSTEM NEVER SHALL incluir `storage_key` en ningún cuerpo ni cabecera de respuesta. La única
   excepción es lo que una URL prefirmada de un proveedor S3-compatible lleva dentro por el propio
   protocolo de firma, ya aceptada por escrito en `file-storage.md` §Catálogo de asimetrías y
   [ADR 0008](../../../docs/adr/0008-object-storage-provider-dev.md).
4. IF la incidencia no existe, o no es del tenant, o el solicitante es un técnico que no la tiene
   asignada, THEN THE SYSTEM SHALL responder `404` de forma indistinguible en los tres casos.

### R4 — Servir la foto con `storage_type = LOCAL`

**Como** navegador, **quiero** resolver la URL firmada de la foto sin enviar cabecera de
autorización, **para que** un `<img src>` funcione.

Criterios de aceptación:

1. WHERE el `storage_type` del tenant es `LOCAL`, THE SYSTEM SHALL servir el fichero desde
   `GET /api/v1/incident-photos/{photo_id}`, **anónimo a propósito**: un `<img src>` no envía
   `Authorization`, así que exigir el token haría la URL firmada inservible para lo único que
   existe. La firma es la credencial — cubre la clave completa, que empieza por el `tenant_id`.
2. THE SYSTEM SHALL resolver `photo_id → (storage_key, tenant_id)` con una lectura **explícitamente
   sin scoping de tenant**, acotada a ese caso de uso y fuera del repositorio de fotos, y SHALL
   verificar la firma **después** de reconstruir la clave. El orden es lo que la hace segura.
3. IF la firma es inválida, ha caducado, ha sido manipulada o nombra una foto inexistente, THEN THE
   SYSTEM SHALL responder `403` con un cuerpo **constante y precomputado**, idéntico en los cuatro
   casos, para no convertir la ruta en un oráculo de existencia para un llamante sin credenciales.
4. WHERE el `storage_type` del tenant es `S3`, THE SYSTEM SHALL responder `404` en esa ruta: el
   navegador va directo al proveedor y aquí no hay nada que servir.
5. THE SYSTEM SHALL derivar el `Content-Type` únicamente de la extensión de la clave almacenada,
   emitir `X-Content-Type-Options: nosniff` con **un solo valor** en toda respuesta de la ruta, y
   responder los bytes con `Cache-Control: private, max-age=<lo que le queda a la firma>` y las
   negativas con `no-store` (`specs/backend-http-posture.md`).
6. THE SYSTEM SHALL montar esta ruta en un router propio y declararla en `ANONYMOUS_ENDPOINTS` de
   `tests/test_route_authorization.py`, de modo que sea la **segunda** ruta anónima de la
   aplicación por diff visible y no por descuido — hasta hoy `GET /api/v1/cleaning-photos/{id}` era
   la única además de login, refresh y `/health`. SHALL NOT colgarse de `incidents_router`, cuyas
   rutas cuelgan todas de un `require(...)`.

### R5 — El tope de tamaño de la subida y su posición

**Como** operador, **quiero** que una subida grande se rechace antes de leer el cuerpo, **para
que** la ruta no sea un amplificador de memoria.

Criterios de aceptación:

1. THE SYSTEM SHALL aplicar a `POST /api/v1/incidents/{incident_id}/photos` el mismo tope de subida
   de foto que ya existe (`PHOTO_UPLOAD_MAX_BYTES`, default 10 MB), comprobado **antes** de leer el
   cuerpo entero, y SHALL reutilizar el ajuste existente en lugar de introducir uno nuevo: es el
   mismo tipo de fichero por la misma clase de puerta.
2. THE SYSTEM SHALL mantener el techo JSON de 1 MiB para **todas** las demás rutas bajo
   `/api/v1/incidents`, y la rama de la foto SHALL evaluarse **antes** que la genérica en el
   proveedor por path de `MaxBodySizeMiddleware`: la ruta comparte prefijo con las doce rutas
   autenticadas del módulo y el orden del `if/elif` es lo que decide.
3. THE SYSTEM SHALL acotar esa rama por **los dos extremos** —prefijo `/incidents/` y sufijo
   `/photos`— igual que la de limpieza, para que no ensanche el techo de ninguna otra ruta del
   módulo, y SHALL cubrirlo con un test que falle si alguien lo sube globalmente.

### R6 — Auditoría y aislamiento

**Como** auditor, **quiero** que cada subida quede registrada y que ningún tenant alcance las fotos
de otro, **para que** las reglas 1 y 9 de `steering/security.md` se cumplan en este módulo también.

Criterios de aceptación:

1. THE SYSTEM SHALL registrar cada subida en `AuditLog` con actor e IP, contra la **propia foto**
   como entidad y no contra la incidencia, por el motivo por el que existe `ENTITY_CLEANING_PHOTO`.
2. THE SYSTEM NEVER SHALL incluir `storage_key` entre los campos auditables de esa entidad: la
   clave interna no entra en la columna diseñada para volcarse.
3. THE SYSTEM SHALL entregar test de aislamiento propio que demuestre que las filas de
   `incident_photos` de un tenant no son alcanzables desde otro por ninguna de las tres rutas.
4. THE SYSTEM SHALL declarar la **única** excepción de scoping —la lectura sin filtro de tenant que
   sirve la ruta anónima de R4— con el mismo tratamiento que su gemela de limpieza: fuera del
   repositorio de fotos y nombrada donde el censo de excepciones la vea.
5. THE SYSTEM SHALL NOT introducir ningún sumidero nuevo de texto libre del llamante, y por tanto
   NOT añade fila al censo de sumideros de la regla 11 de `steering/security.md`. Es consecuencia
   directa del enum cerrado de R1.2, y SHALL verificarse contra el guardián
   `backend/tests/test_rule11_ownership.py`.
6. THE SYSTEM SHALL regenerar `backend/openapi.json` (`make openapi`) y el artefacto derivado del
   frontend en el mismo PR, las dos mitades del mismo puente (`steering/documentation.md`).

## Out of scope

- **Puerta de evidencia en `resolve`.** `resolve` sigue exigiendo únicamente `final_cost`
  (`maintenance` R6) y la foto de cierre es **opcional**. Decidido explícitamente: añadir la puerta
  toca R6, la tabla de transiciones y el contrato publicado, y su sitio natural es
  `tech-cycle-completion`, que ya va a tocar R6 y `AUDITABLE_FIELDS`. Sin esta línea la ausencia de
  puerta se leería como un olvido.
- **Adjuntar foto en el alta de la incidencia.** Ni la limpiadora desde su tarea
  (`cleaner-incident-report`) ni el portal anónimo del huésped (`guest-portal-api`) suben fotos.
  Consecuencia con nombre: «fotos del incidente» de PRD §12 son, tras este change, las `BEFORE` que
  sube el propio técnico y **no** las de quien reportó. Abrir subida de ficheros a un portador
  anónimo es una superficie propia y no se hace de paso.
- **Borrado de fotos por cualquier vía de la API.** El puerto tiene `delete` y su único llamante
  sigue siendo el borrado compensatorio de R2.7. No habrá superficie de borrado sin una decisión de
  retención (`file-storage.md` §Estado).
- **Validación por IA de la foto** (`ai_validation_result`). El `AIAdapter` de `messaging-ai` no
  declara nada equivalente y `maintenance` no tiene puerto propio para ello — el mismo motivo por
  el que `cleaning` lo dejó sin escribir.
- **Ampliar la allowlist de formatos.** HEIC/HEIF sigue fuera (decisión Q1 de
  `cleaning-photos-storage`); es una decisión de producto sobre `file-storage.md`, no de este
  consumidor.
- **Exponer las fotos en la proyección de contexto del técnico** (`GET /api/v1/incidents/{id}/context`,
  `tech-incident-context`). Son rutas distintas y aquélla no cambia por esta causa.
- **La pantalla.** `tech-app` es quien pinta `/tech/incidents/[id]` y consume estas rutas; aquí no
  hay frontend ni claves de i18n.
- **`reject`, ETA, materiales y «en ruta».** Son de `tech-cycle-completion`.

## Affected specs

- `sdd/specs/incident-photos.md` — *(no existe aún — se creará al archivar)*. Spec propia, como
  `cleaner-incident-report.md` y `tech-incident-context.md`: tiene rutas, permisos y entidad
  propios, y `cleaning` metió sus fotos dentro de su spec porque allí eran parte del ciclo de la
  tarea.
- `sdd/specs/maintenance.md` — R8 pasa de trece rutas autenticadas a quince y gana la remisión a la
  spec nueva; la tabla RBAC gana la fila de qué hace el técnico con las fotos, sin permiso nuevo.
  La negativa «NEVER SHALL exponer una ruta de creación de incidencias en este módulo» **no** se
  toca: estas rutas crean fotos, no incidencias.
- `sdd/specs/file-storage.md` — el Purpose dice hoy «su único llamante son las fotos de limpieza» y
  nombra a `maintenance` como *siguiente* consumidor; pasa a ser un consumidor real. §Claves de
  almacenamiento gana la clave de la foto de incidente.
  - **Añadido durante `/sdd:run` (sección 7-9, a raíz de la aclaración D10a)**: §Key Files dice
    que `backend/app/cleaning/api/dependencies.py` es «el **único** punto donde se leen los tres
    ajustes del almacén». Dejó de ser cierto: `get_url_signing_key` y la construcción de la
    factory viven ahora en `app/integrations/api/dependencies.py` (`storage_factory_for`), y cada
    dominio declara la suya con su propio prefijo de URL firmada. Lo detectó el panel de
    documentación de esas secciones; no estaba previsto aquí porque D10a se descubrió
    implementando.
- `sdd/specs/api-contract.md` — el censo de rutas anónimas (que hoy nombra exactamente
  `GET /cleaning-photos/{photo_id}`) y el recuento de las rutas de `maintenance`.
- `sdd/specs/backend-http-posture.md` — la segunda ruta que sella `nosniff` por su cuenta y sirve
  bytes con `Cache-Control` derivado de la firma.
