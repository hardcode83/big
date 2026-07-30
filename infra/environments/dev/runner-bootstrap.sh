#!/usr/bin/env bash
# Bootstrap del runner self-hosted de GitHub Actions (label = $ENV) en la VM.
# Fuente de verdad IaC: lo invoca el cloud-init (VM nueva) y también se ejecuta a mano UNA vez
# sobre la VM viva (metadata ForceNew + ignore_changes; ver RUNBOOK). [R7]
#
# Registro vía GitHub App: lee la clave privada de la App del OCI Vault por INSTANCE PRINCIPAL,
# mintea un installation-token (helper gh-app-install-token.py) y con él pide el registration-token.
# El installation-token va por --config/stdin (fuera de argv). El registration-token, en cambio,
# se pasa a `config.sh --token` por argv — inevitable (el runner oficial no acepta el token por
# stdin/env); mitigado: es efímero, de un solo uso y se consume con --replace. Idempotente.
set -euo pipefail

# shellcheck disable=SC1091
source /etc/autohostai-deploy.env # ENV, GITHUB_REPO, GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, APP_KEY_SECRET_OCID, ...

RUNNER_HOME=/opt/actions-runner
RUNNER_USER=ubuntu

# El usuario del runner debe poder hablar con el socket de Docker (el deploy es `docker compose`
# local). En una VM nueva el cloud-init ya hace este usermod antes de arrancar el runner; aquí lo
# garantizamos también para el alta out-of-band / re-provisión (el servicio, al (re)arrancar más
# abajo con svc.sh, hereda el grupo docker recién añadido).
usermod -aG docker "$RUNNER_USER" || true

# 1) Installation-token de la GitHub App (clave del Vault → helper), sin credenciales en disco.
# GITHUB_APP_ID/INSTALLATION_ID se pasan explícitos al helper: `source` sin `export` no los
# propaga al subproceso python (mismo patrón que el paso de deploy).
INSTALL_TOKEN="$(oci --auth instance_principal secrets secret-bundle get \
  --secret-id "$APP_KEY_SECRET_OCID" \
  --query 'data."secret-bundle-content".content' --raw-output \
  | base64 -d \
  | GITHUB_APP_ID="$GITHUB_APP_ID" GITHUB_APP_INSTALLATION_ID="$GITHUB_APP_INSTALLATION_ID" \
    python3 /opt/gh-app-install-token.py)"

# 2) Registration-token del repo. El token va por --config desde STDIN (no en argv → no aparece
#    en /proc/<pid>/cmdline).
REG_TOKEN="$(printf 'header = "Authorization: Bearer %s"\n' "$INSTALL_TOKEN" \
  | curl -fsSL -X POST --config - \
      -H "Accept: application/vnd.github+json" \
      -H "X-GitHub-Api-Version: 2022-11-28" \
      "https://api.github.com/repos/$GITHUB_REPO/actions/runners/registration-token" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["token"])')"
unset INSTALL_TOKEN

# 3) Descargar el runner (arm64). Se auto-actualiza tras registrarse; basta con la última.
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

# 4) Configurar (unattended, label = entorno) y arrancar como servicio.
sudo -u "$RUNNER_USER" ./config.sh \
  --url "https://github.com/$GITHUB_REPO" \
  --token "$REG_TOKEN" \
  --labels "$ENV" \
  --name "autohostai-${ENV}-vm" \
  --unattended --replace
unset REG_TOKEN
./svc.sh install "$RUNNER_USER"
./svc.sh start

echo "runner registrado y arrancado (label: ${ENV})."
