"""The beat calendar (`celery-jobs` R1.1, R1.2, PRD §8.3, design D13).

In code, inside the image — not a host crontab. `steering/infra.md`'s IaC-first norm and
the plain fact that a schedule outside the artefact cannot be reviewed in a Pull Request.

**Two tables, one calendar.** `CADENCES` holds the jobs that run on a period, `DAILY_JOBS`
the ones that run at an hour of the day, and `beat_schedule()` is derived from both — so the
calendar still has a single source (`revenue-pricing` design D8). The split is not cosmetic:
a periodic job sizes its lock through `lock_ttl_for` from the very same number beat uses, so
a cadence cannot be changed in one place and stay stale in the other, while a daily job
carries its TTL explicitly because that derivation would give it a three-day lock.
"""

from dataclasses import dataclass
from datetime import timedelta

from celery.schedules import crontab

#: Every periodic job, with its cadence: the four of PRD §8.3 that `celery-jobs` owns, with
#: the PRD's own numbers, plus the two that `access-notifications` adds and the one that
#: `reservations-webhooks` adds.
#:
#: Two of PRD §8.3 are absent from *this* table for different reasons.
#: `generate_price_recommendations` is not periodic — it runs at an hour of the day, so it
#: lives in `DAILY_JOBS` below (`revenue-pricing` D8) and the calendar still carries it.
#: `send_checkin_reminders` has no code to schedule yet: it is a message to a guest, so what
#: it needs is the channel adapter and the template that `messaging-ai` /
#: `access-notifications` own. The clock is the trivial half, and a beat entry pointing at a
#: task nobody has written fails once, at 03:00, in a worker log nobody is reading.
#:
#: **`dispatch_notifications` and `provision_access_records` are not in PRD §8.3, and that
#: is a declared divergence** (`access-notifications` design D3 and D2). The PRD says what
#: must happen — §14 delivers notifications, §15 gives every confirmed reservation an access
#: record — and says nothing about what triggers either. Both are clock-driven and
#: idempotent, so beat is where they belong; the four original names are untouched.
#:
#: **`process_webhook_events` is not in §8.3 either**, and joins from `reservations-webhooks`
#: (its D10). Its 60 s is a security parameter, not a tuning knob: rule 12(d) of
#: `steering/security.md` requires the outbound API traffic to be decoupled from the volume of
#: incoming webhooks, and what makes that true is that the job coalesces a whole tick's notices
#: into one call per destination — the cadence IS the ceiling on outbound calls. Making it
#: shorter raises that ceiling. 60 s leaves room against the measured limit of one cycle every
#: 30 s per account (`specs/pms-beds24-spike.md`).
CADENCES: dict[str, timedelta] = {
    "check_checkin_windows": timedelta(minutes=5),
    "process_checkouts": timedelta(minutes=5),
    "mark_occupied_estimated": timedelta(minutes=5),
    "check_sla_breaches": timedelta(minutes=1),
    # Every minute, like the SLA job it feeds: a row can only breach its deadline after it
    # has been delivered, so a slower dispatcher would delay every escalation by its own
    # cadence.
    "dispatch_notifications": timedelta(minutes=1),
    # Every five minutes, like the other reservation-driven jobs. Check-in is days away from
    # the confirmation, so the latency is irrelevant and the reconciliation is cheap.
    "provision_access_records": timedelta(minutes=5),
    "process_webhook_events": timedelta(seconds=60),
    # Every five minutes, from `maintenance` (its D2). Not one of PRD §8.3's either, and the
    # same kind of divergence as the two above: §12 says an incident must arrive classified
    # and says nothing about what triggers the classification. Five minutes rather than one
    # because the wait costs a manager some latency on a triage screen, while the tick costs
    # a call to whatever sits behind `IncidentClassifier` — and the day that is a real AI
    # provider, the cadence is the ceiling on what it is asked.
    "classify_incidents": timedelta(minutes=5),
    # `revenue-reviews` (design D2). Same cadence and same reasoning as
    # `classify_incidents`: PRD §18 declares the pipeline and says nothing about what
    # triggers it. Five minutes is the ceiling on what the analyser is asked, and the
    # lock that prevents two workers from classifying the same row is the same one
    # `run_for_every_tenant` already holds (D16).
    "classify_reviews": timedelta(minutes=5),
}


@dataclass(frozen=True)
class DailySchedule:
    """An hour of the day, and the lock TTL that goes with it (`revenue-pricing` D8).

    **`hour` is UTC**, because `app/worker.py` fixes `celery_app.conf.timezone = "UTC"` on
    purpose (`celery-jobs` R3.7: the process never interprets zones; local hours are derived
    from each property's own zone). For a tenant in Europe/Madrid, hour 6 is 07:00-08:00
    local — irrelevant to a job that plans a 60-day horizon, and a beat entry per tenant zone
    would be N calendar rows bought for nothing.

    **`lock_ttl` is explicit and must not come from `lock_ttl_for`.** That function returns
    cadence x 3, which on a daily job is three days: a worker killed mid-run would wedge the
    job until Thursday. The value here is generous against how long a generation takes
    (minutes) and far below the next window.
    """

    hour: int
    lock_ttl: timedelta


#: Jobs that run at an hour of the day rather than on a period. A `timedelta(days=1)` in
#: `CADENCES` would not do: it fires 24 h after beat starts rather than at the hour PRD §8.3
#: names, and it drags the three-day lock along with it (`revenue-pricing` D8).
DAILY_JOBS: dict[str, DailySchedule] = {
    #: PRD §8.3, "diario 06:00" (`revenue-pricing` R4.1, R4.7). Three hours of lock against a
    #: run measured in minutes.
    "generate_price_recommendations": DailySchedule(hour=6, lock_ttl=timedelta(hours=3)),
}


#: Tasks that have no place on the calendar at all, because nothing fires them on a clock.
#:
#: The first one arrives with `whatsapp-cloud-adapter` (design D7): the anonymous WhatsApp
#: receiver dispatches `process_inbound_whatsapp_message.delay(event_id)` the moment a
#: delivery commits, one task per inbound guest message. A cadence would be wrong twice over
#: — it would add up to a full tick of latency before the AI even sees a guest's question,
#: and there is nothing for a tick to coalesce, since the payload already carries the message
#: and no outbound re-read follows. Rule 12(d)'s "decouple the outbound traffic from webhook
#: volume", which is exactly what `process_webhook_events`' 60 s buys, has no work to do here.
#:
#: **A declared list and not an exemption class.** `tests/scheduler/test_schedule.py` asserts
#: that every task registered with Celery sits in exactly one of these three tables, so a job
#: whose beat entry somebody forgot is still red — it just has a third place to be, and
#: putting a task here is a visible diff that says "nothing schedules this".
ON_DEMAND_TASKS: frozenset[str] = frozenset({"process_inbound_whatsapp_message"})


def beat_schedule() -> dict[str, dict]:
    """The `beat_schedule` Celery expects, derived from `CADENCES` and `DAILY_JOBS`."""
    schedule: dict[str, dict] = {
        f"{name}-every-{int(cadence.total_seconds())}s": {
            "task": name,
            "schedule": cadence,
        }
        for name, cadence in CADENCES.items()
    }
    schedule.update(
        {
            f"{name}-daily-{daily.hour:02d}00-utc": {
                "task": name,
                "schedule": crontab(hour=daily.hour, minute=0),
            }
            for name, daily in DAILY_JOBS.items()
        }
    )
    return schedule
