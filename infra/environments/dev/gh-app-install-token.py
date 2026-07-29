#!/usr/bin/env python3
"""Mintea un installation-token de una GitHub App.

Lee la clave privada (.pem) por STDIN y GITHUB_APP_ID / GITHUB_APP_INSTALLATION_ID del entorno;
imprime el installation-token por STDOUT. Solo usa `cryptography` (dependencia de oci-cli) +
stdlib — sin PyJWT. Lo usan el bootstrap del runner (para el registration-token) y el deploy
(para `docker login ghcr.io`). El token es efímero (~1h); nada se persiste.
"""
import base64
import json
import os
import sys
import time
import urllib.request

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey


def b64url(raw: bytes) -> bytes:
    return base64.urlsafe_b64encode(raw).rstrip(b"=")


def main() -> None:
    app_id = os.environ["GITHUB_APP_ID"]
    installation_id = os.environ["GITHUB_APP_INSTALLATION_ID"]
    key = serialization.load_pem_private_key(sys.stdin.buffer.read(), password=None)
    assert isinstance(key, RSAPrivateKey), "la clave privada de la GitHub App debe ser RSA"

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {"iat": now - 60, "exp": now + 540, "iss": app_id}  # margen de reloj + 9 min
    signing_input = b64url(json.dumps(header).encode()) + b"." + b64url(json.dumps(payload).encode())
    signature = key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
    app_jwt = (signing_input + b"." + b64url(signature)).decode()

    req = urllib.request.Request(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        method="POST",
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        sys.stdout.write(json.loads(resp.read())["token"])


if __name__ == "__main__":
    main()
