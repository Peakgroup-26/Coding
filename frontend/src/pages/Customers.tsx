/* Customers (the CRM): every customer with their type, contacts, sites, jobs, money owed, feedback score and a timeline. */
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { DataTable, ErrorLine, Field, fmtDate, Modal, money, Status, useAction, useLoad } from "../ui";
import { NewJob, WORK_LABELS } from "./WorkBoard";

export const CLIENT_TYPES: Record<string, string> = { residential: "Residential (homeowner)", maintenance: "Maintenance customer", strata: "Strata / real estate",
  builder: "Builder", commercial: "Commercial client", civil: "Civil client", government: "Government / council", other: "Other" };
interface CustBase { id: number; name: string; kind: string; email: string; phone: string; address: string; abn: string; terms_days: number; notes: string; active: boolean; no_marketing: boolean }
interface Cust extends CustBase { jobs?: number }

export default function Customers() {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const { data, reload } = useLoad<Cust[]>(`/api/customers?q=${encodeURIComponent(q)}&kind=${kind}`, [q, kind]);
  const [adding, setAdding] = useState(false);
  const nav = useNavigate();
  return (
    <main className="page">
      <div className="row wrap"><h1 style={{ margin: 0 }}>Customers</h1><span className="spacer" />
        <input placeholder="Search name, email, phone" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="primary" onClick={() => setAdding(true)}>+ Customer</button></div>
      <div className="chips">{[["", "All"], ...Object.entries(CLIENT_TYPES)].map(([k, l]) => <button key={k} className={kind === k ? "chip on" : "chip"} onClick={() => setKind(k)}>{l}</button>)}</div>
      <section className="card">
        <DataTable rows={data ?? []} onRow={(c) => nav(`/customers/${c.id}`)} cols={[
          { key: "n", label: "Customer", render: (c) => <b>{c.name}</b> },
          { key: "k", label: "Type", render: (c) => CLIENT_TYPES[c.kind] ?? c.kind },
          { key: "p", label: "Phone", hideSm: true, render: (c) => c.phone },
          { key: "e", label: "Email", hideSm: true, render: (c) => c.email },
          { key: "j", label: "Jobs", num: true, render: (c) => c.jobs ?? 0 },
        ]} />
      </section>
      {adding && <CustomerEditor onClose={() => setAdding(false)} onSaved={(id) => { setAdding(false); reload(); nav(`/customers/${id}`); }} />}
    </main>
  );
}

function CustomerEditor({ c, onClose, onSaved }: { c?: CustBase; onClose: () => void; onSaved: (id: number) => void }) {
  const [f, setF] = useState<Partial<CustBase>>(c ?? { kind: "residential", terms_days: 14, active: true });
  const [run, error] = useAction();
  return (
    <Modal title={c ? c.name : "New customer"} onClose={onClose}>
      <Field label="Name"><input value={f.name ?? ""} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
      <Field label="Type" hint="Decides which follow-ups and feedback requests they get"><select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
        {Object.entries(CLIENT_TYPES).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
      <div className="settings-grid">
        {(["email", "phone", "address", "abn"] as const).map((k) => <Field key={k} label={k.toUpperCase() === "ABN" ? "ABN" : k}><input value={String(f[k] ?? "")} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></Field>)}
        <Field label="Payment terms (days)"><input type="number" value={f.terms_days} onChange={(e) => setF({ ...f, terms_days: Number(e.target.value) })} /></Field>
      </div>
      <label className="check-line"><input type="checkbox" checked={!!f.no_marketing} onChange={(e) => setF({ ...f, no_marketing: e.target.checked })} /> Don't send review or feedback requests</label>
      <Field label="Notes"><textarea rows={2} value={f.notes ?? ""} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
      <button className="primary" disabled={!f.name} onClick={() => run(async () => {
        const body = { name: f.name, kind: f.kind, email: f.email ?? "", phone: f.phone ?? "", address: f.address ?? "", abn: f.abn ?? "", terms_days: f.terms_days ?? 14,
          notes: f.notes ?? "", active: f.active ?? true, no_marketing: !!f.no_marketing };
        const r = c ? await api.put<Cust>(`/api/customers/${c.id}`, body) : await api.post<Cust>("/api/customers", body);
        onSaved(r.id);
      })}>Save</button><ErrorLine error={error} />
    </Modal>
  );
}

interface Detail extends CustBase {
  contacts: { id: number; name: string; position: string; phone: string; email: string }[];
  sites: { id: number; name: string; address: string; access_notes: string }[];
  jobs: { id: number; job_no: string; name: string; work_status: string; sector: string; contract_value: number | null }[];
  nps: number | null; invoiced_total: number; owing: number;
  feedback: { id: number; kind: string; period: string; score: number | null; comment: string; sent: string; responded_at: string | null }[];
  activities: { id: number; kind: string; text: string; due_date: string | null; done: boolean; user: string; at: string }[];
  messages: { id: number; subject: string; channel: string; status: string; send_at: string; error: string }[];
}

export function CustomerPage() {
  const { customerId } = useParams();
  const nav = useNavigate();
  const { data: c, reload } = useLoad<Detail>(`/api/customers/${customerId}`);
  const rules = useLoad<{ id: number; name: string }[]>("/api/crm/rules");
  const [edit, setEdit] = useState(false);
  const [newJob, setNewJob] = useState(false);
  const [note, setNote] = useState({ kind: "note", text: "", due_date: "" });
  const [contact, setContact] = useState({ name: "", position: "", phone: "", email: "" });
  const [site, setSite] = useState({ name: "", address: "", access_notes: "" });
  const [run, error] = useAction();
  const [msg, setMsg] = useState("");
  if (!c) return <main className="page">Loading…</main>;
  return (
    <main className="page">
      <Link to="/customers" className="small">‹ Customers</Link>
      <div className="row wrap"><h1 style={{ margin: 0 }}>{c.name}</h1><span className="badge">{CLIENT_TYPES[c.kind] ?? c.kind}</span><span className="spacer" />
        <button onClick={() => setEdit(true)}>Edit</button><button className="primary" onClick={() => setNewJob(true)}>+ Job for {c.name.split(" ")[0]}</button></div>
      <p className="muted small">{[c.phone, c.email, c.address, c.abn && `ABN ${c.abn}`, `${c.terms_days} day terms`].filter(Boolean).join(" · ")}</p>
      <div className="tiles">
        <div className="tile"><b>{c.jobs.length}</b><span>jobs</span></div>
        <div className="tile"><b>{money(c.invoiced_total)}</b><span>invoiced</span></div>
        <div className={`tile ${c.owing > 0 ? "warn" : ""}`}><b>{money(c.owing)}</b><span>owing</span></div>
        <div className="tile"><b>{c.nps === null ? "–" : c.nps}</b><span>NPS from {c.feedback.filter((f) => f.score !== null).length} responses</span></div>
      </div>
      <div className="two-col even">
        <section className="card">
          <h2>Jobs</h2>
          <DataTable rows={c.jobs} onRow={(j) => nav(j.work_status ? `/work/${j.id}` : `/jobs/${j.id}`)} cols={[
            { key: "n", label: "Job", render: (j) => <><b>{j.job_no}</b> {j.name}</> },
            { key: "s", label: "Status", render: (j) => (j.work_status ? <Status value={j.work_status} labels={WORK_LABELS} /> : "quote") },
            { key: "v", label: "Value", num: true, render: (j) => money(j.contract_value) },
          ]} />
          <h2>Contacts</h2>
          {c.contacts.map((x) => <div key={x.id} className="kv-row"><span><b>{x.name}</b> {x.position}</span><span className="small">{[x.phone, x.email].filter(Boolean).join(" · ")}
            <button className="link small" onClick={() => run(async () => { await api.del(`/api/customers/${c.id}/contacts/${x.id}`); reload(); })}>✕</button></span></div>)}
          <div className="row wrap">{(["name", "position", "phone", "email"] as const).map((k) => <input key={k} placeholder={k} value={contact[k]} onChange={(e) => setContact({ ...contact, [k]: e.target.value })} />)}
            <button disabled={!contact.name} onClick={() => run(async () => { await api.post(`/api/customers/${c.id}/contacts`, contact); setContact({ name: "", position: "", phone: "", email: "" }); reload(); })}>Add contact</button></div>
          <h2>Sites</h2>
          {c.sites.map((s) => <div key={s.id} className="kv-row"><span><b>{s.name}</b> {s.address}</span><span className="small muted">{s.access_notes}</span></div>)}
          <div className="row wrap">{(["name", "address", "access_notes"] as const).map((k) => <input key={k} placeholder={k.replace("_", " ")} value={site[k]} onChange={(e) => setSite({ ...site, [k]: e.target.value })} />)}
            <button disabled={!site.name} onClick={() => run(async () => { await api.post("/api/sites", { ...site, customer_id: c.id }); setSite({ name: "", address: "", access_notes: "" }); reload(); })}>Add site</button></div>
        </section>
        <section className="card">
          <h2>Timeline</h2>
          <div className="row wrap">
            <select value={note.kind} onChange={(e) => setNote({ ...note, kind: e.target.value })}>{[["note", "Note"], ["call", "Call"], ["meeting", "Meeting"], ["task", "Follow-up task"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
            <input style={{ flex: 1 }} placeholder="What happened / what to do" value={note.text} onChange={(e) => setNote({ ...note, text: e.target.value })} />
            {note.kind === "task" && <input type="date" value={note.due_date} onChange={(e) => setNote({ ...note, due_date: e.target.value })} />}
            <button disabled={!note.text} onClick={() => run(async () => { await api.post(`/api/crm/customers/${c.id}/activities`, { ...note, due_date: note.due_date || null }); setNote({ kind: "note", text: "", due_date: "" }); reload(); })}>Add</button>
          </div>
          <div className="row wrap small">Send now:
            {rules.data?.map((r) => <button key={r.id} className="link small" onClick={() => run(async () => { const m = await api.post<{ status: string; error: string }>("/api/crm/request-feedback", { customer_id: c.id, rule_id: r.id }); setMsg(m.status === "sent" ? "Sent." : m.error || "Queued."); reload(); })}>{r.name}</button>)}</div>
          {msg && <p className="small">{msg}</p>}
          <ul className="timeline">
            {c.activities.map((a) => (
              <li key={a.id} className={`t-${a.kind} ${a.done ? "done" : ""}`}>
                <span className="small muted">{new Date(a.at).toLocaleDateString("en-AU")} {a.user}</span>
                <span>{a.kind === "task" && <input type="checkbox" checked={a.done} onChange={(e) => run(async () => { await api.put(`/api/crm/activities/${a.id}`, { kind: a.kind, text: a.text, due_date: a.due_date, done: e.target.checked }); reload(); })} />}
                  {a.text}{a.due_date && !a.done && <span className="badge warn">by {fmtDate(a.due_date)}</span>}</span>
              </li>
            ))}
          </ul>
          <h3>Feedback</h3>
          {c.feedback.map((f) => <div key={f.id} className="kv-row"><span>{f.kind === "monthly" ? `Monthly ${f.period}` : "Job"} · {f.score === null ? <span className="muted">no answer yet</span> : <b className={f.score >= 9 ? "ok" : f.score <= 6 ? "error" : ""}>{f.score}/10</b>}</span>
            <span className="small">{f.comment}</span></div>)}
          <ErrorLine error={error} />
        </section>
      </div>
      {edit && <CustomerEditor c={c} onClose={() => setEdit(false)} onSaved={() => { setEdit(false); reload(); }} />}
      {newJob && <NewJob onClose={() => setNewJob(false)} onMade={(id) => nav(`/work/${id}`)}
                         defaults={{ customer_id: c.id, customer_name: c.name, sector: c.kind === "residential" ? "residential" : ["builder", "commercial", "civil", "government"].includes(c.kind) ? "commercial" : "maintenance" }} />}
    </main>
  );
}
