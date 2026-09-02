"""Stage 5: link raw_reviews rows to canonical venues.

Every review source names its venue and usually carries coordinates and a street, so this is the
same blocking + scoring used by dedupe, run against the venues table instead of raw_venues.
Rows outside the Manhattan polygon are recorded as such and skipped.
"""

from __future__ import annotations

import logging
from collections import defaultdict

import geohash

from ..db import Run, connect
from ..geo import contains, load_boundary
from ..http import Client
from ..normalize import norm_housenumber, norm_name, norm_phone, norm_street, norm_zip
from .dedupe import (
    GEOHASH_PRECISION,
    MATCH_THRESHOLD,
    MIN_NAME_SIM,
    REVIEW_THRESHOLD,
    Rec,
    score_pair,
)

log = logging.getLogger(__name__)


def _venue_recs(conn) -> list[Rec]:
    recs = []
    for v in conn.execute(
        "select id, name, name_norm, housenumber, street, street_norm, zip, lat, lon, phone, geohash "
        "from venues where retired_at is null"
    ):
        recs.append(
            Rec(
                raw_id=v["id"],
                source="venue",
                source_id=str(v["id"]),
                name=v["name"],
                name_norm=v["name_norm"],
                housenumber=v["housenumber"] or "",
                street=v["street"] or "",
                street_norm=v["street_norm"] or "",
                zip=v["zip"] or "",
                lat=v["lat"],
                lon=v["lon"],
                phone=v["phone"] or "",
                website=None,
                cuisine=None,
                category=None,
                last_inspection=None,
                geohash=v["geohash"],
            )
        )
    return recs


def _review_rec(r) -> Rec:
    street = (
        (r["street"] or "").split(",")[0].strip()
    )  # "96 South St, New York, NY 10038" -> "96 South St"
    hn = ""
    if street and street[0].isdigit():  # "127 E 34th St" -> housenumber + street
        hn, _, street = street.partition(" ")
    lat, lon = r["lat"], r["lon"]
    return Rec(
        raw_id=r["id"],
        source=r["source"],
        source_id=r["source_id"],
        name=r["venue_name"],
        name_norm=norm_name(r["venue_name"]),
        housenumber=norm_housenumber(hn),
        street=street,
        street_norm=norm_street(street),
        zip=norm_zip(r["zip"]),
        lat=lat,
        lon=lon,
        phone=norm_phone((r["payload"] or {}).get("venue", {}).get("phone")),
        website=None,
        cuisine=None,
        category=None,
        last_inspection=None,
        geohash=geohash.encode(lat, lon, GEOHASH_PRECISION) if lat and lon else None,
    )


def run_match_reviews() -> None:
    with Run("match_reviews") as run, connect() as conn:
        poly = load_boundary(conn, Client())
        venues = _venue_recs(conn)
        blocks: dict[str, list[Rec]] = defaultdict(list)
        for v in venues:
            if v.geohash:
                blocks[f"g:{v.geohash}"].append(v)
            if v.zip and v.street_norm:
                blocks[f"a:{v.zip}:{v.street_norm}"].append(v)
        log.info("%d live venues indexed", len(venues))

        reviews = conn.execute(
            "select id, source, source_id, venue_name, street, zip, lat, lon, payload from raw_reviews order by id"
        ).fetchall()
        rows = []
        for r in reviews:
            rec = _review_rec(r)
            if rec.lat and not contains(poly, rec.lat, rec.lon):
                rows.append((r["id"], None, run.id, None, None, None, None, "outside_manhattan", 0))
                run.bump("outside_manhattan")
                continue
            keys = []
            if rec.geohash:
                keys = [f"g:{rec.geohash}"] + [f"g:{n}" for n in geohash.neighbors(rec.geohash)]
            if rec.zip and rec.street_norm:
                keys.append(f"a:{rec.zip}:{rec.street_norm}")
            seen, best, n_cand = set(), None, 0
            for k in keys:
                for v in blocks.get(k, []):
                    if v.raw_id in seen:
                        continue
                    seen.add(v.raw_id)
                    n_cand += 1
                    s = score_pair(rec, v)
                    if best is None or s["score"] > best[0]["score"]:
                        best = (s, v)
            if best is None:
                rows.append((r["id"], None, run.id, None, None, None, None, "unmatched", n_cand))
                run.bump("unmatched")
                continue
            s, v = best
            if s["score"] >= MATCH_THRESHOLD and s["name_sim"] >= MIN_NAME_SIM:
                decision = "matched"
            elif s["score"] >= REVIEW_THRESHOLD:
                decision = "review"
            else:
                decision = "unmatched"
            run.bump(decision)
            rows.append(
                (
                    r["id"],
                    v.raw_id if decision == "matched" else None,
                    run.id,
                    s["score"],
                    s["name_sim"],
                    s["dist_m"],
                    s["addr_score"],
                    decision,
                    n_cand,
                )
            )
        with conn.cursor() as cur:
            cur.executemany(
                """insert into review_venue_links (raw_review_id, venue_id, run_id, score, name_sim, dist_m, addr_score,
                       decision, candidates)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (raw_review_id) do update set venue_id = excluded.venue_id, run_id = excluded.run_id,
                       score = excluded.score, name_sim = excluded.name_sim, dist_m = excluded.dist_m,
                       addr_score = excluded.addr_score, decision = excluded.decision,
                       candidates = excluded.candidates, linked_at = now()""",
                rows,
            )
        run.stats["reviews"] = len(reviews)
        run.mark_done("match_reviews:full", run.stats)
        log.info("match_reviews done: %s", run.stats)
