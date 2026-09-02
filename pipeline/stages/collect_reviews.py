"""Stage 3b: collect venue-centric prose from open web sources into raw_reviews.

Adapters (each yields dicts for raw_reviews; each unit of work is resumable):
  * infatuation — NYC review pages enumerated from the public sitemap, parsed from the server-rendered
                  __NEXT_DATA__ JSON (robots.txt allows generic crawlers; AI-crawler UAs are disallowed,
                  so we identify as this project, not as an AI bot). Unit = one review page.
  * wikipedia   — MediaWiki API: members of the Manhattan restaurant/bar/nightclub categories with
                  plain-text extracts and coordinates. Unit = one category.
  * wikivoyage  — MediaWiki API: {{eat}}/{{drink}} listings on the Manhattan district pages.
                  Unit = one district page.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterator
from datetime import date

import httpx
from psycopg.types.json import Jsonb

from ..db import Run, connect, content_hash
from ..http import Client

log = logging.getLogger(__name__)

UA_BROWSERISH = "Mozilla/5.0 (compatible; venue-insight-pipeline/0.1; portfolio project)"
INF_SITEMAPS = [
    "https://www.theinfatuation.com/sitemap-0.xml",
    "https://www.theinfatuation.com/sitemap-1.xml",
]
INF_REVIEW_RE = re.compile(r"https://www\.theinfatuation\.com/new-york/reviews/[a-z0-9-]+")
WP_API = "https://en.wikipedia.org/w/api.php"
WV_API = "https://en.wikivoyage.org/w/api.php"
WP_CATEGORIES = [
    "Restaurants in Manhattan",
    "Drinking establishments in Manhattan",
    "Nightclubs in Manhattan",
]
NYC_ZIP_RE = re.compile(r"\b1\d{4}\b")


# ----------------------------------------------------------------------------- infatuation
def _rich_text(node, acc: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("nodeType") == "paragraph" and acc:
            acc.append("\n")
        if "value" in node:
            acc.append(node["value"])
        for c in node.get("content", []):
            _rich_text(c, acc)
    elif isinstance(node, list):
        for c in node:
            _rich_text(c, acc)


def infatuation_urls(client: Client) -> list[str]:
    urls: set[str] = set()
    for sm in INF_SITEMAPS:
        urls.update(
            INF_REVIEW_RE.findall(client.get(sm, headers={"User-Agent": UA_BROWSERISH}).text)
        )
    return sorted(urls)


def parse_infatuation(html: str, url: str) -> dict | None:
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL
    )
    if not m:
        return None
    state = json.loads(m.group(1))["props"]["pageProps"].get("initialApolloState", {})
    slug = url.rsplit("/", 1)[-1]

    def deref(v):
        return state.get(v["__ref"], v) if isinstance(v, dict) and "__ref" in v else v

    review = None
    for v in state.values():
        if (
            isinstance(v, dict)
            and v.get("__typename") == "PostReview"
            and deref(v.get("slug", {})).get("name") == slug
        ):
            review = v
            break
    if review is None:
        return None
    venue = deref(review.get("venue")) or {}
    latlong = venue.get("latlong") or {}
    tags, hood = [], None
    for k, v in review.items():
        if k.startswith("cuisineTagsCollection"):
            tags += [deref(i).get("name") for i in v.get("items", [])]
        elif k.startswith("neighborhoodTagsCollection"):
            hoods = [deref(i).get("displayName") for i in v.get("items", [])]
            hood = hoods[0] if hoods else None
        elif k.startswith("sectionsCollection"):
            for i in v.get("items", []):
                path = (deref(i) or {}).get("path") or ""
                if "/perfect-for/" in path:
                    tags.append("perfect-for:" + path.rsplit("/", 1)[-1])
    body: list[str] = []
    content = deref(review.get("content")) or {}
    _rich_text(content.get("json"), body)
    preview, body_text = (review.get("preview") or "").strip(), "".join(body).strip()
    # The preview is usually the body's first sentence; keep it only when it adds something.
    text = body_text if body_text.startswith(preview[:40]) else f"{preview}\n\n{body_text}".strip()
    pub = (review.get("publishDate") or "")[:10]
    return {
        "source_id": slug,
        "url": url,
        "venue_name": venue.get("name") or review.get("title"),
        "street": venue.get("street"),
        "zip": venue.get("postalCode"),
        "lat": latlong.get("lat"),
        "lon": latlong.get("lon"),
        "neighborhood": hood,
        "tags": [t for t in tags if t],
        "price": str(venue["price"]) if venue.get("price") is not None else None,
        "hours": None,
        "published_at": pub or None,
        "title": review.get("title"),
        "text": text,
        "payload": {
            "venue": {k: v for k, v in venue.items() if not isinstance(v, dict) or k == "latlong"},
            "closed": venue.get("closed"),
            "rating": review.get("rating"),
        },
    }


def collect_infatuation(run: Run, client: Client, conn, max_pages: int | None) -> None:
    urls = infatuation_urls(client)
    log.info("infatuation: %d NYC review urls in sitemap", len(urls))
    done = 0
    for url in urls:
        unit = f"infatuation:{url.rsplit('/', 1)[-1]}"
        if run.is_done(unit):
            continue
        if max_pages is not None and done >= max_pages:
            break
        try:
            html = client.get(url, headers={"User-Agent": UA_BROWSERISH}).text
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                raise
            run.bump("infatuation_404")  # dead sitemap entry; recorded so it is not retried
            run.mark_done(unit, {"parsed": False, "status": 404})
            continue
        item = parse_infatuation(html, url)
        if item is None or not item["text"].strip():
            run.bump("infatuation_unparsed")
            run.mark_done(unit, {"parsed": False})
            continue
        _upsert(conn, "infatuation", item)
        run.bump("infatuation_stored")
        run.mark_done(unit, {"parsed": True})
        done += 1


# ----------------------------------------------------------------------------- wikipedia
def _wp(client: Client, api: str, **params) -> dict:
    return client.get(api, params={"format": "json", **params}).json()


def wikipedia_members(client: Client, category: str, depth: int = 0) -> list[str]:
    """Pages in a category plus one level of subcategories (e.g. 'Steakhouses in Manhattan')."""
    titles, cont = [], {}
    while True:
        r = _wp(
            client,
            WP_API,
            action="query",
            list="categorymembers",
            cmtitle=f"Category:{category}",
            cmlimit=500,
            cmtype="page|subcat",
            **cont,
        )
        for m in r["query"]["categorymembers"]:
            if m["ns"] == 14 and depth < 1:
                titles += wikipedia_members(client, m["title"].removeprefix("Category:"), depth + 1)
            elif m["ns"] == 0:
                titles.append(m["title"])
        cont = r.get("continue", {})
        if not cont:
            return list(dict.fromkeys(titles))


def wikipedia_pages(client: Client, titles: list[str]) -> Iterator[dict]:
    # TextExtracts returns a full-page extract for only one page per request.
    for title in titles:
        r = _wp(
            client,
            WP_API,
            action="query",
            prop="extracts|coordinates|info",
            explaintext=1,
            exsectionformat="plain",
            inprop="url",
            titles=title,
        )
        for p in r["query"]["pages"].values():
            text = (p.get("extract") or "").strip()
            if not text or p.get("missing") is not None:
                continue
            co = (p.get("coordinates") or [{}])[0]
            zips = NYC_ZIP_RE.findall(text[:1500])
            yield {
                "source_id": p["title"],
                "url": p.get("fullurl"),
                "venue_name": re.sub(r"\s*\(.*?\)$", "", p["title"]),
                "street": None,
                "zip": zips[0] if zips else None,
                "lat": co.get("lat"),
                "lon": co.get("lon"),
                "neighborhood": None,
                "tags": [],
                "price": None,
                "hours": None,
                "published_at": None,
                "title": p["title"],
                "text": text,
                "payload": {"pageid": p.get("pageid")},
            }


def collect_wikipedia(run: Run, client: Client, conn) -> None:
    for cat in WP_CATEGORIES:
        unit = f"wikipedia:{cat}"
        if run.is_done(unit):
            continue
        titles = wikipedia_members(client, cat)
        n = 0
        for item in wikipedia_pages(client, titles):
            _upsert(conn, "wikipedia", item)
            n += 1
        run.bump("wikipedia_stored", n)
        run.mark_done(unit, {"titles": len(titles), "stored": n})
        log.info("%s: %d titles, %d stored", unit, len(titles), n)


# ----------------------------------------------------------------------------- wikivoyage
# {{eat|...}}, {{drink|...}} or {{listing|type=eat|...}}; tolerates one level of nested {{templates}}.
LISTING_RE = re.compile(
    r"\{\{(eat|drink|listing)\s*\|((?:[^{}]|\{\{[^{}]*\}\})*)\}\}", re.IGNORECASE | re.DOTALL
)


def _fields(body: str) -> dict[str, str]:
    out = {}
    for part in re.split(r"\|(?=\s*\w+\s*=)", body):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def wikivoyage_districts(client: Client) -> list[str]:
    r = _wp(client, WV_API, action="query", list="prefixsearch", pssearch="Manhattan/", pslimit=100)
    return [x["title"] for x in r["query"]["prefixsearch"] if "/" in x["title"]]


def collect_wikivoyage(run: Run, client: Client, conn) -> None:
    for page in wikivoyage_districts(client):
        unit = f"wikivoyage:{page}"
        if run.is_done(unit):
            continue
        r = _wp(client, WV_API, action="parse", page=page, prop="wikitext")
        wikitext = r["parse"]["wikitext"]["*"]
        district = page.split("/", 1)[1]
        n = 0
        for kind, body in LISTING_RE.findall(wikitext):
            f = _fields(body)
            if kind.lower() == "listing":
                kind = f.get("type", "")
                if kind not in ("eat", "drink"):
                    continue
            name, content = (
                f.get("name", ""),
                re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", f.get("content", "")),
            )
            if not name or len(content) < 30:
                continue
            try:
                lat, lon = float(f.get("lat") or 0) or None, float(f.get("long") or 0) or None
            except ValueError:
                lat = lon = None
            _upsert(
                conn,
                "wikivoyage",
                {
                    "source_id": f"{district}:{name}",
                    "url": f"https://en.wikivoyage.org/wiki/{page.replace(' ', '_')}",
                    "venue_name": name,
                    "street": f.get("address") or None,
                    "zip": None,
                    "lat": lat,
                    "lon": lon,
                    "neighborhood": district,
                    "tags": [kind.lower()],
                    "price": f.get("price") or None,
                    "hours": f.get("hours") or None,
                    "published_at": (f.get("lastedit") or None),
                    "title": None,
                    "text": content,
                    "payload": {k: v for k, v in f.items() if k not in ("content",)},
                },
            )
            n += 1
        run.bump("wikivoyage_stored", n)
        run.mark_done(unit, {"listings": n})
        log.info("%s: %d listings", unit, n)


# ----------------------------------------------------------------------------- shared
def _upsert(conn, source: str, item: dict) -> None:
    pub = item.get("published_at")
    try:
        pub = date.fromisoformat(pub) if pub else None
    except ValueError:
        pub = None
    conn.execute(
        """insert into raw_reviews (source, source_id, url, venue_name, street, zip, lat, lon, neighborhood, tags,
               price, hours, published_at, title, text, payload, content_hash)
           values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           on conflict (source, source_id) do update set
               url = excluded.url, venue_name = excluded.venue_name, street = excluded.street, zip = excluded.zip,
               lat = excluded.lat, lon = excluded.lon, neighborhood = excluded.neighborhood, tags = excluded.tags,
               price = excluded.price, hours = excluded.hours, published_at = excluded.published_at,
               title = excluded.title, text = excluded.text, payload = excluded.payload,
               content_hash = excluded.content_hash, fetched_at = now()
           where raw_reviews.content_hash is distinct from excluded.content_hash""",
        (
            source,
            item["source_id"],
            item.get("url"),
            item["venue_name"],
            item.get("street"),
            item.get("zip"),
            item.get("lat"),
            item.get("lon"),
            item.get("neighborhood"),
            item.get("tags") or [],
            item.get("price"),
            item.get("hours"),
            pub,
            item.get("title"),
            item["text"],
            Jsonb(item.get("payload") or {}),
            content_hash({"text": item["text"], "tags": item.get("tags")}),
        ),
    )


def run_collect_reviews(sources: list[str], max_pages: int | None) -> None:
    client = Client(min_interval=1.0, timeout=60)
    with Run("collect_reviews") as run, connect() as conn:
        if "wikipedia" in sources:
            collect_wikipedia(run, client, conn)
        if "wikivoyage" in sources:
            collect_wikivoyage(run, client, conn)
        if "infatuation" in sources:
            collect_infatuation(run, client, conn, max_pages)
        log.info("collect_reviews done: %s", run.stats)
