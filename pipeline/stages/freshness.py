"""Stage 8: nightly freshness.

stage_progress marks units done permanently, so freshness expires markers older than a per-source TTL
and reruns the collectors (which then re-fetch only expired units and upsert only changed content),
then relinks reviews, re-extracts rows whose content hash changed, and recomputes claim readiness.
Editorial/encyclopedic sources change slowly; social sources would get a short TTL.
"""

from __future__ import annotations

import logging

from ..db import Run, connect

log = logging.getLogger(__name__)

TTL_DAYS = {"infatuation": 30, "wikipedia": 14, "wikivoyage": 14, "osm": 30, "dohmh": 7}


def run_freshness(extract_limit: int | None, force: bool) -> None:
    from .claim_readiness import run_claim_readiness
    from .collect_reviews import run_collect_reviews
    from .discover import run_discover
    from .extract_insights import run_extract_insights
    from .match_reviews import run_match_reviews

    with Run("freshness") as run, connect() as conn:
        for prefix, days in TTL_DAYS.items():
            stage = "discover" if prefix in ("osm", "dohmh") else "collect_reviews"
            n = conn.execute(
                "delete from stage_progress where stage = %s and unit_key like %s "
                "and (%s or done_at < now() - make_interval(days => %s))",
                (stage, f"{prefix}:%", force, days),
            ).rowcount
            run.stats[f"expired_{prefix}"] = n
        log.info("expired units: %s", run.stats)
    run_discover(["osm", "dohmh"])
    run_collect_reviews(["wikipedia", "wikivoyage", "infatuation"], None)
    run_match_reviews()
    run_extract_insights(extract_limit, None, True)
    run_claim_readiness()
