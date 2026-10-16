/* Safety (office): dashboard, incidents and hazards with corrective actions, the SWMS library, ITP templates,
   toolbox talks, site pre-starts and SWMS sign-ons. Plus the SWMS, ITP and pre-start tabs on each job. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { level, useApp } from "../App";
import { DataTable, ErrorLine, Field, fmtDate, fmtTime, Modal, Status, Tabs, useAction, useLoad } from "../ui";
import { ReportForm } from "./FieldSafety";
import { PdfShare } from "./Share";

export interface SwmsStep { step: string; hazards: string; risk_before: string; controls: string; risk_after: string; who: string }
export interface SwmsTpl { id: number; title: string; activity: string; high_risk: string[]; ppe: string[]; steps: SwmsStep[]; version: number; active: boolean }
export interface JobSwms { id: number; job_id: number; template_id: number | null; title: string; activity: string; high_risk: string[]; ppe: string[]; steps: SwmsStep[];
  site_notes: string; version: number; status: string; signed: { user_id: number; name: string; typed_name: string; at: string }[]; i_signed: boolean | null; created_at: string }
export interface ItpItem { key: string; stage: string; activity: string; check: string; criteria: string; frequency: string; point: string; who: string; record: string }
export interface ItpCheck { id: number; item_key: string; day: string; result: string; reading: string; notes: string; photos: number[]; user_id: number; by: string;
  signed_name: string; signed_role: string; has_signature: boolean; at: string }
export interface ItpState extends ItpItem { done: boolean; last: ItpCheck | null; count: number; failed: boolean; point_label: string }
export interface JobItp { id: number; job_id: number; name: string; area: string; status: string; items: ItpState[]; done: number; total: number; failed: number;
  history: ItpCheck[]; created_at: string }
export interface Question { key: string; label: string; type: "text" | "yesno" | "multi"; options?: string[] }
export interface Attendee { user_id: number; name: string; signed_at: string; signature?: string }
export interface Prestart { id: number; job_id: number; day: string; led_by: string; answers: Record<string, unknown>; attendees: Attendee[]; questions: Question[]; job?: string }
interface Action { id: number; event_id: number | null; job_id: number | null; description: string; assignee_id: number | null; assignee: string; due: string | null;
  status: string; overdue: boolean; done_note: string; done_at: string | null }
interface Event { id: number; kind: string; kind_label: string; job_id: number | null; job: string; location: string; occurred_at: string; reported_by: string; title: string;
  description: string; immediate_action: string; severity: string; treatment: string; treatment_label: string; people: string; notifiable: boolean; photos: number[];
  status: string; root_cause: string; closed_at: string | null; actions: Action[] }
interface Talk { id: number; job_id: number | null; job: string; topic: string; notes: string; day: string; presenter: string; attendees: Attendee[] }
interface Options { high_risk: string[]; event_kinds: Record<string, string>; treatment: Record<string, string>; prestart_questions: Question[];
  itp_points: Record<string, string>; itp_frequency: Record<string, string>; swms_templates: SwmsTpl[]; itp_templates: { id: number; name: string; items: ItpItem[]; active: boolean }[] }
interface Dash { days_since_lti: number | null; last_lti: string | null; open_events: number; open_actions: number; overdue_actions: number; events_12m: number;
  by_month: ({ month: string } & Record<string, number | string>)[]; toolbox_this_month: number; signons_this_week: number; jobs_on_today: number; prestarts_today: number;
  missing_prestarts: { job_id: number; job: string }[]; kinds: Record<string, string> }

type Tab = "dash" | "events" | "actions" | "swms" | "itp" | "toolbox" | "prestarts" | "signons";
const KIND_COLOURS: Record<string, string> = { hazard: "#ffb27a", near_miss: "#ff6a13", incident: "#c4470a", injury: "#b00020", property: "#2b2b2b", environment: "#4c8c4a" };
export const answer = (v: unknown) => (v === true ? "Yes" : v === false ? "No" : Array.isArray(v) ? v.join(", ") : v ? String(v) : "–");

export default function Safety() {
  const { user } = useApp();
  const edit = level(user, "safety") === "edit";
  const [tab, setTab] = useState<Tab>(() => (new URLSearchParams(window.location.search).get("tab") as Tab) || (new URLSearchParams(window.location.search).get("event") ? "events" : "dash"));
  const opts = useLoad<Options>("/api/safety/options");
  const [reporting, setReporting] = useState(false);
  return (
    <main className="page">
      <div className="row wrap">
        <h1 style={{ margin: 0 }}>Safety</h1><span className="spacer" />
        <button className="primary" onClick={() => setReporting(true)}>⚠️ Report a hazard or incident</button>
      </div>
      <Tabs tabs={[["dash", "Dashboard"], ["events", "Incidents & hazards"], ["actions", "Actions"], ["swms", "SWMS library"], ["itp", "ITP templates"],
        ["toolbox", "Toolbox talks"], ["prestarts", "Site pre-starts"], ["signons", "SWMS sign-ons"]]} value={tab} onChange={setTab} />
      {tab === "dash" && <Dashboard onTab={setTab} />}
      {tab === "events" && opts.data && <Events opts={opts.data} edit={edit} />}
      {tab === "actions" && <Actions edit={edit} />}
      {tab === "swms" && opts.data && <SwmsLibrary opts={opts.data} edit={edit} onSaved={opts.reload} />}
      {tab === "itp" && opts.data && <ItpTemplates opts={opts.data} edit={level(user, "itp") === "edit"} onSaved={opts.reload} />}
      {tab === "toolbox" && <Toolbox />}
      {tab === "prestarts" && <Prestarts />}
      {tab === "signons" && <Signons />}
      {reporting && <Modal title="Report a hazard or incident" onClose={() => setReporting(false)} wide><ReportForm onDone={() => setReporting(false)} /></Modal>}
    </main>
  );
}

function Dashboard({ onTab }: { onTab: (t: Tab) => void }) {
  const { data: d } = useLoad<Dash>("/api/safety/dashboard");
  if (!d) return <p className="muted">Loading…</p>;
  const max = Math.max(1, ...d.by_month.map((m) => Object.keys(d.kinds).reduce((s, k) => s + (Number(m[k]) || 0), 0)));
  return (
    <div className="stack">
      <div className="tiles">
        <div className="tile big-tile ok"><b>{d.days_since_lti ?? "–"}</b><span>{d.days_since_lti === null ? "no lost-time injuries recorded" : "days since a lost-time injury"}</span></div>
        <button className={`tile ${d.open_events ? "warn" : ""}`} onClick={() => onTab("events")}><b>{d.open_events}</b><span>open incidents & hazards</span></button>
        <button className={`tile ${d.overdue_actions ? "bad" : d.open_actions ? "warn" : ""}`} onClick={() => onTab("actions")}><b>{d.open_actions}</b><span>open actions · {d.overdue_actions} overdue</span></button>
        <div className="tile"><b>{d.events_12m}</b><span>reports in 12 months</span></div>
        <button className="tile" onClick={() => onTab("toolbox")}><b>{d.toolbox_this_month}</b><span>toolbox talks this month</span></button>
        <button className="tile" onClick={() => onTab("signons")}><b>{d.signons_this_week}</b><span>SWMS sign-ons this week</span></button>
        <button className={`tile ${d.missing_prestarts.length ? "warn" : "ok"}`} onClick={() => onTab("prestarts")}><b>{d.jobs_on_today ? `${d.prestarts_today} / ${d.jobs_on_today}` : d.prestarts_today}</b><span>{d.jobs_on_today ? "jobs on today with a site pre-start" : "site pre-starts done today"}</span></button>
      </div>
      {d.missing_prestarts.length > 0 && (
        <section className="card"><h3>No site pre-start yet today</h3>
          {d.missing_prestarts.map((m) => <div key={m.job_id}><Link to={`/work/${m.job_id}?tab=prestarts`}>{m.job}</Link></div>)}</section>
      )}
      <section className="card">
        <h3>Reports by month</h3>
        <div className="safety-bars">
          {d.by_month.map((m) => (
            <div key={m.month} className="col" title={Object.entries(d.kinds).map(([k, l]) => `${l}: ${m[k] ?? 0}`).join("\n")}>
              <div className="stack-bar">
                {Object.keys(d.kinds).map((k) => Number(m[k]) > 0 && (
                  <span key={k} style={{ height: `${(Number(m[k]) / max) * 100}%`, background: KIND_COLOURS[k] }} />
                ))}
              </div>
              <small>{new Date(m.month + "-01T00:00:00").toLocaleDateString("en-AU", { month: "short" })}</small>
            </div>
          ))}
        </div>
        <div className="legend">{Object.entries(d.kinds).map(([k, l]) => <span key={k}><i style={{ background: KIND_COLOURS[k] }} />{l}</span>)}</div>
      </section>
    </div>
  );
}

function Events({ opts, edit }: { opts: Options; edit: boolean }) {
  const [status, setStatus] = useState("");
  const [kind, setKind] = useState("");
  const { data, reload } = useLoad<Event[]>(`/api/safety/events?status=${status}&kind=${kind}`, [status, kind]);
  const [open, setOpen] = useState<number | null>(() => Number(new URLSearchParams(window.location.search).get("event")) || null);
  const ev = data?.find((e) => e.id === open);
  return (
    <div className="stack">
      <div className="row wrap">
        <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Any status</option><option value="open">Open</option>
          <option value="investigating">Investigating</option><option value="closed">Closed</option></select>
        <select value={kind} onChange={(e) => setKind(e.target.value)}><option value="">All kinds</option>
          {Object.entries(opts.event_kinds).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
      </div>
      <DataTable rows={data ?? []} onRow={(e) => setOpen(e.id)} empty="Nothing reported."
        rowClass={(e) => (e.severity === "critical" || e.severity === "high") && e.status !== "closed" ? "bad-row" : ""}
        cols={[
          { key: "when", label: "When", render: (e) => `${fmtDate(e.occurred_at)} ${fmtTime(e.occurred_at)}` },
          { key: "kind", label: "Kind", render: (e) => e.kind_label },
          { key: "title", label: "What happened", render: (e) => <><b>{e.title}</b>{e.job && <div className="small muted">{e.job}</div>}</> },
          { key: "sev", label: "Severity", render: (e) => <span className={`sev sev-${e.severity}`}>{e.severity}</span> },
          { key: "treat", label: "Treatment", render: (e) => (e.treatment === "none" ? "" : e.treatment_label), hideSm: true },
          { key: "by", label: "Reported by", render: (e) => e.reported_by, hideSm: true },
          { key: "act", label: "Actions", render: (e) => e.actions.length ? `${e.actions.filter((a) => a.status === "done").length}/${e.actions.length} done` : "", hideSm: true },
          { key: "status", label: "Status", render: (e) => <Status value={e.status} /> },
        ]} />
      {ev && <EventModal ev={ev} opts={opts} edit={edit} onClose={() => setOpen(null)} onSaved={reload} />}
    </div>
  );
}

function EventModal({ ev, opts, edit, onClose, onSaved }: { ev: Event; opts: Options; edit: boolean; onClose: () => void; onSaved: () => void }) {
  const staff = useLoad<{ id: number; name: string }[]>("/api/staff");
  const [f, setF] = useState({ status: ev.status, severity: ev.severity, treatment: ev.treatment, root_cause: ev.root_cause, notifiable: ev.notifiable });
  const [a, setA] = useState({ description: "", assignee_id: "", due: "" });
  const [run, error, busy] = useAction();
  const save = () => run(async () => { await api.patch(`/api/safety/events/${ev.id}`, f); onSaved(); });
  const addAction = () => run(async () => {
    await api.post(`/api/safety/events/${ev.id}/actions`, { description: a.description, assignee_id: a.assignee_id ? Number(a.assignee_id) : null, due: a.due || null, job_id: ev.job_id });
    setA({ description: "", assignee_id: "", due: "" }); onSaved();
  });
  return (
    <Modal title={`${ev.kind_label}: ${ev.title}`} onClose={onClose} wide>
      <div className="row wrap"><PdfShare kind="incident" id={ev.id} title={`${ev.kind_label} report – ${ev.title}`} /></div>
      <div className="two-col">
        <div className="stack">
          <dl className="kv-list">
            <dt>When</dt><dd>{fmtDate(ev.occurred_at)} {fmtTime(ev.occurred_at)}</dd>
            <dt>Job / where</dt><dd>{ev.job_id ? <Link to={`/work/${ev.job_id}`}>{ev.job}</Link> : ""} {ev.location}</dd>
            <dt>Reported by</dt><dd>{ev.reported_by}</dd>
            <dt>People involved</dt><dd>{ev.people || "–"}</dd>
            <dt>What happened</dt><dd className="pre">{ev.description || "–"}</dd>
            <dt>Done straight away</dt><dd className="pre">{ev.immediate_action || "–"}</dd>
            <dt>Photos</dt><dd>{ev.photos.length ? `${ev.photos.length} (in the PDF and the job's documents)` : "–"}</dd>
          </dl>
        </div>
        <div className="stack">
          <div className="grid2">
            <Field label="Status"><select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })} disabled={!edit}>
              <option value="open">Open</option><option value="investigating">Investigating</option><option value="closed">Closed</option></select></Field>
            <Field label="Severity"><select value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })} disabled={!edit}>
              {["low", "medium", "high", "critical"].map((s) => <option key={s}>{s}</option>)}</select></Field>
            <Field label="Treatment"><select value={f.treatment} onChange={(e) => setF({ ...f, treatment: e.target.value })} disabled={!edit}>
              {Object.entries(opts.treatment).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
            <label className="check"><input type="checkbox" checked={f.notifiable} onChange={(e) => setF({ ...f, notifiable: e.target.checked })} disabled={!edit} /> Notifiable to WHSQ</label>
          </div>
          <Field label="Root cause / investigation"><textarea rows={3} value={f.root_cause} onChange={(e) => setF({ ...f, root_cause: e.target.value })} disabled={!edit} /></Field>
          {edit && <button onClick={save} disabled={busy}>Save</button>}
          <h3>Corrective actions</h3>
          {ev.actions.map((x) => (
            <div key={x.id} className="small note-row"><span>{x.status === "done" ? "✅" : x.overdue ? "🔴" : "⬜"} {x.description} <span className="muted">· {x.assignee || "nobody"}{x.due && ` · due ${fmtDate(x.due)}`}</span>
              {x.done_note && <div className="muted">{x.done_note}</div>}</span></div>
          ))}
          {edit && <div className="stack">
            <input placeholder="What needs to happen" value={a.description} onChange={(e) => setA({ ...a, description: e.target.value })} />
            <div className="row">
              <select value={a.assignee_id} onChange={(e) => setA({ ...a, assignee_id: e.target.value })}><option value="">Who</option>
                {(staff.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
              <input type="date" value={a.due} onChange={(e) => setA({ ...a, due: e.target.value })} />
              <button onClick={addAction} disabled={busy || !a.description.trim()}>Add</button>
            </div>
          </div>}
          <ErrorLine error={error} />
        </div>
      </div>
    </Modal>
  );
}

function Actions({ edit }: { edit: boolean }) {
  const [status, setStatus] = useState("open");
  const { data, reload } = useLoad<Action[]>(`/api/safety/actions?status=${status}`, [status]);
  const staff = useLoad<{ id: number; name: string }[]>("/api/staff");
  const [f, setF] = useState({ description: "", assignee_id: "", due: "" });
  const [run, error, busy] = useAction();
  const add = () => run(async () => {
    await api.post("/api/safety/actions", { description: f.description, assignee_id: f.assignee_id ? Number(f.assignee_id) : null, due: f.due || null });
    setF({ description: "", assignee_id: "", due: "" }); reload();
  });
  return (
    <div className="stack">
      <div className="seg"><button className={status === "open" ? "on" : ""} onClick={() => setStatus("open")}>Open</button>
        <button className={status === "done" ? "on" : ""} onClick={() => setStatus("done")}>Done</button><button className={status === "" ? "on" : ""} onClick={() => setStatus("")}>All</button></div>
      {edit && <div className="row wrap card">
        <input placeholder="New action, e.g. replace the damaged trench shield" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} style={{ flex: 1, minWidth: 220 }} />
        <select value={f.assignee_id} onChange={(e) => setF({ ...f, assignee_id: e.target.value })}><option value="">Who</option>
          {(staff.data ?? []).map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
        <input type="date" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} />
        <button className="primary" onClick={add} disabled={busy || !f.description.trim()}>Add</button>
      </div>}
      <ErrorLine error={error} />
      <DataTable rows={data ?? []} rowClass={(a) => (a.overdue ? "bad-row" : "")} empty="No actions."
        cols={[
          { key: "d", label: "Action", render: (a) => <>{a.description}{a.event_id && <div className="small"><Link to={`/safety?event=${a.event_id}`}>From report #{a.event_id}</Link></div>}</> },
          { key: "who", label: "Who", render: (a) => a.assignee },
          { key: "due", label: "Due", render: (a) => <span className={a.overdue ? "bad" : ""}>{fmtDate(a.due)}</span> },
          { key: "s", label: "Status", render: (a) => a.status === "done" ? <>✅ {fmtDate(a.done_at)}{a.done_note && <div className="small muted">{a.done_note}</div>}</>
            : edit ? <button className="small" onClick={async () => { await api.post(`/api/field/safety/actions/${a.id}/done`, { note: "" }); reload(); }}>Mark done</button> : "Open" },
        ]} />
    </div>
  );
}

/* --- the SWMS library --- */
const RISK = ["", "Low", "Medium", "High", "Extreme"];
function SwmsLibrary({ opts, edit, onSaved }: { opts: Options; edit: boolean; onSaved: () => void }) {
  const [open, setOpen] = useState<SwmsTpl | "new" | null>(null);
  return (
    <div className="stack">
      <div className="row"><p className="muted small" style={{ flex: 1 }}>Templates the crew start from. Add one to a job from the job's SWMS tab; everyone on the job signs it on their phone.</p>
        {edit && <button className="primary" onClick={() => setOpen("new")}>+ New SWMS</button>}</div>
      <DataTable rows={opts.swms_templates} onRow={setOpen} cols={[
        { key: "t", label: "SWMS", render: (t) => <><b>{t.title}</b>{!t.active && <span className="muted"> (archived)</span>}<div className="small muted">{t.activity}</div></> },
        { key: "hr", label: "High risk construction work", render: (t) => t.high_risk.join(", "), hideSm: true },
        { key: "s", label: "Steps", render: (t) => t.steps.length, num: true },
        { key: "v", label: "Version", render: (t) => t.version, num: true },
      ]} />
      {open && <SwmsEditor tpl={open === "new" ? null : open} opts={opts} edit={edit} onClose={() => setOpen(null)} onSaved={onSaved} />}
    </div>
  );
}

export function StepsEditor({ steps, onChange, edit }: { steps: SwmsStep[]; onChange: (s: SwmsStep[]) => void; edit: boolean }) {
  const set = (i: number, k: keyof SwmsStep, v: string) => onChange(steps.map((s, n) => (n === i ? { ...s, [k]: v } : s)));
  return (
    <div className="dt-wrap">
      <table className="dt swms-steps">
        <thead><tr><th>Step</th><th>Hazards</th><th>Risk</th><th>Controls</th><th>After</th><th>Who</th>{edit && <th />}</tr></thead>
        <tbody>
          {steps.map((s, i) => (
            <tr key={i}>
              <td><textarea rows={2} value={s.step} onChange={(e) => set(i, "step", e.target.value)} disabled={!edit} /></td>
              <td><textarea rows={3} value={s.hazards} onChange={(e) => set(i, "hazards", e.target.value)} disabled={!edit} /></td>
              <td><select value={s.risk_before} onChange={(e) => set(i, "risk_before", e.target.value)} disabled={!edit}>{RISK.map((r) => <option key={r}>{r}</option>)}</select></td>
              <td><textarea rows={3} value={s.controls} onChange={(e) => set(i, "controls", e.target.value)} disabled={!edit} /></td>
              <td><select value={s.risk_after} onChange={(e) => set(i, "risk_after", e.target.value)} disabled={!edit}>{RISK.map((r) => <option key={r}>{r}</option>)}</select></td>
              <td><input value={s.who} onChange={(e) => set(i, "who", e.target.value)} disabled={!edit} /></td>
              {edit && <td><button className="link" onClick={() => onChange(steps.filter((_, n) => n !== i))} aria-label="Remove step">✕</button></td>}
            </tr>
          ))}
        </tbody>
      </table>
      {edit && <button className="small" onClick={() => onChange([...steps, { step: "", hazards: "", risk_before: "Medium", controls: "", risk_after: "Low", who: "All workers" }])}>+ Add a step</button>}
    </div>
  );
}

function SwmsEditor({ tpl, opts, edit, onClose, onSaved }: { tpl: SwmsTpl | null; opts: Options; edit: boolean; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({ title: tpl?.title ?? "", activity: tpl?.activity ?? "", high_risk: tpl?.high_risk ?? [], ppe: (tpl?.ppe ?? []).join(", "),
    steps: tpl?.steps ?? [], active: tpl?.active ?? true });
  const [run, error, busy] = useAction();
  const save = () => run(async () => {
    const body = { ...f, ppe: f.ppe.split(",").map((x) => x.trim()).filter(Boolean) };
    if (tpl) await api.put(`/api/safety/swms-templates/${tpl.id}`, body); else await api.post("/api/safety/swms-templates", body);
    onSaved(); onClose();
  });
  return (
    <Modal title={tpl ? tpl.title : "New SWMS"} onClose={onClose} wide>
      <div className="stack">
        <div className="grid2">
          <Field label="Title"><input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} disabled={!edit} /></Field>
          <Field label="Work activity"><input value={f.activity} onChange={(e) => setF({ ...f, activity: e.target.value })} disabled={!edit} /></Field>
        </div>
        <Field label="High risk construction work (WHS Regulation s291)">
          <div className="chips">{opts.high_risk.map((h) => (
            <label key={h} className={`chip ${f.high_risk.includes(h) ? "on" : ""}`}><input type="checkbox" hidden disabled={!edit} checked={f.high_risk.includes(h)}
              onChange={(e) => setF({ ...f, high_risk: e.target.checked ? [...f.high_risk, h] : f.high_risk.filter((x) => x !== h) })} />{h}</label>))}</div>
        </Field>
        <Field label="PPE" hint="Separate with commas"><input value={f.ppe} onChange={(e) => setF({ ...f, ppe: e.target.value })} disabled={!edit} /></Field>
        <StepsEditor steps={f.steps} onChange={(steps) => setF({ ...f, steps })} edit={edit} />
        {tpl && <label className="check"><input type="checkbox" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} disabled={!edit} /> In use</label>}
        <ErrorLine error={error} />
        {edit && <button className="primary" onClick={save} disabled={busy || !f.title.trim()}>Save{tpl ? ` (becomes version ${tpl.version + 1})` : ""}</button>}
      </div>
    </Modal>
  );
}

/* --- ITP templates --- */
function ItpTemplates({ opts, edit, onSaved }: { opts: Options; edit: boolean; onSaved: () => void }) {
  const [open, setOpen] = useState<Options["itp_templates"][number] | "new" | null>(null);
  return (
    <div className="stack">
      <div className="row"><p className="muted small" style={{ flex: 1 }}>Inspection and test plans. Add one to a job from the job's ITPs tab; the crew get the day's checks on their phone.</p>
        {edit && <button className="primary" onClick={() => setOpen("new")}>+ New ITP template</button>}</div>
      <DataTable rows={opts.itp_templates} onRow={setOpen} cols={[
        { key: "n", label: "ITP", render: (t) => <><b>{t.name}</b>{!t.active && <span className="muted"> (archived)</span>}</> },
        { key: "i", label: "Items", render: (t) => t.items.length, num: true },
        { key: "h", label: "Hold points", render: (t) => t.items.filter((i) => i.point === "hold").length, num: true },
        { key: "d", label: "Daily checks", render: (t) => t.items.filter((i) => i.frequency === "daily").length, num: true },
      ]} />
      {open && <ItpEditor tpl={open === "new" ? null : open} opts={opts} edit={edit} onClose={() => setOpen(null)} onSaved={onSaved} />}
    </div>
  );
}

function ItpEditor({ tpl, opts, edit, onClose, onSaved }: { tpl: Options["itp_templates"][number] | null; opts: Options; edit: boolean; onClose: () => void; onSaved: () => void }) {
  const [name, setName] = useState(tpl?.name ?? "");
  const [items, setItems] = useState<ItpItem[]>(tpl?.items ?? []);
  const [active, setActive] = useState(tpl?.active ?? true);
  const [run, error, busy] = useAction();
  const set = (i: number, k: keyof ItpItem, v: string) => setItems(items.map((x, n) => (n === i ? { ...x, [k]: v } : x)));
  const save = () => run(async () => {
    if (tpl) await api.put(`/api/itp-templates/${tpl.id}`, { name, items, active }); else await api.post("/api/itp-templates", { name, items, active });
    onSaved(); onClose();
  });
  return (
    <Modal title={tpl ? tpl.name : "New ITP template"} onClose={onClose} wide>
      <div className="stack">
        <Field label="Name"><input value={name} onChange={(e) => setName(e.target.value)} disabled={!edit} /></Field>
        <div className="dt-wrap">
          <table className="dt swms-steps">
            <thead><tr><th>Stage</th><th>Activity</th><th>Check / method</th><th>Acceptance criteria</th><th>How often</th><th>Point</th><th>Who</th><th>Record</th>{edit && <th />}</tr></thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={i}>
                  <td><input value={it.stage} onChange={(e) => set(i, "stage", e.target.value)} disabled={!edit} /></td>
                  <td><textarea rows={2} value={it.activity} onChange={(e) => set(i, "activity", e.target.value)} disabled={!edit} /></td>
                  <td><textarea rows={2} value={it.check} onChange={(e) => set(i, "check", e.target.value)} disabled={!edit} /></td>
                  <td><textarea rows={2} value={it.criteria} onChange={(e) => set(i, "criteria", e.target.value)} disabled={!edit} /></td>
                  <td><select value={it.frequency} onChange={(e) => set(i, "frequency", e.target.value)} disabled={!edit}>
                    {Object.entries(opts.itp_frequency).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></td>
                  <td><select value={it.point} onChange={(e) => set(i, "point", e.target.value)} disabled={!edit}>
                    {Object.entries(opts.itp_points).map(([k, l]) => <option key={k} value={k}>{l || "–"}</option>)}</select></td>
                  <td><input value={it.who} onChange={(e) => set(i, "who", e.target.value)} disabled={!edit} /></td>
                  <td><select value={it.record} onChange={(e) => set(i, "record", e.target.value)} disabled={!edit}>
                    <option value="photo">Photo</option><option value="reading">Reading / result</option><option value="signature">Signature</option><option value="none">Tick only</option></select></td>
                  {edit && <td><button className="link" onClick={() => setItems(items.filter((_, n) => n !== i))} aria-label="Remove item">✕</button></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {edit && <button className="small" onClick={() => setItems([...items, { key: "", stage: "", activity: "", check: "", criteria: "", frequency: "once", point: "none", who: "Plumber", record: "photo" }])}>+ Add an item</button>}
        {tpl && <label className="check"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} disabled={!edit} /> In use</label>}
        <ErrorLine error={error} />
        {edit && <button className="primary" onClick={save} disabled={busy || !name.trim()}>Save</button>}
      </div>
    </Modal>
  );
}

function Toolbox() {
  const { data } = useLoad<Talk[]>("/api/safety/toolbox");
  return <DataTable rows={data ?? []} empty="No toolbox talks yet. Run one from the phone (Safety tab)." cols={[
    { key: "d", label: "Date", render: (t) => fmtDate(t.day) },
    { key: "t", label: "Topic", render: (t) => <><b>{t.topic}</b>{t.notes && <div className="small muted">{t.notes}</div>}</> },
    { key: "j", label: "Job", render: (t) => t.job, hideSm: true },
    { key: "p", label: "Run by", render: (t) => t.presenter, hideSm: true },
    { key: "a", label: "Signed", render: (t) => t.attendees.map((a) => a.name).join(", ") },
    { key: "pdf", label: "", render: (t) => <PdfShare kind="toolbox" id={t.id} title={`Toolbox talk – ${t.topic}`} small /> },
  ]} />;
}

function Prestarts() {
  const [day, setDay] = useState("");
  const { data } = useLoad<Prestart[]>(`/api/safety/prestarts${day ? `?day=${day}` : ""}`, [day]);
  return (
    <div className="stack">
      <div className="row"><Field label="Day"><input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></Field></div>
      <PrestartTable rows={data ?? []} showJob />
    </div>
  );
}

function PrestartTable({ rows, showJob }: { rows: Prestart[]; showJob?: boolean }) {
  return <DataTable rows={rows} empty="No site pre-starts yet. The crew fill them in on the phone each morning." cols={[
    { key: "d", label: "Day", render: (p) => fmtDate(p.day) },
    ...(showJob ? [{ key: "j", label: "Job", render: (p: Prestart) => <Link to={`/work/${p.job_id}?tab=prestarts`}>{p.job}</Link> }] : []),
    { key: "l", label: "Led by", render: (p) => p.led_by },
    { key: "h", label: "Hazards", render: (p) => answer(p.answers.hazards), hideSm: true },
    { key: "a", label: "Crew signed", render: (p) => p.attendees.map((a) => a.name).join(", ") },
    { key: "pdf", label: "", render: (p) => <PdfShare kind="prestart" id={p.id} title={`Site pre-start ${fmtDate(p.day)}`} small /> },
  ]} />;
}

function Signons() {
  const { data } = useLoad<{ swms: string; job_id: number; name: string; version: number; at: string }[]>("/api/safety/signons");
  return <DataTable rows={data ?? []} empty="No sign-ons yet." cols={[
    { key: "a", label: "When", render: (s) => `${fmtDate(s.at)} ${fmtTime(s.at)}` },
    { key: "n", label: "Who", render: (s) => s.name },
    { key: "s", label: "SWMS", render: (s) => <Link to={`/work/${s.job_id}?tab=swms`}>{s.swms}</Link> },
    { key: "v", label: "Version", render: (s) => s.version, num: true },
  ]} />;
}

/* ================= the job hub tabs ================= */
export function JobSwmsTab({ jobId }: { jobId: number }) {
  const { user } = useApp();
  const edit = level(user, "safety") === "edit";
  const { data, reload } = useLoad<JobSwms[]>(`/api/jobs/${jobId}/swms`);
  const opts = useLoad<Options>("/api/safety/options");
  const [tpl, setTpl] = useState("");
  const [open, setOpen] = useState<JobSwms | null>(null);
  const [run, error, busy] = useAction();
  const add = () => run(async () => { await api.post(`/api/jobs/${jobId}/swms`, { template_id: Number(tpl) }); setTpl(""); reload(); });
  return (
    <div className="stack">
      {edit && <div className="row wrap card">
        <select value={tpl} onChange={(e) => setTpl(e.target.value)}><option value="">Add a SWMS from the library…</option>
          {(opts.data?.swms_templates ?? []).filter((t) => t.active).map((t) => <option key={t.id} value={t.id}>{t.title}</option>)}</select>
        <button className="primary" onClick={add} disabled={!tpl || busy}>Add to this job</button>
        <span className="small muted">Everyone working on the job is asked to read and sign it on their phone.</span>
      </div>}
      <ErrorLine error={error} />
      <DataTable rows={data ?? []} onRow={setOpen} empty="No SWMS on this job yet." cols={[
        { key: "t", label: "SWMS", render: (s) => <><b>{s.title}</b>{s.status === "archived" && <span className="muted"> (archived)</span>}<div className="small muted">{s.high_risk.join(", ")}</div></> },
        { key: "v", label: "Version", render: (s) => s.version, num: true },
        { key: "s", label: "Signed on", render: (s) => s.signed.length ? s.signed.map((x) => x.name).join(", ") : <span className="warn">Nobody yet</span> },
        { key: "pdf", label: "", render: (s) => <span onClick={(e) => e.stopPropagation()}><PdfShare kind="swms" id={s.id} title={`SWMS – ${s.title}`} small /></span> },
      ]} />
      {open && <JobSwmsModal s={open} edit={edit} onClose={() => setOpen(null)} onSaved={() => { reload(); setOpen(null); }} />}
    </div>
  );
}

function JobSwmsModal({ s, edit, onClose, onSaved }: { s: JobSwms; edit: boolean; onClose: () => void; onSaved: () => void }) {
  const [steps, setSteps] = useState(s.steps);
  const [notes, setNotes] = useState(s.site_notes);
  const [run, error, busy] = useAction();
  const save = (extra: Record<string, unknown> = {}) => run(async () => { await api.patch(`/api/job-swms/${s.id}`, { steps, site_notes: notes, ...extra }); onSaved(); });
  return (
    <Modal title={`${s.title} (version ${s.version})`} onClose={onClose} wide>
      <div className="stack">
        <PdfShare kind="swms" id={s.id} title={`SWMS – ${s.title}`} />
        <p className="small"><b>High risk work:</b> {s.high_risk.join(", ") || "None"} · <b>PPE:</b> {s.ppe.join(", ")}</p>
        <Field label="Site-specific notes"><textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} disabled={!edit} /></Field>
        <StepsEditor steps={steps} onChange={setSteps} edit={edit} />
        <p className="small"><b>Signed on to this version:</b> {s.signed.map((x) => `${x.name} (${fmtDate(x.at)})`).join(", ") || "nobody yet"}</p>
        <ErrorLine error={error} />
        {edit && <div className="row">
          <button className="primary" onClick={() => save()} disabled={busy}>Save (everyone signs the new version)</button>
          {s.status === "active" ? <button onClick={() => save({ status: "archived" })} disabled={busy}>Archive</button>
            : <button onClick={() => save({ status: "active" })} disabled={busy}>Make active again</button>}
        </div>}
      </div>
    </Modal>
  );
}

export function JobItpsTab({ jobId }: { jobId: number }) {
  const { user } = useApp();
  const edit = level(user, "itp") === "edit";
  const { data, reload } = useLoad<JobItp[]>(`/api/jobs/${jobId}/itps`);
  const opts = useLoad<Options>("/api/safety/options");
  const [tpl, setTpl] = useState("");
  const [area, setArea] = useState("");
  const [open, setOpen] = useState<number | null>(null);
  const [run, error, busy] = useAction();
  const add = () => run(async () => { await api.post(`/api/jobs/${jobId}/itps`, { template_id: Number(tpl), area }); setTpl(""); setArea(""); reload(); });
  const it = data?.find((x) => x.id === open);
  return (
    <div className="stack">
      {edit && <div className="row wrap card">
        <select value={tpl} onChange={(e) => setTpl(e.target.value)}><option value="">Add an ITP…</option>
          {(opts.data?.itp_templates ?? []).filter((t) => t.active).map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
        <input placeholder="Area / stage, e.g. Basement, Level 2" value={area} onChange={(e) => setArea(e.target.value)} />
        <button className="primary" onClick={add} disabled={!tpl || busy}>Add to this job</button>
      </div>}
      <ErrorLine error={error} />
      {(data ?? []).length === 0 && <p className="muted">No ITPs on this job yet.</p>}
      {(data ?? []).map((x) => (
        <div key={x.id} className="card itp-card">
          <div className="row wrap">
            <h3 style={{ margin: 0 }}>{x.name}{x.area && ` – ${x.area}`}</h3>
            <Status value={x.status} />
            {x.failed > 0 && <span className="badge bad">{x.failed} failed</span>}
            <span className="spacer" />
            <PdfShare kind="itp" id={x.id} title={`ITP – ${x.name}${x.area ? ` – ${x.area}` : ""}`} small />
            <button className="small" onClick={() => setOpen(open === x.id ? null : x.id)}>{open === x.id ? "Hide" : "Show items"}</button>
            {edit && x.history.length === 0 && <button className="link small" onClick={async () => { if (confirm("Remove this ITP?")) { await api.del(`/api/job-itps/${x.id}`); reload(); } }}>Remove</button>}
          </div>
          <div className="progress"><span style={{ width: `${x.total ? (x.done / x.total) * 100 : 0}%` }} /></div>
          <small className="muted">{x.done} of {x.total} items done</small>
          {it && it.id === x.id && <ItpTable itp={x} />}
        </div>
      ))}
    </div>
  );
}

export function ItpTable({ itp }: { itp: JobItp }) {
  return (
    <div className="dt-wrap">
      <table className="dt">
        <thead><tr><th>Stage</th><th>Activity</th><th>Criteria</th><th>Point</th><th>Result</th><th>By</th></tr></thead>
        <tbody>
          {itp.items.map((i) => (
            <tr key={i.key} className={i.failed ? "bad-row" : ""}>
              <td>{i.stage}</td>
              <td><b>{i.activity}</b><div className="small muted">{i.check}{i.frequency !== "once" && ` · ${i.frequency === "daily" ? "Daily" : "Each section"}`}</div></td>
              <td className="small">{i.criteria}</td>
              <td>{i.point_label && <span className={`badge ${i.point === "hold" ? "bad" : ""}`}>{i.point_label}</span>}</td>
              <td>{i.last ? <><b className={i.last.result === "fail" ? "bad" : "ok"}>{i.last.result.toUpperCase()}</b>{i.last.reading && <div className="small">{i.last.reading}</div>}</> : <span className="muted">–</span>}</td>
              <td className="small">{i.last && <>{fmtDate(i.last.day)}{i.last.signed_name && <div>✍️ {i.last.signed_name}{i.last.signed_role && ` (${i.last.signed_role})`}</div>}</>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function JobPrestartsTab({ jobId }: { jobId: number }) {
  const { data } = useLoad<Prestart[]>(`/api/jobs/${jobId}/prestarts`);
  return (
    <div className="stack">
      <p className="small muted">The crew fill in the site pre-start on the phone each morning and everyone signs on. Export any day as a PDF for the builder.</p>
      <PrestartTable rows={data ?? []} />
    </div>
  );
}
