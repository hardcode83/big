"""Throwaway probe: reverts _to_endpoint to only guard EncryptedSecret construction, confirming
the two new parametrised cases would fail without the WebhookEndpoint(...) call also inside the
try/except."""
import pytest
from app.core.crypto import SecretDecryptionError
from app.core.encrypted_secret import EncryptedSecret
from app.integrations.domain.entities import WebhookEndpoint
from app.integrations.infrastructure import repositories as repo_mod


def narrow_to_endpoint(model):
    try:
        secret = EncryptedSecret(ciphertext=model.header_secret_encrypted)
    except ValueError as error:
        raise SecretDecryptionError(f"stored webhook endpoint {model.id} is not usable") from error
    # NOT in the try: this is the pre-fix (finding 2) shape.
    return WebhookEndpoint(
        id=model.id, tenant_id=model.tenant_id, provider=model.provider,
        token_hash=model.token_hash, header_name=model.header_name,
        header_secret=secret, rotated_at=model.rotated_at,
    )


@pytest.fixture(autouse=True)
def _revert_guard(monkeypatch):
    monkeypatch.setattr(repo_mod, "_to_endpoint", narrow_to_endpoint)
