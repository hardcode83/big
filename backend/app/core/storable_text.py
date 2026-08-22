"""Text a Postgres `text`/`varchar` column can actually hold, as a Pydantic annotation.

Promoted here from `app/guests/api/portal_schemas.py` by `cleaner-incident-report` (design
D7), unchanged in behaviour: it began as a private helper of that module and is now shared.

**It is not optional polish.** Without the guard a value carrying `U+0000` or a lone
surrogate reaches asyncpg and comes back as an undeclared `500`, which is the exact failure
the section-7 panel of `guest-portal-api` measured twice. What it enforces is one of the
three things rule 11 of `sdd/steering/security.md` names as the whole bound on a free-text
column — *texto que la base de datos pueda almacenar*, beside types and a maximum length.

Home: `app/core/` rather than either module. A second `api/` layer of a different domain will
need it, and neither of the two owns the other, so the alternatives were importing a private
name across domains or keeping a second copy of forty lines that were won two security panels
at a time. Today exactly one module imports it; that is what this promotion is ahead of.

**No column maximum lives here**, and nothing here says who writes any column: both belong
elsewhere by rule, the first to whichever module owns the column and the second to the
rule-11 census of `sdd/steering/security.md`, which is its only home.
"""

import unicodedata
from typing import Annotated

from pydantic import AfterValidator


def storable_text(allowed: str) -> AfterValidator:
    """Refuse text the database cannot hold, keeping `allowed` (a whitespace shortlist).

    **Two `500`s, found one after the other by the panel of section 7 of `guest-portal-api`,
    and they are the same bug wearing different hats**: a `str` field with a length bound
    accepts codepoints that nothing downstream can store, and the failure lands in the driver
    where no handler is watching. An anonymous caller got an unhandled `500` where R5.2 and
    R4.4 of that change promise a refusal "antes de crear la incidencia".

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
    diagnostic id and wrong for a person's own words — silently editing what somebody wrote
    into a column an operator will act on is worse than refusing it. `Cc` is exactly C0 and C1,
    so ordinary text, accents and emoji pass untouched.

    The second reason to refuse rather than strip: `incidents.title` and `guests.full_name` are
    rendered into lists and logs, and a value carrying `\\r` or an escape sequence is the
    line-forging class the security panel of `channex-staging-adapter` measured against a
    provider's identifier.

    No message here echoes the value. The offending codepoints are named — they are a character
    class, not content — but never the surrounding text, because one of the guarded fields is an
    identity document and a `422` body is one more place it must not appear.

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
SingleLineText = Annotated[str, storable_text("")]
#: Free prose a person writes: paragraphs and tabs are how somebody describes a problem.
MultiLineText = Annotated[str, storable_text("\t\n\r")]
