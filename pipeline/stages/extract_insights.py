"""Stage 6: LLM insight extraction per matched review.

Unit of work = one raw_reviews row for (model, PROMPT_VERSION). A row is re-extracted only if its
content_hash changed. Every extraction stores the raw model output, the evidence quotes, and whether
each quote was found verbatim in the source text (the cheap, deterministic check that catches
paraphrased "evidence").
"""

from __future__ import annotations

import logging
import time

from psycopg.types.json import Jsonb

from ..db import Run, connect
from ..llm import extract_json, model_name

log = logging.getLogger(__name__)

PROMPT_VERSION = "v5"

VIBE_VOCAB = [
    "casual",
    "upscale",
    "romantic",
    "lively",
    "cozy",
    "divey",
    "trendy",
    "classic",
    "family-friendly",
    "tourist-heavy",
    "locals",
    "quiet",
    "loud",
    "intimate",
    "spacious",
    "rustic",
    "modern",
    "kitschy",
    "no-frills",
    "late-night",
    "outdoor-seating",
    "counter-service",
    "old-school",
    "scene-y",
    "hidden-gem",
]

SYSTEM = f"""You extract structured venue insights from one review of one venue.

Rules:
- Use only what the text states or clearly implies about THIS venue. Never invent.
- vibe_tags: choose ONLY from this list: {", ".join(VIBE_VOCAB)}. Atmosphere only, never cuisine or dishes.
  Tag only what the text DESCRIBES about the room, decor, crowd, service style or mood. Never infer a vibe from
  awards, critics' lists, Michelin stars, prices, ownership, chefs, history, filming locations or press mentions:
  those say nothing about atmosphere. If the text describes no atmosphere, vibe_tags is [].
- good_for: occasions or company only (e.g. a type of visit), never a dish or a menu item.
- noise_level / crowd_level: only if the text describes sound or how busy it gets; else null.
- best_time: LOOK for it: mentions of lines or waits, "show up early", "avoid weekends", "weeknights", opening hours,
  "open until 3am", "before the show", brunch-only relevance. Turn them into a short recommendation; else null.
- recurring_events: LOOK for regular happenings: live music, open mic, trivia, happy hour, DJ nights, weekly specials;
  quote the sentence; else [].
- good_for: the occasion or company the text itself recommends the venue for, in the text's own words. NEVER a type
  of person, a dish, or a remark about service. Most reviews say nothing: leave it empty.
- Atmosphere words to watch for in vibe_tags: outdoor seating or patio → outdoor-seating; open very late → late-night;
  order at the counter → counter-service; cash-only, bare, unpretentious → no-frills; "tourists" → tourist-heavy;
  "families", "kids" → family-friendly.
- sentiment: the reviewer's overall verdict. A review that recommends, praises or enjoys the place is "positive".
  Use "neutral" ONLY when the text passes no judgement at all (a pure encyclopedia entry or listing); "mixed" only
  when praise and criticism both appear.
- evidence: for EVERY non-null field and non-empty list, one item with field set to the field NAME (vibe_tags,
  noise_level, crowd_level, best_time, recurring_events, good_for, sentiment) and quote an exact,
  character-for-character substring of the review text that supports it. No paraphrase, no ellipses, no fixes.
  A field with no verbatim supporting quote will be discarded, so leave it null/empty instead of guessing.
- confidence: 0-1, how well the text supports the whole extraction."""

SCHEMA = {
    "type": "object",
    "properties": {
        "vibe_tags": {"type": "array", "items": {"type": "string", "enum": VIBE_VOCAB}},
        "noise_level": {"type": ["string", "null"], "enum": ["quiet", "moderate", "loud", None]},
        "crowd_level": {
            "type": ["string", "null"],
            "enum": ["empty", "comfortable", "busy", "packed", None],
        },
        "best_time": {"type": ["string", "null"]},
        "recurring_events": {"type": "array", "items": {"type": "string"}},
        "good_for": {"type": "array", "items": {"type": "string"}},
        "sentiment": {"type": "string", "enum": ["positive", "mixed", "negative", "neutral"]},
        "evidence": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"field": {"type": "string"}, "quote": {"type": "string"}},
                "required": ["field", "quote"],
            },
        },
        "confidence": {"type": "number"},
    },
    "required": [
        "vibe_tags",
        "noise_level",
        "crowd_level",
        "best_time",
        "recurring_events",
        "good_for",
        "sentiment",
        "evidence",
        "confidence",
    ],
}


def _norm_quote(s: str) -> str:
    return " ".join(s.replace("’", "'").replace("“", '"').replace("”", '"').split()).lower()


def evidence_verbatim(evidence: list[dict], text: str) -> bool:
    t = _norm_quote(text)
    return all(_norm_quote(e.get("quote", "")) in t for e in evidence) if evidence else True


GROUNDED_FIELDS = (
    "vibe_tags",
    "noise_level",
    "crowd_level",
    "best_time",
    "recurring_events",
    "good_for",
)


def ground(out: dict, text: str) -> tuple[dict, list[str]]:
    """Drop any grounded field that lacks a verbatim supporting quote. Returns (filtered, dropped_fields)."""
    t = _norm_quote(text)
    supported = {
        e.get("field") for e in out.get("evidence", []) if _norm_quote(e.get("quote", "")) in t
    }
    dropped = []
    for f in GROUNDED_FIELDS:
        v = out.get(f)
        if (v not in (None, [], "")) and f not in supported:
            out[f] = [] if isinstance(v, list) else None
            dropped.append(f)
    return out, dropped


def run_extract_insights(
    limit: int | None,
    sources: list[str] | None,
    only_matched: bool,
    review_ids: list[int] | None = None,
) -> None:
    model = model_name()
    with Run("extract_insights") as run, connect() as conn:
        q = """
            select r.id, r.source, r.venue_name, r.text, r.content_hash, l.venue_id
            from raw_reviews r
            join review_venue_links l on l.raw_review_id = r.id
            left join insights i on i.raw_review_id = r.id and i.model = %s and i.prompt_version = %s
            where (i.id is null or i.content_hash <> r.content_hash)
              and l.decision = any(%s)
              and (%s::text[] is null or r.source = any(%s))
              and (%s::bigint[] is null or r.id = any(%s))
            order by r.id
        """
        decisions = ["matched"] if only_matched else ["matched", "review", "unmatched"]
        rows = conn.execute(
            q, (model, PROMPT_VERSION, decisions, sources, sources, review_ids, review_ids)
        ).fetchall()
        if limit:
            rows = rows[:limit]
        log.info("%d reviews to extract with %s/%s", len(rows), model, PROMPT_VERSION)
        for r in rows:
            t0 = time.time()
            out = extract_json(
                SYSTEM, f"Venue: {r['venue_name']}\n\nReview:\n{r['text'][:4000]}", SCHEMA
            )
            ms = int((time.time() - t0) * 1000)
            verbatim = evidence_verbatim(out.get("evidence", []), r["text"])
            raw = dict(out)
            out, dropped = ground(out, r["text"])
            raw["dropped_fields"] = dropped
            conn.execute(
                """insert into insights (raw_review_id, venue_id, model, prompt_version, content_hash, vibe_tags,
                       noise_level, crowd_level, best_time, recurring_events, good_for, sentiment, evidence,
                       evidence_verbatim, confidence, raw_output, duration_ms, run_id)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   on conflict (raw_review_id, model, prompt_version) do update set
                       venue_id = excluded.venue_id, content_hash = excluded.content_hash,
                       vibe_tags = excluded.vibe_tags, noise_level = excluded.noise_level,
                       crowd_level = excluded.crowd_level, best_time = excluded.best_time,
                       recurring_events = excluded.recurring_events, good_for = excluded.good_for,
                       sentiment = excluded.sentiment, evidence = excluded.evidence,
                       evidence_verbatim = excluded.evidence_verbatim, confidence = excluded.confidence,
                       raw_output = excluded.raw_output, duration_ms = excluded.duration_ms,
                       run_id = excluded.run_id, created_at = now()""",
                (
                    r["id"],
                    r["venue_id"],
                    model,
                    PROMPT_VERSION,
                    r["content_hash"],
                    out["vibe_tags"],
                    out["noise_level"],
                    out["crowd_level"],
                    out["best_time"],
                    out["recurring_events"],
                    out["good_for"],
                    out["sentiment"],
                    Jsonb(out["evidence"]),
                    verbatim,
                    out["confidence"],
                    Jsonb(out),
                    ms,
                    run.id,
                ),
            )
            run.bump("extracted")
            run.bump("evidence_verbatim" if verbatim else "evidence_paraphrased")
            run.bump("fields_dropped", len(dropped))
            run.stats["ms_total"] = run.stats.get("ms_total", 0) + ms
            if run.stats["extracted"] % 25 == 0:
                log.info("progress: %s", run.stats)
        log.info("extract_insights done: %s", run.stats)
