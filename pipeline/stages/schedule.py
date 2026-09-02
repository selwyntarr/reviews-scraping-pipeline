"""Scheduler: run `freshness` every day at a fixed local time; record heartbeats so the status page can
show the last and next scheduled run. Runs as the `scheduler` compose service."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..db import connect

log = logging.getLogger(__name__)

TZ = ZoneInfo(os.environ.get("TZ") or "UTC")  # the compose scheduler service sets TZ from .env


def now() -> datetime:
    return datetime.now(tz=TZ)


def next_run(at: str, at_time: datetime | None = None) -> datetime:
    hh, mm = (int(x) for x in at.split(":"))
    t = at_time or now()
    candidate = t.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return candidate if candidate > t else candidate + timedelta(days=1)


def heartbeat(at: str, status: str, note: str | None = None) -> None:
    with connect() as conn:
        conn.execute(
            """insert into scheduler_state (id, run_at, next_run_at, status, note, updated_at)
               values (1, %s, %s, %s, %s, now())
               on conflict (id) do update set run_at = excluded.run_at, next_run_at = excluded.next_run_at,
                   status = excluded.status, note = excluded.note, updated_at = now()""",
            (at, next_run(at), status, note),
        )


def run_schedule(at: str, extract_limit: int | None, once: bool) -> None:
    from .freshness import run_freshness

    heartbeat(at, "waiting")
    while True:
        target = next_run(at)
        log.info(
            "next freshness run at %s (in %.1f h)",
            target,
            (target - now()).total_seconds() / 3600,
        )
        while now() < target:
            time.sleep(min(60, max(1, (target - now()).total_seconds())))
        heartbeat(at, "running")
        try:
            run_freshness(extract_limit, False)
            heartbeat(at, "waiting", f"last run ok at {now():%Y-%m-%d %H:%M}")
        except (
            Exception
        ) as e:  # keep the daemon alive; the failure is visible in pipeline_runs and here
            log.exception("freshness failed")
            heartbeat(at, "waiting", f"last run FAILED at {now():%Y-%m-%d %H:%M}: {e}")
        if once:
            return
