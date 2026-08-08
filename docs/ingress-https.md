# Ingress HTTPS del entorno dev

Cómo se accede a la aplicación desplegada y cómo se opera esa vía de acceso. El *qué hace* el sistema está en `sdd/specs/ingress-https-dev.md`; la decisión de por qué es así, en [`adr/0003-https-ingress-dev.md`](adr/0003-https-ingress-dev.md); los procedimientos paso a paso, en [`infra/environments/dev/RUNBOOK.md`](../infra/environments/dev/RUNBOOK.md) §7.

## La URL

**https://autohostai.digitalsec.work**

Funciona desde cualquier red, incluido el móvil, que era el objetivo: el principio 2 de `sdd/steering/product.md` exige que la propietaria vea el estado de sus viviendas desde el teléfono en menos de 10 segundos, y antes de esto la app solo era alcanzable por HTTP desde las IPs de los operadores.

## Cómo llega el tráfico

```
navegador  →  edge de Cloudflare  →  túnel  →  contenedor frontend
             (termina TLS)            (conexión saliente     (red `ingress`)
                                       desde la VM)
                                                        frontend  →  backend
                                                                     (red `private`)
```

Lo que hay que entender de este diseño es que **la VM no tiene ningún puerto HTTP abierto**. El contenedor `cloudflared` abre una conexión *saliente* al edge de Cloudflare y el tráfico entra por ahí. El security list de la máquina solo permite SSH (22), acotado a las IPs de los operadores.

Consecuencias prácticas:

- **No hay certificados que renovar.** El TLS lo termina Cloudflare con el certificado de la zona.
- **No hay puerta alternativa.** Si el edge o el túnel caen, la app no es alcanzable por HTTPS; el acceso para diagnosticar es SSH.
- **El backend no está expuesto, y el túnel no puede exponerlo.** El compose de deploy separa dos redes: `cloudflared` solo comparte la red `ingress` con el `frontend`, así que no alcanza `backend`, `postgres`, `redis`, `worker` ni `migrate` — ni por nombre ni por IP. Eso importa porque el routing del túnel se configura en el edge de Cloudflare, no en la VM: sin esa separación, quien tuviera el API token podría publicar la base de datos sin abrir un puerto ni pasar por un `apply`. El razonamiento vive en el comentario de la sección `networks` de `docker-compose.deploy.yml`, y el radio de daño completo del token —con lo que la separación **no** cubre— en [`adr/0003-https-ingress-dev.md`](adr/0003-https-ingress-dev.md) §Addendum 2026-08-04.
- **El backend sigue sin estar expuesto, y aun así el navegador ya llega a la API.** Son cosas distintas y es la clave del diseño: el navegador llama a `/api/...` en **este mismo hostname**, y quien reenvía al backend por la red interna es el propio contenedor `frontend`. No hay hostname nuevo, ni regla de ingress nueva, ni puerto nuevo, ni CORS, ni segundo certificado. Detalle abajo.

## El camino a la API

El navegador llama a `https://autohostai.digitalsec.work/api/v1/...` — misma URL relativa que en local — y un Route Handler de Next (`frontend/app/api/[...path]/route.ts`) lo reenvía a `backend:8000` por la red `private`.

```
navegador  →  edge  →  túnel  →  frontend:3000  →  /api/… → backend:8000
                                 (red ingress)   (red private)
```

**Qué viaja por ese camino, y qué no:**

| Ruta | Alcanzable desde internet |
|---|---|
| `/api/v1/**` | **Sí** — los 18 endpoints del contrato, con su autorización intacta |
| `/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc` | **No** |
| `/health` | **No** |

Que los cuatro endpoints de documentación no viajen es una **decisión explícita**, no un efecto colateral. Son anónimos por allowlist en el backend y hasta ahora estaban protegidos únicamente por que el backend escuchaba en loopback; en el momento en que existe un camino público eso deja de protegerlos. Se decidió no exponerlos: el contrato que necesita el frontend vive versionado en `backend/openapi.json` (`make openapi`), así que `/docs` no aporta nada que compense publicar la forma entera de la API a quien encuentre el hostname. Lo fija un test (`frontend/app/proxy-scope.test.ts`), no la buena voluntad.

Para leer la documentación navegable sigue haciendo falta el túnel SSH de abajo (`http://localhost:8000/docs`).

**Sobre la IP del cliente**: el handler descarta cualquier cabecera de reenvío que traiga el cliente y escribe una `X-Forwarded-For` derivada del `CF-Connecting-IP` que pone el edge. El backend se la cree porque el peer es el contenedor `frontend`, la única dirección de su lista de confianza. Sin esto, el límite de 10 intentos de login por minuto contaría todo el despliegue en un solo contador. Detalle en [`auth-tenancy.md`](auth-tenancy.md) §«De quién es la IP que cuenta el límite».

## Depurar cuando algo va mal

La pregunta que más veces te vas a hacer es **"¿falla la app, el túnel o el edge?"**. Para responderla hay una segunda vía de acceso que no pasa por Cloudflare: los contenedores publican en el `127.0.0.1` de la VM y te los traes a tu portátil por SSH.

```bash
ssh -L 3000:localhost:3000 -L 8000:localhost:8000 ubuntu@<IP de la VM>
# y abres http://localhost:3000 en tu navegador, con devtools
```

Comparando lo que ves por la URL pública con lo que ves por `localhost:3000` sale el diagnóstico:

| Por HTTPS público | Por `localhost:3000` | Es |
|---|---|---|
| falla | falla igual | **la app** |
| falla | funciona | **el túnel o el edge** |
| `530` / error 1033 | funciona | el túnel **sin conector**: `cloudflared` caído |
| `502` | funciona | el túnel arriba, el origen no responde |
| `404` | funciona | el hostname no casa la regla de ingress |

**Si lo que falla es la API y no las páginas**, hay un cuarto caso que este cuadro no cubre, porque la API tiene un salto más:

| Síntoma | Es |
|---|---|
| `404` en `/api/v1/...` pero las páginas cargan | el Route Handler no está resolviendo — mira si `BACKEND_INTERNAL_URL` llegó al contenedor |
| `502` con `{"error":{"code":"INTERNAL_ERROR"}}` en `/api/...` | el salto no alcanzó el backend. El motivo real está en los logs de `frontend`, con el prefijo `[api-proxy]`; a propósito no viaja en la respuesta |
| la API responde pero el throttle de login bloquea a todo el mundo a la vez | la IP real no está llegando: todas las peticiones caen en un contador. Comprueba qué IP registra el backend |

El procedimiento completo —requisitos, alias de `~/.ssh/config`, logs, acceso a la base de datos, errores frecuentes— está en el **RUNBOOK §7.4**.

## Qué se toca para cambiar algo

Todo el lado Cloudflare es Terraform, en `infra/environments/dev/`: el túnel, sus reglas de routing, el registro DNS y el forzado de HTTPS de la zona. **No se configura nada a mano en el dashboard** salvo dos cosas que no son codificables y están documentadas como *bootstrap irreducible* en `sdd/steering/infra.md`: el dominio con su zona, y el API token del provider.

El contenedor `cloudflared` lo despliega el CD (`deploy-dev`), no Terraform, igual que el resto de servicios de la aplicación.

## Limitaciones conocidas

- **El TLS mínimo de la zona está en 1.0**, no en 1.2. `digitalsec.work` aloja otros servicios y subirlo concentraría el riesgo sobre ellos sin aportar nada a este ingress (decisión D7 del change).
- **El hostname debe ser de primer nivel** bajo el apex (`algo.digitalsec.work`). El certificado Universal SSL gratuito solo cubre el apex y un nivel; profundizar exigiría un certificado de pago. Cuando haya un segundo entorno, el patrón es aplanar (`autohostai-staging.digitalsec.work`), no anidar.
- **Cloudflare es dependencia de runtime**, no solo de DNS. Está en el camino del tráfico.
- **Sin autenticación, ni en el edge ni en la app.** Todo lo que sirve este hostname es público y anónimo. `auth-tenancy` (mergeado el 2026-07-30) trajo JWT y RBAC **al backend**, pero no tocó el frontend, así que las páginas siguen siendo anónimas y no hay Cloudflare Access delante. Tenlo en cuenta antes de mostrar en pantalla cualquier cosa que no quieras que lea un desconocido.
