"""Stage 3: collect Reddit posts + comment trees via the official OAuth API (app-only grant).

Units of work (resumable):
  * search:<subreddit>:<keyword>  -> raw_posts
  * comments:<post_id>            -> raw_comments
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

import httpx
from psycopg.types.json import Jsonb  # noqa: F401  (kept for future payload storage)

from ..config import settings
from ..db import Run, connect, content_hash
from ..http import Client

log = logging.getLogger(__name__)

SUBREDDITS = ["AskNYC", "FoodNYC", "nycbars", "nyc"]
KEYWORDS = [
    "bar",
    "happy hour",
    "live music",
    "date spot",
    "cocktail",
    "dive bar",
    "rooftop",
    "brunch",
    "best restaurant",
    "hidden gem",
    "late night",
    "speakeasy",
    "jazz",
    "trivia",
    "karaoke",
]
OAUTH = "https://oauth.reddit.com"


class Reddit:
    def __init__(self, client: Client):
        s = settings()
        if not (s.reddit_client_id and s.reddit_client_secret):
            raise RuntimeError("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET are not set")
        self.client = client
        self._token = None
        self._expires = 0.0

    def _headers(self) -> dict:
        if time.time() > self._expires - 60:
            s = settings()
            resp = httpx.post(
                "https://www.reddit.com/api/v1/access_token",
                auth=(s.reddit_client_id, s.reddit_client_secret),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": s.reddit_user_agent},
                timeout=30,
            )
            resp.raise_for_status()
            tok = resp.json()
            self._token = tok["access_token"]
            self._expires = time.time() + tok.get("expires_in", 3600)
            log.info("reddit token acquired")
        return {
            "Authorization": f"bearer {self._token}",
            "User-Agent": settings().reddit_user_agent,
        }

    def get(self, path: str, **params) -> dict | list:
        resp = self.client.get(
            f"{OAUTH}{path}", params={**params, "raw_json": 1}, headers=self._headers()
        )
        remaining = resp.headers.get("x-ratelimit-remaining")
        if remaining is not None and float(remaining) < 5:
            reset = float(resp.headers.get("x-ratelimit-reset", 60))
            log.warning("reddit rate limit nearly exhausted, sleeping %ss", reset)
            time.sleep(reset)
        return resp.json()

    def search(self, subreddit: str, q: str, limit: int, t: str = "year") -> list[dict]:
        out, after = [], None
        while len(out) < limit:
            page = self.get(
                f"/r/{subreddit}/search",
                q=q,
                restrict_sr=1,
                sort="top",
                t=t,
                limit=min(100, limit - len(out)),
                after=after,
                type="link",
            )["data"]
            out.extend(c["data"] for c in page["children"] if c["kind"] == "t3")
            after = page.get("after")
            if not after:
                break
        return out

    def comments(self, post_id: str) -> tuple[list[dict], int]:
        listing = self.get(f"/comments/{post_id}", limit=500, depth=10, sort="top")
        flat, more = [], 0

        def walk(children, depth=0):
            nonlocal more
            for c in children:
                if c["kind"] == "t1":
                    d = c["data"]
                    d["_depth"] = depth
                    flat.append(d)
                    replies = d.get("replies")
                    if isinstance(replies, dict):
                        walk(replies["data"]["children"], depth + 1)
                elif c["kind"] == "more":
                    more += len(c["data"].get("children", []))

        walk(listing[1]["data"]["children"])
        return flat, more


def _ts(v) -> datetime | None:
    return datetime.fromtimestamp(v, tz=UTC) if v else None


def run_collect_text(posts_per_query: int, min_comments: int, max_posts: int | None) -> None:
    client = Client(min_interval=1.0, timeout=60)
    reddit = Reddit(client)
    with Run("collect_text") as run, connect() as conn:
        # 1. Searches -> raw_posts
        for sub in SUBREDDITS:
            for kw in KEYWORDS:
                unit = f"search:{sub}:{kw}"
                if run.is_done(unit):
                    continue
                posts = reddit.search(sub, kw, posts_per_query)
                n_new = 0
                with conn.cursor() as cur:
                    for p in posts:
                        if p.get("num_comments", 0) < min_comments or p.get("removed_by_category"):
                            continue
                        h = content_hash(
                            {k: p.get(k) for k in ("title", "selftext", "score", "num_comments")}
                        )
                        row = cur.execute(
                            """insert into raw_posts (reddit_id, subreddit, title, selftext, author, score,
                                   num_comments, created_utc, permalink, queries, content_hash)
                               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                               on conflict (reddit_id) do update set
                                   score = excluded.score, num_comments = excluded.num_comments,
                                   queries = (select array(select distinct unnest(raw_posts.queries || excluded.queries))),
                                   content_hash = excluded.content_hash, fetched_at = now()
                               returning (xmax = 0) as inserted""",
                            (
                                p["id"],
                                p["subreddit"],
                                p["title"],
                                p.get("selftext") or None,
                                p.get("author"),
                                p.get("score"),
                                p.get("num_comments"),
                                _ts(p.get("created_utc")),
                                p.get("permalink"),
                                [f"{sub}:{kw}"],
                                h,
                            ),
                        ).fetchone()
                        n_new += bool(row and row["inserted"])
                run.bump("posts_seen", len(posts))
                run.bump("posts_inserted", n_new)
                run.mark_done(unit, {"posts": len(posts), "inserted": n_new})
                log.info("%s: %d posts (%d new)", unit, len(posts), n_new)

        # 2. Comment trees for posts not yet fetched, highest-engagement first
        todo = conn.execute(
            "select reddit_id, num_comments from raw_posts where comments_fetched_at is null "
            "order by num_comments desc limit %s",
            (max_posts or 1_000_000,),
        ).fetchall()
        log.info("fetching comment trees for %d posts", len(todo))
        for row in todo:
            pid = row["reddit_id"]
            unit = f"comments:{pid}"
            if run.is_done(unit):
                continue
            flat, more = reddit.comments(pid)
            n = 0
            with conn.cursor() as cur:
                for c in flat:
                    body = c.get("body") or ""
                    if body in ("[deleted]", "[removed]") or len(body) < 20:
                        continue
                    cur.execute(
                        """insert into raw_comments (reddit_id, post_reddit_id, parent_id, author, body, score,
                               depth, created_utc, content_hash)
                           values (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           on conflict (reddit_id) do update set body = excluded.body, score = excluded.score,
                               content_hash = excluded.content_hash, fetched_at = now()
                           where raw_comments.content_hash is distinct from excluded.content_hash""",
                        (
                            c["id"],
                            pid,
                            c.get("parent_id"),
                            c.get("author"),
                            body,
                            c.get("score"),
                            c["_depth"],
                            _ts(c.get("created_utc")),
                            content_hash(body),
                        ),
                    )
                    n += 1
                cur.execute(
                    "update raw_posts set comments_fetched_at = now() where reddit_id = %s", (pid,)
                )
            run.bump("comments_stored", n)
            run.bump("more_stubs_skipped", more)
            run.mark_done(unit, {"comments": n, "more_skipped": more})
        log.info("collect_text done: %s", run.stats)
