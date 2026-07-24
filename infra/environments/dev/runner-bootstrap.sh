#!/usr/bin/env bash
# Bootstrap del runner self-hosted de GitHub Actions en la VM dev (label `dev`).
# Fuente de verdad IaC: lo invoca el cloud-init de main.tf (VM nueva) y también se ejecuta
# a mano UNA vez sobre la VM viva (metadata ForceNew + ignore_changes; ver RUNBOOK). [R7]
#
# Lee la config (repo + OCID del secret del PAT) de /etc/autohostai-runner.env, obtiene el PAT
# del OCI Vault por INSTANCE PRINCIPAL (sin credenciales en disco), pide un registration-token
# a la API de GitHub y registra el runner como servicio con auto-arranque. El PAT nunca se
# persiste. Idempotente: usa --replace para re-registrar sin duplicar.
set -euo pipefail

# shellcheck disable=SC1091
source /etc/autohostai-runner.env # define GITHUB_REPO y PAT_SECRET_OCID

RUNNER_HOME=/opt/actions-runner
RUNNER_USER=ubuntu

# 1) PAT desde el Vault vía instance principal (nada en disco, nada en el tfstate).
PAT="$(oci --auth instance_principal secrets secret-bundle get \
  --secret-id "$PAT_SECRET_OCID" \
  --query 'data."secret-bundle-content".content' --raw-output | base64 -d)"

# 2) Registration-token efímero (~1h) del repo.
# El PAT se pasa a curl por --config desde STDIN (no en argv), para que no aparezca en la tabla
# de procesos (/proc/<pid>/cmdline) durante la petición.
REG_TOKEN="$(printf 'header = "Authorization: Bearer %s"\n' "$PAT" \
  | curl -fsSL -X POST --config - \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/$GITHUB_REPO/actions/runners/registration-token" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')"
unset PAT # el PAT ya no se necesita

# 3) Descargar el runner (arm64). Se auto-actualiza tras registrarse, así que basta con la última.
RUNNER_VERSION="$(curl -fsSL https://api.github.com/repos/actions/runner/releases/latest \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["tag_name"].lstrip("v"))')"
mkdir -p "$RUNNER_HOME"
cd "$RUNNER_HOME"
if [ ! -x ./config.sh ]; then
  curl -fsSL -o runner.tar.gz \
    "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-arm64-${RUNNER_VERSION}.tar.gz"
  tar xzf runner.tar.gz && rm -f runner.tar.gz
fi
chown -R "$RUNNER_USER:$RUNNER_USER" "$RUNNER_HOME"

# 4) Configurar (unattended, label `dev`) y arrancar como servicio.
sudo -u "$RUNNER_USER" ./config.sh \
  --url "https://github.com/$GITHUB_REPO" \
  --token "$REG_TOKEN" \
  --labels dev \
  --name autohostai-dev-vm \
  --unattended --replace
unset REG_TOKEN
./svc.sh install "$RUNNER_USER"
./svc.sh start

echo "runner registrado y arrancado (label: dev)."
