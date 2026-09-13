"""`render_checkin_reminder_email` (`guest-scheduled-comms` R1, R5, design D6).

Rule 11 of `steering/security.md`: `notification_logs.subject`/`body` is a closed sink. These
tests pin that the reminder text is fixed prose plus the property's name and the reservation's
own check-in date/time, keyed only by language — the same discipline
`tests/guests/test_notifications.py` pins for `render_stored_guest_link_notice`.
"""

from datetime import date, time

from app.reservations.domain.notifications import render_checkin_reminder_email

PROPERTY_NAME = "Casa Sol"
CHECK_IN_DATE = date(2026, 9, 20)
CHECK_IN_TIME = time(15, 0)


def test_the_spanish_template_is_returned_by_default_language() -> None:
    subject, body = render_checkin_reminder_email(
        "es", PROPERTY_NAME, CHECK_IN_DATE, CHECK_IN_TIME
    )

    assert subject.strip()
    assert body.strip()
    assert PROPERTY_NAME in body
    assert "2026-09-20" in body
    assert "15:00" in body


def test_the_english_template_is_a_different_text() -> None:
    es_subject, es_body = render_checkin_reminder_email(
        "es", PROPERTY_NAME, CHECK_IN_DATE, CHECK_IN_TIME
    )
    en_subject, en_body = render_checkin_reminder_email(
        "en", PROPERTY_NAME, CHECK_IN_DATE, CHECK_IN_TIME
    )

    assert en_subject != es_subject
    assert en_body != es_body
    assert PROPERTY_NAME in en_body
    assert "2026-09-20" in en_body
    assert "15:00" in en_body


def test_an_unrecognised_language_falls_back_to_spanish() -> None:
    for unrecognised in ("fr", "", "ES", "en-US", "not-a-language"):
        assert render_checkin_reminder_email(
            unrecognised, PROPERTY_NAME, CHECK_IN_DATE, CHECK_IN_TIME
        ) == render_checkin_reminder_email("es", PROPERTY_NAME, CHECK_IN_DATE, CHECK_IN_TIME)


def test_the_subject_fits_the_column() -> None:
    """`notification_logs.subject` is `String(500)`."""
    for language in ("es", "en"):
        subject, _ = render_checkin_reminder_email(
            language, PROPERTY_NAME, CHECK_IN_DATE, CHECK_IN_TIME
        )
        assert len(subject) <= 500


def test_different_property_names_and_dates_produce_different_bodies() -> None:
    """The only guest-visible variables are the property's name and the reservation's own
    dates/time (R1.4) — changing either must change the rendered body."""
    _, base_body = render_checkin_reminder_email(
        "es", PROPERTY_NAME, CHECK_IN_DATE, CHECK_IN_TIME
    )
    _, other_property_body = render_checkin_reminder_email(
        "es", "Otra Propiedad", CHECK_IN_DATE, CHECK_IN_TIME
    )
    _, other_date_body = render_checkin_reminder_email(
        "es", PROPERTY_NAME, date(2026, 12, 1), CHECK_IN_TIME
    )
    _, other_time_body = render_checkin_reminder_email(
        "es", PROPERTY_NAME, CHECK_IN_DATE, time(18, 30)
    )

    assert other_property_body != base_body
    assert other_date_body != base_body
    assert other_time_body != base_body
