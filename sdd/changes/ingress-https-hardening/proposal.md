# Proposal: ingress-https-hardening

## Why

El panel de `/sdd:review` sobre `ingress-https-dev` (2026-07-29, 7 reviewers) devolvió 13 hallazgos, de los que **3 son bloqueantes**. Los diez restantes son correcciones documentales y se resuelven en el propio change antes de archivarlo; estos tres exigen cambios de infraestructura con su propio `apply`, su propio deploy y su propia verificación, así que se separan.

El más importante **invalida el radio de daño que `ingress-https-dev` documentó en su decisión D10**. Ese change razonó que el API token de Cloudflare permite "reescribir DNS y bajar el TLS de todos los servicios de la zona". El panel demostró que permite bastante más, y por un camino que el proposal original no contemplaba.

No es un fallo del entorno desplegado —la app funciona y ninguna vía pública está abierta— sino de acotado: las tres cosas amplían superficie o contradicen un control que la propia documentación afirma tener.

**Añadido el 2026-08-02, de otra procedencia** (no del panel): el `/sdd:new` de `api-ingress-routing` se cerró sin proposal tras establecer que el change es prematuro, y de camino destapó que la **restricción 2 de ADR 0003** —"todo el acceso al backend es server-side por la red interna del compose"— es falsa, y lo era ya cuando se escribió. Se corrige aquí (**R5**) porque este change ya enmienda ese mismo documento por la misma clase de razón. Mismo patrón que R4: la decisión del ADR aguanta, la premisa no.

## What changes

**El servicio `cloudflared` deja de compartir la red del compose con la base de datos y el backend.** Hoy `docker-compose.deploy.yml` no declara ninguna red, así que los siete servicios viven en la `default` y `cloudflared` resuelve `postgres`, `redis` y `backend` por nombre. Como la configuración de ingress del túnel es **remota** (`config_src = "cloudflare"`), quien tenga el API token puede añadir una regla `hostname → http://backend:8000` o `tcp://postgres:5432` y publicarla en internet **sin abrir un puerto, sin tocar el security list y sin ejecutar un `apply`** — Terraform no detectaría la deriva hasta el siguiente `plan`. Tras este change, `cloudflared` solo comparte red con `frontend`, así que una regla reescrita no resuelve nada más.

**La policy IAM del runner recupera el mínimo privilegio que declara tener.** `ingress-https-dev` añadió `Allow dynamic-group … to read secrets in compartment id …` sin condición, para que el deploy pudiera resolver el secreto del túnel por nombre. La descripción del propio recurso dice "leer **SOLO** …(mínimo privilegio)" e `iam-policy.md` argumenta explícitamente que un `read` sin condición sería incorrecto. El impacto se limita a **metadatos** —el contenido sigue acotado por la enumeración de OCID—, pero el control declarado y el real no coinciden.

**El RUNBOOK deja de enseñar una configuración peligrosa.** Su §7.4.3 indica publicar temporalmente el puerto de Postgres sin el prefijo `127.0.0.1:`, y ese es el default de Docker (`0.0.0.0`). Un operador siguiéndolo al pie de la letra deja Postgres, con la contraseña del superusuario, alcanzable desde toda la VCN — exactamente lo que R4.3 de `ingress-https-dev` prohíbe y lo que su D11 rechazó por escrito.

Y como consecuencia del primero, **se corrige el radio de daño documentado del API token** allí donde sigue vivo (ADR 0003 y `steering/infra.md`), para que describa la realidad posterior al aislamiento en vez de la subestimación actual.

**Y ADR 0003 deja de afirmar que el navegador nunca llama al backend.** Su restricción 2 lo da por hecho, y `docs/ingress-https.md` lo repite aún más fuerte ("El navegador nunca le llama"). Pero `steering/frontend.md` fija desde el primer commit TanStack Query para server state y "JWT en memoria", `auth-tenancy` devuelve los tokens en el cuerpo JSON, y los hooks del dashboard ya son `"use client"`: el fetching de datos es del navegador, aunque el renderizado sea de servidor. El propio ADR se contradice en su viñeta "A vigilar", que asume que el backend recibe `CF-Connecting-IP` — algo imposible si al backend solo se llega por la red interna. **Esto no reabre la elección de Cloudflare Tunnel**: un camino same-origin bajo el hostname existente sigue bastando, sin CORS ni segundo certificado. Solo corrige por qué basta.

## Requirements

### R1 — `cloudflared` aislado en una red que no alcance datos ni backend

**As a** responsable de la infra, **I want** que el contenedor del túnel solo pueda resolver el frontend, **so that** una regla de ingress reescrita en el edge no pueda publicar la base de datos ni el backend.

Acceptance criteria:

1. THE SYSTEM SHALL declarar en `docker-compose.deploy.yml` una red dedicada al ingress a la que pertenezcan **únicamente** `cloudflared` y `frontend`.
2. THE SYSTEM SHALL mantener `backend`, `worker`, `migrate`, `postgres` y `redis` **fuera** de esa red.
3. THE SYSTEM SHALL mantener `frontend` conectado a **ambas** redes, para que siga alcanzando al backend por `BACKEND_INTERNAL_URL` sin cambios en la aplicación.
4. WHEN el deploy termina, THE SYSTEM SHALL demostrar que el contenedor `cloudflared` **no** está conectado a la red que contiene `postgres` — evidencia objetiva: inspección de las redes del contenedor en la VM.
5. THE SYSTEM SHALL conservar el healthcheck y el `depends_on: frontend: service_healthy` funcionando tras el cambio de redes.
6. IF el aislamiento rompiera la conexión del túnel con el frontend, THEN THE SYSTEM SHALL fallar el deploy en `up -d --wait` antes de dar el despliegue por bueno.

### R2 — La policy del runner acotada al mínimo privilegio que declara

**As a** responsable de la infra, **I want** que el statement de lectura de metadatos esté acotado, **so that** el control declarado en la descripción del recurso y en `iam-policy.md` coincida con el real.

Acceptance criteria:

1. THE SYSTEM SHALL acotar el statement que hoy es `read secrets in compartment` sin condición, reduciendo el verbo a `inspect` y/o añadiendo una condición que lo limite al Vault del entorno.
2. THE SYSTEM SHALL preservar la resolución por nombre (`get-secret-bundle-by-name`) que usa el job de deploy; la evidencia es un deploy real cuyo paso "Render .env" pasa.
3. THE SYSTEM SHALL mantener intacta la enumeración explícita de OCID que acota el acceso al **contenido** de los secretos.
4. THE SYSTEM SHALL actualizar `infra/environments/dev/iam-policy.md` para reflejar el statement final y retirar la advertencia "pendiente de verificar", que el deploy ya resolvió.
5. IF la resolución por nombre dejara de funcionar con el statement acotado, THEN THE SYSTEM SHALL volver a leer el secreto por OCID exponiéndolo como `output`, y registrar el motivo.

### R3 — El RUNBOOK no enseña a exponer servicios en interfaces externas

**As a** operador que sigue el runbook durante una incidencia, **I want** que sus ejemplos respeten el propio requisito de acotado, **so that** seguirlo al pie de la letra no abra un servicio a toda la VCN.

Acceptance criteria:

1. THE SYSTEM SHALL corregir el ejemplo de `RUNBOOK.md` §7.4.3 para que cualquier publicación temporal de puerto lleve el prefijo `127.0.0.1:`.
2. THE SYSTEM SHALL revisar el resto del RUNBOOK y de `docs/` y THE SYSTEM SHALL NOT dejar ningún ejemplo que publique un puerto de la VM en una interfaz externa.
3. THE SYSTEM SHALL explicar en ese ejemplo por qué el prefijo importa, remitiendo al razonamiento de D11 de `ingress-https-dev`.

### R4 — El radio de daño documentado del API token corregido

**As a** quien lea la documentación para valorar el riesgo, **I want** que el radio del API token de Cloudflare esté descrito con exactitud, **so that** una decisión futura sobre dónde guardarlo o cómo acotarlo no se tome sobre una premisa falsa.

Acceptance criteria:

1. THE SYSTEM SHALL corregir en `docs/adr/0003-https-ingress-dev.md` y en `sdd/steering/infra.md` la descripción del radio del API token, que hoy lo limita a "reescribir DNS y bajar el TLS de la zona".
2. THE SYSTEM SHALL describir el radio **posterior** a R1: con `cloudflared` aislado, el token permite publicar en internet lo que sea alcanzable desde la red de ingress, es decir el frontend.
3. THE SYSTEM SHALL dejar constancia de que la configuración de ingress del túnel es **remota**, de modo que un cambio en el edge no requiere `apply` ni deja rastro en el `tfstate` hasta el siguiente `plan`.
4. THE SYSTEM SHALL NOT reescribir el `design.md` archivado de `ingress-https-dev`: es un registro histórico, y la corrección va en los documentos vivos.

### R5 — La premisa de arquitectura de ADR 0003 corregida

**As a** quien lea las especificaciones para decidir cómo llega el navegador a la API, **I want** que ADR 0003 describa el acceso al backend como es y no como se supuso, **so that** la decisión futura sobre el ingress de la API no parta de una premisa falsa.

Añadido el 2026-08-02, al abrir el `/sdd:new` de `api-ingress-routing` y cerrarlo sin proposal: el análisis de aquella fase destapó que la **restricción 2** del ADR es falsa, y aterriza aquí porque este change ya enmienda ese mismo documento por la misma clase de razón (R4).

Acceptance criteria:

1. THE SYSTEM SHALL corregir la **restricción 2** de `docs/adr/0003-https-ingress-dev.md` —"todo el acceso al backend es server-side por la red interna del compose"— y THE SYSTEM SHALL basar la corrección en hechos verificables: hoy **ningún** código accede al backend (`getServerConfig()` no se invoca desde el código de aplicación y `getDashboardDataSource()` devuelve un mock), y la arquitectura comprometida en `sdd/steering/frontend.md` (línea 13, TanStack Query para server state; línea 18, "JWT en memoria + refresh", ambas del 2026-07-15) implica acceso **desde el navegador**, como ya lo ejercita `frontend/features/dashboard/components/dashboard-view.tsx:19`.
2. THE SYSTEM SHALL registrar que la evidencia que el ADR invoca no sostiene su conclusión: `public.ts` excluye `BACKEND_INTERNAL_URL` del bundle porque `http://backend:8000` es un nombre de red interna irresoluble desde un navegador, no porque el navegador no vaya a llamar a la API.
3. THE SYSTEM SHALL registrar que ese acceso desde el navegador **no exige exponer el backend**: basta un camino **same-origin** bajo el hostname público existente, de modo que la conclusión operativa del ADR —con un hostname basta, sin CORS ni segundo certificado— **sigue siendo válida**.
4. THE SYSTEM SHALL resolver la **incoherencia interna** del documento: la viñeta "A vigilar" de Consecuencias asume que el backend recibe `CF-Connecting-IP`, lo que solo ocurre si el tráfico al backend atraviesa el proxy — incompatible con la restricción 2 tal como está redactada.
5. THE SYSTEM SHALL corregir `docs/ingress-https.md`, que afirma la premisa en forma aún más fuerte ("El navegador nunca le llama").
6. THE SYSTEM SHALL NOT alterar la **decisión** del ADR (Cloudflare Tunnel) ni su tabla de alternativas: la restricción 2 reforzaba el acotado, no sostenía la elección, así que corregirla no reabre la comparativa.
7. THE SYSTEM SHALL remitir a la entrada `api-ingress-routing` del roadmap como el sitio donde el camino queda pendiente, sin construirlo aquí.

## Out of scope

- **Los diez hallazgos documentales** del mismo panel (ADR desfasado respecto a D11, `steering/infra.md` describiendo mal el roadmap, el `curl` prometido en el CD que no existe, el ID del túnel versionado, el token en el historial del shell, la IP cableada, `docs/ingress-https.md` ausente, el TLS 1.2 afirmado y no aplicado, y la advertencia obsoleta de `iam-policy.md`): se corrigen en `ingress-https-dev` antes de archivarlo. Las dos excepciones son la advertencia de `iam-policy.md` (R2.4, porque el fichero se toca aquí de todos modos) y el radio del token (R4, porque depende de R1).
- **Detectar deriva de la configuración remota del túnel.** Que un cambio en el edge no deje rastro hasta el siguiente `plan` es una propiedad de `config_src = "cloudflare"`; monitorizarlo o alertar sobre ello es un problema aparte.
- **`min_tls_version` de la zona**: sigue en 1.0 por la decisión D7, y este change no la revisa.
- **Verificar el comportamiento de la catch-all 404** (R1.2 de `ingress-https-dev`, calificado *partially met*): sigue exigiendo un CNAME desechable y la decisión de no pagarlo no cambia.
- **Cloudflare Access / autenticación en el edge**: fuera de alcance igual que en el change anterior.
- **Construir el camino del navegador a `/api`** (la `rewrite` de Next.js, la propagación de la IP real del cliente, la lista de proxies de confianza y la decisión sobre `/docs`/`/redoc`/`/openapi.json`): R5 solo corrige la documentación. El camino es la entrada `api-ingress-routing` del roadmap, aplazada el 2026-08-02 hasta que `getDashboardDataSource()` deje de devolver un mock.
- **Revisar dónde vive el fetch del frontend.** R5 documenta que `steering/frontend.md` ya lo fijó en el navegador; cambiarlo sería un change de arquitectura de frontend —reescribiría la capa de datos de `dashboard-web-frontend`, que es de Marta— y no de ingress.

## Affected specs

- `sdd/specs/ingress-https-dev.md` — modificar: la topología de red del compose de deploy y el statement final de la policy.
- `sdd/specs/app-deploy-dev.md` — modificar: el compose de deploy pasa a declarar redes explícitas.
- `sdd/specs/infra-dev-terraform.md` — modificar: el statement de la policy del runner.

Fuera de `sdd/specs/`, este change toca `docs/adr/0003-https-ingress-dev.md`, `sdd/steering/infra.md`, `infra/environments/dev/iam-policy.md` y —por R5— `docs/ingress-https.md`.

**Dependencia de orden: resuelta.** Este proposal decía que convenía archivar `ingress-https-dev` antes de empezar; ya está archivado (2026-07-29, `changes/archive/2026-07-29-ingress-https-dev/`) y `sdd/specs/ingress-https-dev.md` existe, así que la implementación puede arrancar sin espera. Actualizado el 2026-08-02.

**Nota sobre R5:** es el único requisito puramente documental del change; los otros cuatro exigen `apply` y/o deploy. Aterriza aquí porque R4 ya enmienda el mismo ADR por la misma clase de razón —una afirmación del documento que la realidad desmiente— y montar un change propio para tres párrafos costaría más ceremonia que valor. Si al diseñar resulta que arrastra el acotado, se separa.
