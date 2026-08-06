# Credenciales de PMS: cómo se guardan, se rotan y por qué

Cómo se **opera** el almacén de credenciales de proveedor. El *qué hace* está en las specs
(`sdd/specs/`); aquí está lo que hay que teclear y lo que conviene entender antes de teclearlo.

Contexto de la decisión: [ADR 0006](adr/0006-pms-channel-manager-provider.md) decisión 7.

## Lo primero, porque cambia cómo se trata todo lo demás

**La credencial peligrosa es la de cuenta, no la de propiedad.** La intuición engaña: suena a que
«ACCOUNT» es más genérico y por tanto menos sensible. Es al revés. Una credencial de propiedad da
acceso a un piso; **una de cuenta da escritura sobre el calendario, el pricing y la mensajería de
todas las propiedades de esa cuenta**, y una de organización sobre N cuentas de cliente.

Y no es un caso raro: **es el caso normal**. El refresh token de Beds24 es de cuenta, la API key
de Channex es de cuenta. Ninguno de los proveedores evaluados usa credencial por propiedad para
autenticarse — la única de Beds24 es la *access key* de la Arrivals API, que pertenece a la capa
de accesos y está aplazada.

Por eso la tabla es `pms_credentials` con una columna `scope`, y no unas columnas en `properties`:
guardar el secreto de cuenta una vez por propiedad serían N sitios que rotar, y una rotación
parcial deja propiedades autenticando con un token muerto.

## Guardar una credencial

El secreto viaja por **variable de entorno**, nunca como argumento: un argumento queda en el
historial del shell y lo ve cualquiera con `ps`.

```bash
read -rs PMS_CREDENTIAL_SECRET && export PMS_CREDENTIAL_SECRET
docker compose exec -e PMS_CREDENTIAL_SECRET backend \
  python -m app.integrations.cli.pms_credentials set <tenant-uuid> beds24 account
unset PMS_CREDENTIAL_SECRET
```

`read -rs`, **no** `export PMS_CREDENTIAL_SECRET='…'`. El `-e` de `docker compose exec` ya
mantiene el secreto fuera de `ps`, pero un `export` tecleado en el prompt aterriza literal en
`~/.zsh_history` — que es la otra mitad exacta del motivo por el que este comando no lo acepta
como argumento. `read -rs` lo pide sin eco y sin dejarlo en el historial.

**El scope no lo eliges tú: lo determina el proveedor.** El comando lo comprueba y rechaza
cualquier otra combinación, porque una credencial guardada en coordenadas que el resolutor nunca
lee es peor que ninguna — parece configurada y no lo está. Hoy:

| Proveedor | Dónde vive su credencial | ¿Se guarda con este comando? |
|---|---|---|
| `beds24` | cuenta (`account`) | **sí** |
| `channex` | entorno (`CHANNEX_API_KEY`) | no — se rechaza |
| `mock` | ninguna | no — se rechaza |

Así que hoy la única invocación válida es `beds24 account`. **`beds24 property <uuid>` se
rechaza**, aunque el esquema admita el scope de propiedad: ningún proveedor lo usa todavía, y una
versión anterior de este documento lo mostraba como ejemplo cuando el comando ya lo refusaba.

Por debajo hay además dos comprobaciones que no dependen del proveedor: un `scope=property` sin
uuid y un `scope=account` con uuid se rechazan antes de tocar la base de datos, y la propia base
lo impide con `ck_pms_credentials_property_id_matches_scope`. La comprobación doble es
deliberada: sin la de base de datos, una fila `ACCOUNT` con `property_id` esquivaría el índice
parcial y **sobreviviría a todas las rotaciones**.

## Rotar

```bash
read -rs PMS_CREDENTIAL_SECRET && export PMS_CREDENTIAL_SECRET
docker compose exec -e PMS_CREDENTIAL_SECRET backend \
  python -m app.integrations.cli.pms_credentials rotate <tenant-uuid> beds24 account
unset PMS_CREDENTIAL_SECRET
```

`rotate` **falla si no hay nada en esas coordenadas**, y eso es a propósito: casi siempre es una
errata en los argumentos, y crear la credencial en silencio haría creer que se ha sustituido una
comprometida cuando la comprometida sigue viva bajo otras coordenadas.

Una rotación escribe su fila en `audit_logs` con `{"changed": true}` — nunca el valor, ni
enmascarado. Un alta por primera vez **no** escribe fila: no reemplaza nada, y registrarla como
rotación haría creer que existe un secreto anterior en alguna parte.

### Si la fila guardada está corrupta

Tanto `set` como `rotate` **funcionan aunque el valor almacenado no se pueda descifrar** (una fila
escrita a mano, una restauración truncada, una clave que cambió). El comando no lee el secreto que
va a reemplazar: solo necesita saber si hay fila y cuál es, así que la sustituye sin más y `rotate`
escribe su fila de auditoría contra la credencial que había de verdad.

Importa en un caso concreto y malo: la credencial se ha **filtrado** *y* su fila está corrupta. Si
el comando se cayera ahí, la única salida sería SQL a mano — sin cifrado, sin guard cross-tenant y
sin traza de rotación, justo lo que este comando existe para evitar, el día que más falta hace.

## Ver qué proveedor usa cada propiedad

```bash
docker compose exec backend python -m app.integrations.cli.pms_credentials show-providers <tenant-uuid>
```

No toca ninguna credencial, así que no audita nada. `(default)` significa que la propiedad no
declara proveedor y usa el de bootstrap (el mock).

## Asignar el proveedor de una propiedad

Hoy no hay comando para esto —`properties/` no tiene API a propósito— y se hace por el
repositorio (`set_pms_provider`) desde código o un script puntual. Si acaba haciendo falta a
menudo, merece su propio subcomando aquí y no un endpoint: la regla 3(a) prohíbe serializar una
credencial en cualquier respuesta, y una API de propiedades es exactamente la superficie que esa
regla existe para que no exista.

## Qué pasa si se pierde o se cambia `ENCRYPTION_KEY`

**Todo lo cifrado queda indescifrable.** No hay recuperación: Fernet es autenticado, y una clave
distinta produce `SecretDecryptionError` fila a fila. La clave la genera Terraform una vez
(`encryption_key_fernet`), vive en OCI Vault y el CD la escribe en el `.env` de la VM.

En local, `make up` la genera si falta — pero **no la sustituye si ya hay un valor**, ni siquiera
con forma incorrecta: para y avisa. Sustituirla en silencio sería destruir dato sin preguntar.

Consecuencia práctica al rotar la clave (no la credencial): habría que volver a guardar **todas**
las credenciales con el comando de arriba. Hoy es barato porque hay pocas; no lo será siempre.

## Qué NO hace este comando, y por qué

- **No imprime el secreto**, ni un prefijo, ni enmascarado. La forma `****XX` de la regla 4 es
  para códigos de acceso; la regla 3(a) no concede nada equivalente a las credenciales de
  proveedor.
- **No lo lee de un fichero ni de un prompt.** De un prompt no sería usable desde un runbook; de
  un fichero, el fichero queda.
- **No valida contra el proveedor.** Guardar una credencial no comprueba que funcione. Lo primero
  que la ejercita es `pms_sync`, y ahí un token inválido sale como error del proveedor.
