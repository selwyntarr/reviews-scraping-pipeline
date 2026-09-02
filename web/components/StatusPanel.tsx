"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { useTheme } from "./ThemeShell";

type Row = { stage: string; run_id: number | null; status: string; started_at: string | null; finished_at: string | null;
  stats: Record<string, number> | null; error: string | null; units_done: number; last_unit_at: string | null; is_running: boolean; runs: number };
type Counts = Record<string, number>;
type Sched = { run_at: string; next_run_at: string | null; status: string; note: string | null; updated_at: string };

const STAGES: { n: string; stage: string; label: string; total?: (c: Counts) => number | null; done?: (c: Counts) => number }[] = [
  { n: "1", stage: "discover", label: "pull OSM + DOHMH venues into raw_venues" },
  { n: "2", stage: "dedupe", label: "merge into canonical venues" },
  { n: "3", stage: "collect_reviews", label: "Infatuation, Wikipedia, Wikivoyage into raw_reviews", total: () => 8142, done: (c) => c.infatuation_units },
  { n: "3r", stage: "collect_text", label: "Reddit (blocked: needs API credentials)" },
  { n: "5", stage: "match_reviews", label: "link reviews to venues" },
  { n: "6", stage: "extract_insights", label: "LLM insight extraction", total: (c) => c.reviews_matched, done: (c) => c.insights },
  { n: "7", stage: "review_sample", label: "human / Claude review loop" },
  { n: "8", stage: "freshness", label: "nightly TTL re-pull and re-extract" },
  { n: "9", stage: "claim_readiness", label: "claim-readiness scoring" },
];

const fmt = (iso: string | null) => (iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const ago = (iso: string | null) => { if (!iso) return ""; const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000); return m < 60 ? `${m} min ago` : `${Math.round(m / 60)} h ago`; };

export function StatusPanel() {
  const { mode, toggle } = useTheme();
  const [rows, setRows] = useState<Row[]>([]);
  const [counts, setCounts] = useState<Counts>({});
  const [sched, setSched] = useState<Sched | null>(null);
  const [tick, setTick] = useState(0);
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
