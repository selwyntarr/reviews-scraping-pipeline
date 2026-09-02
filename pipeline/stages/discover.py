"""Stage 1: pull venue candidates from open sources into raw_venues.

Sources:
  * OpenStreetMap via Overpass, chunked by amenity type so each chunk is a resumable unit.
  * NYC DOHMH restaurant inspections via Socrata, paged by offset; one row per establishment.
"""

from __future__ import annotations

import logging

from ..config import settings
from ..db import Run, connect, upsert_raw_venues
from ..geo import MANHATTAN_BBOX, contains, load_boundary
from ..http import Client

log = logging.getLogger(__name__)

OSM_AMENITIES = ["bar", "pub", "restaurant", "cafe", "nightclub", "biergarten", "fast_food"]

# Overpass "area" lookups for the Manhattan relation are unreliable on public instances, so we pull a
# bbox and clip to the borough polygon (see pipeline/geo.py).
OSM_BBOX = ",".join(str(v) for v in MANHATTAN_BBOX)

DOHMH_URL = "https://data.cityofnewyork.us/resource/43nn-pn8j.json"
DOHMH_PAGE = 5000


def discover_osm(run: Run, client: Client) -> None:
    with connect() as conn:
        poly = load_boundary(conn, client)
        for amenity in OSM_AMENITIES:
            unit = f"osm:{amenity}"
            if run.is_done(unit):
                log.info("skip %s (done)", unit)
                continue
            query = (
                f'[out:json][timeout:180];nwr["amenity"="{amenity}"]({OSM_BBOX});out center tags;'
            )
            resp = client.post(settings().overpass_url, data={"data": query})
            elements = resp.json().get("elements", [])
            rows = []
            for el in elements:
                tags = el.get("tags") or {}
                if not tags.get("name"):
                    continue
                center = el.get("center") or {"lat": el.get("lat"), "lon": el.get("lon")}
                if not contains(poly, center.get("lat"), center.get("lon")):
                    run.bump("osm_outside_boundary")
                    continue
                rows.append(
                    (
                        f"{el['type']}/{el['id']}",
                        {
                            "osm_type": el["type"],
                            "osm_id": el["id"],
                            "lat": center.get("lat"),
                            "lon": center.get("lon"),
                            "tags": tags,
                        },
                    )
                )
            counts = upsert_raw_venues(conn, "osm", rows)
            log.info("%s: %d named elements -> %s", unit, len(rows), counts)
            for k, v in counts.items():
                run.bump(f"osm_{k}", v)
            run.mark_done(unit, {"elements": len(elements), **counts})


def discover_dohmh(run: Run, client: Client) -> None:
    headers = {}
    if settings().socrata_app_token:
        headers["X-App-Token"] = settings().socrata_app_token
    select = (
        "camis, dba, building, street, zipcode, phone, cuisine_description, "
        "latitude, longitude, max(inspection_date) as last_inspection"
    )
    group = "camis, dba, building, street, zipcode, phone, cuisine_description, latitude, longitude"
    offset = 0
    with connect() as conn:
        while True:
            unit = f"dohmh:{offset}"
            if run.is_done(unit):
                log.info("skip %s (done)", unit)
                offset += DOHMH_PAGE
                continue
            params = {
                "$select": select,
                "$where": "boro = 'Manhattan'",
                "$group": group,
                "$order": "camis",
                "$limit": DOHMH_PAGE,
                "$offset": offset,
            }
            data = client.get(DOHMH_URL, params=params, headers=headers).json()
            rows = [(r["camis"], r) for r in data if r.get("dba")]
            counts = upsert_raw_venues(conn, "dohmh", rows)
            log.info("%s: %d rows -> %s", unit, len(data), counts)
            for k, v in counts.items():
                run.bump(f"dohmh_{k}", v)
            run.mark_done(unit, {"rows": len(data), **counts})
            if len(data) < DOHMH_PAGE:
                break
            offset += DOHMH_PAGE


def run_discover(sources: list[str]) -> None:
    client = Client(min_interval=1.0)
    with Run("discover") as run:
        if "osm" in sources:
            discover_osm(run, client)
        if "dohmh" in sources:
            discover_dohmh(run, client)
