"""The beat calendar against PRD §8.3 (`celery-jobs` R1.1, R1.2) and its declared additions.

The tables here are transcribed from the PRD, not derived from `CADENCES`/`DAILY_JOBS`, so a
cadence or an hour cannot be changed without this failing — which is the whole point of R1.2
naming the numbers.
"""

from datetime import timedelta

from celery.schedules import crontab

from app.scheduler.locks import lock_ttl_for
from app.scheduler.schedule import (
    CADENCES,
    DAILY_JOBS,
    ON_DEMAND_TASKS,
    beat_schedule,
)

#: PRD §8.3, "Jobs programados (Celery)", the rows that run on a period. The one row still
#: unowned is listed with its owner so the omission reads as a decision instead of an
#: oversight:
#:   send_checkin_reminders | cada hora | -> `messaging-ai` / `access-notifications`
#: The remaining row, `generate_price_recommendations`, is transcribed in `PRD_8_3_DAILY`
#: below: it has an hour, not a cadence.
PRD_8_3 = {
    "check_checkin_windows": timedelta(minutes=5),
    "process_checkouts": timedelta(minutes=5),
    "check_sla_breaches": timedelta(minutes=1),
    "mark_occupied_estimated": timedelta(minutes=5),
}

#: Jobs that are NOT in PRD §8.3, kept in their own table so the divergence is visible
#: rather than absorbed into the transcription above (`access-notifications` design D2/D3,
#: `reservations-webhooks` design D10). The PRD says *what* must happen — §14 delivers
#: notifications, §15 gives every confirmed reservation an access record, §16 receives the
#: PMS notices — and is silent on what triggers any of them. Keeping them apart is also what
#: stops "the PRD says so" ever being claimed for a cadence the PRD has never heard of.
#:   process_webhook_events | 60 s | the cadence is the ceiling on outbound provider calls
#:                                   (rule 12(d)), not a tuning knob
#:   classify_incidents     | 5 min | `maintenance` D2. §12 says an incident must arrive
#:                                   classified and is silent on what triggers it; the
#:                                   cadence is the ceiling on what the classifier is asked,
#:                                   which matters the day a real AI provider is behind it
BEYOND_PRD_8_3 = {
    "dispatch_notifications": timedelta(minutes=1),
    "provision_access_records": timedelta(minutes=5),
    "process_webhook_events": timedelta(seconds=60),
    "classify_incidents": timedelta(minutes=5),
    # `revenue-reviews` D2 — every-five-minutes classification of pending reviews.
    "classify_reviews": timedelta(minutes=5),
}

ALL_CADENCES = PRD_8_3 | BEYOND_PRD_8_3

#: PRD §8.3's daily row, transcribed as its hour rather than derived from `DAILY_JOBS`, for
#: the same reason the table above is transcribed (`revenue-pricing` R4.1). **The hour is
#: UTC**: `app/worker.py` fixes the process timezone there on purpose.
PRD_8_3_DAILY = {
    "generate_price_recommendations": 6,
}


def test_the_cadences_of_prd_8_3_are_untouched() -> None:
    """Additions may not quietly retune a cadence the PRD specifies."""
    for name, cadence in PRD_8_3.items():
        assert CADENCES[name] == cadence


def test_the_calendar_is_prd_8_3_plus_exactly_the_declared_additions() -> None:
    assert CADENCES == ALL_CADENCES


def test_the_daily_hours_of_prd_8_3_are_untouched() -> None:
    """The same guard as the cadences, for the table that has hours instead."""
    for name, hour in PRD_8_3_DAILY.items():
        assert DAILY_JOBS[name].hour == hour


def test_the_calendar_is_the_two_tables_and_nothing_else() -> None:
    assert set(DAILY_JOBS) == set(PRD_8_3_DAILY)


def test_the_beat_schedule_covers_both_tables_and_nothing_else() -> None:
    schedule = beat_schedule()

    assert {entry["task"] for entry in schedule.values()} == set(ALL_CADENCES) | set(
        DAILY_JOBS
    )
    for entry in schedule.values():
        if entry["task"] in ALL_CADENCES:
            assert entry["schedule"] == ALL_CADENCES[entry["task"]]


def test_a_daily_job_fires_at_its_hour_and_not_a_period_after_beat_starts() -> None:
    """A `crontab`, not a `timedelta` — which is the whole of `revenue-pricing` D8's first half.

    `timedelta(days=1)` in `CADENCES` would have fired 24 h after the worker started, so the
    hour PRD §8.3 names would drift with every redeploy.
    """
    schedule = beat_schedule()

    for name, daily in DAILY_JOBS.items():
        entry = schedule[f"{name}-daily-{daily.hour:02d}00-utc"]
        assert entry["task"] == name
        assert not isinstance(entry["schedule"], timedelta)
        assert entry["schedule"] == crontab(hour=daily.hour, minute=0)


def test_the_three_tables_are_disjoint() -> None:
    """A job in two of them would get two beat entries and two different lock TTLs.

    `ON_DEMAND_TASKS` joins the comparison with `whatsapp-cloud-adapter` (design D7): a task
    that appears both there and in a cadence table would be claiming two contradictory things
    about what starts it.
    """
    assert not set(CADENCES) & set(DAILY_JOBS)
    assert not set(CADENCES) & ON_DEMAND_TASKS
    assert not set(DAILY_JOBS) & ON_DEMAND_TASKS


def test_every_registered_task_is_in_exactly_one_of_the_three_tables() -> None:
    """A scheduled task the calendar forgot never runs, and nothing else would say so.

    The complement of `test_every_scheduled_task_is_registered_with_celery`: that one catches
    a calendar entry with no task, this one a task with no calendar entry.

    **`ON_DEMAND_TASKS` is a third table and not an exemption**, and the distinction is what
    keeps this check worth having. `whatsapp-cloud-adapter`'s inbound task is dispatched with
    `.delay(event_id)` the moment a webhook delivery commits (design D7), so a cadence would
    be wrong rather than missing — but a task with no entry in *any* of the three is still
    red, so a genuinely forgotten beat entry cannot hide behind "it must be on demand".
    """
    from app.worker import celery_app

    ours = {
        name for name in celery_app.tasks if not name.startswith("celery.")
    }

    assert ours == set(CADENCES) | set(DAILY_JOBS) | ON_DEMAND_TASKS
    for name in ours:
        assert [name in CADENCES, name in DAILY_JOBS, name in ON_DEMAND_TASKS].count(
            True
        ) == 1, name


def test_no_on_demand_task_has_a_beat_entry() -> None:
    """The absence design D7 asks for, checked rather than assumed.

    `beat_schedule()` derives from the two cadence tables, so this cannot fail today — which
    is exactly why it is written down: an entry added by hand to satisfy a future guard would
    give every inbound guest message a cadence's worth of latency, and nothing else would say
    so.
    """
    scheduled = {entry["task"] for entry in beat_schedule().values()}

    assert not scheduled & ON_DEMAND_TASKS


def test_the_on_demand_task_names_are_the_ones_the_tasks_register() -> None:
    """The name is spelled in two places, so the two are compared here.

    A rename that missed `ON_DEMAND_TASKS` would leave the set naming a task that does not
    exist — and the exhaustiveness check above would go red for the *other* half of the same
    typo, which is a confusing way to find out.
    """
    from app.scheduler.whatsapp_tasks import WHATSAPP_INBOUND_TASK

    assert ON_DEMAND_TASKS == {WHATSAPP_INBOUND_TASK}


def test_no_daily_job_derives_its_lock_ttl_from_the_cadence_rule() -> None:
    """`revenue-pricing` D8's second half: cadence x 3 on a daily job is a three-day lock.

    A worker killed mid-run would wedge the job for three windows, and the symptom is a job
    that silently stops producing rather than an error anybody reads. So the TTL is explicit,
    and it has to stay below the gap to the next run for that to mean anything.
    """
    one_day = timedelta(days=1)

    for name, daily in DAILY_JOBS.items():
        assert daily.lock_ttl != lock_ttl_for(one_day), name
        assert daily.lock_ttl < one_day, name


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
