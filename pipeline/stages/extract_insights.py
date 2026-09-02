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

PROMPT_VERSION = "v1"

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
- noise_level / crowd_level: only if the text describes sound or how busy it gets; else null.
- best_time: the moment the text recommends or warns about (a day, time, season, "before 7pm", "weekday lunch"); else null.
- recurring_events: regular happenings the text names (live jazz Tuesdays, trivia night, happy hour 4-7); else [].
- good_for: occasions the text recommends it for (date night, big groups, solo lunch, kids, work meetings); else [].
- sentiment: the reviewer's overall verdict.
- evidence: for EVERY non-null field and non-empty list, one item whose quote is an exact, character-for-character
  substring of the review text. Do not paraphrase, shorten with ellipses, or fix typos. If you cannot quote it,
  leave the field null/empty instead.
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
        "sentiment": {"type": "string", "enum": ["positive", "mixed", "negative"]},
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


def run_extract_insights(limit: int | None, sources: list[str] | None, only_matched: bool) -> None:
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
            order by r.id
        """
        decisions = ["matched"] if only_matched else ["matched", "review", "unmatched"]
        rows = conn.execute(q, (model, PROMPT_VERSION, decisions, sources, sources)).fetchall()
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
            run.stats["ms_total"] = run.stats.get("ms_total", 0) + ms
            if run.stats["extracted"] % 25 == 0:
                log.info("progress: %s", run.stats)
        log.info("extract_insights done: %s", run.stats)
