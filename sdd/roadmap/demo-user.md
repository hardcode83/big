# demo-user

[CROSS] **un tenant de demostración con credenciales conocidas, para que gente de fuera pueda trastear el producto en el `dev` público** (https://autohostai.digitalsec.work): segundo tenant «AutoHostAI Demo» sembrado por los comandos que ya existen, sus cuatro cuentas `@demo.autohostai.test` con una contraseña fija **convergente**, un **comando de reset por tenant** y su disparo periódico desde un workflow con `schedule:` sobre el runner self-hosted que ya corre en la VM.

Añadida el **2026-08-23** a petición del usuario; no está en el plan original. La investigación previa a la entrada está aquí entera, porque tres de sus conclusiones cambian el alcance y ninguna es evidente leyendo el código por encima.

---

## 1. Lo que ya está resuelto y NO hay que reescribir

`make bootstrap` crea tenant + `TENANT_OWNER` + `PROPERTY_MANAGER`. `make seed-demo` (`backend/app/cli/seed_demo.py`) **completa** ese tenant con el dataset de PRD §27 y, desde `seed-data-demo-extension`, además **hace correr el reloj**: los disparadores de estado, el aprovisionador del checkout, el ciclo entero de la limpiadora y el clasificador de incidencias, todo por sus casos de uso reales. El timeline de la demo cuenta una historia verdadera, no una columna escrita a mano.

**Un segundo tenant es viable sin tocar el modelo de datos**, y esto se comprobó una a una:

- `tenants` no tiene unicidad de nombre, y `bootstrap` ancla su idempotencia en el **nombre** → basta `BOOTSTRAP_TENANT_NAME='AutoHostAI Demo'`.
- `internal_code` es único **por tenant** (`uq_properties_tenant_id_internal_code`) y `external_pms_id` también (`uq_reservations_tenant_id_external_pms_id`) → `REDES11`, `PAJARITOS8` y `SEED-AIRBNB-1` se repiten en el tenant demo sin colisionar con los del tenant de dev.
- Los correos son únicos **en toda la instalación** (`uq_users_lower_email`, ADR 0005) → las cuatro cuentas demo necesitan direcciones propias; reutilizar una aborta con `BootstrapConflictError`.
- El aislamiento por tenant está enforced y `saas-cross-tenant` sigue abierta, así que no hay vía por la que el tenant demo alcance al de dev.
- **Beat corre sus jobs por tenant**, así que el tenant demo hereda gratis access records, notificaciones, clasificación de incidencias y recomendaciones de precio.

## 2. La premisa que hay que acotar: 8 de las 12 rutas del workspace son `RoutePlaceholder`

Superficies **reales** hoy: login, dashboard, timeline, properties (+detalle), reservations (+detalle), cleaning, incidents (+detalle) y el portal de huésped `/guest/[token]`.

Superficies **placeholder**: conversations, reviews, pricing, statements, approvals, settings, settings/integrations, forgot-password, `/cleaner` (+detalle) y `/tech` (+detalle).

Consecuencias directas sobre lo que la demo puede enseñar:

- **Valoraciones: no existen.** `backend/app/reviews/` tiene sólo `domain/entities.py`, `domain/enums.py` e `infrastructure/models.py` — cero capa de aplicación, cero router, cero frontend. `revenue-reviews` [BE] sigue sin empezar. **Sembrar filas de `reviews` sería sembrar datos que ningún endpoint ni pantalla lee**, así que quedan fuera de alcance y la entrada lo dice en vez de prometerlo.
- **Mensajes: backend sí, pantalla no todavía.** `messaging-ai` está archivada y el `MockAIAdapter` es determinista y **offline** (sin claves de proveedor), así que el dataset se puede sembrar y ejercita el pipeline entero — clasificación, política de escalado y respuesta automática. La bandeja `/conversations` es `conversations-inbox` [FE], hoy `READY_FOR_PR`. Se siembra igualmente: el dato es correcto y la pantalla llega detrás.
- **Limpiadora y técnico entran, pero no tienen a dónde ir.** `AuthGuard` comprueba autenticación y **no rol**; `/` redirige a `/dashboard`, y `CLEANER` es `_SELF_SERVICE | _CLEANING_EXECUTE` (sin `READ_PROPERTIES`). Un visitante que entre con esas cuentas ve errores. Las cuentas se crean —el seed ya lo hace— pero **no se publican como recorrido** hasta que aterricen `cleaner-app` y `tech-app`, ambas [FE] sin empezar.

## 3. El cron: Actions sí, cron de máquina no, y la razón es dura

`deploy-dev.yml` tiene un job con `runs-on: [self-hosted, dev]`: **el runner de Actions ya corre EN la VM** y hace `docker compose -f docker-compose.deploy.yml ...` en local. Un workflow con `schedule:` no necesita alcanzar la BD ni la API desde fuera — corre dentro de la máquina. Cero puertos entrantes, cero SSH, el security list del hardening intacto.

El cron de máquina está **descartado por construcción**: el `metadata` de la instancia (donde vive el cloud-init) es **`ForceNew` con `ignore_changes`** (`infra/environments/dev/main.tf:176-180`). Un cron añadido al cloud-init no llegaría nunca a la VM viva, y forzarlo la recrearía — «ruleta de capacidad + pérdida de datos», dice el propio comentario. Instalarlo a mano por SSH sería deriva invisible y contra la norma IaC-first de `steering/infra.md`.

**Cómo llega la contraseña.** El job de deploy ya resuelve secretos del OCI Vault **por nombre determinista** (`autohostai-${ENV}-<clave>`) con `--auth instance_principal`, sin credenciales en Actions y sin tocar cloud-init. Un `oci_vault_secret` nuevo se declara en Terraform y se consume igual. **El filo**: la política IAM del dynamic-group (`main.tf:238`) enumera los OCIDs uno a uno, así que el secreto nuevo hay que añadirlo también ahí o el runner no podrá leerlo.

Salvedades de `schedule:` que conviene tener escritas: sólo dispara desde la rama por defecto, la hora no es exacta (se encola), GitHub desactiva los workflows programados tras 60 días de inactividad del repo, y con el runner caído el job espera en cola.

## 4. La contraseña fija obliga a hacerla convergente

- Las cuatro cuentas pueden compartir contraseña: `build_plan` sólo prohíbe que coincidan los **correos**.
- `PASSWORD_MIN_LENGTH = 12` gobierna las contraseñas que elige una persona, no las de bootstrap/seed — pero por debajo de 12 un visitante no podría volver a ponerla desde `/auth/change-password`. Mínimo 12.
- `must_change_password` es `False` por la vía de bootstrap (`entities.py:50`): las cuentas operan al instante, que es lo que una demo necesita.
- **Lo que es trabajo nuevo**: hoy bootstrap y seed son *create-only* para usuarios (`if existing is not None: continue`), y `POST /auth/change-password` existe. Un visitante puede cambiar la contraseña compartida y dejar fuera a los demás. Para que «la contraseña es siempre la misma» sea cierto, el reset tiene que **re-fijarla en cada ejecución**. Precedente exacto a citar: `bootstrap.apply_plan` ya converge `storage_type` y se describe a sí misma como *convergente* y no idempotente (su D10).
- Efecto lateral bueno: el bloqueo por 10 fallos consecutivos (15 min, `RedisLoginThrottle`) deja de ser permanente, porque el reset lo limpia.

## 5. El dominio de correo

`ConsoleEmailAdapter` **no envía correo**: registra la entrega en el log. SMTP llega con `hardening-release`. Y `normalize_email` no valida formato — sólo el API de usuarios aplica `EMAIL_PATTERN`, que acepta cualquier dominio con punto. O sea que hoy funciona cualquiera, y la decisión es sobre el día que SMTP aterrice.

Se eligió **`demo.autohostai.test`**: `.test` está reservado por RFC 6761, así que no es un dominio inventado, nunca resuelve y nadie puede registrarlo — el día que haya SMTP los envíos fallarán de forma ruidosa en vez de salir hacia un dominio ajeno.

**Por qué NO `adamar.test`**, que es lo que publica PRD §27: «Adamar Inmuebles» es el nombre del tenant real del PRD (`docs/AutoHostAI_PRD_v5_Claude.md:2172`, con un `billing_email` de gmail real). El tenant de demostración no debe llevar la identidad del operador real, y menos conviviendo con `AutoHostAI Dev` en el mismo entorno público.

## 6. La obligación de seguridad que esta entrada invierte

`sdd/roadmap/seed-data-demo.md` dejó escrito, cuando aquella entrada se separó de `hardening-release`:

> «PRD §27 fija las contraseñas de los cuatro usuarios en un valor conocido, y el entorno dev **es público por el túnel de Cloudflare**, así que un seed que corra allí es una puerta abierta con credenciales publicadas en el PRD — hay que decidir el mecanismo que lo impide (rechazo por `APP_ENV`, contraseñas generadas, o confinamiento a local) y probarlo en rojo, no confiar en que nadie lo ejecute.»

`seed-data-demo` lo resolvió con la postura que hoy está en el código —cero defaults, el operador pone las contraseñas en su `.env`— y `docs/seed-demo.md` dice explícitamente que meter el seed en un workflow de CD «sería publicar credenciales conocidas en un entorno alcanzable».

**`demo-user` invierte esa postura a conciencia**, porque es exactamente lo que la demo pública requiere. No es un descuido y no debe colarse: el proposal la cita y **acota** la reversión —contraseña conocida sólo en el tenant `AutoHostAI Demo` y nunca en `AutoHostAI Dev`, verificado por el comando en vez de confiado; el valor sigue fuera del árbol, en el Vault; y el aislamiento por tenant nombrado como la única barrera real en vez de darlo por supuesto.

## 7. Alcance acordado con el usuario (2026-08-23)

| | |
|---|---|
| Tenant | segundo tenant «AutoHostAI Demo», por `bootstrap` + `seed-demo` existentes |
| Cuentas | 4, `@demo.autohostai.test`, contraseña fija ≥12 desde el OCI Vault |
| Contraseña | **convergente**: el reset la re-fija en cada ejecución |
| Reset | comando nuevo por tenant: borra, re-siembra y re-ancla fechas |
| Cron | workflow de Actions con `schedule:` + `runs-on: [self-hosted, dev]` |
| Dataset extra | conversaciones con `MockAIAdapter` + token de portal de huésped |
| Fuera | valoraciones (`revenue-reviews` sin empezar), pricing, cleaner-app, tech-app |

Sobre las pantallas que están por aterrizar, decisión explícita del usuario: «ya veremos si llegamos a tiempo o no, vamos a empezar sin ellas».
