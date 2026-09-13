"""Guest-facing check-in/check-out reminder texts (`guest-scheduled-comms` R1, R2, D6).

Fixed template plus the property's own name and the reservation's own dates/local time —
never guest- or operator-authored text (rule 11 of `sdd/steering/security.md`: "constante
más identificadores"). Keyed by the guest's own `preferred_language`, following the
`"es"`/`"en"` fallback convention `guests/domain/notifications.py` already established for
`render_stored_guest_link_notice`: `"es"` first because that is `Guest.preferred_language`'s
own default, `"en"` second, and any other value falls back to `"es"` rather than raising — a
send must not fail over a language it does not recognise.

Pure Python, no ORM/framework import: `sdd/steering/backend-architecture.md` forbids
`sqlalchemy`/`fastapi`/`pydantic` inside any `domain/` package, enforced by
`tests/test_layering.py`.
"""

from datetime import date, time

_CHECKIN_SUBJECT = {
    "es": "Recordatorio de check-in",
    "en": "Check-in reminder",
}

_CHECKIN_BODY = {
    "es": (
        "Le recordamos que su check-in en {property_name} está previsto para el "
        "{check_in_date}, a partir de las {check_in_time}."
    ),
    "en": (
        "This is a reminder that your check-in at {property_name} is scheduled for "
        "{check_in_date}, from {check_in_time}."
    ),
}


def render_checkin_reminder_email(
    language: str,
    property_name: str,
    check_in_date: date,
    check_in_time_local: time,
) -> tuple[str, str]:
    """The `(subject, body)` pair for both `CHECKIN_REMINDER_24H` and `CHECKIN_REMINDER_2H`
    (R1.4, design D6).

    One builder for both types: `SendCheckinRemindersUseCase` decides *which* type(s) are due
    (design D3's 24h/2h thresholds) — this function only ever renders what a due reminder
    says, and the two types say the same thing. `language` other than `"es"`/`"en"` falls
    back to `"es"`, the same shrug `guests/domain/notifications.py` gives an unrecognised
    `Guest.preferred_language`.

    Fixed prose plus the property's name and the reservation's own check-in date/local time —
    nothing guest- or operator-authored ever reaches this function, so there is nothing here
    that could leak into `notification_logs.subject`/`body` (R1.4, rule 11 of
    `sdd/steering/security.md`).
    """
    key = language if language in _CHECKIN_SUBJECT else "es"
    body = _CHECKIN_BODY[key].format(
        property_name=property_name,
        check_in_date=check_in_date.isoformat(),
        check_in_time=check_in_time_local.strftime("%H:%M"),
    )
    return _CHECKIN_SUBJECT[key], body
