# ingress-https-dev

[INFRA] ingress HTTPS público de la app en dev vía **Cloudflare Tunnel** (`cloudflared` en el compose de deploy, sin abrir ningún puerto): túnel, routing y DNS declarados con el provider `cloudflare`, secreto del túnel generado por Terraform y guardado en OCI Vault; cierra el acceso HTTP directo dejando `ingress_ports = [22]`. Alternativas descartadas (nginx + Origin Cert, Caddy + LE DNS-01, Traefik) en ADR 0003 (no está en el plan original, añadido tras `app-deploy-dev`)
