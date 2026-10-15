import { useEffect, useState } from "react";
import { api } from "../api";
import type { Job, SalesSettings, SalesStage, Sector } from "../types";
import { SECTOR_LABELS, STAGE_LABELS } from "../types";

const STEPS: SalesStage[] = ["lead", "quoting", "quote_sent"];
const fmt = (iso?: string | null) => (iso ? new Date(iso + "T00:00:00").toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" }) : "");
const daysBetween = (a?: string | null, b?: string | null) =>
  a && b ? Math.round((new Date(b + "T00:00:00").getTime() - new Date(a + "T00:00:00").getTime()) / 86400000) : null;

/** Where the job is in the sales pipeline, with its dates, value and source. */
export default function SalesPanel({ job, onSaved }: { job: Job; onSaved: () => void }) {
  const [settings, setSettings] = useState<SalesSettings | null>(null);
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState(job.tender_value ? String(job.tender_value) : "");
  const [error, setError] = useState("");
  useEffect(() => { api.get<SalesSettings>("/api/sales/settings").then(setSettings); }, []);
  useEffect(() => setValue(job.tender_value ? String(job.tender_value) : ""), [job.tender_value]);

  const save = async (body: Record<string, unknown>) => {
    setError("");
    try { await api.put(`/api/jobs/${job.id}/sales`, body); onSaved(); } catch (e) { setError((e as Error).message); }
  };
  const stage = job.sales_stage ?? "lead";
  const decided = ["won", "lost", "withdrawn"].includes(stage);
  const reached = (s: SalesStage) => STEPS.indexOf(s) <= STEPS.indexOf(decided ? "quote_sent" : stage);
  const l2q = daysBetween(job.lead_date, job.quote_sent_date);
  const q2d = daysBetween(job.quote_sent_date, job.decided_date);

  return (
    <section className="card sales-panel">
      <div className="row wrap">
        <span className="badge">{SECTOR_LABELS[job.sector ?? "commercial"]}</span>
        <b>{job.quote_no}</b>
        <div className="steps">
          {STEPS.map((s) => (
            <span key={s} className={`step ${reached(s) ? "done" : ""} ${stage === s ? "current" : ""}`}>
              {STAGE_LABELS[s]}
              <small>{s === "lead" ? fmt(job.lead_date) : s === "quote_sent" ? fmt(job.quote_sent_date) : ""}</small>
            </span>
          ))}
          <span className={`step ${decided ? "done current " + stage : ""}`}>
            {decided ? STAGE_LABELS[stage] : "Won / lost"}<small>{fmt(job.decided_date)}</small>
          </span>
        </div>
        <span className="spacer" />
        {!job.quote_sent_date && <button className="primary" onClick={() => save({ mark_quote_sent: true, tender_value: value ? Number(value) : null })}>Mark quote sent</button>}
        {job.quote_sent_date && !decided && (
          <>
            <button className="primary" onClick={() => save({ tender_result: "won" })}>Won it</button>
            <button onClick={() => save({ tender_result: "lost" })}>Lost</button>
          </>
        )}
        <button className="link" onClick={() => setOpen(!open)}>{open ? "Hide details" : "Details"}</button>
      </div>
      <div className="small muted">
        {l2q !== null && <>Quoted {l2q} day{l2q === 1 ? "" : "s"} after the lead came in. </>}
        {q2d !== null && <>{STAGE_LABELS[stage]} {q2d} day{q2d === 1 ? "" : "s"} after the quote went out. </>}
        {job.lead_source && <>Source: {job.lead_source}. </>}
        {job.contact && <>Contact: {job.contact}.</>}
      </div>
      {open && settings && (
        <div className="sales-details">
          <label>Sector
            <select value={job.sector ?? "commercial"} onChange={(e) => save({ sector: e.target.value as Sector })}>
              {settings.sectors.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </label>
          <label>Price quoted (ex GST)
            <input type="number" min={0} value={value} onChange={(e) => setValue(e.target.value)}
                   onBlur={() => save({ tender_value: value ? Number(value) : null })} />
          </label>
          <label>Result
            <select value={job.tender_result ?? "pending"} onChange={(e) => save({ tender_result: e.target.value })}>
              <option value="pending">Pending</option><option value="won">Won</option><option value="lost">Lost</option><option value="withdrawn">Withdrawn</option>
            </select>
          </label>
          <label>Lead came in<input type="date" value={job.lead_date ?? ""} onChange={(e) => e.target.value && save({ lead_date: e.target.value })} /></label>
          <label>Quote sent
            <input type="date" value={job.quote_sent_date ?? ""}
                   onChange={(e) => save(e.target.value ? { quote_sent_date: e.target.value } : { clear_quote_sent: true })} />
          </label>
          <label>Decided<input type="date" value={job.decided_date ?? ""} disabled={!decided}
                               onChange={(e) => e.target.value && save({ decided_date: e.target.value })} /></label>
          <label>Quote due<input type="date" value={job.due_date ?? ""} onChange={(e) => save({ due_date: e.target.value || null })} /></label>
          <label>Lead source
            <input list="sources" defaultValue={job.lead_source ?? ""} onBlur={(e) => e.target.value !== job.lead_source && save({ lead_source: e.target.value })} />
            <datalist id="sources">{settings.lead_sources.map((s) => <option key={s} value={s} />)}</datalist>
          </label>
          <label>Contact<input defaultValue={job.contact ?? ""} onBlur={(e) => e.target.value !== job.contact && save({ contact: e.target.value })} /></label>
        </div>
      )}
      {error && <p className="error small">{error}</p>}
    </section>
  );
}
