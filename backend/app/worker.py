"""The Celery application, shared by the `worker` and `beat` services.

Celery is imported here and under `app/scheduler/` and nowhere else —
`tests/test_layering.py` enforces it, so a domain module cannot quietly grow a task
decorator.

`app.scheduler.tasks` is imported for its side effect (registering the clock-driven tasks) at
the bottom, after `celery_app` exists, because the task module imports it back. So is
`app.scheduler.whatsapp_tasks`, which registers the one task nothing schedules.
"""

from celery import Celery

from app.core.config import settings
from app.scheduler.schedule import beat_schedule

celery_app = Celery("autohostai", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.beat_schedule = beat_schedule()
# Every instant this system reasons about is timezone-aware UTC (R3.7): the jobs receive
# `now` explicitly and derive local time from the property's own zone, never from the
# process. Pinning beat to UTC keeps it from applying an interpretation of its own.
celery_app.conf.timezone = "UTC"

import app.scheduler.tasks  # noqa: E402,F401  (registers the tasks with `celery_app`)

# `whatsapp-cloud-adapter` (design D7): the one task nothing schedules. Imported for the same
# side effect and for the same reason — a task that is not registered with `celery_app` is a
# `.delay(...)` that vanishes into the broker and is never routed to a worker. It has no
# `beat_schedule` entry on purpose; `ON_DEMAND_TASKS` in `app/scheduler/schedule.py` is where
# that is declared.
import app.scheduler.whatsapp_tasks  # noqa: E402,F401
