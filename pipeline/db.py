"""Connection helpers plus run/progress bookkeeping shared by every stage."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Self

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .config import settings

log = logging.getLogger(__name__)


@contextmanager
def connect() -> Iterator[psycopg.Connection]:
    with psycopg.connect(settings().database_url, row_factory=dict_row, autocommit=True) as conn:
        yield conn


def content_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


class Run:
    """Context manager that records a pipeline_runs row and per-unit progress.

    Usage:
        with Run("discover") as run:
            for unit in units:
                if run.is_done(unit): continue
                ...
                run.mark_done(unit, {"rows": n})
    """

    def __init__(self, stage: str):
        self.stage = stage
        self.stats: dict[str, Any] = {}
        self.id: int | None = None
        self.conn: psycopg.Connection | None = None
        self._t0 = time.monotonic()

    def __enter__(self) -> Self:
        self.conn = psycopg.connect(settings().database_url, row_factory=dict_row, autocommit=True)
        row = self.conn.execute(
            "insert into pipeline_runs (stage) values (%s) returning id", (self.stage,)
        ).fetchone()
        self.id = row["id"]
        log.info("run %s started: stage=%s pid=%s", self.id, self.stage, os.getpid())
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        status = "succeeded"
        error = None
        if exc_type is KeyboardInterrupt:
            status = "interrupted"
        elif exc_type is not None:
            status = "failed"
            error = f"{exc_type.__name__}: {exc}"
        self.conn.execute(
            "update pipeline_runs set finished_at = now(), status = %s, stats = %s, error = %s "
            "where id = %s",
            (status, Jsonb(self.stats), error, self.id),
        )
        log.info(
            "run %s %s after %.0fs: %s%s",
            self.id,
            status,
            time.monotonic() - self._t0,
            self.stats,
            f" error={error}" if error else "",
        )
        self.conn.close()
        return False

    def is_done(self, unit_key: str) -> bool:
        row = self.conn.execute(
            "select 1 from stage_progress where stage = %s and unit_key = %s",
            (self.stage, unit_key),
        ).fetchone()
        return row is not None

    def mark_done(self, unit_key: str, stats: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "insert into stage_progress (stage, unit_key, run_id, stats) values (%s, %s, %s, %s) "
            "on conflict (stage, unit_key) do update set done_at = now(), run_id = excluded.run_id, "
            "stats = excluded.stats",
            (self.stage, unit_key, self.id, Jsonb(stats or {})),
        )

    def bump(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n


def upsert_raw_venues(conn: psycopg.Connection, source: str, rows: list[tuple[str, Any]]) -> dict:
    """Upsert (source_id, payload) pairs. Returns counts of inserted / updated / unchanged."""
    counts = {"inserted": 0, "updated": 0, "unchanged": 0}
    with conn.cursor() as cur:
        for source_id, payload in rows:
            h = content_hash(payload)
            row = cur.execute(
                """
                insert into raw_venues (source, source_id, payload, content_hash)
                values (%s, %s, %s, %s)
                on conflict (source, source_id) do update
                    set payload = excluded.payload,
                        content_hash = excluded.content_hash,
                        fetched_at = now()
                    where raw_venues.content_hash is distinct from excluded.content_hash
                returning (xmax = 0) as inserted
                """,
                (source, source_id, Jsonb(payload), h),
            ).fetchone()
            if row is None:
                counts["unchanged"] += 1
            elif row["inserted"]:
                counts["inserted"] += 1
            else:
                counts["updated"] += 1
    return counts
