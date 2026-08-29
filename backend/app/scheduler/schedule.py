"""The beat calendar (`celery-jobs` R1.1, R1.2, PRD §8.3, design D13).

In code, inside the image — not a host crontab. `steering/infra.md`'s IaC-first norm and
the plain fact that a schedule outside the artefact cannot be reviewed in a Pull Request.

**Three tables, one calendar.** `CADENCES` holds the jobs that run on a period, `DAILY_JOBS`
the ones that run at an hour of the day, and `MONTHLY_JOBS` the ones that run on a day of
the month (`revenue-statements` design D11). `beat_schedule()` is derived from all three —
so the calendar still has a single source. The split is not cosmetic: a periodic job sizes
its lock through `lock_ttl_for` from the very same number beat uses, so a cadence cannot be
changed in one place and stay stale in the other, while a daily job carries its TTL
explicitly because that derivation would give it a three-day lock, and a monthly job
carries its `day_of_month` explicitly because `crontab(month_of_year=...)` would not.
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
    # Every five minutes, from `revenue-statements` (its D4). The reconciliation applies
    # owner answers to expense rows; the SQL is idempotent on the row state, so a faster
    # cadence would not buy anything but a tighter feedback loop on the manager's screen.
    "reconcile_owner_approvals_for_expenses": timedelta(minutes=5),
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


@dataclass(frozen=True)
class MonthlySchedule:
    """A day of the month and an hour of the day (`revenue-statements` design D11).

    **`day_of_month` is a 1-based day of the UTC calendar**, like `DailySchedule.hour`,
    and `hour` is UTC for the same reason (`revenue-pricing` D8): the worker never
    interprets zones, and a tenant's local hour is derived from its own property time.

    **`lock_ttl` is explicit and must not come from `lock_ttl_for`**, for the same reason
    `DailySchedule` does not: deriving from a cadence would be wrong-shaped — there is no
    cadence on a monthly job, and `lock_ttl_for(cadence)` here would couple the TTL to a
    duration that has nothing to do with the run. Six hours covers a 100-property tenant
    on a slow day without wedging the next monthly window if a worker dies mid-run.
    """

    day_of_month: int
    hour: int
    lock_ttl: timedelta


#: Jobs that run on a specific day of the month rather than at an hour of the day
#: (`revenue-statements` design D11). A `crontab(month_of_year='1')` does not read as a
#: monthly job — Celery supports it, but the legibility costs more than the dataclass.
MONTHLY_JOBS: dict[str, MonthlySchedule] = {
    #: `revenue-statements` R1.1 / D11 — the monthly liquidation. Day 1 at 02:00 UTC is the
    #: PRD §8.3 cadence for "monthly" plus the design's choice of hour; six hours of lock
    #: against a run measured in minutes, with margin for a tenant on the slow side.
    "generate_owner_statements": MonthlySchedule(
        day_of_month=1, hour=2, lock_ttl=timedelta(hours=6)
    ),
}


def beat_schedule() -> dict[str, dict]:
    """The `beat_schedule` Celery expects, derived from `CADENCES`, `DAILY_JOBS` and
    `MONTHLY_JOBS` (`revenue-statements` D11)."""
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
    schedule.update(
        {
            f"{name}-monthly-{monthly.day_of_month:02d}{monthly.hour:02d}00-utc": {
                "task": name,
                "schedule": crontab(
                    day_of_month=monthly.day_of_month,
                    hour=monthly.hour,
                    minute=0,
                ),
            }
            for name, monthly in MONTHLY_JOBS.items()
        }
    )
    return schedule
