"""Boundary fetching and point-in-polygon clipping."""

from __future__ import annotations

import logging

from psycopg.types.json import Jsonb
from shapely.geometry import LineString, Point, mapping, shape
from shapely.ops import linemerge, polygonize, unary_union

from .config import settings
from .http import Client

log = logging.getLogger(__name__)

MANHATTAN_REL = 8398124
# Generous bbox around Manhattan; clipped to the polygon afterwards.
MANHATTAN_BBOX = (40.698, -74.026, 40.882, -73.907)


def fetch_osm_boundary(client: Client, rel_id: int):
    q = f"[out:json][timeout:90];rel({rel_id});out geom;"
    data = client.post(settings().overpass_url, data={"data": q}).json()
    lines = []
    for el in data["elements"]:
        for m in el.get("members", []):
            if m.get("type") == "way" and m.get("role") in ("outer", "") and m.get("geometry"):
                lines.append(LineString([(p["lon"], p["lat"]) for p in m["geometry"]]))
    merged = linemerge(unary_union(lines))
    poly = unary_union(list(polygonize(merged)))
    log.info("boundary rel %s: %d ways -> area %.5f deg^2", rel_id, len(lines), poly.area)
    return poly


def load_boundary(conn, client: Client, name: str = "manhattan"):
    row = conn.execute("select geojson from boundaries where name = %s", (name,)).fetchone()
    if row:
        return shape(row["geojson"])
    poly = fetch_osm_boundary(client, MANHATTAN_REL)
    conn.execute(
        "insert into boundaries (name, geojson) values (%s, %s) on conflict (name) do nothing",
        (name, Jsonb(mapping(poly))),
    )
    return poly


def contains(poly, lat: float | None, lon: float | None) -> bool:
    if lat is None or lon is None:
        return False
    return poly.contains(Point(lon, lat))
