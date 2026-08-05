"""The beat calendar (`celery-jobs` R1.1, R1.2, PRD §8.3, design D13).

In code, inside the image — not a host crontab. `steering/infra.md`'s IaC-first norm and
the plain fact that a schedule outside the artefact cannot be reviewed in a Pull Request.

`CADENCES` is the single source: `beat_schedule` is derived from it, and `lock_ttl_for`
sizes each task's lock from the same numbers, so a cadence cannot be changed in one place
and stay stale in the other.
"""

from datetime import timedelta

#: The four jobs of PRD §8.3 that this change owns, with the PRD's own cadences.
#:
#: The other two of PRD §8.3 are deliberately absent: `generate_price_recommendations`
#: belongs to `revenue` and `send_checkin_reminders` to `messaging-ai` /
#: `access-notifications` — they are messages to a guest, not clock-driven state.
CADENCES: dict[str, timedelta] = {
    "check_checkin_windows": timedelta(minutes=5),
    "process_checkouts": timedelta(minutes=5),
    "mark_occupied_estimated": timedelta(minutes=5),
    "check_sla_breaches": timedelta(minutes=1),
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
