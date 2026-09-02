"""Stage 2: build canonical venues from raw_venues (OSM + DOHMH).

Deterministic full rebuild. Blocking by geohash cell (+ neighbours) for records with coordinates and
by (zip, street) for records without; scoring by name similarity, address agreement, distance and
phone. Every scored pair is persisted to match_candidates; accepted pairs become venue_sources.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from .. import geohash
from ..db import Run, connect
from ..normalize import norm_housenumber, norm_name, norm_phone, norm_street, norm_zip

log = logging.getLogger(__name__)

GEOHASH_PRECISION = 7  # ~150 m cells
MATCH_THRESHOLD = 0.80
CERTAIN_THRESHOLD = 0.95  # exact-looking pairs may join an already-matched cluster
MIN_NAME_SIM = 0.75
MIN_NAME_SIM_NO_ADDR = 0.85
REVIEW_THRESHOLD = 0.70
SAME_SOURCE_NAME_SIM = 0.90
SAME_SOURCE_MAX_M = 80

DOHMH_CATEGORY = {
    "Bottled Beverages": "other",
    "Coffee/Tea": "cafe",
    "Juice, Smoothies, Fruit Salads": "cafe",
    "Bakery Products/Desserts": "cafe",
    "Donuts": "cafe",
    "Frozen Desserts": "cafe",
    "Hamburgers": "fast_food",
    "Sandwiches": "fast_food",
    "Hotdogs": "fast_food",
    "Pizza": "fast_food",
    "Chicken": "fast_food",
}


@dataclass
class Rec:
    raw_id: int
    source: str
    source_id: str
    name: str
    name_norm: str
    housenumber: str
    street: str
    street_norm: str
    zip: str
    lat: float | None
    lon: float | None
    phone: str
    website: str | None
    cuisine: str | None
    category: str | None
    last_inspection: str | None
    geohash: str | None = None
    name_variants: list[str] = field(default_factory=list)

    def __post_init__(self):
        # DOHMH DBAs often list several concepts at one license: "FELLINI CUCINA / FELLINI COFFEE".
        parts = [norm_name(p) for p in self.name.split("/")]
        self.name_variants = [v for v in dict.fromkeys([self.name_norm, *parts]) if v]


def _rec_from_osm(row) -> Rec | None:
    p = row["payload"]
    t = p.get("tags", {})
    name = t.get("name")
    if not name:
        return None
    lat, lon = p.get("lat"), p.get("lon")
    amenity = t.get("amenity")
    return Rec(
        raw_id=row["id"],
        source="osm",
        source_id=row["source_id"],
        name=name,
        name_norm=norm_name(name),
        housenumber=norm_housenumber(t.get("addr:housenumber")),
        street=t.get("addr:street") or "",
        street_norm=norm_street(t.get("addr:street")),
        zip=norm_zip(t.get("addr:postcode")),
        lat=lat,
        lon=lon,
        phone=norm_phone(t.get("phone") or t.get("contact:phone")),
        website=t.get("website") or t.get("contact:website"),
        cuisine=t.get("cuisine"),
        category=amenity
        if amenity in ("bar", "pub", "restaurant", "cafe", "nightclub", "fast_food")
        else "other",
        last_inspection=None,
        geohash=geohash.encode(lat, lon, GEOHASH_PRECISION) if lat and lon else None,
    )


def _rec_from_dohmh(row) -> Rec | None:
    p = row["payload"]
    name = p.get("dba")
    if not name:
        return None
    lat = float(p.get("latitude") or 0) or None
    lon = float(p.get("longitude") or 0) or None
    cuisine = p.get("cuisine_description")
    insp = (p.get("last_inspection") or "")[:10]
    return Rec(
        raw_id=row["id"],
        source="dohmh",
        source_id=row["source_id"],
        name=name.title(),
        name_norm=norm_name(name),
        housenumber=norm_housenumber(p.get("building")),
        street=(p.get("street") or "").strip(),
        street_norm=norm_street(p.get("street")),
        zip=norm_zip(p.get("zipcode")),
        lat=lat,
        lon=lon,
        phone=norm_phone(p.get("phone")),
        website=None,
        cuisine=cuisine,
        category=DOHMH_CATEGORY.get(cuisine, "restaurant"),
        last_inspection=insp if insp and insp > "1901" else None,
        geohash=geohash.encode(lat, lon, GEOHASH_PRECISION) if lat and lon else None,
    )


def haversine_m(lat1, lon1, lat2, lon2) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _name_sim(x: str, y: str) -> float:
    return (
        max(
            fuzz.ratio(x, y),
            0.5 * fuzz.token_set_ratio(x, y) + 0.5 * fuzz.token_sort_ratio(x, y),
        )
        / 100.0
    )


def score_pair(a: Rec, b: Rec) -> dict:
    # token_set alone scores any subset as 100 ("the bao" vs "nan xiang xiao long bao"), so blend it
    # with token_sort, which penalises the missing tokens.
    name_sim = max((_name_sim(x, y) for x in a.name_variants for y in b.name_variants), default=0.0)
    dist = None
    if a.lat and b.lat:
        dist = haversine_m(a.lat, a.lon, b.lat, b.lon)
    dist_score = (
        None if dist is None else max(0.0, 1.0 - max(0.0, dist - 40) / 260)
    )  # 1 at <=40m, 0 at 300m
    addr = None
    if a.street_norm and b.street_norm:
        if a.street_norm == b.street_norm:
            addr = 1.0 if (a.housenumber and a.housenumber == b.housenumber) else 0.5
        else:
            addr = 0.0
    phone = bool(a.phone and a.phone == b.phone)
    # Location evidence: address when available, otherwise distance.
    loc = addr if addr is not None else dist_score
    if loc is None:
        loc = 0.0
    score = 0.55 * name_sim + 0.30 * loc + 0.15 * (dist_score if dist_score is not None else loc)
    if phone:
        score = min(1.0, score + 0.15)
    if addr == 0.0 and dist is not None and dist > 150:
        score *= 0.7  # different street and far apart: strong negative
    return {
        "score": round(score, 4),
        "name_sim": round(name_sim, 4),
        "dist_m": None if dist is None else round(dist, 1),
        "addr_score": addr,
        "phone_match": phone,
    }


def _blocks(recs: list[Rec]) -> dict[str, list[Rec]]:
    blocks: dict[str, list[Rec]] = defaultdict(list)
    for r in recs:
        if r.geohash:
            blocks[f"g:{r.geohash}"].append(r)
        elif r.zip and r.street_norm:
            blocks[f"a:{r.zip}:{r.street_norm}"].append(r)
    return blocks


def _candidates_for(rec: Rec, blocks: dict[str, list[Rec]], source: str) -> list[Rec]:
    keys = []
    if rec.geohash:
        keys = [f"g:{rec.geohash}"] + [f"g:{n}" for n in geohash.neighbors(rec.geohash)]
    if rec.zip and rec.street_norm:
        keys.append(f"a:{rec.zip}:{rec.street_norm}")
    seen, out = set(), []
    for k in keys:
        for c in blocks.get(k, []):
            if c.source == source and c.raw_id not in seen and c.raw_id != rec.raw_id:
                seen.add(c.raw_id)
                out.append(c)
    return out


class UnionFind:
    def __init__(self):
        self.p: dict[int, int] = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def run_dedupe() -> None:
    with Run("dedupe") as run, connect() as conn:
        rows = conn.execute(
            "select id, source, source_id, payload from raw_venues order by id"
        ).fetchall()
        recs: list[Rec] = []
        for row in rows:
            r = _rec_from_osm(row) if row["source"] == "osm" else _rec_from_dohmh(row)
            if r:
                recs.append(r)
        osm = [r for r in recs if r.source == "osm"]
        dohmh = [r for r in recs if r.source == "dohmh"]
        log.info("loaded %d osm + %d dohmh records", len(osm), len(dohmh))
        blocks = _blocks(recs)
        uf = UnionFind()
        cands: list[tuple] = []

        # 1. Same-source duplicates: OSM node-vs-way double mapping, and DOHMH re-registrations of the
        #    same venue under a new license (camis). Same name + same spot => one cluster.
        for source, pool in (("osm", osm), ("dohmh", dohmh)):
            merged = 0
            for a in pool:
                for b in _candidates_for(a, blocks, source):
                    if a.raw_id >= b.raw_id:
                        continue
                    sc = score_pair(a, b)
                    same_addr = bool(
                        a.housenumber
                        and a.housenumber == b.housenumber
                        and a.street_norm == b.street_norm
                    )
                    close = sc["dist_m"] is not None and sc["dist_m"] <= SAME_SOURCE_MAX_M
                    if sc["name_sim"] >= SAME_SOURCE_NAME_SIM and (same_addr or close):
                        uf.union(a.raw_id, b.raw_id)
                        cands.append((a.raw_id, b.raw_id, sc, "matched"))
                        merged += 1
            run.stats[f"{source}_internal_merged"] = merged

        # 2. DOHMH -> OSM cross-source matching, greedy one-to-one by score
        pairs = []
        for d in dohmh:
            for o in _candidates_for(d, blocks, "osm"):
                s = score_pair(d, o)
                if s["score"] >= REVIEW_THRESHOLD:
                    pairs.append((s["score"], d, o, s))
        pairs.sort(key=lambda x: -x[0])
        taken_d, taken_o = set(), set()
        matched_pairs = 0
        for score, d, o, sc in pairs:
            rd, ro = uf.find(d.raw_id), uf.find(o.raw_id)
            # Name gate: address agreement alone must not merge different businesses at one address.
            very_close = sc["dist_m"] is not None and sc["dist_m"] <= 25
            name_floor = (
                MIN_NAME_SIM
                if (sc["addr_score"] is not None or very_close)
                else MIN_NAME_SIM_NO_ADDR
            )
            if sc["name_sim"] < name_floor:
                if score >= REVIEW_THRESHOLD:
                    cands.append((d.raw_id, o.raw_id, sc, "review"))
                continue
            certain = score >= CERTAIN_THRESHOLD and (
                sc["addr_score"] == 1.0 or (sc["dist_m"] is not None and sc["dist_m"] <= 50)
            )
            if rd == ro:  # already in one cluster via an earlier pair
                cands.append((d.raw_id, o.raw_id, sc, "matched"))
                matched_pairs += 1
            elif score >= MATCH_THRESHOLD and (
                certain or (rd not in taken_d and ro not in taken_o)
            ):
                uf.union(d.raw_id, o.raw_id)
                root = uf.find(d.raw_id)
                taken_d.update((rd, root))
                taken_o.update((ro, root))
                cands.append((d.raw_id, o.raw_id, sc, "matched"))
                matched_pairs += 1
            elif score >= REVIEW_THRESHOLD:
                cands.append((d.raw_id, o.raw_id, sc, "review"))
        run.stats["cross_matched_pairs"] = matched_pairs
        run.stats["review_pairs"] = sum(1 for c in cands if c[3] == "review")

        # 3. Persist candidates
        with conn.cursor() as cur:
            cur.executemany(
                "insert into match_candidates (run_id, left_raw_id, right_raw_id, score, name_sim, dist_m, addr_score, phone_match, decision) "
                "values (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [
                    (
                        run.id,
                        l,
                        r,
                        s["score"],
                        s["name_sim"],
                        s["dist_m"],
                        s["addr_score"],
                        s["phone_match"],
                        dec,
                    )
                    for l, r, s, dec in cands
                ],
            )

        # 4. Build clusters -> venues
        clusters: dict[int, list[Rec]] = defaultdict(list)
        for r in recs:
            clusters[uf.find(r.raw_id)].append(r)

        def rank(r: Rec):  # primary record preference: OSM first, then richer address
            return (r.source != "osm", not r.housenumber, not r.phone, r.raw_id)

        venue_rows, source_rows = [], []
        for members in clusters.values():
            members.sort(key=rank)
            p = members[0]
            key = f"{p.source}:{p.source_id}"

            def best(attr, members=members):
                return next((getattr(m, attr) for m in members if getattr(m, attr)), None)

            lat = best("lat")
            lon = best("lon")
            venue_rows.append(
                (
                    key,
                    p.name,
                    p.name_norm,
                    p.category,
                    best("housenumber"),
                    best("street"),
                    best("street_norm"),
                    best("zip"),
                    lat,
                    lon,
                    geohash.encode(lat, lon, GEOHASH_PRECISION) if lat and lon else None,
                    best("phone"),
                    best("website"),
                    best("cuisine"),
                    best("last_inspection"),
                    len(members),
                )
            )
            for m in members:
                method = (
                    "primary" if m is p else ("same-source" if m.source == p.source else "auto")
                )
                source_rows.append((key, m.source, m.source_id, m.raw_id, method))

        with conn.cursor() as cur:
            cur.execute("update venues set retired_at = now() where retired_at is null")
            cur.executemany(
                """insert into venues (key, name, name_norm, category, housenumber, street, street_norm, zip, lat, lon,
                       geohash, phone, website, cuisine, last_inspection, source_count)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (key) do update set
                       name = excluded.name, name_norm = excluded.name_norm, category = excluded.category,
                       housenumber = excluded.housenumber, street = excluded.street, street_norm = excluded.street_norm,
                       zip = excluded.zip, lat = excluded.lat, lon = excluded.lon, geohash = excluded.geohash,
                       phone = excluded.phone, website = excluded.website, cuisine = excluded.cuisine,
                       last_inspection = excluded.last_inspection, source_count = excluded.source_count,
                       updated_at = now(), retired_at = null""",
                venue_rows,
            )
            cur.execute("delete from venue_sources")
            cur.executemany(
                """insert into venue_sources (venue_id, source, source_id, raw_venue_id, match_score, match_method)
                   select v.id, %s, %s, %s, mc.score, %s from venues v
                   left join lateral (
                       select score from match_candidates mc
                       where mc.decision = 'matched' and %s in (mc.left_raw_id, mc.right_raw_id)
                       order by score desc limit 1) mc on true
                   where v.key = %s""",
                [(src, sid, rid, method, rid, key) for key, src, sid, rid, method in source_rows],
            )
        run.stats["venues"] = len(venue_rows)
        run.stats["raw_records"] = len(recs)
        run.mark_done("dedupe:full", run.stats)
        log.info("dedupe done: %s", run.stats)
