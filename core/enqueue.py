"""Defer Procrastinate tasks after the current transaction commits.

Services call `enqueue(task, **kwargs)` instead of `task.defer(...)` so a job never
runs against rows that were rolled back, and tests can patch one function.
"""

import logging

from django.db import transaction

log = logging.getLogger(__name__)


def enqueue(task, **kwargs):
    def _defer():
        try:
            task.defer(**kwargs)
        except Exception:  # worker DB down must not break the request
            log.exception("Could not defer %s(%s)", task.name, kwargs)

    transaction.on_commit(_defer)
