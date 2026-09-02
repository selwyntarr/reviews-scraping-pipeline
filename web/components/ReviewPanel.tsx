"use client";
import { useEffect, useMemo, useState } from "react";
import { supabase } from "@/lib/supabase";
import { SOURCE_LABEL } from "@/lib/vocab";
import { useTheme } from "./ThemeShell";

type Verdict = "correct" | "partial" | "wrong";
type Item = {
  insight_id: number; venue_id: number | null; venue_name: string | null; source: string; url: string | null; text: string;
  model: string; prompt_version: string; vibe_tags: string[]; noise_level: string | null; crowd_level: string | null;
  best_time: string | null; recurring_events: string[]; good_for: string[]; sentiment: string; confidence: number;
  evidence: { field: string; quote: string }[]; evidence_verbatim: boolean; dropped_fields: string[] | null;
  verdicts: Record<string, { verdict: Verdict; fields: Record<string, Verdict>; notes: string | null }>;
};
const FIELDS = ["vibe_tags", "noise_level", "crowd_level", "best_time", "recurring_events", "good_for", "sentiment"] as const;
const REVIEWER_KEY = "reviewer";

export function ReviewPanel() {
  const { mode, toggle } = useTheme();
  const [reviewer, setReviewer] = useState("selwyn");
  const [items, setItems] = useState<Item[]>([]);
  const [idx, setIdx] = useState(0);
  const [only, setOnly] = useState<"unreviewed" | "all" | "disagree">("unreviewed");
  const [version, setVersion] = useState<string>("");
  const [fields, setFields] = useState<Record<string, Verdict>>({});
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { try { const r = localStorage.getItem(REVIEWER_KEY); if (r) setReviewer(r); } catch {} }, []);
  useEffect(() => { try { localStorage.setItem(REVIEWER_KEY, reviewer); } catch {} }, [reviewer]);

  const load = () => supabase.from("review_queue").select("*").order("insight_id", { ascending: false }).limit(1000)
    .then(({ data, error }) => { if (error) setError(error.message); else setItems((data ?? []) as Item[]); });
  useEffect(() => { load(); }, []);

  const versions = useMemo(() => Array.from(new Set(items.map((i) => i.prompt_version))).sort(), [items]);
  const queue = useMemo(() => items.filter((i) => {
    if (version && i.prompt_version !== version) return false;
    const mine = i.verdicts?.[reviewer];
    if (only === "unreviewed") return !mine;
    if (only === "disagree") { const others = Object.entries(i.verdicts ?? {}).filter(([r]) => r !== reviewer); return !!mine && others.some(([, v]) => v.verdict !== mine.verdict); }
    return true;
  }), [items, only, version, reviewer]);
  const cur = queue[Math.min(idx, Math.max(queue.length - 1, 0))];

  useEffect(() => { const mine = cur?.verdicts?.[reviewer]; setFields(mine?.fields ?? {}); setNotes(mine?.notes ?? ""); }, [cur?.insight_id, reviewer]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async (verdict: Verdict) => {
    if (!cur) return;
    setSaving(true); setError(null);
    const { error } = await supabase.from("extraction_reviews").upsert(
      { insight_id: cur.insight_id, reviewer, verdict, field_verdicts: fields, notes: notes || null, reviewed_at: new Date().toISOString() },
      { onConflict: "insight_id,reviewer" });
    setSaving(false);
    if (error) { setError(error.message); return; }
    setItems((all) => all.map((i) => i.insight_id === cur.insight_id ? { ...i, verdicts: { ...i.verdicts, [reviewer]: { verdict, fields, notes } } } : i));
    if (only === "unreviewed") setIdx((k) => Math.min(k, Math.max(queue.length - 2, 0))); else setIdx((k) => Math.min(k + 1, queue.length - 1));
  };

  const highlight = (text: string, quotes: string[]) => {
    let parts: (string | { q: string })[] = [text];
    for (const q of quotes.filter(Boolean)) {
      parts = parts.flatMap((p) => typeof p !== "string" ? [p] : p.split(q).flatMap((s, i, a) => i < a.length - 1 ? [s, { q }] : [s]));
    }
    return parts.map((p, i) => typeof p === "string" ? <span key={i}>{p}</span> : <mark key={i}>{p.q}</mark>);
  };

  const stats = useMemo(() => {
    const mine = items.filter((i) => i.verdicts?.[reviewer]);
    const c = { correct: 0, partial: 0, wrong: 0 } as Record<Verdict, number>;
    mine.forEach((i) => { c[i.verdicts[reviewer].verdict]++; });
    return { reviewed: mine.length, ...c };
  }, [items, reviewer]);

  return (
    <div className="review">
      <div className="toolbar" style={{ margin: "0 0 12px" }}>
        <label className="field text"><span>&nbsp;</span><span className="brand">Extraction review</span></label>
        <label className="field"><span>&nbsp;</span><a href="/" className="control">← Explorer</a></label>
        <label className="field text grow"><span>&nbsp;</span><span className="stat">{items.length} insights · queue {queue.length} · you: {stats.reviewed} reviewed ({stats.correct} correct · {stats.partial} partial · {stats.wrong} wrong)</span></label>
        <label className="field"><span>Reviewer</span><input value={reviewer} onChange={(e) => setReviewer(e.target.value.trim() || "selwyn")} className="control" style={{ width: 110 }} /></label>
        <label className="field"><span>Queue</span><select value={only} onChange={(e) => { setOnly(e.target.value as typeof only); setIdx(0); }}>
          <option value="unreviewed">unreviewed by me</option><option value="all">all</option><option value="disagree">where I disagree with others</option>
        </select></label>
        <label className="field"><span>Prompt</span><select value={version} onChange={(e) => { setVersion(e.target.value); setIdx(0); }}>
          <option value="">any prompt</option>{versions.map((v) => <option key={v} value={v}>{v}</option>)}
        </select></label>
        <label className="field"><span>&nbsp;</span><button className="control icon" onClick={toggle}>{mode === "dark" ? "☀︎" : "☾"}</button></label>
      </div>
      {error && <div className="empty">Error: {error}</div>}
      {!cur && !error && <div className="empty">Nothing in this queue.</div>}
      {cur && (
        <div className="review-grid">
          <section className="pane">
            <h2>{cur.venue_name ?? "(unlinked venue)"}</h2>
            <div className="meta">{SOURCE_LABEL[cur.source] ?? cur.source}{cur.url && <> · <a href={cur.url} target="_blank" rel="noreferrer">source</a></>} · insight #{cur.insight_id} · {cur.model}/{cur.prompt_version}</div>
            <h5>Source text (evidence highlighted)</h5>
            <p className="text">{highlight(cur.text, (cur.evidence ?? []).map((e) => e.quote))}</p>
          </section>
          <section className="pane">
            <div className="nav">
              <button className="chip" disabled={idx <= 0} onClick={() => setIdx((k) => k - 1)}>‹ prev</button>
              <span className="stat">{Math.min(idx + 1, queue.length)} / {queue.length}</span>
              <button className="chip" disabled={idx >= queue.length - 1} onClick={() => setIdx((k) => k + 1)}>next ›</button>
            </div>
            <h5>Extraction</h5>
            <table className="fields"><tbody>
              {FIELDS.map((f) => {
                const v = (cur as unknown as Record<string, unknown>)[f];
                const shown = Array.isArray(v) ? (v.length ? v.join(", ") : "—") : (v ?? "—");
                const fv = fields[f];
                return (
                  <tr key={f}><th>{f}</th><td>{String(shown)}</td>
                    <td className="fv">{(["correct", "partial", "wrong"] as Verdict[]).map((x) => (
                      <button key={x} className={`chip ${x}${fv === x ? " on" : ""}`} onClick={() => setFields((s) => ({ ...s, [f]: s[f] === x ? undefined as unknown as Verdict : x }))}>{x[0]}</button>
                    ))}</td>
                  </tr>);
              })}
            </tbody></table>
            <h5>Evidence · verbatim: {cur.evidence_verbatim ? "yes" : "no"} · confidence {cur.confidence}{cur.dropped_fields?.length ? ` · dropped by grounding: ${cur.dropped_fields.join(", ")}` : ""}</h5>
            {(cur.evidence ?? []).map((e, i) => <div key={i} className="quote">“{e.quote}”<small>{e.field}</small></div>)}
            {Object.entries(cur.verdicts ?? {}).filter(([r]) => r !== reviewer).map(([r, v]) => (
              <div key={r} className="other"><b>{r}</b> said <b>{v.verdict}</b>{v.notes ? <> — {v.notes}</> : null}</div>
            ))}
            <h5>Your verdict</h5>
            <textarea className="notes" placeholder="notes (optional)" value={notes} onChange={(e) => setNotes(e.target.value)} />
            <div className="verdicts">
              <button className="chip correct on" disabled={saving} onClick={() => save("correct")}>correct</button>
              <button className="chip partial on" disabled={saving} onClick={() => save("partial")}>partial</button>
              <button className="chip wrong on" disabled={saving} onClick={() => save("wrong")}>wrong</button>
              {cur.verdicts?.[reviewer] && <span className="stat">saved: {cur.verdicts[reviewer].verdict}</span>}
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
