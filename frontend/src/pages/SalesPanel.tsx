import { useEffect, useState } from "react";
import { api } from "../api";
import type { ClientChoice, Job, SalesSettings, SalesStage, Sector } from "../types";
import { SECTOR_LABELS, STAGE_LABELS } from "../types";
import { clientNames } from "./Home";
import { Chips, DateChips, PickOrNew, daysFromToday } from "./Pick";

const STEPS: SalesStage[] = ["lead", "quoting", "quote_sent"];
const fmt = (iso?: string | null) => (iso ? new Date(iso + "T00:00:00").toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" }) : "");
const daysBetween = (a?: string | null, b?: string | null) =>
  a && b ? Math.round((new Date(b + "T00:00:00").getTime() - new Date(a + "T00:00:00").getTime()) / 86400000) : null;
const withCurrent = (list: string[], v?: string) => (v && !list.includes(v) ? [...list, v] : list);

/** Where the job is in the sales pipeline, with its dates, value and source. Answers are picked, not typed. */
export default function SalesPanel({ job, onSaved }: { job: Job; onSaved: () => void }) {
  const [settings, setSettings] = useState<SalesSettings | null>(null);
  const [clients, setClients] = useState<ClientChoice[]>([]);
  const [open, setOpen] = useState(false);
  const [asking, setAsking] = useState<"" | "sent" | "lost" | "withdrawn">("");
  const [sentOn, setSentOn] = useState(daysFromToday(0));
  const [value, setValue] = useState(job.tender_value ? String(job.tender_value) : "");
  const [error, setError] = useState("");
  useEffect(() => {
    api.get<SalesSettings>("/api/sales/settings").then(setSettings);
    api.get<ClientChoice[]>("/api/sales/clients").then(setClients).catch(() => setClients([]));
  }, []);
  useEffect(() => setValue(job.tender_value ? String(job.tender_value) : ""), [job.tender_value]);

  const save = async (body: Record<string, unknown>) => {
    setError("");
    try { await api.put(`/api/jobs/${job.id}/sales`, body); setAsking(""); onSaved(); } catch (e) { setError((e as Error).message); }
  };
  const stage = job.sales_stage ?? "lead";
  const sector = job.sector ?? "commercial";
  const decided = ["won", "lost", "withdrawn"].includes(stage);
  const reached = (s: SalesStage) => STEPS.indexOf(s) <= STEPS.indexOf(decided ? "quote_sent" : stage);
  const l2q = daysBetween(job.lead_date, job.quote_sent_date);
  const q2d = daysBetween(job.quote_sent_date, job.decided_date);
  const contacts = withCurrent(clients.find((c) => c.name.toLowerCase() === (job.client ?? "").trim().toLowerCase())?.contacts ?? [], job.contact);
  const band = settings?.value_bands.find((b) => b.key === job.value_band)?.label;

  return (
    <section className="card sales-panel">
      <div className="row wrap">
        <span className="badge">{SECTOR_LABELS[sector]}</span>
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
        {!job.quote_sent_date && <button className="primary" onClick={() => setAsking(asking === "sent" ? "" : "sent")}>Mark quote sent</button>}
        {job.quote_sent_date && !decided && (
          <>
            <button className="primary" onClick={() => save({ tender_result: "won" })}>Won it</button>
            <button onClick={() => setAsking(asking === "lost" ? "" : "lost")}>Lost</button>
            <button onClick={() => setAsking(asking === "withdrawn" ? "" : "withdrawn")}>Withdrawn</button>
          </>
        )}
        <button className="link" onClick={() => setOpen(!open)}>{open ? "Hide details" : "Details"}</button>
      </div>

      {asking === "sent" && (
        <div className="ask">
          <span className="q">When did it go out?</span>
          <DateChips value={sentOn} onChange={setSentOn} choices={([["Today", 0], ["Yesterday", -1], ["2 days ago", -2]] as [string, number][])
                       .filter(([, n]) => !job.lead_date || daysFromToday(n) >= job.lead_date)} />
          <span className="q">Price quoted (ex GST)</span>
          <div className="row">
            <input type="number" min={0} placeholder="$" value={value} onChange={(e) => setValue(e.target.value)} />
            <button className="primary" disabled={!sentOn}
                    onClick={() => save({ quote_sent_date: sentOn, tender_value: value ? Number(value) : null })}>Save</button>
            <button className="link" onClick={() => setAsking("")}>Cancel</button>
          </div>
        </div>
      )}
      {(asking === "lost" || asking === "withdrawn") && settings && (
        <div className="ask">
          <span className="q">{asking === "lost" ? "Why did we lose it?" : "Why was it withdrawn?"} <small className="muted">Tap one</small></span>
          <Chips options={settings.lost_reasons} value="" onChange={(r) => save({ tender_result: asking, outcome_reason: r })} />
          <button className="link small" onClick={() => save({ tender_result: asking })}>Don't know: just mark it {STAGE_LABELS[asking].toLowerCase()}</button>
        </div>
      )}

      <div className="small muted">
        {l2q !== null && <>Quoted {l2q} day{l2q === 1 ? "" : "s"} after the lead came in. </>}
        {q2d !== null && <>{STAGE_LABELS[stage]} {q2d} day{q2d === 1 ? "" : "s"} after the quote went out. </>}
        {job.outcome_reason && <>Reason: {job.outcome_reason}. </>}
        {job.work_type && <>{job.work_type}. </>}
        {band && <>Size: {band}. </>}
        {job.lead_source && <>Source: {job.lead_source}. </>}
        {job.contact && <>Contact: {job.contact}.</>}
      </div>
      {open && settings && (
        <div className="sales-details">
          <label>Sector
            <select value={sector} onChange={(e) => save({ sector: e.target.value as Sector })}>
              {settings.sectors.map((s) => <option key={s.key} value={s.key}>{s.label}</option>)}
            </select>
          </label>
          <label>Type of work
            <select value={job.work_type ?? ""} onChange={(e) => save({ work_type: e.target.value })}>
              <option value="">Not set</option>
              {withCurrent(settings.work_types[sector] ?? [], job.work_type).map((w) => <option key={w}>{w}</option>)}
            </select>
          </label>
          <label>Rough size
            <select value={job.value_band ?? ""} onChange={(e) => save({ value_band: e.target.value })}>
              <option value="">Not set</option>
              {settings.value_bands.map((b) => <option key={b.key} value={b.key}>{b.label}</option>)}
            </select>
          </label>
          <label>Client
            <PickOrNew options={withCurrent(clientNames(clients, sector), job.client)} value={job.client ?? ""} emptyLabel="Not set"
                       onChange={(v) => v !== job.client && v.trim() && save({ client: v })} placeholder="New client name" newLabel="+ New client…" lazy />
          </label>
          <label>Contact
            <PickOrNew options={contacts} value={job.contact ?? ""} emptyLabel="Not set" placeholder="Name and phone / email" newLabel="+ New contact…" lazy
                       onChange={(v) => v !== job.contact && save({ contact: v })} />
          </label>
          <label>Lead source
            <select value={job.lead_source ?? ""} onChange={(e) => save({ lead_source: e.target.value })}>
              <option value="">Not set</option>
              {withCurrent(settings.lead_sources, job.lead_source).map((s) => <option key={s}>{s}</option>)}
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
          {(stage === "lost" || stage === "withdrawn") && (
            <label>Reason
              <select value={job.outcome_reason ?? ""} onChange={(e) => save({ outcome_reason: e.target.value })}>
                <option value="">Not given</option>
                {withCurrent(settings.lost_reasons, job.outcome_reason).map((r) => <option key={r}>{r}</option>)}
              </select>
            </label>
          )}
          <label>Lead came in<input type="date" value={job.lead_date ?? ""} onChange={(e) => e.target.value && save({ lead_date: e.target.value })} /></label>
          <label>Quote sent
            <input type="date" value={job.quote_sent_date ?? ""}
                   onChange={(e) => save(e.target.value ? { quote_sent_date: e.target.value } : { clear_quote_sent: true })} />
          </label>
          <label>Decided<input type="date" value={job.decided_date ?? ""} disabled={!decided}
                               onChange={(e) => e.target.value && save({ decided_date: e.target.value })} /></label>
          <label>Quote due<input type="date" value={job.due_date ?? ""} onChange={(e) => save({ due_date: e.target.value || null })} /></label>
        </div>
      )}
      {error && <p className="error small">{error}</p>}
    </section>
  );
}
