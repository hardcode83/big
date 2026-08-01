"""Value objects of the guests domain (design D8).

`normalize_email` is intentionally a **second** definition of the same rule that
`app/auth/domain/value_objects.py` applies to users, and not an import of it. Two
reasons: the guest domain must not depend on the auth domain to compare two strings,
and the two rules answer different questions — for a user a normalised address is a
globally unique identity (ADR 0005, enforced by `uq_users_lower_email`), while for a
guest it is only a dedup hint, because `guests.email` is a plain index and the same
person can legitimately appear twice.

If the two ever need to *differ*, that is a bug in whichever change made them differ:
"the same email address" has one meaning in this system. Consolidating both into a
shared module is a candidate for the change that next touches `auth` (design D3 records
the same debt for the unit of work).
"""

import uuid
from dataclasses import dataclass

from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus


@dataclass(frozen=True)
class GuestSummary:
    """What a reservation is allowed to know about its guest (R1.8, design D17).

    Everything the operation needs to contact and identify the guest, and **nothing** from
    the identity document: no `document_number_encrypted`, no `document_expiry_date`, no
    `date_of_birth`, no `nationality`. `document_status` is included because rule 4 of
    `steering/security.md` says exactly that — "número de documento jamás en listados
    (solo `document_status`)".

    A frozen projection rather than the `Guest` entity so the guarantee is structural: no
    future serialiser can reach a field that is not here, and R1.8 does not depend on
    every author of a response model remembering to exclude one.
    """

    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    preferred_language: str
    document_status: GuestDocumentStatus
    legal_registration_status: LegalRegistrationStatus


def normalize_email(value: str) -> str:
    """`strip` + `lower`, applied in Python on both write and read.

    Never `lower()` inside the SQL: Postgres and Python do not agree on case folding
    for every alphabet, so folding on one side and storing raw on the other makes the
    lookup and the stored data disagree — the same trap documented at length in
    `app/auth/domain/value_objects.py`.
    """
    return value.strip().lower()
