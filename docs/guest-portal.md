# Portal del huésped

Cómo se opera lo que trajo el change `guest-portal-api`: el enlace que se le da al huésped
para que consulte su estancia, complete el check-in legal de PRD §17 y abra una incidencia,
**sin cuenta y sin JWT** (PRD §§6, 7.6, 7.7, 17, 22, 23). El *qué hace* estará en
`sdd/specs/guest-portal-api.md` al archivar; esta página es el *cómo se usa, se opera y se
diagnostica*.

**Lo que este change NO trae: la página.** La ruta `frontend/app/(guest)/guest/[token]/`
existe reservada, pero la interfaz —estados de carga, formulario, i18n— es `guest-portal-web`.
Hoy el portal se opera y se prueba con `curl`.

## El token es el enlace, y el enlace es la credencial

Un token por estancia, 256 bits de CSPRNG, que viaja **en la ruta**. No hay cabecera, no hay
contraseña y no hay segundo factor: quien tiene el enlace es el huésped a efectos del sistema.
De ahí las tres propiedades que conviene tener presentes al operarlo:

- **Vigencia corta y derivada de la estancia**: autoriza hasta el `check_out_date` más
  `GUEST_PORTAL_TOKEN_GRACE_DAYS` (2 por defecto). No hace falta caducarlo a mano.
- **Muere con la reserva**: si la reserva pasa a `CANCELLED`, deja de autorizar sin que nadie
  haga nada.
- **Revocable en cualquier momento**, y la revocación es inmediata.

En reposo solo se guarda su SHA-256. No existe ninguna ruta que lo lea de vuelta: si se
pierde, se emite otro.

## Emitir y revocar (ruta de operador, con JWT)

Requiere el permiso `MANAGE_GUEST_ACCESS_TOKENS`, que tienen `TENANT_OWNER` y
`PROPERTY_MANAGER`.

```bash
# Acuñar el token de una estancia. Devuelve el valor EN CLARO, una sola vez.
curl -X POST http://localhost:8000/api/v1/reservations/$RESERVATION_ID/guest-access-token \
  -H "Authorization: Bearer $ACCESS_TOKEN"
# → 201 {"token":"kR8x…"}

# Revocarlo. Idempotente: dos veces responde 204 las dos.
curl -X DELETE http://localhost:8000/api/v1/reservations/$RESERVATION_ID/guest-access-token \
  -H "Authorization: Bearer $ACCESS_TOKEN"
# → 204
```

**El `201` es la única vez que el valor existe fuera del sistema.** Cópialo en ese momento;
después solo queda su hash. Es la excepción nombrada de la regla 3(a) de
[`sdd/steering/security.md`](../sdd/steering/security.md) y no se ensancha.

**Re-emitir sustituye, no acumula.** Si la estancia ya tenía un token vivo, el `POST` lo revoca
y devuelve el nuevo en la misma transacción: el huésped que tuviera el enlace anterior deja de
entrar en cuanto se acuña el siguiente. Nunca hay dos tokens vivos para una estancia.

**Entregar el enlace es manual, hoy.** Ningún adapter de envío puede hacerlo todavía
(`ConsoleEmailAdapter` y `MockWhatsAppAdapter` son los únicos, y sus plantillas no llevan
enlace de portal), así que el operador construye la URL y la manda por su cuenta. La emisión
automática llega con el change que traiga un adapter real — la costura ya está hecha.

## Qué ve el huésped

Cuatro rutas, todas con el token en la ruta y ninguna con `Authorization`:

| Ruta | Qué devuelve |
|---|---|
| `GET /api/v1/guest/info/{token}` | Fechas y horas, datos públicos de la vivienda, instrucciones de llegada, código de acceso enmascarado y vía de soporte |
| `GET /api/v1/guest/checkin/{token}` | **Qué falta** de los ocho campos de PRD §17, y los dos estados |
| `POST /api/v1/guest/checkin/{token}` | Guarda los seis campos que aporta el huésped; cifra el documento en la misma llamada |
| `POST /api/v1/guest/incident/{token}` | Crea la incidencia en `OPEN` y devuelve `id`, `status` y `created_at` |

Lo que **nunca** sale por aquí: notas internas de la reserva, importes, identificadores de
PMS o canal, datos de otros huéspedes, credenciales, ni el número de documento — ni siquiera
al huésped que lo aportó (para eso sigue estando `GET /api/v1/guests/{id}/document`, con su
rol y su auditoría).

### Un recorrido completo

```bash
TOKEN=...   # el que devolvió el POST de arriba

curl http://localhost:8000/api/v1/guest/info/$TOKEN
curl http://localhost:8000/api/v1/guest/checkin/$TOKEN

curl -X POST http://localhost:8000/api/v1/guest/checkin/$TOKEN \
  -H 'content-type: application/json' \
  -d '{"full_name":"Ada Lovelace","nationality":"GB","date_of_birth":"1815-12-10",
       "document_type":"PASSPORT","document_number":"12345678Z",
       "document_expiry_date":"2032-01-01"}'

curl -X POST http://localhost:8000/api/v1/guest/incident/$TOKEN \
  -H 'content-type: application/json' \
  -d '{"title":"La caldera hace un ruido muy fuerte","description":"Empezó anoche."}'
```

Reenviar el formulario de check-in es seguro: converge en el mismo estado y no añade un
segundo evento a la timeline. Reenviar una **incidencia** sí crea una segunda: no está
deduplicada a propósito, y lo que la acota es el límite de tasa.

## Dos advertencias que van juntas, y son la misma en los dos sentidos

Este flujo pone texto de una persona delante de la otra, **tal cual**, en las dos
direcciones. Las dos advertencias son de operación, no de código, y por eso viven aquí:

1. **Lo que el operador escribe en `properties.access_notes` se le muestra al huésped
   literalmente**, en `GET /guest/info`. Es el campo cuyo propósito son las instrucciones de
   llegada, así que se expone a propósito — pero **no debe contener códigos de puerta ni
   contraseñas en claro**: para el código de acceso ya hay un campo propio, que sale
   enmascarado (`****XX`). Cualquier cosa que se pegue ahí la lee cualquiera que tenga el
   enlace.

2. **Lo que el huésped escribe en el título y la descripción de una incidencia se le muestra
   al operador literalmente**, sin estructurar y sin enmascarar. Puede contener lo que decidiera
   teclear, incluido su propio número de documento. Es texto de un tercero que el sistema no ha
   ido a buscar, y así está declarado: `incidents.title`/`description` son la **segunda
   excepción nombrada de la regla 11** de [`sdd/steering/security.md`](../sdd/steering/security.md),
   que es donde vive el contrato. Consecuencia práctica: al exportar, reenviar o pegar una
   incidencia en otro sitio, trátala como un dato personal, no como una etiqueta.

Lo que sí está cerrado por construcción: ese texto **no viaja**. No entra en `audit_logs`
—cuya fila registra `source`, `status` y `reservation_id`, nunca lo que se escribió— ni en la
timeline, cuyo evento lleva un título constante y solo identificadores. Y el dashboard tampoco
lo lee: su proyección de incidencias excluye ambos campos.

## Límites de abuso

Dos límites, asimétricos a propósito:

- **Por IP, contado solo sobre autenticaciones fallidas** (`GUEST_PORTAL_PROBE_LIMIT_PER_MINUTE`,
  20): es lo que hace que adivinar un token cueste. Se cobra **antes** de cualquier consulta.
- **Por token, después de autorizar** (`GUEST_PORTAL_RATE_LIMIT_PER_MINUTE`, 60): acota lo que
  un enlace legítimo puede hacer, incluidas las incidencias que una estancia puede abrir.

El tope de cuerpo es el general de `/api/v1/` (1 MiB), aplicado antes del routing. El título de
una incidencia está topado en 300 caracteres y la descripción en 5.000.

## Diagnóstico

**Todo fallo de autorización responde el mismo `404`**, con el mismo cuerpo: token inexistente,
mal formado, revocado, fuera de ventana o de una reserva cancelada son indistinguibles desde
fuera. Es deliberado —si no, la ruta diría si una reserva existe— y significa que **el `404` no
sirve para diagnosticar**. Para saber qué pasa, mira la fila:

```sql
SELECT id, reservation_id, revoked_at, created_at
FROM guest_access_tokens WHERE reservation_id = '…';
```

- `revoked_at` no nulo → revocado (y el instante es cuándo).
- Sin fila → nunca se emitió, o se emitió y se sustituyó.
- Fila viva y sigue fallando → mira `reservations.status` y `check_out_date` contra la ventana.

**El token no aparece en los logs.** El log de acceso redacta el último segmento de
`/api/v1/guest/{acción}/{token}`, así que verás la acción y no la credencial. Si alguna vez lo
ves en claro en un log, es un incidente: rota el token de esa estancia.

**Quién tocó qué**: cada escritura del huésped deja una fila en `audit_logs` con
`actor_guest_token_hash` (el hash, nunca el token), la IP y los campos afectados.

```sql
SELECT action, entity_type, actor_ip, changes, created_at
FROM audit_logs WHERE actor_guest_token_hash IS NOT NULL ORDER BY created_at DESC;
```

## Variables de entorno

| Variable | Defecto | Qué hace |
|---|---|---|
| `GUEST_PORTAL_TOKEN_GRACE_DAYS` | `2` | Días después del `check_out_date` en que el enlace sigue autorizando |
| `GUEST_PORTAL_RATE_LIMIT_PER_MINUTE` | `60` | Peticiones por minuto y token, tras autorizar |
| `GUEST_PORTAL_PROBE_LIMIT_PER_MINUTE` | `20` | Autenticaciones **fallidas** por minuto e IP |
| `GUEST_PORTAL_SUPPORT_CHANNEL` | — | Lo que se le enseña al huésped como vía de soporte |

Ninguna es secreta, así que las tres primeras llevan defecto funcional.
