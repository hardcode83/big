"""The beat calendar against PRD §8.3 (`celery-jobs` R1.1, R1.2) and its one addition.

The table is transcribed from the PRD, not derived from `CADENCES`, so a cadence cannot be
changed without this failing — which is the whole point of R1.2 naming the numbers.
"""

from datetime import timedelta

from app.scheduler.locks import lock_ttl_for
from app.scheduler.schedule import CADENCES, beat_schedule

#: PRD §8.3, "Jobs programados (Celery)". The two rows this change does not own are listed
#: with their owner so the omission reads as a decision instead of an oversight:
#:   generate_price_recommendations | diario 06:00 | -> `revenue`
#:   send_checkin_reminders         | cada hora    | -> `messaging-ai` / `access-notifications`
PRD_8_3 = {
    "check_checkin_windows": timedelta(minutes=5),
    "process_checkouts": timedelta(minutes=5),
    "check_sla_breaches": timedelta(minutes=1),
    "mark_occupied_estimated": timedelta(minutes=5),
}

#: Jobs that are NOT in PRD §8.3, with the change that added them and why the number is what
#: it is. Kept apart from `PRD_8_3` so "the PRD says so" never gets claimed for a cadence the
#: PRD has never heard of.
#:   process_webhook_events | 60 s | `reservations-webhooks` D10 — the cadence is the ceiling
#:                                   on outbound provider calls (rule 12(d)), not a tuning knob
BEYOND_PRD_8_3 = {
    "process_webhook_events": timedelta(seconds=60),
}

EXPECTED_CADENCES = {**PRD_8_3, **BEYOND_PRD_8_3}


def test_the_cadences_are_the_ones_prd_8_3_specifies() -> None:
    assert CADENCES == EXPECTED_CADENCES


def test_the_beat_schedule_covers_every_cadence_and_nothing_else() -> None:
    schedule = beat_schedule()

    assert {entry["task"] for entry in schedule.values()} == set(EXPECTED_CADENCES)
    for entry in schedule.values():
        assert entry["schedule"] == EXPECTED_CADENCES[entry["task"]]


def test_the_beat_entry_and_the_lock_ttl_both_derive_from_one_number() -> None:
    """`reservations-webhooks` 4.8, and the property `celery-jobs` built `CADENCES` for.

    A cadence written twice — once for beat, once to size the lock — is a cadence that can be
    changed in one place and stay stale in the other, and the symptom would be a lock expiring
    mid-run rather than an error anyone could read.
    """
    for name, cadence in CADENCES.items():
        entry = beat_schedule()[f"{name}-every-{int(cadence.total_seconds())}s"]
        assert entry["schedule"] is cadence
        assert lock_ttl_for(cadence) == cadence * 3


def test_every_scheduled_task_is_registered_with_celery() -> None:
    """A calendar entry naming a task that does not exist fails at run time, once, in a
    worker log nobody is watching."""
    from app.worker import celery_app

    for entry in beat_schedule().values():
        assert entry["task"] in celery_app.tasks, entry["task"]


def test_the_worker_applies_the_schedule() -> None:
    from app.worker import celery_app

    assert celery_app.conf.beat_schedule == beat_schedule()
    # R3.7: local time is derived from each property's own zone, never from the process.
    assert celery_app.conf.timezone == "UTC"
