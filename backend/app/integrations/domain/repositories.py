"""Ports owned by the integrations domain.

`PmsCredentialRepository` lives HERE and not in `properties/domain/`, which is where it was
first written. The architecture panel of sections 4-5 caught that: its entire vocabulary —
`PmsCredential`, `PMSProvider`, `PmsCredentialScope` — belongs to this domain, and `properties`
contributes only an optional foreign key, exactly the scalar relationship
`PropertyStateTransitionRepository` already handles without importing a foreign entity.

The misplacement was not merely untidy: it made `properties` the owner of another domain's
aggregate, and `infrastructure/pms_factory.py` then imported the port back out of `properties`,
a properties→integrations→properties round trip that did not exist before this change.
`tests/test_layering.py` does not catch it, because it checks layer direction within a domain
and not port ownership across domains.
"""

import uuid
from typing import Protocol

from app.integrations.domain.entities import PmsCredential
from app.integrations.domain.enums import PMSProvider, PmsCredentialScope


class PmsCredentialRepository(Protocol):
    """Provider credentials, stored encrypted (ADR 0006 decision 7, R3/R4).

    Read `get_for` as "the credential this property's provider needs at this granularity". Where
    this port lives, and why it moved, is the module docstring above — not repeated here, because
    a sentence stating its own location in two places is how this one went stale in the first
    place: it still claimed to live in `properties/` fifteen lines below the paragraph explaining
    it no longer does.

    **No `list` and no `get_all`, deliberately.** Every read of a credential is an audited act
    (R4.2) and a decryption point, so a method that returns many of them would multiply both by
    the size of the portfolio. Callers resolve exactly the one they are about to use.
    """

    async def get_for(
        self,
        tenant_id: uuid.UUID,
        provider: PMSProvider,
        scope: PmsCredentialScope,
        property_id: uuid.UUID | None = None,
    ) -> PmsCredential | None:
        """The stored credential, or `None` when there is none.

        `None` rather than raising: absence is an answer the caller must handle, and the caller
        is the one that knows whether it is fatal. The command turns it into
        `MissingPmsCredentialError` and exits non-zero — never a silent fall back to the mock,
        which would report "created 0" and be indistinguishable from an empty PMS.

        Returns the ciphertext inside an `EncryptedSecret`. Decrypting is a separate, explicit
        act; this port never hands back cleartext.
        """
        ...

    async def upsert(self, tenant_id: uuid.UUID, credential: PmsCredential) -> None:
        """Store or replace the credential at its (provider, scope, property) coordinates.

        Upsert rather than add/update because the caller's intent is always "this is the
        credential now" — the provisioning command has no use for the distinction, and a
        separate `add` would invite a read-then-write race on rotation.

        Raises `CrossTenantWriteError` when the credential belongs to another tenant.
        """
        ...
