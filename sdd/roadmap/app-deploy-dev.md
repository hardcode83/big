# app-deploy-dev

[INFRA] CD de la app al entorno dev: GitHub Actions construye las imágenes arm64, las publica en GHCR y las despliega en la VM mediante un **runner self-hosted en la propia VM** (`docker compose pull && up -d`, sin SSH); trigger = push a `main`. Runner + secrets como IaC (GitHub App + instance principal + secrets generados por TF → Vault). Repo movido a la org `autohostai-labs`. (no está en el plan original, añadido tras `infra-dev-hardening`)
