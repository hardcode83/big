# BLOCKED — ingress-https-dev

Cola de bloqueos de este change. `/sdd:status` la muestra primero y `/sdd:archive` se niega a cerrar con entradas sin resolver. Resolver una entrada = borrarla; cuando quede vacío, borrar el fichero.

---

## 1. Faltan los secrets y variables de Cloudflare en el repositorio

- **Fase**: run (sección 1 cerrada; bloquea 2.8 en adelante)
- **Tipo**: `decision` — requiere a un humano. El API token se acuña en el dashboard de Cloudflare, que es *bootstrap irreducible* (`steering/infra.md`, tarea 7.3), y subir credenciales es una acción que no puede hacer el agente.
- **Qué y por qué**: verificado con `gh secret list` / `gh variable list` (2026-07-29) que **ninguno** de estos existe. Sin ellos, `terraform plan`/`apply` fallan nombrando la variable ausente (comportamiento correcto, verificado en la tarea 1.5), así que no se puede aplicar nada real ni verificar las tareas 2.8, 3.2 y 4.3.

  ```bash
  gh secret   set CLOUDFLARE_API_TOKEN   --repo autohostai-labs/AutoHostAI
  gh secret   set CLOUDFLARE_ZONE_ID     --repo autohostai-labs/AutoHostAI
  gh variable set CLOUDFLARE_ACCOUNT_ID  --repo autohostai-labs/AutoHostAI
  gh variable set CLOUDFLARE_ZONE_NAME   --repo autohostai-labs/AutoHostAI --body 'digitalsec.net'
  gh variable set PUBLIC_HOSTNAME        --repo autohostai-labs/AutoHostAI --body 'autohostai.digitalsec.net'
  gh variable set OCI_VAULT_ID           --repo autohostai-labs/AutoHostAI
  ```

  Permisos mínimos del token (los tres, y ojo que "Cloudflare Tunnel" **no** está bajo "Zero Trust" en el selector): `Account | Cloudflare Tunnel | Edit`, `Zone | DNS | Edit`, `Zone | Zone Settings | Edit`. Acotar a la zona `digitalsec.net`, no "All zones". El valor de `OCI_VAULT_ID` sale de `terraform output vault_id`.

  Verificar el token antes de subirlo:
  ```bash
  curl -s -H "Authorization: Bearer <TOKEN>" https://api.cloudflare.com/client/v4/user/tokens/verify | jq .success
  ```

- **Comando de reanudación**: `/sdd:run ingress-https-dev`

---

## 2. `apply` real de infra pendiente de ejecución manual

- **Fase**: run (tareas 2.8, 3.2)
- **Tipo**: `deferred` — el flujo puede reanudarlo en cuanto exista la entrada 1.
- **Qué y por qué**: el único camino a recursos reales es `workflow_dispatch` del workflow `infra-dev`, y **desde este change tanto `apply` como `plan` están acotados a `main`** (el gating de `plan` se añadió al corregir un hallazgo del panel de seguridad: ese job recibe ahora un token con control de DNS de toda la zona, ver design D10). Consecuencia: **no se puede ni planificar desde la rama `sdd/ingress-https-dev`**. El orden obligado es PR → merge a `main` → `plan` → `apply`, lo que significa que las tareas 2.8, 3.2 y 4.3 se verifican **después** del merge, no antes. Eso choca con el orden habitual del flujo SDD (verificar y luego PR) y es una consecuencia deliberada, no un descuido.

  **Aviso del panel de seguridad (segunda ronda):** la salida a este bloqueo **no** debe ser relajar el gating de `plan` — eso reabre el hallazgo tal cual (un `workflow_dispatch` sobre una rama arbitraria ejecuta el workflow de esa rama con un token que controla el DNS de toda la zona). La vía correcta es aceptar el orden merge → `plan` → `apply`, con las tareas 2.9, 3.2 y 4.3 verificadas después del merge y el change sin archivar hasta que lo estén.
- **Comando de reanudación**: `/sdd:run ingress-https-dev` tras resolver la entrada 1 y decidir el orden merge/apply.

---

## 3. Verificación HTTPS externa: solo la puede hacer una persona

- **Fase**: run (tareas 5.1, 5.2 — y por tanto toda la sección 6)
- **Tipo**: `decision` — requiere a un humano con una red fuera de los CIDRs de operador.
- **Qué y por qué**: R4.4 prohíbe cerrar los puertos sin evidencia registrada de que el túnel sirve la app. La comprobación exige una red **fuera** de `var.allowed_ssh_cidrs` (p. ej. datos móviles del teléfono), porque desde una IP autorizada el acceso directo enmascararía un túnel roto. El agente no tiene esa red.
- **Comando de reanudación**: `/sdd:run ingress-https-dev 6` una vez registrada la evidencia de 5.1 y 5.2.
