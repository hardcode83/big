"""Guest-facing access-instructions text (`guest-scheduled-comms` R3, design D6).

Fixed template plus the masked form of the access code, `****XX` — rule 11 of
`sdd/steering/security.md`'s exception 1: `notification_logs.subject`/`body` may carry that
masked form and nothing else. `render_access_instructions_email` is the one place that
interpolates it, and it takes `code_masked` as its only variable input — never
`access_records.notes`, never any other field of `AccessRecord` or the linked
`Reservation`/`Guest`.

Its own file, not `guests/domain/notifications.py` (design D6, which rejects that alternative
by name): that module is guest-identity-scoped (portal tokens), not the owner of `Reservation`
or `AccessRecord`. Same fallback convention `reservations/domain/notifications.py` established
for `render_checkin_reminder_email`/`render_checkout_reminder_email`: `"es"` first, `"en"`
second, anything else falls back to `"es"` rather than raising.

Pure Python, no ORM/framework import: `sdd/steering/backend-architecture.md` forbids
`sqlalchemy`/`fastapi`/`pydantic` inside any `domain/` package, enforced by
`tests/test_layering.py`.
"""

_ACCESS_INSTRUCTIONS_SUBJECT = {
    "es": "Tus instrucciones de acceso",
    "en": "Your access instructions",
}

_ACCESS_INSTRUCTIONS_BODY = {
    "es": (
        "Tu código de acceso ya está disponible. Por seguridad, aquí solo mostramos su forma "
        "enmascarada: {code_masked}. Si necesitas el código completo, contacta con el anfitrión."
    ),
    "en": (
        "Your access code is now available. For security, only its masked form is shown here: "
        "{code_masked}. Contact your host if you need the full code."
    ),
}


def render_access_instructions_email(language: str, code_masked: str) -> tuple[str, str]:
    """The `(subject, body)` pair for `ACCESS_INSTRUCTIONS_SENT` (R3.1, R3.2, design D6).

    `language` other than `"es"`/`"en"` falls back to `"es"`, the same shrug
    `render_checkin_reminder_email`/`render_checkout_reminder_email` give an unrecognised
    language.

    `code_masked` is the ONLY variable input. Rule 11's exception 1 licenses exactly this — the
    masked form, and nothing else, reaching `notification_logs.subject`/`body` — so this
    function has no parameter through which `access_records.notes` or any other free text
    could reach the rendered text even by accident.
    """
    key = language if language in _ACCESS_INSTRUCTIONS_SUBJECT else "es"
    body = _ACCESS_INSTRUCTIONS_BODY[key].format(code_masked=code_masked)
    return _ACCESS_INSTRUCTIONS_SUBJECT[key], body
