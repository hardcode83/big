"""Request/response DTOs of the anonymous guest portal (PRD §17, §23; design D9, D10, D16).

**Every request model here is filled in by somebody with no account**, which changes what the
schema is for. On the authenticated side a Pydantic model mostly documents a contract between
us and a frontend we also write; here it is the outer boundary of the system against the open
internet, and it is the only thing standing between a form field and the database.

Two consequences run through the file:

* `extra="forbid"` everywhere, including — especially — for identity fields. A body carrying
  `tenant_id` or `reservation_id` is rejected rather than ignored, because R2.1 says those
  come from the token and nowhere else, and silently dropping them would leave a caller
  believing they had been accepted.
* the types are the narrowest that will hold the value. `document_expiry_date` is a `date`
  and not a `str`; `nationality` keeps its two-character bound. That is not politeness about
  input validation — those four fields are the ones still *diffable* in `audit_logs.changes`
  after section 2 put the rest on rule 11's denylist, so the schema is what stops guest-typed
  text reaching a cleartext sink. Task 6.6 carries that obligation from the security panel.
"""

import unicodedata
import uuid
from datetime import date, datetime, time
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.guests.application.portal import CheckinResult, CheckinStatus
from app.guests.domain.enums import (
    GuestDocumentStatus,
    GuestDocumentType,
    LegalRegistrationStatus,
)
from app.guests.domain.portal_ports import StayInfo
from app.maintenance.domain.entities import Incident
from app.maintenance.domain.enums import IncidentStatus

MAX_FULL_NAME = 300
MAX_DOCUMENT_NUMBER = 100
NATIONALITY_LENGTH = 2
#: `incidents.title` is `VARCHAR(300)`, and a value that does not fit dies at the driver and
#: aborts the transaction. Bounded here so an over-long title is the `422` R5.2 asks for.
MAX_INCIDENT_TITLE = 300
#: `incidents.description` is unbounded `TEXT`, so nothing downstream refuses a large value —
#: this constant is the whole bound. 5000 is the house figure for a free-text field a person
#: writes (`properties.MAX_NOTES`, `reservations.MAX_TEXT`), and a guest describing a broken
#: boiler needs far less.
#:
#: **Added by the security panel of section 7, and the reasoning is worth keeping.** The first
#: version left it unbounded, arguing the body ceiling was the bound. It is not the right bound:
#: the ceiling is per *request*, while D6's per-token budget is 60 requests a minute, so one
#: link holder could sustain tens of MiB a minute into a column with no maximum, on a write D13
#: deliberately does not deduplicate. `title` was already capped against the same class of
#: abuse; the asymmetry was the bug.
MAX_INCIDENT_DESCRIPTION = 5000


def _storable_text(allowed: str) -> "AfterValidator":
    """Refuse text the database cannot hold, keeping `allowed` (a whitespace shortlist).

    **Two `500`s, found one after the other by the panel of section 7, and they are the same
    bug wearing different hats**: a `str` field with a length bound accepts codepoints that
    nothing downstream can store, and the failure lands in the driver where no handler is
    watching. An anonymous caller got an unhandled `500` where R5.2 and R4.4 promise a refusal
    "antes de crear la incidencia".

    1. **`U+0000`** (QA panel). Postgres refuses a NUL in a `text` value, so asyncpg raises
       `CharacterNotInRepertoireError`. Measured on `POST /guest/incident` and, with the same
       one-byte body, on `POST /guest/checkin`'s `full_name`.
    2. **An unpaired surrogate** (security panel, round 2, against the first version of this
       function). `"boiler\\ud800"` is category `Cs`, not `Cc`, so a category denylist waved it
       through, and `str.encode("utf-8")` raises on it — "surrogates not allowed" — inside
       asyncpg's parameter binding.

    So the guard is written on the property that actually matters — **the value survives
    UTF-8** — rather than on an enumeration of character classes, which is what let the second
    one through. The `Cc` check remains beside it because a NUL *does* encode in Python and is
    refused one layer later, by Postgres.

    **The second one is defence in depth, and saying otherwise was wrong.** An earlier version of
    this docstring claimed a live HTTP vector: a `\\uD800` escape in an ASCII body, decoded into a
    lone surrogate by `json.loads`. That is true of the standard library and **false of this
    stack** — FastAPI parses bodies with pydantic-core's `jiter`, which refuses to build such a
    string at all, so the request dies as `json_invalid` before any field validator runs. Measured
    both ways after the QA panel of section 7 caught the claim outrunning the code; the same panel
    also showed the endpoints are safe either way. The branch stays because it is correct, cheap
    and one JSON-parser change away from being the only thing standing there — but it is pinned by
    a test that drives the validator **directly**, since no body can reach it.

    **`document_number` is guarded too, and the reason the first version excluded it was
    wrong.** That version argued Fernet encryption made the field immune. It does not:
    `app/core/crypto.py` calls `plaintext.encode()`, which raises on a surrogate *before* the
    cipher runs — so the field had the same `500`, with the same one-character body. Reported by
    the security panel, which read the crypto path instead of taking the claim.

    Category `Cc` and not `str.isprintable()`: the house pattern for a log reference *drops*
    non-printable characters (`_element_reference` in the PMS adapters), which is right for a
    diagnostic id and wrong for the guest's own words — silently editing what somebody wrote
    into a column an operator will act on is worse than refusing it. `Cc` is exactly C0 and C1,
    so ordinary text, accents and emoji pass untouched.

    The second reason to refuse rather than strip: `incidents.title` and `guests.full_name` are
    rendered into lists and logs, and a value carrying `\\r` or an escape sequence is the
    line-forging class the security panel of `channex-staging-adapter` measured against a
    provider's identifier. Here the writer is anonymous, so the argument is stronger.

    No message here echoes the value. The offending codepoints are named — they are a character
    class, not content — but never the surrounding text, because one of the guarded fields is an
    identity document and a `422` body is one more place it must not appear (R3.3).

    That last clause is only true because the application replaces FastAPI's default validation
    handler, which would serialise Pydantic's `input` field and answer a rejected document number
    with the number. Nothing pinned it until
    `tests/guests/test_portal_incident_api.py::test_a_validation_failure_does_not_echo_what_was_rejected`,
    added when the security panel raised the doubt.
    """

    def check(value: str) -> str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            # Deliberately not chained and deliberately not quoting the exception, whose own
            # message carries the offending fragment of the value.
            raise ValueError(
                "must be text that survives UTF-8: found an unpaired surrogate"
            ) from None
        offenders = sorted(
            {
                character
                for character in value
                if character not in allowed and unicodedata.category(character) == "Cc"
            }
        )
        if offenders:
            raise ValueError(
                "must not contain control characters: found "
                + ", ".join(f"U+{ord(character):04X}" for character in offenders)
            )
        return value

    return AfterValidator(check)


#: A single line an operator reads in a list: no control characters at all, not even a newline.
SingleLineText = Annotated[str, _storable_text("")]
#: Free prose the guest writes: paragraphs and tabs are how a person describes a problem.
MultiLineText = Annotated[str, _storable_text("\t\n\r")]


class StayInfoResponse(BaseModel):
    """What `GET /guest/info/{token}` returns — exactly `StayInfo` (D9).

    A field-for-field mirror on purpose. The projection is where R3.2 is enforced
    structurally, so this model earning its own opinion about which fields to include would
    reintroduce the very decision `StayInfo` exists to remove. `tests/guests/test_portal_ports.py`
    pins the projection's field set; the contract test pins this one against the code.
    """

    model_config = ConfigDict(from_attributes=True)

    check_in_date: date
    check_out_date: date
    check_in_time: time
    check_out_time: time
    property_name: str
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    country: str
    timezone: str
    wifi_name: str | None
    arrival_notes: str | None
    access_code_masked: str | None
    support_channel: str | None

    @classmethod
    def from_domain(cls, info: StayInfo) -> "StayInfoResponse":
        return cls.model_validate(info)


class CheckinStatusResponse(BaseModel):
    """What `GET /guest/checkin/{token}` returns: **what is missing**, never what was given.

    R4.1 asks for the absent fields "sin devolver los ya aportados que sean sensibles", and
    this returns names only — which the guest already knows, since they are the boxes they
    left empty. R3.3 makes the document number binding even for the guest who supplied it.
    """

    missing_fields: list[str]
    document_status: GuestDocumentStatus
    legal_registration_status: LegalRegistrationStatus

    @classmethod
    def from_domain(cls, status: CheckinStatus) -> "CheckinStatusResponse":
        return cls(
            missing_fields=list(status.missing_fields),
            document_status=status.document_status,
            legal_registration_status=status.legal_registration_status,
        )


# Why this model looks the way it does — a comment and not the docstring, because a model
# docstring becomes the schema's `description` in `/openapi.json`, which is itself in
# `ANONYMOUS_ENDPOINTS`: the rule `portal_router.py` states for the response descriptions, and
# none of what follows is a consumer's business. `ReportIncidentRequest` below carries the same
# note.
#
# Six and not eight: `check_in_date` and `check_out_date` are the reservation's, and the guest is
# not asked for them — nor allowed to send them, since `extra="forbid"` rejects anything not
# declared here. That is R2.1 at the boundary.
#
# All six required together, like the manager's `SetDocumentRequest`: PRD §17 needs the set, and a
# guest who sends a number without an expiry date looks documented and cannot be reported.
#
# **`str_strip_whitespace=True` is load-bearing, not tidiness.** `min_length=1` counts characters,
# so `"   "` satisfied it in the first version, and the consequences diverged by branch: on a stay
# that already had a `Guest` the write landed and replaced the legal name with whitespace — after
# which `missing_fields`, which *does* normalise, kept the stay in `PENDING_GUEST_DATA` for ever
# with no error anywhere; on a stay with no guest it came back as the `404` reserved for "your link
# does not work". Both found by the QA panel of section 6. Stripping first makes a blank name the
# `422` R4.4 asks for, in one place, for every field of the form.
#
# **The types are the guard the audit sink depends on.** `document_type` is an enum,
# `date_of_birth` and `document_expiry_date` are `date`s, `nationality` is bounded to two
# characters. After section 2 denylisted `full_name` and `nationality`, the fields still recorded
# as real diffs are exactly the enum and the dates — so declaring any of them `str` here, for a
# friendlier error message, would put guest-typed text into `audit_logs.changes`. Carried from the
# security panel of section 2 into task 6.6.
class SubmitCheckinRequest(BaseModel):
    """The six fields of PRD §17 the guest supplies.

    All six are required together. `check_in_date` and `check_out_date` are the
    reservation's and are neither asked for nor accepted here. Surrounding whitespace is
    stripped before validation.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # `SingleLineText` on all three text fields. Section 6 shipped them as bare `str`, and the
    # panel of section 7 measured the consequence on its own route: a value the database cannot
    # store is an unhandled `500` from the driver, not the `422` R4.4 asks for. The same body
    # reproduces it here, so the fix belongs to both routes and lives in one place.
    #
    # **`document_number` included**, against the first version of this comment, which excluded
    # it on the grounds that Fernet encryption made it immune. `app/core/crypto.py` calls
    # `plaintext.encode()`, so an unpaired surrogate raises before the cipher runs and the field
    # had the same `500`. None of these three is a charset rule about identity documents: the
    # guard refuses only what nothing downstream can hold.
    full_name: Annotated[SingleLineText, Field(min_length=1, max_length=MAX_FULL_NAME)]
    nationality: Annotated[
        SingleLineText, Field(min_length=NATIONALITY_LENGTH, max_length=NATIONALITY_LENGTH)
    ]
    date_of_birth: date
    document_type: GuestDocumentType
    document_number: Annotated[
        SingleLineText, Field(min_length=1, max_length=MAX_DOCUMENT_NUMBER)
    ]
    document_expiry_date: date


class CheckinSubmittedResponse(BaseModel):
    """Two statuses, and **no echo of the document** (R3.3, D10).

    The guest just sent the number; returning it would put it in one more response body, one
    more proxy log and one more browser cache. Same contract `DocumentStoredResponse` already
    holds on the authenticated side.
    """

    document_status: GuestDocumentStatus
    legal_registration_status: LegalRegistrationStatus

    @classmethod
    def from_domain(cls, result: CheckinResult) -> "CheckinSubmittedResponse":
        return cls(
            document_status=result.document_status,
            legal_registration_status=result.legal_registration_status,
        )


# Why this model looks the way it does. Deliberately a comment and not the docstring: a model
# docstring becomes the schema's `description` in `/openapi.json`, which is itself in
# `ANONYMOUS_ENDPOINTS`, so anything written there is published to the same caller D5 defends
# against — the rule `portal_router.py` states for the response descriptions. The reasoning is
# identical; only its home is safe.
#
# **`title` is required because `incidents.title` is `NOT NULL`**, and deriving it from the first
# characters of the description — the tempting alternative — would invent a datum the guest did
# not write and put it in a column an operator reads as the guest's own words (D15).
#
# Neither field is echoed anywhere it could not be redacted later: `AUDITABLE_FIELDS` leaves both
# out of the incident's audit row and the timeline entry carries a constant title, so what a
# stranger types here reaches exactly one place — the `incidents` row a manager is meant to read.
#
# **Both fields are bounded, and `description`'s bound is not the body ceiling.** D7 — "el tope de
# cuerpo ya está puesto; no se añade nada" — is about the middleware that refuses an oversized
# *request* before routing, and it stays untouched: no new middleware, no new setting. What it does
# not do is bound how much text a legitimate-sized request may store, and with
# `MAX_INCIDENT_DESCRIPTION` absent the only limit left was per-request, while the per-token budget
# of D6 allows many requests a minute. A field-level maximum is not a second ceiling; it is the
# thing the ceiling was never doing. The budget's actual value stays in `design.md`,
# `app/core/config.py` and `.env.example`, none of which are served over HTTP.
#
# `str_strip_whitespace=True` and `min_length=1` together are what make a whitespace-only report
# the `422` R5.2 requires — the same pairing `SubmitCheckinRequest` documents.
class ReportIncidentRequest(BaseModel):
    """What `POST /guest/incident/{token}` accepts: a title and a description.

    `title` is required. Both fields are bounded and must be non-empty; surrounding
    whitespace is stripped first, so the maxima count characters after stripping.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: Annotated[
        SingleLineText, Field(min_length=1, max_length=MAX_INCIDENT_TITLE)
    ]
    description: Annotated[
        MultiLineText, Field(min_length=1, max_length=MAX_INCIDENT_DESCRIPTION)
    ]


class IncidentReportedResponse(BaseModel):
    """The acknowledgement, and **only** the acknowledgement (R5.3, D15).

    Three fields: the id of the incident just created, its status and when. R5.3 forbids the
    bearer of a token from listing, reading, modifying, assigning, classifying or resolving
    incidents — "la única lectura permitida es el acuse de la que acaba de crear" — so this
    model is the whole of what the portal may ever say about an incident.

    It carries no `category`, no `severity` and no `ai_*`: those are `maintenance`'s to fill
    in, and returning their initial values would promise the guest a shape that changes
    underneath them.
    """

    id: uuid.UUID
    status: IncidentStatus
    created_at: datetime

    @classmethod
    def from_domain(cls, incident: Incident) -> "IncidentReportedResponse":
        return cls(
            id=incident.id, status=incident.status, created_at=incident.created_at
        )
