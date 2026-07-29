# Proposal: ingress-https-hardening

## Why

El panel de `/sdd:review` sobre `ingress-https-dev` (2026-07-29, 7 reviewers) devolvió 13 hallazgos, de los que **3 son bloqueantes**. Los diez restantes son correcciones documentales y se resuelven en el propio change antes de archivarlo; estos tres exigen cambios de infraestructura con su propio `apply`, su propio deploy y su propia verificación, así que se separan.

El más importante **invalida el radio de daño que `ingress-https-dev` documentó en su decisión D10**. Ese change razonó que el API token de Cloudflare permite "reescribir DNS y bajar el TLS de todos los servicios de la zona". El panel demostró que permite bastante más, y por un camino que el proposal original no contemplaba.

No es un fallo del entorno desplegado —la app funciona y ninguna vía pública está abierta— sino de acotado: las tres cosas amplían superficie o contradicen un control que la propia documentación afirma tener.

## What changes

**El servicio `cloudflared` deja de compartir la red del compose con la base de datos y el backend.** Hoy `docker-compose.deploy.yml` no declara ninguna red, así que los siete servicios viven en la `default` y `cloudflared` resuelve `postgres`, `redis` y `backend` por nombre. Como la configuración de ingress del túnel es **remota** (`config_src = "cloudflare"`), quien tenga el API token puede añadir una regla `hostname → http://backend:8000` o `tcp://postgres:5432` y publicarla en internet **sin abrir un puerto, sin tocar el security list y sin ejecutar un `apply`** — Terraform no detectaría la deriva hasta el siguiente `plan`. Tras este change, `cloudflared` solo comparte red con `frontend`, así que una regla reescrita no resuelve nada más.

**La policy IAM del runner recupera el mínimo privilegio que declara tener.** `ingress-https-dev` añadió `Allow dynamic-group … to read secrets in compartment id …` sin condición, para que el deploy pudiera resolver el secreto del túnel por nombre. La descripción del propio recurso dice "leer **SOLO** …(mínimo privilegio)" e `iam-policy.md` argumenta explícitamente que un `read` sin condición sería incorrecto. El impacto se limita a **metadatos** —el contenido sigue acotado por la enumeración de OCID—, pero el control declarado y el real no coinciden.

**El RUNBOOK deja de enseñar una configuración peligrosa.** Su §7.4.3 indica publicar temporalmente el puerto de Postgres sin el prefijo `127.0.0.1:`, y ese es el default de Docker (`0.0.0.0`). Un operador siguiéndolo al pie de la letra deja Postgres, con la contraseña del superusuario, alcanzable desde toda la VCN — exactamente lo que R4.3 de `ingress-https-dev` prohíbe y lo que su D11 rechazó por escrito.

Y como consecuencia del primero, **se corrige el radio de daño documentado del API token** allí donde sigue vivo (ADR 0003 y `steering/infra.md`), para que describa la realidad posterior al aislamiento en vez de la subestimación actual.

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

## Out of scope

- **Los diez hallazgos documentales** del mismo panel (ADR desfasado respecto a D11, `steering/infra.md` describiendo mal el roadmap, el `curl` prometido en el CD que no existe, el ID del túnel versionado, el token en el historial del shell, la IP cableada, `docs/ingress-https.md` ausente, el TLS 1.2 afirmado y no aplicado, y la advertencia obsoleta de `iam-policy.md`): se corrigen en `ingress-https-dev` antes de archivarlo. Las dos excepciones son la advertencia de `iam-policy.md` (R2.4, porque el fichero se toca aquí de todos modos) y el radio del token (R4, porque depende de R1).
- **Detectar deriva de la configuración remota del túnel.** Que un cambio en el edge no deje rastro hasta el siguiente `plan` es una propiedad de `config_src = "cloudflare"`; monitorizarlo o alertar sobre ello es un problema aparte.
- **`min_tls_version` de la zona**: sigue en 1.0 por la decisión D7, y este change no la revisa.
- **Verificar el comportamiento de la catch-all 404** (R1.2 de `ingress-https-dev`, calificado *partially met*): sigue exigiendo un CNAME desechable y la decisión de no pagarlo no cambia.
- **Cloudflare Access / autenticación en el edge**: fuera de alcance igual que en el change anterior.

## Affected specs

- `sdd/specs/ingress-https-dev.md` — modificar *(no existe aún — lo crea `/sdd:archive` de `ingress-https-dev`)*: la topología de red del compose de deploy y el statement final de la policy.
- `sdd/specs/app-deploy-dev.md` — modificar: el compose de deploy pasa a declarar redes explícitas.
- `sdd/specs/infra-dev-terraform.md` — modificar: el statement de la policy del runner.

Fuera de `sdd/specs/`, este change toca `docs/adr/0003-https-ingress-dev.md`, `sdd/steering/infra.md` e `infra/environments/dev/iam-policy.md`.

**Dependencia de orden:** conviene archivar `ingress-https-dev` antes de empezar la implementación, para que exista `sdd/specs/ingress-https-dev.md` y para no arrastrar los diez hallazgos documentales a este change.
