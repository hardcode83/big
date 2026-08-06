"""The ciphertext type, kept free of any crypto dependency on purpose.

Named `encrypted_secret` rather than the more natural `secrets` because that is a standard
library module name: absolute imports mean `app.core.secrets` would resolve correctly, but a
package module that shadows a stdlib name confuses tooling and readers for no gain.

Split from `crypto.py` (design D3) so that `domain/` can name an encrypted value without
importing `cryptography` or `Settings`. `tests/test_layering.py` only inspects the import
statements of a file, so a single module would have passed it while still dragging a
framework into the pure layer — the split makes the layering honest rather than merely
undetected.

`EncryptedSecret` carries ciphertext and nothing else. There is deliberately no `plaintext`
attribute, no `reveal()` method and no way back: producing cleartext requires calling
`crypto.decrypt`, which is the single chokepoint rule 3(a) and the AuditLog obligation of
ADR 0006 both need in order to exist at all. A value object that could decrypt itself would
put that chokepoint inside every caller.
"""

import base64
import binascii
from dataclasses import dataclass

REDACTED = "***"

# Every Fernet token starts with this version byte. `cryptography` is deliberately NOT imported
# here — that is the split this module exists for — so the check is done on the raw bytes.
_FERNET_VERSION = 0x80


@dataclass(frozen=True)
class EncryptedSecret:
    """Fernet ciphertext for one secret at rest.

    `__repr__` is redacted for the same reason `ChannexClient.__repr__` is: an object holding
    a credential is one `logger.debug` away from writing it to disk. Here the value is already
    encrypted, so the leak is smaller — but a ciphertext is still the material an offline
    attack works against, and printing it invites treating it as harmless.
    """

    ciphertext: str

    def __post_init__(self) -> None:
        """Refuse anything that is not a Fernet token — by construction, not by convention.

        The security panel of sections 4-5 found the gap: this type validated nothing, so
        `EncryptedSecret(ciphertext=token)` was a legal way to put a **plaintext** account
        credential into a column called `secret_encrypted`, and neither the type, the repository,
        the schema nor the "is it ciphertext?" test would object — that test only exercises the
        path that did call `encrypt`. D3 claimed this type closed its contract "por construcción,
        el mismo argumento que llevó a `ChangeSet`", and `ChangeSet.__init__` really does raise.
        This one did not.

        The check is structural and cheap: a Fernet token is base64url of a payload whose first
        byte is the version `0x80`. It cannot prove the token decrypts — only the key can — but
        it makes the realistic accident impossible, which is a credential typed by a human or
        read from a file landing here unencrypted.
        """
        try:
            raw = base64.urlsafe_b64decode(self.ciphertext.encode())
        except (binascii.Error, ValueError, AttributeError) as error:
            raise ValueError(
                "EncryptedSecret takes Fernet ciphertext, not arbitrary text — "
                "build it with app.core.crypto.encrypt()"
            ) from error
        if not raw or raw[0] != _FERNET_VERSION:
            raise ValueError(
                "EncryptedSecret takes Fernet ciphertext, not arbitrary text — "
                "build it with app.core.crypto.encrypt()"
            )

    def __repr__(self) -> str:
        return f"EncryptedSecret(ciphertext={REDACTED})"

    def __str__(self) -> str:
        # dataclass does not define __str__, so without this it falls back to __repr__ today
        # and would start leaking the moment someone added one. Pinned by its own test.
        return self.__repr__()
