"""Long digit runs die here, in provider free text (design D8).

`card_data.py` governs `raw_payload`, where a **key** says what a value is. This module governs
the other half of rule 13 of `steering/security.md`: `special_requests`, a column that persists
and that the API returns, filled from provider text nobody structures — `comments` in Beds24,
`notes` in Channex. No key names what is inside it, so a denylist has nothing to look at.

**Why this exists now and not before.** `pms-beds24-adapter` scoped rule 13 to `raw_payload` and
left this field out (its D9 and task P.8) with a literal expiry: *"it becomes due as soon as an
unauthenticated write from the internet over that same column exists, which is what
`reservations-webhooks` and `beds24-messaging-adapter` bring"*. This change is that write.

**What it does, and what it deliberately does not.** It redacts long runs of digits. No Luhn
check: D9 already rejected one over false positives on an operational field, and a checksum
would also make the rule weaker in the direction that matters — a PAN with one mistyped digit
would start surviving. Applied on **external sources only** (webhook and PMS sync), never to
what a person types through the authenticated API: P.8's trigger is the anonymous write, and
that is where the false-positive cost is worth paying.

**The false positive is real, accepted, and reversible here in one place.** What can be eaten is
a digit run of 13 or more in a note the cleaning staff reads. What is measured to sit *below*
that threshold is every operational case: a Spanish portal code is 4-8 digits, a Spanish mobile
9, an international one with prefix 11-12. What survives the redaction is what actually matters
operationally, and a long OTA reference is reconstructible from `external_pms_id`.
"""

import re

LONG_DIGIT_RUN_REDACTED = "***long-digit-run-removed***"
"""What replaces a redacted run.

Says what happened without claiming what it was, which is the honest reading: this rule has no
checksum, so it detects a *shape*, not a card. Distinct from `card_data.CARD_DATA_REMOVED`,
which replaces a value a key positively identified as cardholder data.
"""

MIN_REDACTED_DIGITS = 13
"""The shortest PAN, and therefore the threshold.

D8's stated form is "runs of 13-19 digits" — the PAN length band. The operative rule here is
**at least** 13, and the difference is not cosmetic: read as a closed band, a maximal run of 20+
digits is left alone, so a PAN followed by any other number (`4111111111111111 1225` — card then
expiry) merges into one 20-digit run and survives in clear. Redacting from 13 up only ever
removes more than the ratified form, and on inputs its own argument covers a fortiori: if
nothing operational reaches 13 digits, nothing operational reaches 20 either.
"""

_DIGIT_RUN = re.compile(r"(?<![0-9])[0-9](?:[ -]*[0-9])*")
"""A maximal run of digits, tolerating spaces and hyphens between them.

The separators are the whole difficulty of the rule. A human copies a card the way it is
printed — `4111 1111 1111 1111` — so a check that stops at the first space sees four runs of
four and redacts nothing, on the shape a card is *most* likely to arrive in.

`[ -]*` rather than `[ -]?`: a double space is a typo, and a rule a typo defeats is not a rule.
The lookbehind keeps the match from starting mid-run, which is what makes the length test below
a test of the whole run rather than of an arbitrary window inside it.
"""


def redact_long_digit_runs(text: str | None) -> str | None:
    """`text` with every run of `MIN_REDACTED_DIGITS`+ digits replaced by a marker.

    `None` in, `None` out: the column is nullable and "no note" is not the same fact as "an
    empty note". Everything around a redacted run is preserved — the note is what the cleaning
    staff reads, and eating it would cost more than the PAN it removed.
    """
    if text is None:
        return None
    return _DIGIT_RUN.sub(_redact_if_long, text)


def _redact_if_long(match: re.Match[str]) -> str:
    run = match.group()
    digits = sum(character.isdigit() for character in run)
    return LONG_DIGIT_RUN_REDACTED if digits >= MIN_REDACTED_DIGITS else run
