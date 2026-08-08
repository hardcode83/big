# BLOCKED — api-ingress-routing

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

- **Comando de reanudación**: `/sdd:run api-ingress-routing 6`
