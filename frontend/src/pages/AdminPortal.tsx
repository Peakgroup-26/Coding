import { FormEvent, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../App";
import type { Job, Memory, Permissions, Sector, User } from "../types";
import Admin from "./Admin";
import { jobStage } from "./Home";
import ReportingSettings from "./ReportingSettings";
import { Integrations, OpsSettings } from "./AdminOps";

type Tab = "people" | "jobs" | "memory" | "reporting" | "settings" | "integrations" | "operations";

const SECTORS: [Sector, string][] = [["residential", "Res"], ["commercial", "Com"], ["maintenance", "Maint"]];

const PERMS: { key: keyof Permissions; label: string; help: string }[] = [
  { key: "can_hydraulic", label: "Plumbing", help: "Plumbing / hydraulic jobs" },
  { key: "can_civil", label: "Civil", help: "Civil jobs" },
  { key: "can_all_jobs", label: "Everyone's jobs", help: "Other people's jobs and previous tenders. Off = only jobs they started" },
  { key: "can_past_rates", label: "Past civil rates", help: "The previous civil job rates library" },
  { key: "can_pricing", label: "Edit pricing", help: "Change price books, mappings and fitting rules" },
  { key: "can_ops", label: "Operations", help: "Live jobs, scheduling, timesheets, purchasing, plant, customers and CRM" },
  { key: "can_finance", label: "Finance", help: "WIP, budgets, cash flow, invoices, supplier prices and Xero" },
  { key: "can_hr", label: "People (HR)", help: "Staff records, pay history, leave balances, licences, reviews, surveys and hiring" },
];
const TRADES = ["", "plumber", "apprentice", "labourer", "supervisor", "project manager", "office", "manager"];

function People() {
  const { user: me } = useApp();
  const [users, setUsers] = useState<User[]>([]);
  const blank = { email: "", name: "", role: "estimator", password: "", trade: "", cost_rate: 0, can_hydraulic: true, can_civil: true,
    can_all_jobs: true, can_past_rates: true, can_pricing: true, can_ops: true, can_finance: false, can_hr: false };
  const [form, setForm] = useState(blank);
  const [error, setError] = useState("");
  const load = () => api.get<User[]>("/api/users").then(setUsers);
  useEffect(() => { load(); }, []);
  const patch = async (u: User, body: object) => {
    setError("");
    try { await api.patch(`/api/users/${u.id}`, body); load(); } catch (e) { setError((e as Error).message); }
  };
  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try { await api.post("/api/users", form); setForm(blank); load(); } catch (err) { setError((err as Error).message); }
  };
  return (
    <section className="card">
      <h2>People and what they can see</h2>
      <p className="small muted">Admins always see everything. Untick a box to hide that part of the app from someone; it's enforced on the server, not just hidden.</p>
      <table className="perm-table">
        <thead>
          <tr><th>Person</th><th>Role</th><th title="Trade, for the schedule and crew predictions">Trade</th>
            <th title="What an hour costs the business, incl. super, workcover and leave: used for job costing">Cost $/h</th>{PERMS.map((p) => <th key={p.key} title={p.help}>{p.label}</th>)}<th>Sectors</th><th>Active</th><th></th></tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className={u.active ? "" : "inactive"}>
              <td><b>{u.name || u.email}</b><div className="small muted">{u.email}</div></td>
              <td>
                <select value={u.role} disabled={u.id === me.id} onChange={(e) => patch(u, { role: e.target.value })}>
                  <option value="estimator">Estimator</option><option value="reviewer">Reviewer</option><option value="admin">Admin</option>
                  <option value="field">On the tools (phone app only)</option>
                </select>
              </td>
              <td>
                <select value={u.trade ?? ""} onChange={(e) => patch(u, { trade: e.target.value })}>
                  {TRADES.map((t) => <option key={t} value={t}>{t || "–"}</option>)}
                </select>
              </td>
              <td><input type="number" min={0} step="0.5" style={{ width: 80 }} defaultValue={u.cost_rate || ""} placeholder="default"
                         onBlur={(e) => Number(e.target.value || 0) !== (u.cost_rate || 0) && patch(u, { cost_rate: Number(e.target.value || 0) })} /></td>
              {PERMS.map((p) => (
                <td key={p.key} className="c">
                  <input type="checkbox" title={p.help} checked={u.role === "admin" || u[p.key]} disabled={u.role === "admin"}
                         onChange={(e) => patch(u, { [p.key]: e.target.checked })} />
                </td>
              ))}
              <td className="sectors-cell">
                {SECTORS.map(([k, l]) => (
                  <label key={k} className="inline small" title="Untick all three to allow every sector">
                    <input type="checkbox" disabled={u.role === "admin"} checked={u.role === "admin" || !u.sectors?.length || u.sectors.includes(k)}
                           onChange={(e) => {
                             const now = new Set(u.sectors?.length ? u.sectors : SECTORS.map(([x]) => x));
                             if (e.target.checked) now.add(k); else now.delete(k);
                             if (now.size === 0) return;  // at least one sector
                             patch(u, { sectors: [...now] });
                           }} /> {l}
                  </label>
                ))}
              </td>
              <td className="c"><input type="checkbox" checked={u.active} disabled={u.id === me.id} onChange={(e) => patch(u, { active: e.target.checked })} /></td>
              <td><button className="link" onClick={() => {
                const pw = window.prompt(`New password for ${u.email} (8+ characters)`);
                if (pw) patch(u, { password: pw });
              }}>Reset password</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="add-user" onSubmit={add}>
        <h3>Add a person</h3>
        <div className="row wrap">
          <input placeholder="Email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <input placeholder="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            <option value="estimator">Estimator</option><option value="reviewer">Reviewer</option><option value="admin">Admin</option>
            <option value="field">On the tools (phone app only)</option>
          </select>
          <select value={form.trade} onChange={(e) => setForm({ ...form, trade: e.target.value })}>
            {TRADES.map((t) => <option key={t} value={t}>{t || "Trade…"}</option>)}
          </select>
          <input type="number" min={0} placeholder="Cost $/h" style={{ width: 100 }} value={form.cost_rate || ""}
                 onChange={(e) => setForm({ ...form, cost_rate: Number(e.target.value || 0) })} />
          <input placeholder="Starting password (8+)" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        </div>
        <div className="row wrap">
          {PERMS.map((p) => (
            <label key={p.key} className="inline" title={p.help}>
              <input type="checkbox" checked={form[p.key]} onChange={(e) => setForm({ ...form, [p.key]: e.target.checked })} /> {p.label}
            </label>
          ))}
          <button className="primary" type="submit" disabled={!form.email || form.password.length < 8}>Add person</button>
        </div>
        <p className="small muted">They can change their password under My account. Microsoft 365 sign-in also works once it's set up.
          "On the tools" people only get the phone app (clock in, their jobs, POs, pre-starts) and stay signed in on their phone.
          Their login can be a username instead of an email.</p>
      </form>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

function AllJobs() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [users, setUsers] = useState<Record<number, string>>({});
  const [kind, setKind] = useState<"" | "hydraulic" | "civil">("");
  useEffect(() => {
    api.get<Job[]>("/api/jobs").then(setJobs);
    api.get<User[]>("/api/users").then((us) => setUsers(Object.fromEntries(us.map((u) => [u.id, u.name || u.email]))));
  }, []);
  const shown = jobs.filter((j) => !kind || (j.kind ?? "hydraulic") === kind);
  return (
    <section className="card">
      <div className="row">
        <h2 style={{ margin: 0 }}>All jobs</h2>
        <span className="spacer" />
        <div className="tabs">
          {([["", "All"], ["hydraulic", "Plumbing"], ["civil", "Civil"]] as const).map(([k, l]) => (
            <button key={k} className={kind === k ? "active" : ""} onClick={() => setKind(k)}>
              {l} ({jobs.filter((j) => !k || (j.kind ?? "hydraulic") === k).length})
            </button>
          ))}
        </div>
      </div>
      <table>
        <thead><tr><th>Job</th><th>Type</th><th>Client</th><th>Started by</th><th>Started</th><th>Where it's up to</th></tr></thead>
        <tbody>
          {shown.map((j) => {
            const st = jobStage(j);
            return (
              <tr key={j.id}>
                <td><Link to={`/jobs/${j.id}`}>{j.name}</Link></td>
                <td><span className={`badge ${j.kind === "civil" ? "civil" : "hyd"}`}>{j.kind === "civil" ? "Civil" : "Plumbing"}</span></td>
                <td>{j.client}</td>
                <td>{j.created_by ? users[j.created_by] ?? "" : ""}</td>
                <td>{j.created_at ? new Date(j.created_at).toLocaleDateString("en-AU") : ""}</td>
                <td className={`status ${st.tone}`}>{st.text}</td>
              </tr>
            );
          })}
          {shown.length === 0 && <tr><td colSpan={6} className="muted">No jobs.</td></tr>}
        </tbody>
      </table>
    </section>
  );
}

function MemoryAdmin() {
  const [items, setItems] = useState<Memory[]>([]);
  const [showOff, setShowOff] = useState(false);
  const [form, setForm] = useState({ text: "", scope: "company", client: "", kind: "" });
  const [error, setError] = useState("");
  const load = () => api.get<Memory[]>(`/api/memories?include_inactive=${showOff}`).then(setItems);
  useEffect(() => { load(); }, [showOff]); // eslint-disable-line react-hooks/exhaustive-deps
  const patch = async (m: Memory, body: object) => { await api.patch(`/api/memories/${m.id}`, body); load(); };
  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError("");
    try { await api.post("/api/memories", form); setForm({ ...form, text: "" }); load(); } catch (err) { setError((err as Error).message); }
  };
  const remove = async (m: Memory) => {
    if (!window.confirm("Delete this memory for good? (Unticking 'In use' switches it off instead.)")) return;
    await api.del(`/api/memories/${m.id}`);
    load();
  };
  const scopeLabel = (m: Memory) => m.scope === "company" ? "All jobs" : m.scope === "client" ? `Client: ${m.client}` : `Job: ${m.job}`;
  return (
    <section className="card">
      <div className="row">
        <h2 style={{ margin: 0 }}>What the AI remembers</h2>
        <span className="spacer" />
        <label className="inline small"><input type="checkbox" checked={showOff} onChange={(e) => setShowOff(e.target.checked)} /> show switched off</label>
      </div>
      <p className="small muted">
        The AI saves these when someone tells it a preference or corrects it in the chat. They're used in every chat and every
        automatic read they apply to. Edit the wording, switch off anything wrong, or add your own rules.
      </p>
      <table>
        <thead><tr><th>Applies to</th><th>Memory</th><th>Plumbing / civil</th><th>From</th><th>In use</th><th></th></tr></thead>
        <tbody>
          {items.map((m) => (
            <tr key={m.id} className={m.active ? "" : "inactive"}>
              <td className="small">{scopeLabel(m)}</td>
              <td style={{ minWidth: 380 }}>
                <input className="cell wide" defaultValue={m.text} onBlur={(e) => e.target.value !== m.text && patch(m, { text: e.target.value })} />
              </td>
              <td>
                <select value={m.kind} onChange={(e) => patch(m, { kind: e.target.value })}>
                  <option value="">Both</option><option value="hydraulic">Plumbing</option><option value="civil">Civil</option>
                </select>
              </td>
              <td className="small muted">{m.created_by}{m.job ? ` · ${m.job}` : ""}<div>{new Date(m.created_at).toLocaleDateString("en-AU")}</div></td>
              <td className="c"><input type="checkbox" checked={m.active} onChange={(e) => patch(m, { active: e.target.checked })} /></td>
              <td><button className="link danger" onClick={() => remove(m)}>Delete</button></td>
            </tr>
          ))}
          {items.length === 0 && <tr><td colSpan={6} className="muted">Nothing yet. The AI adds memories as you chat with it.</td></tr>}
        </tbody>
      </table>
      <form className="row wrap add-line" onSubmit={add}>
        <b>Add a rule:</b>
        <input required placeholder="e.g. Always price sanitary drainage in ceilings as acoustic PVC" style={{ minWidth: 380 }}
               value={form.text} onChange={(e) => setForm({ ...form, text: e.target.value })} />
        <select value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })}>
          <option value="company">All jobs</option><option value="client">One client</option>
        </select>
        {form.scope === "client" && <input placeholder="Client name" value={form.client} onChange={(e) => setForm({ ...form, client: e.target.value })} />}
        <select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
          <option value="">Plumbing and civil</option><option value="hydraulic">Plumbing</option><option value="civil">Civil</option>
        </select>
        <button type="submit">Add</button>
      </form>
      {error && <p className="error">{error}</p>}
    </section>
  );
}

export default function AdminPortal() {
  const [tab, setTab] = useState<Tab>(() => (new URLSearchParams(window.location.search).get("tab") as Tab) || "people");
  const tabs: [Tab, string][] = [["people", "People & permissions"], ["operations", "Operations & plant"], ["integrations", "Xero & messages"],
    ["jobs", "All jobs"], ["memory", "AI memory"], ["reporting", "Reporting"], ["settings", "Lists & settings"]];
  return (
    <main className="page">
      <h1>Admin portal</h1>
      <div className="tabs big-tabs scroll">
        {tabs.map(([k, l]) => <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>)}
      </div>
      {tab === "people" && <People />}
      {tab === "jobs" && <AllJobs />}
      {tab === "memory" && <MemoryAdmin />}
      {tab === "reporting" && <ReportingSettings />}
      {tab === "settings" && <Admin embedded />}
      {tab === "integrations" && <Integrations />}
      {tab === "operations" && <OpsSettings />}
    </main>
  );
}
