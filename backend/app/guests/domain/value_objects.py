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

import re
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


# `whatsapp-cloud-adapter` design D5 / R4.2, and its risk note on normalisation: a hand-
# rolled parser that guesses at an unfamiliar national format can either miss a real guest
# match or, worse, collide two different numbers. These bounds and the two shapes below are
# deliberately the whole of it — no general international parser.
_E164_MIN_DIGITS = 8
_E164_MAX_DIGITS = 15
_ES_NATIONAL_LENGTH = 9
_ES_COUNTRY_CODE = "+34"

# Formatting a human (or a copy-pasted contact card) might add around digits — not a
# character class phone numbers use, so stripping it can never turn one number into another.
_FORMATTING_CHARS = re.compile(r"[\s\-().]")


def normalize_phone_e164(value: str) -> str | None:
    """Best-effort E.164 normalisation, narrow on purpose (design D5, its risk note).

    Recognises exactly two shapes and fails closed — returns `None`, never a guess — for
    everything else (R4.3's "sin adivinar"):

    - **Already E.164**: `+` followed by 8-15 digits. Covers `+34612345678` and any other
      country's number a guest's phone happens to already be stored/typed in.
    - **Spanish national**: a bare 9-digit number with no leading `+`/`00`, which defaults
      to `+34` — the pilot properties are in Madrid (PRD context), so this is the one
      "guess" allowed by design, and only for the one market it is safe to assume.

    Formatting characters (spaces, hyphens, dots, parentheses) are stripped before either
    shape is checked. A bare number of any other length, a `00`-prefixed international
    number, or anything containing letters returns `None` rather than a misparse — the
    risk this function exists to avoid is a false *match* (colliding two guests), which is
    worse than a false negative (escalating one message a smarter parser would have
    resolved).

    Idempotent: normalising an already-normalised value returns it unchanged.
    """
    if not value:
        return None
    cleaned = _FORMATTING_CHARS.sub("", value.strip())
    if not cleaned:
        return None

    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if digits.isdigit() and _E164_MIN_DIGITS <= len(digits) <= _E164_MAX_DIGITS:
            return "+" + digits
        return None

    if cleaned.isdigit() and len(cleaned) == _ES_NATIONAL_LENGTH:
        return _ES_COUNTRY_CODE + cleaned

    return None
