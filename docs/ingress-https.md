# Ingress HTTPS del entorno dev

Cómo se accede a la aplicación desplegada y cómo se opera esa vía de acceso. El *qué hace* el sistema está en `sdd/specs/ingress-https-dev.md`; la decisión de por qué es así, en [`adr/0003-https-ingress-dev.md`](adr/0003-https-ingress-dev.md); los procedimientos paso a paso, en [`infra/environments/dev/RUNBOOK.md`](../infra/environments/dev/RUNBOOK.md) §7.

## La URL

**https://autohostai.digitalsec.work**

Funciona desde cualquier red, incluido el móvil, que era el objetivo: el principio 2 de `sdd/steering/product.md` exige que la propietaria vea el estado de sus viviendas desde el teléfono en menos de 10 segundos, y antes de esto la app solo era alcanzable por HTTP desde las IPs de los operadores.

## Cómo llega el tráfico

```
navegador  →  edge de Cloudflare  →  túnel  →  contenedor frontend
             (termina TLS)            (conexión saliente
                                       desde la VM)
```

Lo que hay que entender de este diseño es que **la VM no tiene ningún puerto HTTP abierto**. El contenedor `cloudflared` abre una conexión *saliente* al edge de Cloudflare y el tráfico entra por ahí. El security list de la máquina solo permite SSH (22), acotado a las IPs de los operadores.

Consecuencias prácticas:

- **No hay certificados que renovar.** El TLS lo termina Cloudflare con el certificado de la zona.
- **No hay puerta alternativa.** Si el edge o el túnel caen, la app no es alcanzable por HTTPS; el acceso para diagnosticar es SSH.
- **El backend no está expuesto.** El navegador nunca le llama: el frontend habla con él server-side por la red interna del compose.

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

El procedimiento completo —requisitos, alias de `~/.ssh/config`, logs, acceso a la base de datos, errores frecuentes— está en el **RUNBOOK §7.4**.

## Qué se toca para cambiar algo

Todo el lado Cloudflare es Terraform, en `infra/environments/dev/`: el túnel, sus reglas de routing, el registro DNS y el forzado de HTTPS de la zona. **No se configura nada a mano en el dashboard** salvo dos cosas que no son codificables y están documentadas como *bootstrap irreducible* en `sdd/steering/infra.md`: el dominio con su zona, y el API token del provider.

El contenedor `cloudflared` lo despliega el CD (`deploy-dev`), no Terraform, igual que el resto de servicios de la aplicación.

## Limitaciones conocidas

- **El TLS mínimo de la zona está en 1.0**, no en 1.2. `digitalsec.work` aloja otros servicios y subirlo concentraría el riesgo sobre ellos sin aportar nada a este ingress (decisión D7 del change).
- **El hostname debe ser de primer nivel** bajo el apex (`algo.digitalsec.work`). El certificado Universal SSL gratuito solo cubre el apex y un nivel; profundizar exigiría un certificado de pago. Cuando haya un segundo entorno, el patrón es aplanar (`autohostai-staging.digitalsec.work`), no anidar.
- **Cloudflare es dependencia de runtime**, no solo de DNS. Está en el camino del tráfico.
- **Sin autenticación en el edge.** La app es pública; la autenticación del producto llega con `auth-tenancy`.
