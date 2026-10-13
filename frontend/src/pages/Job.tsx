import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, download } from "../api";
import { useApp } from "../App";
import type { Job, Level, Sheet, Totals } from "../types";
import { fmtM } from "../util";

const SHEET_TYPES = ["plan", "section", "detail", "schematic", "legend", "cover", "other"];

export default function JobPage() {
  const { jobId } = useParams();
  const [job, setJob] = useState<Job | null>(null);
  const [tab, setTab] = useState<"sheets" | "levels" | "totals">("sheets");
  const [error, setError] = useState("");

  useEffect(() => { api.get<Job>(`/api/jobs/${jobId}`).then(setJob); }, [jobId]);
  if (!job) return null;

  return (
    <main className="page">
      <div className="row">
        <div>
          <h1>{job.name}</h1>
          <p className="muted">
            {[job.quote_no && `Quote ${job.quote_no}`, job.client, job.builder, job.address, job.due_date && `Due ${job.due_date}`]
              .filter(Boolean).join(" · ")}
          </p>
        </div>
        <span className="spacer" />
        <button onClick={() => download(`/api/jobs/${job.id}/export.xlsx`, "BOQ.xlsx").catch((e) => setError(e.message))}>
          Export Excel BOQ
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      <div className="tabs">
        {(["sheets", "levels", "totals"] as const).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t === "sheets" ? "Sheet register" : t === "levels" ? "Levels" : "Totals"}
          </button>
        ))}
      </div>
      {tab === "sheets" && <SheetRegister jobId={job.id} />}
      {tab === "levels" && <Levels jobId={job.id} />}
      {tab === "totals" && <TotalsView jobId={job.id} />}
    </main>
  );
}

function SheetRegister({ jobId }: { jobId: number }) {
  const { settings } = useApp();
  const [sheets, setSheets] = useState<Sheet[]>([]);
  const [showAll, setShowAll] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(
    () => api.get<Sheet[]>(`/api/jobs/${jobId}/sheets?include_duplicates=${showAll}`).then(setSheets),
    [jobId, showAll],
  );
  useEffect(() => { load(); }, [load]);

  const upload = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    const fd = new FormData();
    Array.from(files).forEach((f) => fd.append("files", f));
    try { await api.post(`/api/jobs/${jobId}/files`, fd); await load(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  const patch = async (s: Sheet, body: Partial<Sheet>) => {
    try {
      await api.patch(`/api/sheets/${s.id}`, body);
      await load(); // sheet number / revision edits can change which sheets are current
    } catch (e) { setError((e as Error).message); }
  };

  const visible = sheets.filter((s) => showAll || s.is_current);

  return (
    <section className="card">
      <div className="row">
        <label className="upload">
          <input type="file" accept="application/pdf" multiple disabled={busy} onChange={(e) => { upload(e.target.files); e.target.value = ""; }} />
          <span className="button primary">{busy ? "Splitting and reading sheets…" : "Upload drawings (PDF)"}</span>
        </label>
        <span className="muted">One combined PDF or many single-page PDFs, up to 200 MB each.</span>
        <span className="spacer" />
        <label className="inline"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} /> Show superseded and duplicate sheets</label>
      </div>
      {error && <p className="error">{error}</p>}
      <table className="register">
        <thead>
          <tr>
            <th>Sheet no.</th><th>Title</th><th>Rev</th><th>Type</th><th>Services</th><th>Hydraulic</th>
            <th>Page</th><th>Stated scale</th><th>Scale</th><th>Confirmed</th><th></th>
          </tr>
        </thead>
        <tbody>
          {visible.map((s) => (
            <tr key={s.id} className={!s.is_current ? "superseded" : ""}>
              <td><EditCell value={s.sheet_no} onSave={(v) => patch(s, { sheet_no: v })} /></td>
              <td><EditCell value={s.title} onSave={(v) => patch(s, { title: v })} wide /></td>
              <td><EditCell value={s.revision} onSave={(v) => patch(s, { revision: v })} /></td>
              <td>
                <select value={s.classification} onChange={(e) => patch(s, { classification: e.target.value })}>
                  {SHEET_TYPES.map((t) => <option key={t}>{t}</option>)}
                </select>
                <div className="muted small">{Math.round(s.confidence * 100)}% sure</div>
              </td>
              <td>
                <EditCell value={(s.services_shown ?? []).join(", ")}
                  onSave={(v) => patch(s, { services_shown: v.split(",").map((x) => x.trim().toUpperCase()).filter(Boolean) })} />
              </td>
              <td><input type="checkbox" checked={s.is_hydraulic} onChange={(e) => patch(s, { is_hydraulic: e.target.checked })} /></td>
              <td>{s.page_size}{!s.has_text_layer && <div className="warn small">No text layer</div>}</td>
              <td><EditCell value={s.stated_scale} onSave={(v) => patch(s, { stated_scale: v })} /></td>
              <td>{s.scale_verified ? <span className="ok">Verified</span> : s.calibrated_scale ? <span className="warn">Not verified</span> : <span className="bad">Not set</span>}</td>
              <td><input type="checkbox" checked={s.confirmed} onChange={(e) => patch(s, { confirmed: e.target.checked })} /></td>
              <td>
                {s.is_duplicate ? <span className="muted">Duplicate</span>
                  : !s.is_current ? <span className="muted">Superseded</span>
                  : <Link to={`/sheets/${s.id}`}>Open</Link>}
              </td>
            </tr>
          ))}
          {visible.length === 0 && <tr><td colSpan={11} className="muted">No sheets yet. Upload drawings to start.</td></tr>}
        </tbody>
      </table>
      <p className="muted small">Service codes: {settings.services.map((s) => s.code).join(", ")}</p>
    </section>
  );
}

function EditCell({ value, onSave, wide }: { value: string; onSave: (v: string) => void; wide?: boolean }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  return (
    <input className={wide ? "cell wide" : "cell"} value={v} onChange={(e) => setV(e.target.value)}
      onBlur={() => v !== value && onSave(v)} onKeyDown={(e) => e.key === "Enter" && (e.target as HTMLInputElement).blur()} />
  );
}

function Levels({ jobId }: { jobId: number }) {
  const [levels, setLevels] = useState<Level[]>([]);
  const [form, setForm] = useState({ name: "", rl: "", floor_to_floor_m: "" });
  const [error, setError] = useState("");
  const load = useCallback(() => api.get<Level[]>(`/api/jobs/${jobId}/levels`).then(setLevels), [jobId]);
  useEffect(() => { load(); }, [load]);

  const add = async () => {
    setError("");
    try {
      await api.post(`/api/jobs/${jobId}/levels`, { name: form.name, rl: Number(form.rl || 0), floor_to_floor_m: Number(form.floor_to_floor_m || 0) });
      setForm({ name: "", rl: "", floor_to_floor_m: "" });
      load();
    } catch (e) { setError((e as Error).message); }
  };
  const save = async (l: Level, body: Partial<Level>) => {
    try { await api.put(`/api/levels/${l.id}`, { ...l, ...body }); load(); } catch (e) { setError((e as Error).message); }
  };

  return (
    <section className="card narrow">
      <p className="muted">Level-based verticals (risers, stacks) add up the floor-to-floor heights between two levels.</p>
      <table>
        <thead><tr><th>Level</th><th>RL (m)</th><th>Floor to floor (m)</th><th></th></tr></thead>
        <tbody>
          {levels.map((l) => (
            <tr key={l.id}>
              <td><EditCell value={l.name} onSave={(v) => save(l, { name: v })} /></td>
              <td><EditCell value={String(l.rl)} onSave={(v) => save(l, { rl: Number(v) })} /></td>
              <td><EditCell value={String(l.floor_to_floor_m)} onSave={(v) => save(l, { floor_to_floor_m: Number(v) })} /></td>
              <td><button className="link" onClick={() => api.del(`/api/levels/${l.id}`).then(load)}>Delete</button></td>
            </tr>
          ))}
          <tr>
            <td><input className="cell" placeholder="e.g. Level 1" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></td>
            <td><input className="cell" type="number" step="0.01" value={form.rl} onChange={(e) => setForm({ ...form, rl: e.target.value })} /></td>
            <td><input className="cell" type="number" step="0.01" value={form.floor_to_floor_m} onChange={(e) => setForm({ ...form, floor_to_floor_m: e.target.value })} /></td>
            <td><button onClick={add} disabled={!form.name}>Add</button></td>
          </tr>
        </tbody>
      </table>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

export function TotalsView({ jobId, compact }: { jobId: number; compact?: boolean }) {
  const [t, setT] = useState<Totals | null>(null);
  useEffect(() => { api.get<Totals>(`/api/jobs/${jobId}/totals`).then(setT); }, [jobId]);
  if (!t) return null;
  return <TotalsTables t={t} compact={compact} />;
}

export function TotalsTables({ t, compact }: { t: Totals; compact?: boolean }) {
  const ex = t.excluded;
  return (
    <section className={compact ? "" : "card"}>
      <table className="num">
        <thead><tr><th>Service</th><th>DN</th><th>Material</th><th>Plan</th><th>Vertical</th><th>Waste</th><th>Total (m)</th></tr></thead>
        <tbody>
          {t.lines.map((l) => (
            <tr key={`${l.service_code}-${l.dn}-${l.material}`}>
              <td><span className="swatch" style={{ background: l.colour }} />{l.service_code}</td>
              <td>{l.dn}</td><td>{l.material}</td>
              <td>{fmtM(l.plan_m)}</td><td>{fmtM(l.vertical_m)}</td><td>{fmtM(l.waste_m)}</td><td><b>{fmtM(l.total_m)}</b></td>
            </tr>
          ))}
          <tr className="total"><td colSpan={6}>Total</td><td>{fmtM(t.grand_total_m)}</td></tr>
        </tbody>
      </table>
      {!compact && (
        <>
          <h3>By stage</h3>
          <table className="num">
            <thead><tr><th>Stage</th><th>Service</th><th>Total (m)</th></tr></thead>
            <tbody>{t.stages.map((s) => <tr key={`${s.stage}-${s.service_code}`}><td>{s.stage}</td><td>{s.service_code}</td><td>{fmtM(s.total_m)}</td></tr>)}</tbody>
          </table>
        </>
      )}
      <h3>Counts</h3>
      <table className="num">
        <thead><tr><th>Service</th><th>Item</th>{!compact && <th>Stage</th>}<th>Qty</th></tr></thead>
        <tbody>{t.counts.map((c) => <tr key={`${c.service_code}-${c.item_type}-${c.stage}`}><td>{c.service_code}</td><td>{c.item_type}</td>{!compact && <td>{c.stage}</td>}<td>{c.qty}</td></tr>)}</tbody>
      </table>
      {(ex.suggested_runs > 0 || ex.suggested_counts > 0 || ex.superseded_runs > 0) && (
        <p className="warn small">
          Not in totals: {ex.suggested_runs} unconfirmed runs, {ex.suggested_counts} unconfirmed counts, {ex.superseded_runs} runs on superseded sheets.
        </p>
      )}
    </section>
  );
}
