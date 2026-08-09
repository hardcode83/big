# backend-response-hardening

[CROSS] **postura de cabeceras y de topes de cuerpo para TODO el backend**, no ruta a ruta. Separada
de `cleaning-photos-storage` el 2026-08-09 al cerrar su `/sdd:review` (entradas §6(b) y §7 de su
`BLOCKED.md`). Son dos hallazgos distintos que comparten la misma forma: **una propiedad que se
decidió bien en una ruta y que nadie ha aplicado a las demás**.

**(a) `X-Content-Type-Options: nosniff` existe en una sola ruta de todo el backend.** Lo midió el
revisor de seguridad de `cleaning-photos-storage`: el único `nosniff` de `backend/app` es el que
aquel change añadió a su ruta anónima de servido de fotos, y las 12 rutas autenticadas no lo llevan.
Allí era obligatorio y la razón está escrita (un *polyglot* que empiece por `FF D8 FF` y contenga
HTML es **XSS almacenado sobre el origen de `/api/v1`**, que `api-ingress-routing` dejó alcanzable
desde internet), pero el razonamiento no es exclusivo de las fotos: cualquier respuesta cuyo
`Content-Type` el navegador pueda adivinar tiene el mismo problema. Un middleware global lo cierra de
una vez. Se dejó fuera de aquel change **a propósito**: es postura de seguridad de todo el backend y
merece su propio diff revisable, no colarse en un change de fotos.

**(b) El mismo error de razonamiento sobre topes de tamaño ya está reproducido en dos módulos.** El
panel de `/sdd:review` de `cleaning-photos-storage` gastó **dos rondas** en una afirmación falsa: que
el conteo por trozos dentro del caso de uso protege de un `Content-Length` mentido o de un
`Transfer-Encoding: chunked`. No puede — FastAPI llama a `await request.form()` **antes** de resolver
las dependencias y Starlette vuelca la parte a un `SpooledTemporaryFile` sin techo propio, así que
cuando el bucle pide su primer trozo el fichero ya se recibió entero y se escribió en disco. Quien
cumple «rechazar antes de leer el cuerpo» es el **contador acumulativo del middleware**, y sólo él.
Aquella afirmación estaba reenunciada en **cinco ficheros** y cuatro habían derivado a decir lo
contrario del código; quedó arreglada allí, con un solo hogar.

Lo que hace que esto sea una entrada y no una anécdota: **el patrón se reprodujo solo, en otro
change**. `backend/app/integrations/api/router.py:56-58` (import de CSV, de `integrations` /
`api-ingress-routing`) justifica su `file.read(limit+1)` como *«defence in depth for a request whose
body arrived in one chunk under a lying `Content-Length`»*. Un cuerpo que «arrived» ya está volcado:
esa lectura acota la copia en memoria, **no** caza al que miente. Misma clase de error, módulo
distinto, escrito por gente distinta sin copiarse.

Así que la salida no es un tercer arreglo de redacción sino una **nota de steering** en
`steering/backend.md` o `steering/security.md`: *una comprobación de tamaño posterior a
`request.form()` o a `file.read()` acota memoria, no satisface un requisito de «rechazar antes de
leer»; eso sólo lo puede hacer el middleware*. Escrita una vez, deja de reinventarse por módulo — que
es exactamente lo que `rule11-ownership-single-source` persigue para la regla 11.

completes: cleaning-photos-storage · size: S · kind: tech
