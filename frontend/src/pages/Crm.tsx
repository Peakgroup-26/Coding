/* Feedback & follow-ups: NPS by department, client type, customer and month; the follow-up rules; the message queue; call-back tasks. */
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { DataTable, ErrorLine, Field, fmtDate, Modal, Status, Tabs, useAction, useLoad } from "../ui";
import { SERIES } from "./Charts";
import { CLIENT_TYPES } from "./Customers";

interface Block { responses: number; sent: number; response_rate: number | null; nps: number | null; promoters: number; passives: number; detractors: number; avg_score: number | null; ratings: Record<string, number> }
interface Nps { overall: Block; by_department: (Block & { key: string; label: string })[]; by_client_type: (Block & { key: string; label: string })[];
  by_customer: (Block & { customer_id: number; name: string; kind: string })[]; by_month: (Block & { month: string; departments: Record<string, number | null> })[];
  recent: { id: number; customer: string; customer_id: number; job_id: number | null; score: number; comment: string; department: string; kind: string; period: string; at: string; followed_up: boolean }[] }
interface Settings { client_types: Record<string, string>; departments: Record<string, string>; triggers: Record<string, string>; ratings: Record<string, string>; email_ready: boolean; sms_ready: boolean; google_review_url: string }
interface Rule { id?: number; name: string; trigger: string; client_types: string[]; departments: string[]; delay_days: number; channel: string; subject: string; body: string;
  ask_feedback: boolean; ask_review: boolean; min_days_between: number; active: boolean }
type Tab = "nps" | "rules" | "messages" | "tasks";

const npsClass = (v: number | null) => (v === null ? "" : v >= 50 ? "ok" : v < 0 ? "error" : "warn");

function NpsBar({ b }: { b: Block }) {
  const t = Math.max(1, b.responses);
  return (
    <div className="nps-bar" title={`${b.promoters} promoters, ${b.passives} passives, ${b.detractors} detractors`}>
      <span style={{ width: `${(100 * b.detractors) / t}%`, background: SERIES[1] }} />
      <span style={{ width: `${(100 * b.passives) / t}%`, background: "#d9d2cc" }} />
      <span style={{ width: `${(100 * b.promoters) / t}%`, background: SERIES[2] }} />
    </div>
  );
}

function Trend({ months }: { months: Nps["by_month"] }) {
  const pts = months.filter((m) => m.nps !== null);
  if (pts.length < 2) return null;
  const W = 640, H = 180, L = 40, B = 26, T = 10;
  const x = (i: number) => L + (i * (W - L - 10)) / (months.length - 1 || 1);
  const y = (v: number) => T + ((100 - v) / 200) * (H - T - B);
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="NPS by month">
      {[-100, 0, 100].map((v) => <g key={v}><line x1={L} x2={W - 10} y1={y(v)} y2={y(v)} stroke="#e7e2dd" /><text x={L - 6} y={y(v) + 4} fontSize="11" textAnchor="end" fill="#6f6a66">{v}</text></g>)}
      <polyline fill="none" stroke={SERIES[0]} strokeWidth="2" points={months.map((m, i) => (m.nps === null ? null : `${x(i)},${y(m.nps)}`)).filter(Boolean).join(" ")} />
      {months.map((m, i) => m.nps !== null && <circle key={m.month} cx={x(i)} cy={y(m.nps)} r="3" fill={SERIES[0]}><title>{`${m.month}: ${m.nps}`}</title></circle>)}
      {months.map((m, i) => <text key={m.month} x={x(i)} y={H - 8} fontSize="11" textAnchor="middle" fill="#161616">{new Date(m.month + "-01T00:00:00").toLocaleDateString("en-AU", { month: "short" })}</text>)}
    </svg>
  );
}

export default function Crm() {
  const [tab, setTab] = useState<Tab>("nps");
  const settings = useLoad<Settings>("/api/crm/settings");
  return (
    <main className="page">
      <div className="row wrap"><h1 style={{ margin: 0 }}>Feedback & follow-ups</h1><span className="spacer" />
        <Tabs tabs={[["nps", "Scores"], ["rules", "Follow-up rules"], ["messages", "Messages"], ["tasks", "Call-backs"]]} value={tab} onChange={setTab} /></div>
      {settings.data && (!settings.data.email_ready || !settings.data.google_review_url) && (
        <p className="warn small">{!settings.data.email_ready && "Email isn't set up yet, so messages wait in the queue. "}
          {!settings.data.google_review_url && "Add your Google review link in Admin → Operations & plant. "}<Link to="/admin?tab=integrations">Set up ›</Link></p>
      )}
      {tab === "nps" && <Scores />}
      {tab === "rules" && settings.data && <Rules s={settings.data} />}
      {tab === "messages" && <Messages />}
      {tab === "tasks" && <Tasks />}
    </main>
  );
}

function Scores() {
  const [months, setMonths] = useState(12);
  const { data, reload } = useLoad<Nps>(`/api/crm/nps?months=${months}`, [months]);
  if (!data) return <p className="muted">Loading…</p>;
  const o = data.overall;
  return (
    <>
      <div className="row"><span className="spacer" /><select value={months} onChange={(e) => setMonths(Number(e.target.value))}>
        <option value={3}>Last 3 months</option><option value={6}>Last 6 months</option><option value={12}>Last 12 months</option></select></div>
      <div className="tiles">
        <div className="tile"><b className={npsClass(o.nps)}>{o.nps ?? "–"}</b><span>NPS overall</span></div>
        <div className="tile"><b>{o.responses}</b><span>responses from {o.sent} sent ({o.response_rate ?? 0}%)</span></div>
        <div className="tile"><b>{o.avg_score ?? "–"}</b><span>average score /10</span></div>
        {Object.entries(o.ratings).map(([k, v]) => <div key={k} className="tile"><b>{v}</b><span>{k} /5</span></div>)}
      </div>
      <div className="two-col even">
        <section className="card">
          <h2>By department</h2>
          <p className="small muted">NPS = % who'd recommend us (9–10) minus % who wouldn't (0–6). Bars: <span style={{ color: SERIES[1] }}>■</span> 0–6, ▒ 7–8, <span style={{ color: SERIES[2] }}>■</span> 9–10.</p>
          {data.by_department.map((d) => <div key={d.key} className="nps-row"><b>{d.label}</b><span className={npsClass(d.nps)}>{d.nps ?? "–"}</span><NpsBar b={d} /><small className="muted">{d.responses} of {d.sent}</small></div>)}
          <h2>By client type</h2>
          {data.by_client_type.map((d) => <div key={d.key} className="nps-row"><b>{d.label}</b><span className={npsClass(d.nps)}>{d.nps ?? "–"}</span><NpsBar b={d} /><small className="muted">{d.responses} of {d.sent}</small></div>)}
        </section>
        <section className="card">
          <h2>Month by month</h2>
          <Trend months={data.by_month} />
          <DataTable rows={data.by_month} cols={[
            { key: "m", label: "Month", render: (m) => new Date(m.month + "-01T00:00:00").toLocaleDateString("en-AU", { month: "short", year: "numeric" }) },
            { key: "n", label: "NPS", num: true, render: (m) => <span className={npsClass(m.nps)}>{m.nps ?? "–"}</span> },
            ...Object.entries({ residential: "Res", commercial: "Com", maintenance: "Maint", civil: "Civil" }).map(([k, l]) => (
              { key: k, label: l, num: true, render: (m: Nps["by_month"][number]) => <span className={npsClass(m.departments[k] ?? null)}>{m.departments[k] ?? ""}</span> })),
            { key: "r", label: "Replies", num: true, render: (m) => `${m.responses}/${m.sent}` },
          ]} />
        </section>
      </div>
      <div className="two-col even">
        <section className="card">
          <h2>Customers, lowest score first</h2>
          <DataTable rows={data.by_customer.filter((c) => c.responses)} cols={[
            { key: "n", label: "Customer", render: (c) => <Link to={`/customers/${c.customer_id}`}>{c.name}</Link> },
            { key: "k", label: "Type", hideSm: true, render: (c) => CLIENT_TYPES[c.kind] ?? c.kind },
            { key: "s", label: "NPS", num: true, render: (c) => <span className={npsClass(c.nps)}>{c.nps}</span> },
            { key: "a", label: "Avg /10", num: true, render: (c) => c.avg_score },
            { key: "r", label: "Replies", num: true, render: (c) => c.responses },
          ]} />
        </section>
        <section className="card">
          <h2>What they said</h2>
          {data.recent.map((r) => (
            <div key={r.id} className={`comment ${r.score <= 6 ? "low" : r.score >= 9 ? "high" : ""}`}>
              <div className="row"><b>{r.score}/10</b> <Link to={`/customers/${r.customer_id}`}>{r.customer}</Link><span className="muted small">{r.department} · {fmtDate(r.at)}</span><span className="spacer" />
                {r.score <= 6 && (r.followed_up ? <span className="badge ok">called</span> : <button className="link small" onClick={async () => { await api.post(`/api/crm/feedback/${r.id}/followed-up`); reload(); }}>Mark called</button>)}</div>
              {r.comment && <p>{r.comment}</p>}
            </div>
          ))}
        </section>
      </div>
    </>
  );
}

const BLANK: Rule = { name: "", trigger: "invoice_sent", client_types: [], departments: [], delay_days: 2, channel: "email", subject: "Thanks from {company}",
  body: "Hi {first_name},\n\nThanks for having us out for {job}. How did we go?\n\n{feedback_link}\n\nThe team at {company}", ask_feedback: true, ask_review: false,
  min_days_between: 30, active: true };

function Rules({ s }: { s: Settings }) {
  const { data, reload } = useLoad<Rule[]>("/api/crm/rules");
  const [edit, setEdit] = useState<Rule | null>(null);
  const [run, error] = useAction();
  const toggle = (list: string[], v: string) => (list.includes(v) ? list.filter((x) => x !== v) : [...list, v]);
  return (
    <section className="card">
      <div className="row"><h2 style={{ margin: 0 }}>Follow-up rules</h2><span className="spacer" /><button onClick={() => setEdit({ ...BLANK })}>+ Rule</button></div>
      <p className="small muted">Each rule says what to send, to which kinds of customer, and when. Homeowners and maintenance customers can be asked for a Google review;
        commercial and civil clients get a monthly check-in instead. Customers marked "don't send" never get any.</p>
      <DataTable rows={data ?? []} onRow={(r) => setEdit(r)} cols={[
        { key: "n", label: "Rule", render: (r) => <><b>{r.name}</b>{!r.active && <span className="badge">off</span>}</> },
        { key: "t", label: "When", render: (r) => `${s.triggers[r.trigger] ?? r.trigger}${r.delay_days ? `, ${r.delay_days} days later` : ""}` },
        { key: "c", label: "Who", render: (r) => (r.client_types.length ? r.client_types.map((k) => s.client_types[k] ?? k).join(", ") : "Everyone") },
        { key: "a", label: "Asks for", render: (r) => [r.ask_feedback && "feedback", r.ask_review && "Google review"].filter(Boolean).join(" + ") },
        { key: "ch", label: "By", render: (r) => r.channel },
      ]} />
      {edit && (
        <Modal title={edit.id ? edit.name : "New rule"} onClose={() => setEdit(null)} wide>
          <Field label="Name"><input value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
          <div className="settings-grid">
            <Field label="When"><select value={edit.trigger} onChange={(e) => setEdit({ ...edit, trigger: e.target.value })}>{Object.entries(s.triggers).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
            <Field label="Days after"><input type="number" min={0} value={edit.delay_days} onChange={(e) => setEdit({ ...edit, delay_days: Number(e.target.value) })} /></Field>
            <Field label="Send by"><select value={edit.channel} onChange={(e) => setEdit({ ...edit, channel: e.target.value })}><option value="email">Email</option><option value="sms">Text message</option></select></Field>
            <Field label="Not more than once every (days)"><input type="number" min={0} value={edit.min_days_between} onChange={(e) => setEdit({ ...edit, min_days_between: Number(e.target.value) })} /></Field>
          </div>
          <Field label="Client types (none = all)"><div className="chips">{Object.entries(s.client_types).map(([k, l]) => <button key={k} className={edit.client_types.includes(k) ? "chip on" : "chip"} onClick={() => setEdit({ ...edit, client_types: toggle(edit.client_types, k) })}>{l}</button>)}</div></Field>
          <Field label="Departments (none = all)"><div className="chips">{Object.entries(s.departments).map(([k, l]) => <button key={k} className={edit.departments.includes(k) ? "chip on" : "chip"} onClick={() => setEdit({ ...edit, departments: toggle(edit.departments, k) })}>{l}</button>)}</div></Field>
          <div className="row wrap">
            <label className="inline"><input type="checkbox" checked={edit.ask_feedback} onChange={(e) => setEdit({ ...edit, ask_feedback: e.target.checked })} /> Feedback form</label>
            <label className="inline"><input type="checkbox" checked={edit.ask_review} onChange={(e) => setEdit({ ...edit, ask_review: e.target.checked })} /> Offer the Google review link to happy customers (9–10)</label>
            <label className="inline"><input type="checkbox" checked={edit.active} onChange={(e) => setEdit({ ...edit, active: e.target.checked })} /> On</label>
          </div>
          {edit.channel === "email" && <Field label="Subject"><input value={edit.subject} onChange={(e) => setEdit({ ...edit, subject: e.target.value })} /></Field>}
          <Field label="Message" hint="Fill-ins: {first_name} {customer} {job} {job_no} {company} {feedback_link} {invoice_no}">
            <textarea rows={6} value={edit.body} onChange={(e) => setEdit({ ...edit, body: e.target.value })} /></Field>
          <button className="primary" onClick={() => run(async () => { if (edit.id) await api.put(`/api/crm/rules/${edit.id}`, edit); else await api.post("/api/crm/rules", edit); setEdit(null); reload(); })}>Save rule</button>
          <ErrorLine error={error} />
        </Modal>
      )}
    </section>
  );
}

function Messages() {
  const [status, setStatus] = useState("");
  const { data, reload } = useLoad<{ id: number; customer: string; customer_id: number; channel: string; to: string; subject: string; body: string; send_at: string; status: string; error: string }[]>(`/api/crm/messages?status=${status}`, [status]);
  const [run, error] = useAction();
  return (
    <section className="card">
      <div className="row wrap"><div className="tabs compact">{[["", "All"], ["queued", "Waiting"], ["sent", "Sent"], ["failed", "Failed"]].map(([k, l]) => <button key={k} className={status === k ? "active" : ""} onClick={() => setStatus(k)}>{l}</button>)}</div>
        <span className="spacer" /><button onClick={() => run(async () => { await api.post("/api/crm/send-now"); reload(); })}>Send what's due now</button></div>
      <DataTable rows={data ?? []} cols={[
        { key: "w", label: "When", render: (m) => new Date(m.send_at).toLocaleString("en-AU", { dateStyle: "short", timeStyle: "short" }) },
        { key: "c", label: "To", render: (m) => <><Link to={`/customers/${m.customer_id}`}>{m.customer}</Link><div className="small muted">{m.to}</div></> },
        { key: "s", label: "Message", render: (m) => <details><summary>{m.subject || m.body.slice(0, 50)}</summary><pre className="small">{m.body}</pre></details> },
        { key: "st", label: "Status", render: (m) => <><Status value={m.status} />{m.error && <div className="small error">{m.error}</div>}</> },
        { key: "x", label: "", render: (m) => m.status === "queued" && <button className="link small" onClick={() => run(async () => { await api.post(`/api/crm/messages/${m.id}/cancel`); reload(); })}>Cancel</button> },
      ]} />
      <ErrorLine error={error} />
    </section>
  );
}

function Tasks() {
  const { data, reload } = useLoad<{ id: number; customer_id: number; customer: string; text: string; due_date: string | null }[]>("/api/crm/tasks");
  return (
    <section className="card">
      <h2>Call-backs and follow-ups</h2>
      <DataTable rows={data ?? []} cols={[
        { key: "d", label: "By", render: (t) => fmtDate(t.due_date) },
        { key: "c", label: "Customer", render: (t) => <Link to={`/customers/${t.customer_id}`}>{t.customer}</Link> },
        { key: "t", label: "What", render: (t) => t.text },
        { key: "x", label: "", render: (t) => <button className="small" onClick={async () => { await api.put(`/api/crm/activities/${t.id}`, { kind: "task", text: t.text, due_date: t.due_date, done: true }); reload(); }}>Done</button> },
      ]} empty="Nothing to follow up." />
    </section>
  );
}
