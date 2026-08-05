"""The beat calendar against PRD §8.3 (`celery-jobs` R1.1, R1.2).

The table is transcribed from the PRD, not derived from `CADENCES`, so a cadence cannot be
changed without this failing — which is the whole point of R1.2 naming the numbers.
"""

from datetime import timedelta

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


def test_the_cadences_are_the_ones_prd_8_3_specifies() -> None:
    assert CADENCES == PRD_8_3


def test_the_beat_schedule_covers_every_cadence_and_nothing_else() -> None:
    schedule = beat_schedule()

    assert {entry["task"] for entry in schedule.values()} == set(PRD_8_3)
    for entry in schedule.values():
        assert entry["schedule"] == PRD_8_3[entry["task"]]


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
