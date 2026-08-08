# BLOCKED — api-ingress-routing

> **Por qué este change va a PR en `ACTIVE` y no en `READY_FOR_PR`.** No es un olvido ni un
> atajo: `mark-local-verified` exige `BLOCKED.md` vacío, y esta entrada no se puede resolver
> antes del merge porque el entorno que hay que medir solo recibe código después. La regla
> compartida 5 clasifica una «verificación omitida» exactamente como esto, así que la puerta
> se está negando **con razón** — el change no cumple la definición de verificado-en-local
> del propio proyecto mientras 6.2 no se haya ejecutado.
>
> Es una dependencia circular real del proceso para changes de infra que solo se manifiestan
> desplegados, y se elige convivir con ella en vez de vaciar este fichero para forzar la
> puerta: borrarlo destruiría el registro de lo que no está probado, que es precisamente lo
> que el flujo existe para impedir.
>
> **Secuencia acordada**: PR y merge → deploy → `/sdd:run api-ingress-routing 6` → si 6.2
> sale bien, se resuelve esta entrada y entonces sí `mark-local-verified` + `mark-ready`
> antes de archivar. Si 6.2 sale mal, R3.3 manda: R1 no se da por cumplido y esto pasa a ser
> una entrada de tipo `decision`.
>
> El código sí está revisado: panel de 7 revisores en PASS tras dos rondas, backend 3410
> passed / 35 skipped, frontend 318 passed, lint y typecheck limpios, `make openapi` sin
> diff. Lo que falta es la medición contra el entorno real, no la revisión.

## 1. La sección 6 entera necesita el entorno desplegado

- **Fase**: run
- **Tipo**: `deferred` — el flujo puede reanudarlo, no hace falta decidir nada
- **Qué y por qué**: las tareas 6.1-6.6 verifican el camino contra
  `https://autohostai.digitalsec.work`, y ese entorno solo recibe el código **después del
  merge** (el CD despliega desde `main`; `.github/workflows/deploy-dev.yml` está acotado a
  esa rama, y el `plan`/`apply` de infra también, por `specs/ingress-https-dev.md`). No es
  un obstáculo que se pueda saltar desde aquí ni un fallo del entorno: es el orden del
  pipeline del proyecto.

  Todo lo que **sí** se podía verificar en local está verificado y no depende de esto: el
  camino `/api/` alcanza el backend, los cuatro endpoints anónimos dan 404 sin tocarlo (con
  control positivo: el backend los sirve en 200 directamente), el traversal por `%2f` está
  cerrado contra el servidor real, y el tope de cuerpo responde `413` en los dos prefijos.

- **La que decide, y conviene no perderla de vista**: **6.2**. R3.2 exige comprobar **por
  observación** que el backend ve la IP pública real del cliente y no la del contenedor
  `frontend`. Si no lo hace, R3.3 obliga a **no dar R1 por cumplido** y a abrir una entrada
  de tipo `decision` aquí: el camino existiría pero el límite de 10 intentos/min contaría
  todo el despliegue en un solo contador y `audit_logs.actor_ip` registraría el contenedor,
  las dos cosas en silencio. Procedimiento ya escrito en
  `infra/environments/dev/RUNBOOK.md` §7.4, subsección «Comprobar el camino a la API, y la
  IP que el backend observa».

- **6.6 es de las que se olvidan**: mide la postura local que D7 justifica, desde otra
  máquina de la LAN. No cambia ninguna decisión — la confianza seguirá desactivada en local
  pase lo que pase — pero corrige lo que el comentario del compose y el doc **afirman**, y
  la regla 8 de `steering/security.md` tiene precedente exacto de una exención razonable
  sostenida por una justificación que describía una postura que el compose no implementaba.

- **Aviso operativo para ese primer deploy, medido y no supuesto**: el IPAM nuevo en la red
  `private` hace que Compose **recree la red**, lo que para y levanta **todos** los
  servicios conectados a ella (`postgres`, `redis`, `migrate`, `backend`, `worker`, `beat`,
  `frontend`), no solo los dos que este change toca. `up -d --wait` sigue saliendo en 0. Es
  esperado, es de un solo uso, y está anotado junto al `ipam:` del compose.

- **Las seis comprobaciones, íntegras.** Vivían como casillas en `tasks.md` y se han
  movido aquí, que es su única casa: no son verificación local, son post-merge, y tenerlas
  en las dos partes atascaba `mark-local-verified` (se niega, correctamente, con tareas sin
  cerrar) además de duplicar estado derivado, que es lo que la regla compartida 1 prohíbe.

  - [ ] 6.1 Tras el deploy, comprobar que `https://<hostname público>/api/v1/auth/login` responde el sobre del backend y que `/openapi.json`, `/docs`, `/docs/oauth2-redirect` y `/redoc` **no** son alcanzables por ese hostname [R1.1, R2.1, R2.2]
  - [ ] 6.2 **La medición que decide el change** (R3.2): comprobar **por observación** que la IP que el backend registra es la IP pública real del cliente, no la del contenedor `frontend`. Control positivo barato: dos clientes con IP pública distinta —portátil por WiFi y móvil por datos— deben caer en contadores `login:ip:*` distintos, y 10 intentos de uno no deben agotar el presupuesto del otro. Si la propagación no funciona, **no dar R1 por cumplido**: entrada en `BLOCKED.md` de tipo `decision` con el hallazgo, según obliga R3.3 [R3.1, R3.2, R3.3, R5.1, R5.2, R5.3]
  - [ ] 6.3 Comprobar que el residual que D2 acepta por escrito sigue siendo el que se describió y no otro: por `ssh -L 3000:localhost:3000` el `CF-Connecting-IP` es el que envía quien llama, porque esa petición no viene del edge. Se documenta, no se mitiga — requiere SSH en la VM, posición desde la que ya se llega a `127.0.0.1:8000` [R3.1]
  - [ ] 6.4 Comprobar que el aislamiento que R1.3 protege sigue intacto **en el entorno vivo**, con el procedimiento repetible que `RUNBOOK.md` §7.4.6 ya documenta: desde la red `ingress`, `cloudflared` no resuelve `backend` ni `postgres` [R1.2, R1.3]
  - [ ] 6.6 **Medir la postura local que D7 justifica**, porque su primera redacción se apoyaba en un comportamiento de SNAT no medido (hallazgo 5 del panel de seguridad, y la regla 8 de `steering/security.md` tiene precedente exacto de justificaciones que describen una postura que el compose no implementa): desde otra máquina de la LAN, llamar a `<ip-del-host>:8000` y comprobar **qué IP observa el backend** — la del cliente o la del gateway del bridge. La decisión (confianza desactivada en local) no cambia con el resultado; lo que se corrige es lo que el comentario del compose y el doc afirman [R4.1, R6.1]
  - [ ] 6.5 Comprobar que la importación CSV sigue funcionando por el camino público con el tope de 2.6, o registrar el tope efectivo si la medición de 2.6 salió distinta [R1.1]

- **Comando de reanudación**: `/sdd:run api-ingress-routing 6` — reabre la sección desde
  aquí; quien la ejecute vuelve a escribirla en `tasks.md` si prefiere llevar las casillas.
