# Proposal: demo-user

## Why

Hoy no hay forma de enseñar el producto a alguien de fuera. El entorno `dev` es
público (https://autohostai.digitalsec.work, túnel de Cloudflare) y está sembrado, pero su único
tenant es `AutoHostAI Dev` — el que usa el equipo — y sus credenciales son personales: `bootstrap` y
`seed_demo` no traen ningún default, y `docs/seed-demo.md` dice en voz alta que ponerlos en un
workflow de CD «sería publicar credenciales conocidas en un entorno alcanzable». Así que para que
alguien pruebe la aplicación hay que darle las llaves del entorno de trabajo del equipo, o no
enseñársela.

Esta entrada crea un **segundo tenant de demostración**, aislado del de dev, con credenciales
conocidas y publicables, y —lo que hoy no existe y sin lo cual la demo se pudre en dos semanas— un
**reset periódico** que la devuelve a su estado inicial con las fechas del día.

Análisis completo, con lo que se midió en el árbol para decidir el alcance: `sdd/roadmap/demo-user.md`.

## What changes

Después de este change existe un tenant «AutoHostAI Demo» sembrado con el dataset de PRD §27 más
conversaciones y un enlace de portal de huésped, con cuatro cuentas `@demo.autohostai.test` que
comparten una contraseña conocida y **convergente**; un comando de reset acotado a ese tenant que lo
borra, lo vuelve a sembrar y re-ancla sus fechas a hoy; y un workflow de GitHub Actions con
`schedule:` que lo ejecuta a diario sobre el runner self-hosted que ya corre en la VM, sin exponer
la base de datos ni la API. La contraseña vive en el OCI Vault y llega por el mismo camino que el
resto de secretos del deploy.

No se escribe ningún seed nuevo para lo que §27 ya cubre: `bootstrap` y `seed_demo` se reutilizan
tal cual, parametrizados por entorno.

## Requirements

### R1 — El tenant de demostración y sus cuatro cuentas

**As a** persona que quiere enseñar AutoHostAI, **I want** un tenant de demostración separado del de
trabajo del equipo, **so that** pueda dar acceso a gente de fuera sin entregarles el entorno del
equipo.

Acceptance criteria:

1. WHEN se ejecuta el aprovisionamiento de la demo contra un entorno ya desplegado, THE SYSTEM SHALL
   crear o completar un tenant cuyo nombre es distinto del tenant de trabajo del entorno, con las dos
   viviendas, los tres huéspedes, las tres reservas, la plantilla de checklist, la limpieza cerrada y
   las tres incidencias que `specs/seed-data-demo.md` ya contrata.
2. THE SYSTEM SHALL crear en ese tenant las cuatro cuentas de los cuatro roles —`TENANT_OWNER`,
   `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`— con direcciones bajo el dominio `demo.autohostai.test`.
3. THE SYSTEM SHALL dejar las cuatro cuentas operativas al instante, sin cambio de contraseña forzado.
4. IF el aprovisionamiento se ejecutara contra el tenant de trabajo del entorno, THEN THE SYSTEM SHALL
   rechazarlo y salir sin escribir nada.
5. THE SYSTEM SHALL NOT modificar ninguna fila del tenant de trabajo del entorno en ninguna de sus
   fases.

### R2 — Una contraseña conocida, fija y convergente, acotada al tenant de demostración

**As a** persona que publica el acceso a la demo, **I want** que la contraseña sea siempre la misma y
que el sistema la restaure aunque alguien la cambie, **so that** las credenciales que publico sigan
funcionando sin que yo intervenga.

Acceptance criteria:

1. THE SYSTEM SHALL usar una sola contraseña para las cuatro cuentas de demostración, tomada de la
   configuración del entorno y **nunca de un valor por defecto en el árbol**.
2. WHEN el reset de R3 se ejecuta y alguna de las cuatro cuentas tiene otra contraseña, THE SYSTEM
   SHALL restaurarla al valor configurado — es decir, la contraseña es **convergente** y no
   *create-only*, al modo en que `bootstrap` ya converge `storage_type`.
3. IF la contraseña configurada tiene menos de `PASSWORD_MIN_LENGTH` caracteres, THEN THE SYSTEM SHALL
   rechazarla antes de escribir nada, porque por debajo de ese umbral el propio sistema rechazaría que
   un visitante volviera a fijarla desde `POST /auth/change-password`.
4. THE SYSTEM SHALL NOT aplicar esta contraseña conocida a ninguna cuenta fuera del tenant de
   demostración, y SHALL comprobarlo en vez de confiarlo.
5. THE SYSTEM SHALL NOT emitir la contraseña, su hash ni ningún token por la salida del comando, sus
   logs o el informe del workflow — **con una excepción, y sólo una: el token del enlace de portal
   de huésped que R4.3 obliga a publicar**, que SHALL emitirse.

   > **Enmienda del gate de `/sdd:design`, 2026-08-23** (design D19). Tal y como estaba escrita, esta
   > cláusula y R4.3 no podían cumplirse a la vez: el valor en claro de ese token existe una sola vez
   > —en el retorno de `IssueGuestAccessTokenUseCase`, que sólo persiste su digest—, así que no
   > emitirlo es perderlo. La excepción está acotada por tres hechos y no por una intención: es el
   > token del tenant de demostración, así que lo que abre son datos de demostración; muere en el
   > reset siguiente, que revoca el token vivo de la estancia y borra la estancia entera; y no hay
   > otro canal por el que pueda llegar a nadie. **No alcanza a la contraseña ni a su hash, que
   > siguen prohibidos sin matices**, ni a ningún otro token del sistema — ni los de portal del
   > tenant de trabajo, ni `password_reset_tokens`, ni las sesiones.

> **Esta requirement invierte a conciencia una obligación de seguridad escrita.**
> `sdd/roadmap/seed-data-demo.md` dejó dicho que «un seed que corra allí es una puerta abierta con
> credenciales publicadas en el PRD — hay que decidir el mecanismo que lo impide […] y probarlo en
> rojo». Lo que este change hace es **acotar** esa apertura en vez de rodearla: la credencial conocida
> existe sólo dentro del tenant de demostración (R2.4), su valor sigue fuera del árbol (R2.1), y la
> única barrera real —el aislamiento por tenant— se nombra como tal. El diseño debe decir cómo se
> prueba en rojo cada una de esas tres cláusulas.

### R3 — Un comando de reset acotado a un tenant

**As a** operadora del entorno de demostración, **I want** devolver la demo a su estado inicial con un
comando, **so that** lo que hayan hecho los visitantes y el envejecimiento de las fechas no la
degraden.

Acceptance criteria:

1. WHEN se ejecuta el reset nombrando el tenant de demostración, THE SYSTEM SHALL borrar sus datos y
   volver a sembrarlo, dejando las fechas del dataset ancladas al día de la ejecución.
2. THE SYSTEM SHALL acotar todo borrado al tenant nombrado, y SHALL rechazar la ejecución contra el
   tenant de trabajo del entorno sin borrar nada.
3. WHEN el reset termina con éxito, THE SYSTEM SHALL dejar el tenant en un estado indistinguible del
   que produce un aprovisionamiento desde cero ese mismo día.
4. IF alguna fase del reset falla, THEN THE SYSTEM SHALL dejar la base de datos sin cambios parciales
   y salir con código distinto de cero nombrando la fase.
5. THE SYSTEM SHALL informar de los objetos de almacenamiento que el borrado deja sin fila que los
   referencie, de modo que no queden huérfanos silenciosos — el ciclo de vida de la base y el del
   almacén de objetos son distintos, y `docs/seed-demo.md` ya documenta esa asimetría.
6. THE SYSTEM SHALL dejar intacto el registro de auditoría.

### R4 — Dataset que llegue a las pantallas que existen

**As a** persona de fuera que entra a la demo, **I want** encontrar contenido en las secciones que la
aplicación sabe enseñar, **so that** pueda hacerme una idea del producto y no de un esqueleto vacío.

Acceptance criteria:

1. THE SYSTEM SHALL sembrar al menos una conversación con mensajes de huésped procesados por la vía
   real de entrada, de modo que la clasificación, la política de escalado y la respuesta automática
   queden ejercitadas y visibles en el hilo.
2. THE SYSTEM SHALL sembrar esas conversaciones **sin depender de red ni de credenciales de ningún
   proveedor de IA**, apoyándose en el adaptador determinista que `messaging-ai` ya provee.
3. THE SYSTEM SHALL emitir un enlace de portal de huésped válido para la estancia activa de la demo, y
   SHALL publicarlo junto con las credenciales.
4. THE SYSTEM SHALL escribir cada uno de estos datos por la vía canónica de su dominio, nunca por el
   modelo ORM — la misma regla que `seed_demo` ya sostiene.

### R5 — Ejecución periódica sin exponer la base de datos ni la API

**As a** responsable del entorno, **I want** que el reset se dispare solo, **so that** la demo esté
siempre presentable sin que nadie se acuerde de ejecutarla.

Acceptance criteria:

1. THE SYSTEM SHALL ejecutar el reset de forma programada mediante un workflow de GitHub Actions con
   disparo `schedule:`, y SHALL admitir además el disparo manual.
2. THE SYSTEM SHALL ejecutar ese trabajo **sobre el runner self-hosted que ya corre en la VM**, de modo
   que alcance la base de datos por la red interna del compose.
3. THE SYSTEM SHALL NOT abrir ningún puerto entrante, ni publicar la base de datos, ni requerir SSH, ni
   modificar el security list del entorno.
4. THE SYSTEM SHALL obtener la contraseña de demostración del OCI Vault por el mismo mecanismo que el
   despliegue ya usa, sin escribirla en el repositorio ni en un secret de Actions.
5. WHEN el reset programado falla, THE SYSTEM SHALL terminar el workflow en rojo nombrando la fase que
   falló, sin volcar la contraseña ni el detalle de una excepción de base de datos.
6. THE SYSTEM SHALL declarar como código todo lo anterior —workflow, secreto del Vault y el permiso que
   lo hace legible por el runner—, conforme a la norma IaC-first de `steering/infra.md`.

### R6 — Las credenciales publicadas y la operación, documentadas

**As a** persona que enseña el producto o que opera el entorno, **I want** un sitio único que diga
quién es quién en la demo y qué hacer cuando se rompe, **so that** no haya que leer el código para
usarla.

Acceptance criteria:

1. THE SYSTEM SHALL documentar las cuatro cuentas, su rol y qué puede hacer cada una, y SHALL declarar
   explícitamente qué secciones de la aplicación **no** son demostrables todavía.
2. THE SYSTEM SHALL documentar cómo se cambia la contraseña de demostración y qué hay que ejecutar para
   que el cambio surta efecto.
3. THE SYSTEM SHALL documentar el procedimiento de reset manual y su cadencia programada.

## Out of scope

- **Las valoraciones.** `backend/app/reviews/` tiene entidades y modelos pero ni capa de aplicación, ni
  router, ni pantalla; sembrar `reviews` produciría filas que ningún endpoint lee. Su casa es la entrada
  de roadmap `revenue-reviews` [BE], sin empezar.
- **La bandeja de conversaciones, la pantalla de precios y las apps de limpiadora y técnico.** El
  dataset de R4 se siembra igualmente porque el dato es correcto, pero las pantallas son
  `conversations-inbox`, `pricing-web`, `cleaner-app` y `tech-app`. Decisión explícita del usuario el
  2026-08-23: empezar sin ellas.
- **Publicar las cuentas `CLEANER` y `TECHNICIAN` como recorrido demostrable.** Se crean (R1.2) porque
  el dataset las necesita, pero `AuthGuard` no distingue rol y `/cleaner` y `/tech` son placeholders,
  así que R6.1 las declara no demostrables en vez de anunciarlas.
- **Statements y aprobaciones**, por el mismo motivo que las valoraciones (`revenue-statements`).
- **SMTP y el envío real de correo.** Hoy `ConsoleEmailAdapter` registra la entrega en el log y no
  envía nada; el día que SMTP llegue con `hardening-release`, `.test` no resolverá — que es
  precisamente el comportamiento buscado.
- **Un entorno separado para la demo.** El tenant de demostración convive con el de dev en la misma VM,
  base de datos y bucket; el límite es el aislamiento por tenant. Un entorno propio es otra decisión y
  otro coste.
- **La visibilidad cross-tenant del `SUPER_ADMIN`** (`saas-cross-tenant`): que siga cerrada es parte de
  lo que hace seguro este change, no algo que este change abra.

## Affected specs

- `sdd/specs/demo-tenant.md` — *(no existe aún — se creará al archivar)*: el tenant de demostración, su
  contraseña convergente, el comando de reset y su disparo programado.
- `sdd/specs/seed-data-demo.md` — modificada: el seed deja de presuponer un único tenant por entorno, y
  gana las conversaciones y el enlace de portal de R4.
- `sdd/specs/auth-tenancy.md` — **no modificada**. Esta entrada anunciaba que R2.2 volvería
  convergente en la contraseña el `bootstrap` *create-only* que contrata su R7. El gate de
  `/sdd:design` del 2026-08-23 lo descartó (design D8): `make bootstrap` es el comando que el
  RUNBOOK manda ejecutar contra el entorno desplegado, así que volverlo convergente en contraseñas
  significa que una re-ejecución **reescribe las contraseñas del equipo** en `AutoHostAI Dev` con lo
  que haya en `BOOTSTRAP_*_PASSWORD` — y pondría la única escritura de contraseñas del árbol en el
  sitio que toca los dos tenants, cuando R2.4 exige justo lo contrario. La convergencia vive en el
  comando de la demo, acotada a las cuatro direcciones constantes del tenant de demostración, y R7
  se queda como está.
- `sdd/specs/app-deploy-dev.md` — modificada: un segundo workflow sobre el runner self-hosted.
- `sdd/specs/infra-dev-terraform.md` — modificada: el secreto del Vault y la sentencia de política que
  lo hace legible por el dynamic-group del runner.
- `sdd/specs/local-environment.md` — modificada si el reset se expone también como objetivo de
  `Makefile` para el stack local.
