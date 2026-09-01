# smtp-delivery-adapter

[BE+INFRA] **el email real, extraído de `hardening-release` para que deje de estar enterrado en un `[CROSS]`
de cinco cosas**.

**El hecho medido (2026-08-28)**: el único adapter de email es `ConsoleEmailAdapter`
(`notifications/infrastructure/adapters.py`), que hace un `logger.info` con las *longitudes* de `subject` y
`body` y devuelve `NotificationResult.ok()`. Está registrado para `EMAIL` **y** para `CONSOLE`, y
`messaging/infrastructure/channels.py` delega en él la respuesta de la IA por email. Su docstring nombra ya
al dueño del trabajo pendiente: *"The SMTP half is out of scope here (`hardening-release` owns settings and
integrations)"*. Las variables `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`
y `SMTP_USE_TLS` **ya están reservadas y vacías** en `.env.example`, por la regla 8 de
`steering/security.md`, y no las lee nadie.

**Lo que hace fácil la entrada, y conviene no volver a derivarlo**: el puerto ya existe y el adapter real es
sustituible por contrato — mismo tipo de retorno, misma disciplina de fallo por valor, misma precondición
(destinatario en blanco es fallo, no excepción). El registro es un `dict` construido con avidez, así que
sustituir la entrada `EMAIL` es una línea; y el emisor ya tiene reintentos acotados por
`NOTIFICATION_MAX_ATTEMPTS`, que registra el intento **antes** de llamar al adapter, de modo que un proceso
muerto a mitad reenvía hasta ese techo y no más.

**Lo que decide y no es cosmético**:

1. **Proveedor y autenticación del dominio**. Recomendación de partida: relay SMTP de un proveedor
   transaccional (Brevo, Resend o SES) sobre el dominio que ya sirve el dev
   (`autohostai.digitalsec.work`), con SPF y DKIM en DNS — sin SDK nuevo, que es justo lo que los nombres
   `SMTP_*` ya reservados permiten. Elegir un SDK en su lugar es una dependencia nueva y dispara el trigger
   de revisión extra de `steering/security.md`.
2. **Dónde viven las credenciales en el despliegue**. `app-deploy-dev` despliega con un runner self-hosted
   en la VM y `docker-compose.deploy.yml`; el secreto tiene que llegar por ahí, y la parte GitHub-side es
   trabajo a mano que `infra-github-iac` quiere convertir en código. Hay que decir cuál de las dos vías se
   usa hoy y no dejarlo implícito.
3. **Fail-fast, no default**. La regla 8 exige que un secreto real nunca tenga valor por defecto y que su
   ausencia falle pronto; pero el arranque **no** puede exigir SMTP mientras haya despliegues sin email, así
   que la decisión es dónde falla: al construir el registro con `EMAIL` activo, no al importar el módulo.
4. **`last_error` es un sumidero de la regla 11 y es el motivo por el que esa fila existe**: una excepción
   de un cliente SMTP suele traer incrustado el mensaje que no pudo enviar. `access-notifications` ya dejó
   escrito que la forma tiene que ser **estructurada**; este change es el primero que produce errores de un
   sistema externo de verdad, así que es donde esa exigencia se prueba en rojo.
5. **Qué es «entregado»**. SMTP acepta, no entrega: un `250` no es un buzón. Hay que decidir si `SENT`
   significa «aceptado por el relay» —lo honesto y lo barato— y declararlo, en vez de dejar que el nombre
   sugiera otra cosa; los rebotes son webhook del proveedor y quedan fuera.

**Depende de `notification-channel-routing`** y el orden importa: sin ella ninguna fila nace con
`channel = EMAIL` salvo el reset de contraseña, así que un adapter real entregaría un caso de prueba y nada
más. Con ella, el reset de contraseña deja de ser un `logger.info` el mismo día — y ése es el primer
recorrido que conviene medir en dev.
