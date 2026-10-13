import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../App";
import type { AuditEntry, CountItem, Flag, GeneratedItem, Rule, Run, StageMatrix } from "../types";
import { fmtM } from "../util";

/** Where a generated line came from, linked to the drawing when it's a run or a counted item. */
function useSources(jobId: number) {
  const [runs, setRuns] = useState<Map<number, Run>>(new Map());
  const [counts, setCounts] = useState<Map<number, CountItem>>(new Map());
  useEffect(() => {
    api.get<Run[]>(`/api/jobs/${jobId}/runs`).then((r) => setRuns(new Map(r.map((x) => [x.id, x]))));
    api.get<CountItem[]>(`/api/jobs/${jobId}/counts`).then((c) => setCounts(new Map(c.map((x) => [x.id, x]))));
  }, [jobId]);
  return (ref: string) => {
    const [kind, id] = ref.split(":");
    if (kind === "run" && runs.get(Number(id))) {
      const r = runs.get(Number(id))!;
      return <Link to={`/sheets/${r.sheet_id}?run=${r.id}`}>Run #{id}</Link>;
    }
    if (kind === "count" && counts.get(Number(id))) {
      const c = counts.get(Number(id))!;
      return <Link to={`/sheets/${c.sheet_id}?count=${c.id}`}>{c.item_type} #{id}</Link>;
    }
    return <span className="muted">{ref === "job" ? "Whole job" : ref === "manual" ? "Added by hand" : ref}</span>;
  };
}

export function Fittings({ jobId, locked }: { jobId: number; locked: boolean }) {
  const { settings } = useApp();
  const [items, setItems] = useState<GeneratedItem[]>([]);
  const [rules, setRules] = useState<Map<number, Rule>>(new Map());
  const [disclaimer, setDisclaimer] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [view, setView] = useState<"lines" | "summary">("lines");
  const [summary, setSummary] = useState<{ stage: string; service_code: string; description: string; uom: string; qty: number; lines: number }[]>([]);
  const [manual, setManual] = useState({ description: "", uom: "ea", qty: "", stage_id: "" });
  const source = useSources(jobId);
  const svc = useMemo(() => new Map(settings.services.map((s) => [s.id, s])), [settings.services]);

  const load = useCallback(async () => {
    setItems(await api.get<GeneratedItem[]>(`/api/jobs/${jobId}/generated`));
    const s = await api.get<{ rows: typeof summary; disclaimer: string }>(`/api/jobs/${jobId}/fittings-summary`);
    setSummary(s.rows);
    setDisclaimer(s.disclaimer);
  }, [jobId]);
  useEffect(() => {
    load();
    api.get<Rule[]>("/api/rules").then((r) => setRules(new Map(r.map((x) => [x.id, x]))));
  }, [load]);

  const generate = async () => {
    setError(""); setMsg("");
    try {
      const r = await api.post<{ lines: number; rules: number; errors: { rule: string; error: string }[]; dropped_overrides: number }>(`/api/jobs/${jobId}/generate`);
      setMsg(`${r.lines} lines from ${r.rules} active rules.` +
        (r.dropped_overrides ? ` ${r.dropped_overrides} overridden line(s) no longer apply and were removed.` : ""));
      if (r.errors.length) setError(r.errors.map((e) => `${e.rule}: ${e.error}`).join(" · "));
      await load();
    } catch (e) { setError((e as Error).message); }
  };
  const patch = async (g: GeneratedItem, body: object) => {
    try { await api.patch(`/api/generated/${g.id}`, body); await load(); } catch (e) { setError((e as Error).message); }
  };
  const addManual = async () => {
    try {
      await api.post(`/api/jobs/${jobId}/generated`, { description: manual.description, uom: manual.uom, qty: Number(manual.qty),
        stage_id: manual.stage_id ? Number(manual.stage_id) : null });
      setManual({ description: "", uom: "ea", qty: "", stage_id: "" });
      await load();
    } catch (e) { setError((e as Error).message); }
  };

  const sorted = [...items].sort((a, b) => (a.stage_id ?? 999) - (b.stage_id ?? 999) || a.description.localeCompare(b.description));

  return (
    <section className="card">
      <div className="row wrap">
        <button className="primary" disabled={locked} onClick={generate}>Generate from rules</button>
        <span className="muted small">Uses confirmed runs and counts on current sheets. Your overrides and notes are kept.</span>
        <span className="spacer" />
        <div className="tabs compact">
          <button className={view === "lines" ? "active" : ""} onClick={() => setView("lines")}>Lines</button>
          <button className={view === "summary" ? "active" : ""} onClick={() => setView("summary")}>Summary by stage</button>
        </div>
      </div>
      {disclaimer && <p className="disclaimer">{disclaimer}</p>}
      {msg && <p className="ok small">{msg}</p>}
      {error && <p className="error">{error}</p>}
      {rules.size === 0 && <p className="warn">No rules yet. An admin adds Peak's fitting and sundry rules under Rules.</p>}

      {view === "summary" ? (
        <table className="num-last">
          <thead><tr><th>Stage</th><th>Service</th><th>Item</th><th>Unit</th><th>Qty</th></tr></thead>
          <tbody>{summary.map((r, i) => <tr key={i}><td>{r.stage}</td><td>{r.service_code}</td><td>{r.description}</td><td>{r.uom}</td><td>{r.qty}</td></tr>)}</tbody>
        </table>
      ) : (
        <table>
          <thead><tr><th>Stage</th><th>Service</th><th>Item</th><th>Unit</th><th>Generated</th><th>Override</th><th>Rule</th><th>Source</th><th>Note</th></tr></thead>
          <tbody>
            {sorted.map((g) => {
              const rule = g.rule_id ? rules.get(g.rule_id) : undefined;
              return (
                <tr key={g.id} className={g.overridden_qty !== null ? "overridden" : ""}>
                  <td>
                    <select disabled={locked} value={g.stage_id ?? ""} onChange={(e) => patch(g, { stage_id: Number(e.target.value) || null })}>
                      <option value="">–</option>
                      {settings.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                    </select>
                  </td>
                  <td>{g.service_id ? svc.get(g.service_id)?.code : ""}</td>
                  <td>{g.description}</td>
                  <td>{g.uom}</td>
                  <td className="numcell">{g.rule_id ? g.qty : "—"}</td>
                  <td>
                    <NumCell disabled={locked} value={g.rule_id ? g.overridden_qty : g.qty}
                      onSave={(v) => patch(g, v === null ? { clear_override: true } : { overridden_qty: v })} />
                  </td>
                  <td className="small">
                    {g.rule_id ? <>{rule?.name ?? `Rule ${g.rule_id}`}{rule && rule.version !== g.rule_version && <span className="warn"> (rule changed: regenerate)</span>}</>
                      : "Manual"}
                    {g.source_qty !== null && <div className="muted">from {Math.round(g.source_qty * 100) / 100}</div>}
                  </td>
                  <td className="small">{source(g.source_ref)}</td>
                  <td><TextCell disabled={locked} value={g.note} onSave={(v) => patch(g, { note: v })} /></td>
                </tr>
              );
            })}
            {!locked && (
              <tr>
                <td>
                  <select value={manual.stage_id} onChange={(e) => setManual({ ...manual, stage_id: e.target.value })}>
                    <option value="">–</option>
                    {settings.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
                  </select>
                </td>
                <td></td>
                <td><input placeholder="Add an item by hand" value={manual.description} onChange={(e) => setManual({ ...manual, description: e.target.value })} /></td>
                <td><input className="tiny" value={manual.uom} onChange={(e) => setManual({ ...manual, uom: e.target.value })} /></td>
                <td></td>
                <td><input className="tiny" type="number" min={0} value={manual.qty} onChange={(e) => setManual({ ...manual, qty: e.target.value })} /></td>
                <td colSpan={3}><button disabled={!manual.description || !(Number(manual.qty) > 0)} onClick={addManual}>Add</button></td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </section>
  );
}

function NumCell({ value, onSave, disabled }: { value: number | null; onSave: (v: number | null) => void; disabled?: boolean }) {
  const [v, setV] = useState(value === null ? "" : String(value));
  useEffect(() => setV(value === null ? "" : String(value)), [value]);
  const commit = () => {
    const next = v.trim() === "" ? null : Number(v);
    if (next !== value && (next === null || !Number.isNaN(next))) onSave(next);
  };
  return <input className="tiny" type="number" min={0} disabled={disabled} placeholder="–" value={v}
    onChange={(e) => setV(e.target.value)} onBlur={commit} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />;
}

function TextCell({ value, onSave, disabled }: { value: string; onSave: (v: string) => void; disabled?: boolean }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return <input className="cell" disabled={disabled} value={v} onChange={(e) => setV(e.target.value)} onBlur={() => v !== value && onSave(v)}
    onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />;
}

const CHECK_NAMES: Record<string, string> = {
  no_measurements: "Sheet not measured", open_end: "Open run end", fixture_unconnected: "Fixture not connected",
  size_jump: "Size jump", scale_mismatch: "Scale mismatch", benchmark: "Benchmark ratio", duplicate_run: "Possible duplicate",
  second_pass: "Second-pass total", unconfirmed: "Unconfirmed items", fittings_missing: "Fittings not generated",
};

export function Checks({ jobId, onChange }: { jobId: number; onChange: () => void }) {
  const [flags, setFlags] = useState<Flag[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showClosed, setShowClosed] = useState(false);
  const load = useCallback(() => api.get<Flag[]>(`/api/jobs/${jobId}/flags`).then(setFlags), [jobId]);
  useEffect(() => { load(); }, [load]);

  const runChecks = async () => {
    setBusy(true); setError("");
    try { setFlags(await api.post<Flag[]>(`/api/jobs/${jobId}/checks`)); onChange(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const setStatus = async (f: Flag, status: Flag["status"], note: string) => {
    setError("");
    try { await api.patch(`/api/flags/${f.id}`, { status, note }); await load(); } catch (e) { setError((e as Error).message); }
  };

  const open = flags.filter((f) => f.status === "open");
  const shown = showClosed ? flags : open;
  return (
    <section className="card">
      <div className="row wrap">
        <button className="primary" disabled={busy} onClick={runChecks}>{busy ? "Checking…" : "Run check-measure"}</button>
        <span className={open.length ? "bad" : "ok"}>{open.length} open</span>
        <span className="muted">· {flags.length - open.length} resolved or accepted</span>
        <span className="spacer" />
        <label className="inline"><input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> Show resolved and accepted</label>
      </div>
      <p className="muted small">Check-measure only flags problems; it never changes quantities. Resolve or accept every flag with a note before sign-off.</p>
      {error && <p className="error">{error}</p>}
      <table>
        <thead><tr><th></th><th>Check</th><th>Message</th><th>Where</th><th>Status</th><th>Note</th><th></th></tr></thead>
        <tbody>
          {shown.map((f) => <FlagRow key={f.id} f={f} onStatus={setStatus} />)}
          {shown.length === 0 && <tr><td colSpan={7} className="muted">{flags.length ? "No open flags." : "Run check-measure to validate this take-off."}</td></tr>}
        </tbody>
      </table>
    </section>
  );
}

function FlagRow({ f, onStatus }: { f: Flag; onStatus: (f: Flag, s: Flag["status"], note: string) => void }) {
  const [note, setNote] = useState(f.note);
  useEffect(() => setNote(f.note), [f.note]);
  const where = f.sheet_id
    ? <Link to={`/sheets/${f.sheet_id}${f.x !== null ? `?x=${f.x}&y=${f.y}` : ""}`}>Show on drawing</Link>
    : <span className="muted">Whole job</span>;
  return (
    <tr className={f.status !== "open" ? "closed" : ""}>
      <td><span className={`badge ${f.severity === "error" ? "bad" : "warn"}`}>{f.severity}</span></td>
      <td className="small">{CHECK_NAMES[f.check_type] ?? f.check_type}</td>
      <td>{f.message}</td>
      <td className="small">{where}</td>
      <td className="small">{f.status}</td>
      <td><input className="cell wide" placeholder="Why it's resolved or accepted" value={note} onChange={(e) => setNote(e.target.value)} /></td>
      <td className="actions">
        {f.status === "open" ? (
          <>
            <button disabled={!note.trim()} onClick={() => onStatus(f, "resolved", note)}>Resolved</button>
            <button disabled={!note.trim()} onClick={() => onStatus(f, "accepted", note)}>Accept</button>
          </>
        ) : <button className="link" onClick={() => onStatus(f, "open", "")}>Reopen</button>}
      </td>
    </tr>
  );
}

export function StageMatrixView({ jobId }: { jobId: number }) {
  const [m, setM] = useState<StageMatrix | null>(null);
  useEffect(() => { api.get<StageMatrix>(`/api/jobs/${jobId}/stage-matrix`).then(setM); }, [jobId]);
  if (!m || m.rows.length === 0) return null;
  return (
    <section className="card">
      <h3>Stage × service (m)</h3>
      <table className="matrix">
        <thead><tr><th>Stage</th>{m.services.map((c) => <th key={c}>{c}</th>)}<th>Total</th></tr></thead>
        <tbody>
          {m.rows.map((r) => (
            <tr key={r.stage}><td>{r.stage}</td>{m.services.map((c) => <td key={c}>{r.cells[c] !== undefined ? fmtM(r.cells[c]) : ""}</td>)}<td><b>{fmtM(r.total_m)}</b></td></tr>
          ))}
          <tr className="total"><td>Total</td>{m.services.map((c) => <td key={c}>{fmtM(m.service_totals[c])}</td>)}<td>{fmtM(m.grand_total_m)}</td></tr>
        </tbody>
      </table>
    </section>
  );
}

export function Audit({ jobId }: { jobId: number }) {
  const [entries, setEntries] = useState<(AuditEntry & { user_name: string })[]>([]);
  useEffect(() => { api.get<(AuditEntry & { user_name: string })[]>(`/api/jobs/${jobId}/audit`).then(setEntries); }, [jobId]);
  return (
    <section className="card">
      <table>
        <thead><tr><th>When</th><th>Who</th><th>What</th><th>Changes</th></tr></thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id}>
              <td className="small nowrap">{new Date(e.at).toLocaleString("en-AU")}</td>
              <td className="small">{e.user_name}</td>
              <td className="small">{e.action} {e.entity.replace("_", " ")} #{e.entity_id}</td>
              <td className="small">{describeChange(e)}</td>
            </tr>
          ))}
          {entries.length === 0 && <tr><td colSpan={4} className="muted">No changes recorded yet.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}

const HIDDEN = new Set(["id", "job_id", "created_at", "created_by", "geometry", "extracted_text", "calibration_data", "verification_data"]);

function describeChange(e: AuditEntry): string {
  if (e.before && e.after) {
    const changed = Object.keys(e.after).filter((k) => !HIDDEN.has(k) && JSON.stringify(e.before![k]) !== JSON.stringify(e.after![k]));
    if (e.before.geometry && JSON.stringify(e.before.geometry) !== JSON.stringify(e.after.geometry)) changed.push("geometry");
    return changed.map((k) => `${k}: ${fmt(e.before![k])} → ${fmt(e.after![k])}`).join("; ");
  }
  const obj = e.after ?? e.before;
  if (!obj) return "";
  const keys = ["description", "name", "item_type", "service_id", "dn", "material", "length_m", "lines", "flags", "open"];
  return keys.filter((k) => k in obj).map((k) => `${k}: ${fmt(obj[k])}`).join("; ");
}

function fmt(v: unknown): string {
  if (v === null || v === undefined || v === "") return "–";
  if (typeof v === "number") return String(Math.round(v * 1000) / 1000);
  if (typeof v === "object") return JSON.stringify(v).slice(0, 60);
  return String(v).slice(0, 60);
}
