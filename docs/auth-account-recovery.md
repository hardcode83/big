# Autoservicio de contraseña y recuperación

Cómo se opera el cambio de contraseña por el propio usuario, la recuperación por enlace y la
vía de rescate para un entorno sin relay. Change `auth-account-recovery`; la especificación viva
está en `sdd/specs/auth-account-recovery.md`.

> **El correo de recuperación llega de verdad cuando hay relay configurado.** Desde el change
> `smtp-delivery-adapter` (2026-09-03), con `SMTP_HOST` puesto el canal `EMAIL` entrega por un
> relay SMTP real — dev lo tiene (OCI Email Delivery), y el primer reset real llegó a una bandeja
> real. Sin relay configurado el canal resuelve a `ConsoleEmailAdapter`, y
> `sdd/specs/access-notifications.md` le prohíbe registrar el contenido y el destinatario: solo
> anota el canal y las **longitudes** de asunto y cuerpo, así que el enlace no se puede leer del
> log — ahí la vía que sí recupera una cuenta es el comando de rescate de más abajo.

## Los tres endpoints

| Método | Ruta | Auth | Respuesta |
|---|---|---|---|
| POST | `/api/v1/auth/change-password` | Bearer + `MANAGE_OWN_SESSION` | `204`; `401 INVALID_CREDENTIALS`; `422 VALIDATION_ERROR` |
| POST | `/api/v1/auth/forgot-password` | anónimo | `202` con cuerpo fijo; `429 RATE_LIMITED` |
| POST | `/api/v1/auth/reset-password` | anónimo | `204`; `401 INVALID_TOKEN`; `422 VALIDATION_ERROR`; `429 RATE_LIMITED` |

### `POST /auth/change-password`

El sujeto es el titular del token de acceso; el cuerpo **no puede nombrar a otro usuario** y un
campo extra se rechaza con `422` en lugar de ignorarse en silencio. Al completarse se revocan
**todas** las familias de refresh, incluida la de la llamada, así que quien lo use tiene que
volver a entrar: un cambio que dejara vivas las sesiones anteriores no rota la credencial, le
añade otra.

Contabiliza los fallos en el **mismo** contador por cuenta que `login` y respeta su bloqueo: a
los 10 fallos la cuenta se bloquea 15 minutos, y estando bloqueada la petición se rechaza
**sin llegar a bcrypt**. Eso último no es una optimización — es lo que impide que un bucle de
contraseñas erróneas retenga el limitador de bcrypt que comparte con `login`.

### `POST /auth/forgot-password`

Responde **siempre** el mismo `202` con el mismo cuerpo: da igual que la dirección exista, que
el usuario esté inactivo, que su tenant esté suspendido o que la cuenta ya tenga su cuota de
enlaces vivos. Cualquier diferencia lo convertiría en un enumerador de usuarios anónimo
expuesto a internet.

Comparte el presupuesto por IP con `login` y `refresh` (10/min): gastar el de uno agota el de
los otros, a propósito.

Una cuenta no acumula más de `PASSWORD_RESET_MAX_LIVE_TOKENS` enlaces vivos. Al llegar a la
cota, la solicitud nueva **revoca el más antiguo y envía** — nunca se descarta, porque
descartarla dejaba que cualquiera que conociera la dirección silenciara la recuperación real
del titular. Con una excepción: un enlace más joven que `PASSWORD_RESET_GRACE_MINUTES` no se
retira, y si todos los vivos están dentro de ese margen la solicitud no envía nada. Eso es lo
que acota el correo por cuenta y lo que protege el enlace que alguien está leyendo ahora mismo.

### `POST /auth/reset-password`

El token del enlace es la credencial y es de **un solo uso**. Todas las formas de fallar
—inexistente, ya usado, caducado, revocado, o cuenta/tenant que dejaron de estar activos—
responden el mismo `401`, así que el endpoint no sirve para averiguar qué tokens existen.

Al completarse: se reemplaza el hash, se revocan todas las sesiones, se invalidan **los demás
enlaces vivos** de la cuenta y se levanta el bloqueo por fallos de login. Ese último punto es
el que hace que la recuperación recupere de verdad: 10 intentos fallidos son justo lo que
precede a un «he perdido la contraseña», y sin levantarlo el login inmediatamente posterior
seguiría rechazado.

**No devuelve sesión.** Hay que hacer login después. Tener el enlace no debe convertirse en una
sesión sin presentar una credencial.

## Política de contraseña

Dos reglas, y ninguna de composición: **mínimo 12 caracteres** y **máximo 72 bytes en UTF-8**.

El tope son los 72 bytes que bcrypt acepta; validarlo en el borde es lo que convierte el rechazo
del hasher en un `422` con la regla nombrada en vez de un `500`. El mínimo **no es
configurable** a propósito: tiene que aceptar sin excepción toda contraseña que el propio
sistema genera, y un despliegue que lo subiera haría que rechazáramos las credenciales que
repartimos.

No se exigen clases de caracteres: no miden fuerza, hay que explicárselas al usuario y rechazan
frases largas que son mejores que casi todo lo que permitirían.

## El gate `PASSWORD_CHANGE_REQUIRED`

Una cuenta creada por un administrador —o reseteada por él, o rescatada por el comando de abajo—
recibe una contraseña **temporal** y queda con `must_change_password`. Mientras lo esté:

- puede **hacer login** y obtener el par de tokens, y puede **refrescarlo**;
- toda petición autenticada responde `403 PASSWORD_CHANGE_REQUIRED` **salvo** tres:
  `GET /auth/me`, `POST /auth/logout` y `POST /auth/change-password`;
- `GET /auth/me` expone `must_change_password`, para que el frontend redirija sin adivinar.

Las tres exenciones son la vía de salida y no son negociables: sin `change-password` la bandera
sería un bloqueo permanente sin endpoint de vuelta, sin `me` el cliente solo podría descubrir el
estado provocando un `403` en otra llamada, y sin `logout` alguien que no puede cambiarla ahora
no podría cerrar limpiamente.

## Rescate sin relay configurado

```
docker compose exec backend python -m app.cli.reset_password --email <dirección>
```

Genera una temporal, la imprime **una sola vez** por salida estándar y deja la cuenta obligada a
cambiarla. Es lo que sustituye al SQL improvisado, y sigue siendo la única vía real en dos casos:
un entorno **sin** `SMTP_HOST` configurado (donde el enlace no llega ni puede leerse del log), y
el único `TENANT_OWNER` activo de un tenant que además no pueda usar el flujo anónimo: solo
`TENANT_OWNER` tiene `MANAGE_USERS`, así que nadie más puede resetearlo, y él tendría que
autenticarse para resetearse a sí mismo.

No abre superficie nueva: quien puede ejecutarlo ya tiene shell en el host y por tanto acceso a
la base de datos. Lo que aporta sobre un `UPDATE` a mano son cuatro cosas que este hace y aquel
no — pasa por la entidad, revoca las sesiones, levanta el bloqueo por cuenta y deja fila de
auditoría (sin actor, porque una línea de comandos no tiene identidad que registrar).

Deliberadamente **no** hay objetivo de `Makefile`: es una operación de rescate, y un verbo de
`make` la haría parecer parte del flujo normal.

Si Redis no responde, el comando avisa por `stderr` de que **la contraseña sí se cambió** y que
el bloqueo caducará por su cuenta. Es la degradación buena: lo contrario sería informar de un
fallo tras haber cambiado la credencial.

### Después del rescate: el gate no se levanta desde la aplicación

El frontend **no tiene pantalla** para ninguno de los tres endpoints exentos: `/forgot-password`
está en el registro de rutas pero renderiza un `RoutePlaceholder`, no hay página que consuma el
token del enlace y ningún componente lee `must_change_password`. Así que la cuenta rescatada entra
por el navegador y recibe `403 PASSWORD_CHANGE_REQUIRED` en todo lo demás, sin salida visible.

La salida es llamar al endpoint:

```bash
BASE=<origen>/api/v1/auth

ACCESS=$(curl -sS "$BASE/login" -H 'Content-Type: application/json' \
  -d '{"email":"<dirección>","password":"<temporal>"}' | jq -r .access_token)

curl -sS -o /dev/null -w '%{http_code}\n' -X POST "$BASE/change-password" \
  -H "Authorization: Bearer $ACCESS" -H 'Content-Type: application/json' \
  -d '{"current_password":"<temporal>","new_password":"<la nueva>"}'
```

`204` y a volver a entrar: el cambio revoca todas las familias de refresh, incluida la que hizo la
llamada. `GET /auth/me` responde `must_change_password: false` cuando ha surtido efecto.

El procedimiento completo contra el entorno `dev` —SSH, directorio del compose y comprobación—
está en [`infra/environments/dev/RUNBOOK.md`](../infra/environments/dev/RUNBOOK.md) §8.

## Configuración

| Variable | Defecto | Para qué |
|---|---|---|
| `PASSWORD_RESET_TOKEN_MINUTES` | `30` | vida del enlace |
| `PASSWORD_RESET_MAX_LIVE_TOKENS` | `3` | enlaces vivos por cuenta |
| `PASSWORD_RESET_GRACE_MINUTES` | `2` | margen en el que un enlace no se retira |
| `FRONTEND_BASE_URL` | `http://localhost:3000` | base del enlace |

Ninguna es un secreto, así que todas llevan valor por defecto. `PASSWORD_RESET_GRACE_MINUTES`
**tiene que ser menor** que `PASSWORD_RESET_TOKEN_MINUTES` o la aplicación no arranca: con una
gracia igual o mayor nada sería nunca retirable y la cota volvería a ser un descarte permanente.
El mínimo coherente de vida del token es por tanto 2 minutos.

Los seis nombres `SMTP_*` siguen **sin valor** en `.env.example`, pero desde
`smtp-delivery-adapter` sí existen en `Settings` (con defaults vacíos, para que un entorno sin
relay arranque igual). El fail-fast de la regla 8 de `sdd/steering/security.md` vive en la
construcción del registro de adapters: `SMTP_HOST` puesto con cualquier otro campo vacío —o con
`SMTP_USE_TLS` en falso— rompe alto y claro en cada petición hasta que se arregla. El detalle
está en `sdd/specs/access-notifications.md`.

## Lo que este change no hace

- **Frontend**: la página `/forgot-password` y la pantalla de cambio llegan con
  `dashboard-web`/`hardening-release`. El enlace que se compone ya es válido; la página que abre
  todavía no existe.
- **Adapter SMTP real**: llegó después, con `smtp-delivery-adapter` (2026-09-03). Aquí solo se
  reservaron los nombres.
- **Segundo factor, magic links, caducidad periódica de contraseñas**: nada en el PRD los pide.
- **Cambiar el propio email**: es identidad de login y sigue siendo administrado
  (`PATCH /api/v1/users/{id}`).
- **Recuperación de huéspedes**: el portal usa token opaco por estancia y es `guest-portal-api`.

## Límites conocidos

Registrados aquí porque son decisiones, no descuidos; el razonamiento completo está en el
`design.md` del change.

- **Oráculo de latencia en `forgot-password` — vivo desde que hay SMTP real.** Con cuenta hay una
  inserción y una llamada al adapter; sin cuenta, nada. Con `smtp-delivery-adapter` el envío sigue
  **dentro de la petición** (ese change declaró fuera de alcance reescribir el mecanismo de
  entrega), así que el endpoint distingue hoy por tiempo —hasta 10 s de timeout del relay— lo que
  iguala en código y cuerpo. Sacar el envío del camino de la petición sigue pendiente y sin change
  dueño; la deuda está registrada en `sdd/specs/auth-account-recovery.md`.
- **La cota por cuenta no es a prueba de carreras.** Es «comprobar y actuar» sin bloqueo, así
  que peticiones concurrentes pueden dejar más enlaces vivos que la cota. Se acepta: el
  presupuesto por IP es lo que acota el volumen, tener más enlaces no ayuda a adivinar ninguno
  (son 256 bits cada uno), y un candado por cuenta en superficie anónima sería un punto de
  contención que cualquiera puede hacer tomar.
- **Dos `change-password` simultáneos: gana el último.** No hay compare-and-set sobre el hash
  anterior, así que quien pierda la carrera recibe `204` por un cambio que no quedó. Las dos
  llamadas exigen conocer la contraseña actual, así que el resultado es una de las dos que
  eligió el titular — pero se le informa mal.
- **La prueba de sumideros vigila una costura, no todas.** El test que demuestra R4.1-R4.3 captura
  el token parcheando `generate_recovery_token` **en `app/auth/application/recovery.py`**, que hoy
  es el único sitio que lo llama. Un camino futuro —reenvío del enlace, magic link— que importara
  la función en otro módulo, o que llamara a `secrets.token_urlsafe` por su cuenta, emitiría un
  token que ese fixture no ve, y los dos sumideros del escritor (`notification_logs` y el log de
  aplicación) volverían a quedarse ciegos para ese camino. Quien añada un emisor nuevo tiene que
  ampliar la captura.
- **El enlace lleva el token en la query string.** `…/reset-password?token=<token>`. R4 enumera
  nuestros cinco sumideros y este no es ninguno, pero cuando `dashboard-web` sirva la página el
  token pasará por el log de acceso del frontend, el historial del navegador y la cabecera
  `Referer` de lo que esa página cargue. **Nota de traspaso** para el change que la construya: o
  fragmento (`#token=`), o consumirlo y limpiar la URL al llegar. Lo levantó el panel de seguridad
  de la sección 10, fuera de su lista de referentes y por eso aquí y no como defecto.
- **`change-password` gasta un bcrypt sin contabilizar** cuando la contraseña actual es correcta
  y la nueva se rechaza por política. Requiere conocer una contraseña válida y no obtiene
  credencial alguna; lo cerraría un presupuesto por usuario y por minuto, evaluado y descartado.
