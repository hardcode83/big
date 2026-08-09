"""The beat calendar (`celery-jobs` R1.1, R1.2, PRD §8.3, design D13).

In code, inside the image — not a host crontab. `steering/infra.md`'s IaC-first norm and
the plain fact that a schedule outside the artefact cannot be reviewed in a Pull Request.

`CADENCES` is the single source: `beat_schedule` is derived from it, and `lock_ttl_for`
sizes each task's lock from the same numbers, so a cadence cannot be changed in one place
and stay stale in the other.
"""

from datetime import timedelta

#: Every periodic job, with its cadence. The first four are PRD §8.3's, with the PRD's own
#: numbers; `process_webhook_events` is not in §8.3 at all and joins from
#: `reservations-webhooks` (its D10).
#:
#: Two of PRD §8.3 are deliberately absent: `generate_price_recommendations` belongs to
#: `revenue` and `send_checkin_reminders` to `messaging-ai` / `access-notifications` — they
#: are messages to a guest, not clock-driven state.
#:
#: **`process_webhook_events` at 60 s is a security parameter, not a tuning knob.** Rule 12(d)
#: of `steering/security.md` requires the outbound API traffic to be decoupled from the volume
#: of incoming webhooks, and what makes that true is that the job coalesces a whole tick's
#: notices into one call per destination: the cadence IS the ceiling on outbound calls. Making
#: it shorter raises that ceiling. 60 s leaves room against the measured limit of one cycle
#: every 30 s per account (`specs/pms-beds24-spike.md`).
CADENCES: dict[str, timedelta] = {
    "check_checkin_windows": timedelta(minutes=5),
    "process_checkouts": timedelta(minutes=5),
    "mark_occupied_estimated": timedelta(minutes=5),
    "check_sla_breaches": timedelta(minutes=1),
    "process_webhook_events": timedelta(seconds=60),
}


def beat_schedule() -> dict[str, dict]:
    """The `beat_schedule` Celery expects, derived from `CADENCES`."""
    return {
        f"{name}-every-{int(cadence.total_seconds())}s": {
            "task": name,
            "schedule": cadence,
        }
        for name, cadence in CADENCES.items()
    }
