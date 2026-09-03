"""Stage 7: human/Claude review loop for extractions.

  pipeline review-sample --n 30           -> reviews/sample_<run>.md with N random insights
  pipeline review-ingest reviews/sample_<run>.md --reviewer claude
                                          -> verdict lines parsed back into extraction_reviews
  pipeline scorecard                      -> precision per field from verdicts + verbatim-evidence rate

Sample file format (one block per insight); the reviewer edits the `verdict:` line and optional
`fields:` / `notes:` lines and leaves everything else alone:

    ### insight 42 · 169 Bar (infatuation)
    verdict: correct | partial | wrong
    fields: vibe_tags=correct good_for=wrong
    notes: ...
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from psycopg.types.json import Jsonb

from ..db import Run, connect

log = logging.getLogger(__name__)

FIELDS = (
    "vibe_tags",
    "noise_level",
    "crowd_level",
    "best_time",
    "recurring_events",
    "good_for",
    "sentiment",
)
BLOCK_RE = re.compile(r"^### insight (\d+) .*?$", re.MULTILINE)


def write_sample(n: int, out_dir: Path, unreviewed_only: bool, prompt_version: str | None = None) -> Path:
    with Run("review_sample") as run, connect() as conn:
        rows = conn.execute(
            """select i.id, i.venue_id, r.source, r.venue_name, r.text, i.vibe_tags, i.noise_level, i.crowd_level,
                      i.best_time, i.recurring_events, i.good_for, i.sentiment, i.evidence, i.evidence_verbatim,
                      i.confidence, i.model, i.prompt_version
               from insights i join raw_reviews r on r.id = i.raw_review_id
               where (%s = false or not exists (select 1 from extraction_reviews e where e.insight_id = i.id))
                 and (%s::text is null or i.prompt_version = %s)
               order by random() limit %s""",
            (unreviewed_only, prompt_version, prompt_version, n),
        ).fetchall()
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"sample_run{run.id}.md"
        lines = [
            f"# Extraction review sample — run {run.id}",
            "",
            f"{len(rows)} insights. For each block set `verdict:` to correct / partial / wrong. Optionally set",
            "`fields:` as space-separated `field=verdict` pairs and add `notes:`. Then run",
            f"`pipeline review-ingest {path} --reviewer <name>`.",
            "",
        ]
        for r in rows:
            ex = {k: r[k] for k in FIELDS}
            lines += [
                f"### insight {r['id']} · {r['venue_name']} ({r['source']}) · {r['model']}/{r['prompt_version']}",
                "",
                "**Source text**",
                "",
                "> " + re.sub(r"\s+", " ", r["text"])[:2500],
                "",
                "**Extraction**",
                "",
                "```json",
                json.dumps(ex, ensure_ascii=False),
                "```",
                "",
                f"evidence_verbatim: {r['evidence_verbatim']} · confidence: {r['confidence']}",
                "",
                "```json",
                json.dumps(r["evidence"], ensure_ascii=False),
                "```",
                "",
                "verdict: ",
                "fields: ",
                "notes: ",
                "",
            ]
        path.write_text("\n".join(lines))
        run.stats["sampled"] = len(rows)
        run.mark_done(f"sample:{path.name}", {"n": len(rows)})
        log.info("wrote %s (%d insights)", path, len(rows))
        return path


def ingest(path: Path, reviewer: str) -> dict:
    text = path.read_text()
    blocks = list(BLOCK_RE.finditer(text))
    counts = {"ingested": 0, "skipped_blank": 0}
    with connect() as conn:
        for i, m in enumerate(blocks):
            body = text[m.end() : blocks[i + 1].start() if i + 1 < len(blocks) else len(text)]
            verdict = (
                (re.search(r"^verdict:\s*(\w*)", body, re.MULTILINE) or [None, ""])[1]
                .strip()
                .lower()
            )
            if verdict not in ("correct", "partial", "wrong"):
                counts["skipped_blank"] += 1
                continue
            fields_line = (re.search(r"^fields:\s*(.*)$", body, re.MULTILINE) or [None, ""])[1]
            field_verdicts = dict(p.split("=", 1) for p in fields_line.split() if "=" in p)
            notes = (re.search(r"^notes:\s*(.*)$", body, re.MULTILINE) or [None, ""])[
                1
            ].strip() or None
            conn.execute(
                """insert into extraction_reviews (insight_id, reviewer, verdict, field_verdicts, notes)
                   values (%s,%s,%s,%s,%s)
                   on conflict (insight_id, reviewer) do update set verdict = excluded.verdict,
                       field_verdicts = excluded.field_verdicts, notes = excluded.notes, reviewed_at = now()""",
                (int(m.group(1)), reviewer, verdict, Jsonb(field_verdicts), notes),
            )
            counts["ingested"] += 1
    log.info("ingested %s: %s", path, counts)
    return counts


def scorecard() -> dict:
    with connect() as conn:
        total = conn.execute(
            "select count(*) n, avg(evidence_verbatim::int) v, avg(confidence) c from insights"
        ).fetchone()
        overall = conn.execute(
            "select reviewer, verdict, count(*) from extraction_reviews group by 1,2 order by 1,2"
        ).fetchall()
        per_field = conn.execute(
            """select reviewer, kv.key as field, kv.value as verdict, count(*)
               from extraction_reviews e, jsonb_each_text(e.field_verdicts) kv group by 1,2,3 order by 1,2,3"""
        ).fetchall()
        dropped = conn.execute(
            "select coalesce(sum(jsonb_array_length(raw_output->'dropped_fields')),0) as n from insights"
        ).fetchone()["n"]
    return {
        "insights": total["n"],
        "evidence_verbatim_rate": round(float(total["v"] or 0), 3),
        "mean_confidence": round(float(total["c"] or 0), 3),
        "fields_dropped_by_grounding": dropped,
        "verdicts": [dict(r) for r in overall],
        "field_verdicts": [dict(r) for r in per_field],
    }
