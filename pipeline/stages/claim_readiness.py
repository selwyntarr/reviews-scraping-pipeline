"""Stage 9: claim-readiness score per venue.

A business-claim flow converts best where (a) the profile already says something worth correcting or
owning, (b) the venue is demonstrably active, and (c) there is a way to reach the owner. Score in [0, 1]
with the components stored so the ranking is explainable.
"""

from __future__ import annotations

import logging

from psycopg.types.json import Jsonb

from ..db import Run, connect

log = logging.getLogger(__name__)


def run_claim_readiness() -> None:
    with Run("claim_readiness") as run, connect() as conn:
        rows = conn.execute(
            """
            select v.id, v.website, v.phone, v.last_inspection, v.source_count,
                   coalesce(p.review_count, 0) as review_count,
                   coalesce(p.mean_confidence, 0) as mean_confidence,
                   coalesce(cardinality(p.top_vibe_tags), 0) as tag_count,
                   coalesce(p.sentiment_score, 0) as sentiment_score,
                   (select count(*) from review_venue_links l where l.venue_id = v.id and l.decision = 'matched') as links
            from venues v
            left join venue_profiles p on p.venue_id = v.id
            where v.retired_at is null
            """
        ).fetchall()
        out = []
        for r in rows:
            insight = min(
                1.0,
                0.5 * min(r["review_count"], 3) / 3
                + 0.3 * float(r["mean_confidence"])
                + 0.2 * min(r["tag_count"], 3) / 3,
            )
            active = 0.0
            if r["last_inspection"] and str(r["last_inspection"]) >= "2025":
                active = 1.0
            elif r["last_inspection"]:
                active = 0.5
            elif r["source_count"] >= 2:
                active = 0.6
            contact = (0.6 if r["website"] else 0.0) + (0.4 if r["phone"] else 0.0)
            corroboration = min(1.0, (r["source_count"] - 1) / 2)
            score = round(0.45 * insight + 0.25 * active + 0.20 * contact + 0.10 * corroboration, 4)
            out.append(
                (
                    r["id"],
                    run.id,
                    score,
                    Jsonb(
                        {
                            "insight": round(insight, 3),
                            "active": active,
                            "contact": contact,
                            "corroboration": round(corroboration, 3),
                            "review_count": r["review_count"],
                            "sentiment_score": float(r["sentiment_score"]),
                        }
                    ),
                )
            )
        with conn.cursor() as cur:
            cur.executemany(
                """insert into claim_readiness (venue_id, run_id, score, components) values (%s,%s,%s,%s)
                   on conflict (venue_id) do update set run_id = excluded.run_id, score = excluded.score,
                       components = excluded.components, computed_at = now()""",
                out,
            )
        run.stats["venues_scored"] = len(out)
        run.stats["with_insights"] = sum(1 for r in rows if r["review_count"])
        run.mark_done("claim_readiness:full", run.stats)
        log.info("claim_readiness done: %s", run.stats)
