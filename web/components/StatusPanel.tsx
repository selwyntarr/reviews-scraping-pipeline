"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useTheme } from "./ThemeShell";

type Row = { stage: string; run_id: number | null; status: string; started_at: string | null; finished_at: string | null;
  stats: Record<string, number> | null; error: string | null; units_done: number; last_unit_at: string | null; is_running: boolean; runs: number };
type Counts = Record<string, number>;
type Sched = { run_at: string; next_run_at: string | null; status: string; note: string | null; updated_at: string };

type StageDef = { n: string; stage: string; label: string; total?: (c: Counts) => number | null; done?: (c: Counts) => number;
  what: string; in: string; out: string; resume: string };

const STAGES: StageDef[] = [
  { n: "1", stage: "discover", label: "pull OSM + DOHMH venues into raw_venues",
    what: "Asks two open sources for every bar, pub, restaurant, cafe and nightclub in Manhattan. OpenStreetMap comes through the Overpass API as a bounding box clipped to the borough polygon; the NYC health-inspection dataset comes through the Socrata API, one row per licensed establishment.",
    in: "Overpass API, Socrata API", out: "raw_venues (whole payload as JSON, content hash, never edited afterwards)",
    resume: "One unit per amenity type (OSM) and per 5,000-row page (DOHMH). A rerun skips finished units; a re-pull only touches rows whose payload hash changed." },
  { n: "2", stage: "dedupe", label: "merge into canonical venues",
    what: "Turns the two feeds into one venue each. Names lose apostrophes, corporate suffixes and store numbers; streets are canonicalised ('WEST 23 STREET' and 'West 23rd Street' both become 'w 23 st'); phones become digits. Records are compared only within the same 150 m geohash cell, scored on name, address, distance and phone, and merged when the score clears 0.80. Same-source duplicates (the inspection data re-registers a venue under a new license after an ownership change) merge first.",
    in: "raw_venues", out: "venues, venue_sources (which raw rows back each venue), match_candidates (every scored pair with its components, so any merge can be audited)",
    resume: "A deterministic full rebuild in ~30 s. Venue ids are stable across rebuilds because they derive from the primary source id." },
  { n: "3", stage: "collect_reviews", label: "Infatuation, Wikipedia, Wikivoyage into raw_reviews", total: () => 8142, done: (c) => c.infatuation_units,
    what: "Gathers prose about venues from three open sources: The Infatuation's review pages (found through its sitemap, parsed from the server-rendered JSON), Wikipedia articles in the Manhattan restaurant, bar and nightclub categories, and the eat/drink listings on Wikivoyage's district pages. Each row keeps the venue name, address, coordinates and any tags the source offers alongside the text.",
    in: "theinfatuation.com, en.wikipedia.org, en.wikivoyage.org", out: "raw_reviews (text plus venue fields, content hash)",
    resume: "One unit per page, category or district. Dead links are recorded so they are not retried; a rerun fetches only what is missing." },
  { n: "3r", stage: "collect_text", label: "Reddit (blocked: needs API credentials)",
    what: "Would search r/AskNYC, r/FoodNYC and r/nycbars for venue chatter and store whole comment trees. The code and tables exist; Reddit refuses anonymous access from this network, so it needs an API app's credentials to run.",
    in: "Reddit official API", out: "raw_posts, raw_comments", resume: "One unit per search and per post." },
  { n: "5", stage: "match_reviews", label: "link reviews to venues",
    what: "Attaches each collected review to a canonical venue using the same blocking and scoring as dedupe, run against the venues table. Rows outside the Manhattan polygon are marked as such; rows scoring between 0.70 and 0.80 are held for review rather than linked; closed venues that no longer exist in either venue feed stay unmatched.",
    in: "raw_reviews, venues", out: "review_venue_links (decision plus score components per review)",
    resume: "Deterministic; reruns in seconds whenever collection grows." },
  { n: "6", stage: "extract_insights", label: "LLM insight extraction", total: (c) => c.reviews_matched, done: (c) => c.insights,
    what: "Sends each matched review to the local model (Qwen 2.5 7B through Ollama) with a JSON schema: vibe tags from a 25-word vocabulary, noise and crowd level, best time, recurring events, good-for, sentiment, confidence, and one verbatim quote per field. The pipeline then checks every quote against the source text and drops any field without one, recording what it dropped. Prompt versions live side by side so a new prompt can be compared row for row.",
    in: "raw_reviews joined to review_venue_links", out: "insights (one row per review, model and prompt version); venue_profiles view aggregates them per venue",
    resume: "One unit per review. Only reviews with no result for the current prompt, or whose text hash changed, are processed. About 25 s per review on a laptop." },
  { n: "7", stage: "review_sample", label: "human / Claude review loop",
    what: "Measures the model instead of trusting it. A sample of extractions is judged against its source text, per field, by a reviewer (Claude in a session, then a human spot-check) on this site's review page or in a markdown file. Verdicts are stored per reviewer, so disagreement between reviewers is itself visible. The first pass found the model inferring 'upscale' from awards rather than descriptions, which produced prompt v3.",
    in: "insights, raw_reviews", out: "extraction_reviews; the scorecard command reports precision per field, verbatim-evidence rate and grounding drops",
    resume: "Samples skip insights the reviewer has already judged." },
  { n: "8", stage: "freshness", label: "nightly TTL re-pull and re-extract",
    what: "Keeps the data current without babysitting. Progress markers older than each source's TTL (inspections 7 days, wiki 14, OSM and Infatuation 30) are expired, the collectors rerun and re-fetch only those units, changed rows are relinked and re-extracted, and claim scores are recomputed. The scheduler container runs it daily.",
    in: "stage_progress, all sources", out: "updated raw tables, insights and scores",
    resume: "Composed of the resumable stages above; --force expires everything." },
  { n: "9", stage: "claim_readiness", label: "claim-readiness scoring",
    what: "Ranks venues by how worthwhile a business-claim outreach would be: how much the profile already says (insight richness), whether the venue is demonstrably active (a recent inspection), whether there is a website or phone to reach it, and how many sources corroborate it. The components are stored, so the ranking is explainable.",
    in: "venues, venue_profiles, review_venue_links", out: "claim_readiness (score 0–1 plus components)",
    resume: "Deterministic full rebuild." },
];

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const ago = (iso: string | null) => { if (!iso) return ""; const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000); return m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`; };

export function StatusPanel() {
  const { mode, toggle } = useTheme();
  const [rows, setRows] = useState<Row[]>([]);
  const [counts, setCounts] = useState<Counts>({});
  const [sched, setSched] = useState<Sched | null>(null);
  const [tick, setTick] = useState(0);
  const [open, setOpen] = useState<string | null>(null);
  useEffect(() => {
    supabase.from("pipeline_status").select("*").then(({ data }) => setRows((data ?? []) as Row[]));
    supabase.from("pipeline_counts").select("*").single().then(({ data }) => setCounts((data ?? {}) as Counts));
    supabase.from("scheduler_state").select("*").maybeSingle().then(({ data }) => setSched((data as Sched) ?? null));
    const t = setTimeout(() => setTick((x) => x + 1), 30000); return () => clearTimeout(t);
  }, [tick]);
  const byStage = new Map(rows.map((r) => [r.stage, r]));
  const mark = (r: Row | undefined) => !r || r.status === "never" ? "[ ]" : r.is_running ? "[~]" : r.status === "succeeded" ? "[x]" : "[!]";

  return (
    <div className="status">
      <div className="toolbar" style={{ margin: "0 0 16px" }}>
        <label className="field text"><span>&nbsp;</span><span className="brand">Pipeline status</span></label>
        <label className="field"><span>&nbsp;</span><Link href="/" className="control">← Explorer</Link></label>
        <label className="field"><span>&nbsp;</span><Link href="/review" className="control">Review</Link></label>
        <label className="field text grow"><span>&nbsp;</span><span className="stat">refreshes every 30 s</span></label>
        <label className="field"><span>&nbsp;</span><button className="control icon" onClick={toggle}>{mode === "dark" ? "☀︎" : "☾"}</button></label>
      </div>

      <ul className="stages">
        {STAGES.map((s) => {
          const r = byStage.get(s.stage);
          const total = s.total?.(counts) ?? null; const done = s.done?.(counts) ?? null;
          const pct = total && done != null ? Math.min(100, Math.round((done / total) * 100)) : null;
          return (
            <li key={s.stage} className={r?.is_running ? "running" : r?.status === "failed" ? "failed" : ""}>
              <code className="mark">{mark(r)}</code>
              <div className="stage-main">
                <div><code className="name">{s.n.padStart(2, " ")} {s.stage}</code> <span className="label">{s.label}</span></div>
                <div className="stat">
                  {r && r.status !== "never" ? <>{r.status}{r.is_running ? " now" : ""} · last run {fmt(r.started_at)} ({ago(r.started_at)}) · {r.runs} run{r.runs === 1 ? "" : "s"} · {r.units_done.toLocaleString()} units</> : "not run yet"}
                  {r?.error ? <> · <span className="err">{r.error.slice(0, 120)}</span></> : null}
                </div>
                {pct != null && <div className="progress"><div className="bar"><i style={{ width: `${pct}%` }} /></div><code className="pct">{done?.toLocaleString()} / {total?.toLocaleString()} · {pct}%</code></div>}
                <button className="link explain" onClick={() => setOpen(open === s.stage ? null : s.stage)}>{open === s.stage ? "hide" : "what this stage does"}</button>
                {open === s.stage && (
                  <div className="explain-body">
                    <p>{s.what}</p>
                    <dl><dt>reads</dt><dd><code>{s.in}</code></dd><dt>writes</dt><dd><code>{s.out}</code></dd><dt>rerun</dt><dd>{s.resume}</dd></dl>
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      <h5 className="counts-head">scheduler</h5>
      <ul className="stages">
        <li className={sched?.status === "running" ? "running" : ""}>
          <code className="mark">{sched ? (sched.status === "running" ? "[~]" : "[x]") : "[ ]"}</code>
          <div className="stage-main">
            <div><code className="name">   scheduler</code> <span className="label">runs <code>freshness</code> daily{sched ? ` at ${sched.run_at}` : ""}</span></div>
            <div className="stat">{sched ? <>{sched.status} · next run {fmt(sched.next_run_at)} · heartbeat {ago(sched.updated_at)}{sched.note ? ` · ${sched.note}` : ""}</> : "scheduler container not running"}</div>
          </div>
        </li>
      </ul>

      <h5 className="counts-head">tables</h5>
      <ul className="counts">
        {(["raw_venues", "venues", "raw_reviews", "reviews_matched", "insights", "verdicts", "claims_scored"] as const).map((k) => (
          <li key={k}><code className="name">{k}</code><code className="num">{(counts[k] ?? 0).toLocaleString()}</code></li>
        ))}
      </ul>
    </div>
  );
}
