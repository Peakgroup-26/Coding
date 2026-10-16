/* People (the BambooHR side, for whoever has the People permission): the team, an org chart, everyone's leave,
   licences and tickets, onboarding steps, hiring, reviews, staff surveys, policies to sign, news and the HR reports.
   /people/:userId is one person's record. */
import { FormEvent, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, fetchBlobUrl, upload } from "../api";
import { Avatar, DataTable, ErrorLine, Field, fmtDate, Modal, money, num, Status, Tabs, todayIso, useAction, useLoad } from "../ui";
import { Balance, Cred, CRED_LABEL, OrgChart, Person } from "./FieldMe";

interface Row extends Person { employment_type: string; start_date: string | null; years_of_service: number | null; missing: number; expired: number; expiring: number; active: boolean }
interface Options {
  departments: string[]; employment_types: string[]; stages: string[];
  credential_types: { id: number; name: string; category: string; renew_months: number | null; required_for: string[]; active: boolean }[];
  checklists: { id: number; name: string; kind: string; tasks: { title: string; who: string; due_days: number }[]; active: boolean }[];
  policies: { id: number; kind: string; name: string; hours_per_year: number; accrues_on_hours: boolean; after_years: number; casuals: boolean; active: boolean }[];
  review_questions: { key: string; label: string; type: string }[];
}
const TYPE_LABEL: Record<string, string> = { full_time: "Full time", part_time: "Part time", casual: "Casual", apprentice: "Apprentice", contractor: "Contractor" };
const STAGE_LABEL: Record<string, string> = { applied: "Applied", screen: "Phone screen", interview: "Interview", offer: "Offer", hired: "Hired", rejected: "Not this time" };
type Tab = "team" | "chart" | "leave" | "licences" | "onboarding" | "hiring" | "reviews" | "surveys" | "policies" | "news" | "reports" | "setup";

export default function People() {
  const [sp, setSp] = useSearchParams();
  const tab = (sp.get("tab") as Tab) || "team";
  const { data: opts, reload: reloadOpts } = useLoad<Options>("/api/people/options");
  return (
    <main className="page">
      <div className="row"><h1 style={{ margin: 0 }}>People</h1></div>
      <Tabs<Tab> value={tab} onChange={(t) => setSp({ tab: t })} tabs={[["team", "Team"], ["chart", "Org chart"], ["leave", "Leave"], ["licences", "Licences & training"],
        ["onboarding", "On/offboarding"], ["hiring", "Hiring"], ["reviews", "Reviews"], ["surveys", "Surveys & eNPS"], ["policies", "Policies to sign"],
        ["news", "News"], ["reports", "Reports"], ["setup", "Set-up"]]} />
      {tab === "team" && opts && <Team opts={opts} />}
      {tab === "chart" && <ChartTab />}
      {tab === "leave" && <LeaveTab />}
      {tab === "licences" && <Licences />}
      {tab === "onboarding" && <Onboarding />}
      {tab === "hiring" && opts && <Hiring opts={opts} />}
      {tab === "reviews" && <Reviews />}
      {tab === "surveys" && <Surveys />}
      {tab === "policies" && <Policies />}
      {tab === "news" && <News />}
      {tab === "reports" && <Reports />}
      {tab === "setup" && opts && <Setup opts={opts} onChange={reloadOpts} />}
    </main>
  );
}

function Team({ opts }: { opts: Options }) {
  const [left, setLeft] = useState(false);
  const { data, reload } = useLoad<Row[]>(`/api/people?include_left=${left}`, [left]);
  const [adding, setAdding] = useState(false);
  const [q, setQ] = useState("");
  const nav = useNavigate();
  if (!data) return <p className="muted">Loading…</p>;
  const rows = data.filter((p) => !q || `${p.name} ${p.position} ${p.department} ${p.trade}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <div className="row wrap">
        <input placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="inline small"><input type="checkbox" checked={left} onChange={(e) => setLeft(e.target.checked)} /> Show people who've left</label>
        <span className="spacer" /><button className="primary" onClick={() => setAdding(true)}>+ New starter</button>
      </div>
      <DataTable rows={rows} onRow={(p) => nav(`/people/${p.user_id}`)} cols={[
        { key: "n", label: "Name", render: (p) => <span className="row" style={{ margin: 0 }}><Avatar userId={p.user_id} name={p.name} has={p.has_photo} small /><b>{p.name}</b></span> },
        { key: "p", label: "Position", render: (p) => p.position || p.trade },
        { key: "d", label: "Department", render: (p) => p.department, hideSm: true },
        { key: "t", label: "Type", render: (p) => TYPE_LABEL[p.employment_type] ?? "", hideSm: true },
        { key: "s", label: "Started", render: (p) => p.start_date ? `${fmtDate(p.start_date)} (${num(p.years_of_service, 1)} y)` : "", hideSm: true },
        { key: "m", label: "Manager", render: (p) => p.manager, hideSm: true },
        { key: "c", label: "Licences", render: (p) => p.expired || p.missing ? <span className="bad">{[p.expired && `${p.expired} expired`, p.missing && `${p.missing} missing`].filter(Boolean).join(", ")}</span>
          : p.expiring ? <span className="warn">{p.expiring} expiring</span> : <span className="ok">OK</span> },
        { key: "a", label: "", render: (p) => !p.active ? <span className="muted">Left</span> : p.status === "terminated" ? <span className="warn">Leaving</span> : "" },
      ]} />
      {adding && <NewStarter opts={opts} people={data} onClose={() => setAdding(false)} onDone={(id) => { setAdding(false); reload(); nav(`/people/${id}`); }} />}
    </>
  );
}

function NewStarter({ opts, people, onClose, onDone }: { opts: Options; people: Row[]; onClose: () => void; onDone: (id: number) => void }) {
  const starter = opts.checklists.find((c) => c.kind === "onboarding" && c.active);
  const [f, setF] = useState({ name: "", email: "", password: "", role: "field", trade: "plumber", phone: "", position: "", department: "plumbing",
    employment_type: "full_time", start_date: todayIso(), manager_id: "", checklist_id: starter ? String(starter.id) : "" });
  const [run, err, busy] = useAction();
  const set = (k: string, v: string) => setF({ ...f, [k]: v });
  return (
    <Modal title="New starter" onClose={onClose}>
      <form className="form" onSubmit={(e: FormEvent) => { e.preventDefault(); run(async () => {
        const r = await api.post<{ user_id: number }>("/api/people", { ...f, manager_id: f.manager_id ? +f.manager_id : null, checklist_id: f.checklist_id ? +f.checklist_id : null });
        onDone(r.user_id);
      }); }}>
        <Field label="Full name"><input required value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Email (they sign in with this)"><input type="email" required value={f.email} onChange={(e) => set("email", e.target.value)} /></Field>
        <Field label="First password" hint="At least 8 characters. Give it to them on their first day; they can change it in My account.">
          <div className="row" style={{ margin: 0 }}><input required minLength={8} value={f.password} onChange={(e) => set("password", e.target.value)} />
            <button type="button" onClick={async () => set("password", (await api.get<{ password: string }>("/api/field/me/new-password")).password)}>Make one</button></div></Field>
        <div className="row wrap">
          <Field label="Uses"><select value={f.role} onChange={(e) => set("role", e.target.value)}><option value="field">Phone app (on the tools)</option>
            <option value="estimator">Office app</option><option value="reviewer">Office app + sign-off</option></select></Field>
          <Field label="Trade"><select value={f.trade} onChange={(e) => set("trade", e.target.value)}>
            {["plumber", "apprentice", "labourer", "supervisor", "project manager", "office", "manager"].map((t) => <option key={t}>{t}</option>)}</select></Field>
        </div>
        <div className="row wrap">
          <Field label="Position"><input value={f.position} onChange={(e) => set("position", e.target.value)} placeholder="e.g. Licensed plumber" /></Field>
          <Field label="Department"><select value={f.department} onChange={(e) => set("department", e.target.value)}>{opts.departments.map((d) => <option key={d}>{d}</option>)}</select></Field>
          <Field label="Type"><select value={f.employment_type} onChange={(e) => set("employment_type", e.target.value)}>{opts.employment_types.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}</select></Field>
        </div>
        <div className="row wrap">
          <Field label="Start date"><input type="date" value={f.start_date} onChange={(e) => set("start_date", e.target.value)} /></Field>
          <Field label="Reports to"><select value={f.manager_id} onChange={(e) => set("manager_id", e.target.value)}><option value="">–</option>
            {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name}</option>)}</select></Field>
          <Field label="Mobile"><input value={f.phone} onChange={(e) => set("phone", e.target.value)} /></Field>
        </div>
        <Field label="Onboarding checklist"><select value={f.checklist_id} onChange={(e) => set("checklist_id", e.target.value)}><option value="">None</option>
          {opts.checklists.filter((c) => c.kind === "onboarding").map((c) => <option key={c.id} value={c.id}>{c.name} ({c.tasks.length} steps)</option>)}</select></Field>
        <button className="primary" disabled={busy}>Add {f.name || "them"}</button>
        <ErrorLine error={err} />
      </form>
    </Modal>
  );
}

function ChartTab() {
  const { data } = useLoad<Person[]>("/api/field/me/directory");
  const nav = useNavigate();
  if (!data) return <p className="muted">Loading…</p>;
  return <div className="card"><OrgChart people={data} onPick={(p) => nav(`/people/${p.user_id}`)} /><p className="muted small">Set who reports to whom on each person's Job tab.</p></div>;
}

function LeaveTab() {
  const { data } = useLoad<{ user_id: number; name: string; balances: Balance[] }[]>("/api/people/leave");
  const { data: req, reload } = useLoad<{ id: number; user_id: number; name: string; kind: string; start_date: string; end_date: string; hours: number | null; status: string; notes: string }[]>("/api/time-off?status=requested");
  const [run, err] = useAction();
  if (!data) return <p className="muted">Loading…</p>;
  const kinds = Array.from(new Set(data.flatMap((p) => p.balances.map((b) => b.kind))));
  const names = Object.fromEntries(data.flatMap((p) => p.balances.map((b) => [b.kind, b.name])));
  const total = (k: string) => data.reduce((s, p) => s + (p.balances.find((b) => b.kind === k)?.value ?? 0), 0);
  return (
    <>
      {req && req.length > 0 && (
        <section className="card">
          <h2>Waiting for approval</h2>
          {req.map((t) => (
            <div key={t.id} className="row wrap">
              <b>{t.name}</b><span>{t.kind}</span><span>{fmtDate(t.start_date)} – {fmtDate(t.end_date)}</span><span className="muted">{t.notes}</span><span className="spacer" />
              <button onClick={() => run(async () => { await api.put(`/api/time-off/${t.id}`, { status: "approved" }); await reload(); })}>Approve</button>
              <button className="danger" onClick={() => run(async () => { await api.put(`/api/time-off/${t.id}`, { status: "declined" }); await reload(); })}>Decline</button>
            </div>
          ))}
          <ErrorLine error={err} />
        </section>
      )}
      <section className="card">
        <h2>Balances (hours)</h2>
        <DataTable rows={data} cols={[
          { key: "n", label: "Name", render: (p) => <Link to={`/people/${p.user_id}`}>{p.name}</Link> },
          ...kinds.map((k) => ({ key: k, label: names[k], num: true, render: (p: { balances: Balance[] }) => {
            const b = p.balances.find((x) => x.kind === k);
            return b ? <span title={`Built up ${num(b.accrued, 1)} h, taken ${num(b.taken, 1)} h`} className={b.balance < 0 ? "bad" : ""}>{num(b.balance, 1)}
              {b.booked_or_requested > 0 && <small className="muted"> ({num(b.booked_or_requested, 1)} booked)</small>}</span> : "–";
          } })),
          { key: "v", label: "Owed ($)", num: true, render: (p) => money(p.balances.filter((b) => b.kind === "annual" || b.kind === "long_service").reduce((s, b) => s + (b.value ?? 0), 0)) },
        ]} />
        <p className="small muted">Leave owed (annual and long service) for everyone: {money(total("annual") + total("long_service"))}. Built up from approved timesheet hours.
          Opening balances go on each person's Leave tab. Xero Payroll is still the pay run.</p>
      </section>
    </>
  );
}

function Licences() {
  const { data } = useLoad<Cred[]>("/api/people/credentials");
  const [show, setShow] = useState<"attention" | "all">("attention");
  if (!data) return <p className="muted">Loading…</p>;
  const rows = show === "all" ? data : data.filter((c) => c.status !== "current" || !c.verified);
  return (
    <>
      <div className="row"><Tabs value={show} onChange={setShow} tabs={[["attention", "Needs attention"], ["all", "Everything"]]} /></div>
      <DataTable rows={rows} empty="Nothing expiring or waiting to be checked." cols={[
        { key: "n", label: "Person", render: (c) => <Link to={`/people/${c.user_id}`}>{c.name}</Link> },
        { key: "t", label: "Licence / ticket", render: (c) => c.type },
        { key: "no", label: "Number", render: (c) => c.number, hideSm: true },
        { key: "e", label: "Expires", render: (c) => c.expires ? fmtDate(c.expires) : "No expiry" },
        { key: "s", label: "", render: (c) => <Status value={c.status} labels={CRED_LABEL} /> },
        { key: "v", label: "Checked", render: (c) => c.verified ? "✓" : <span className="warn">To check</span> },
      ]} />
    </>
  );
}

interface TaskRow { id: number; user_id: number; person: string; kind: string; title: string; who: string; assignee: string; due: string | null; done: boolean; overdue: boolean }
function Onboarding() {
  const { data, reload } = useLoad<TaskRow[]>("/api/people/tasks");
  const [run, err] = useAction();
  if (!data) return <p className="muted">Loading…</p>;
  const people = Array.from(new Set(data.map((t) => t.person)));
  return (
    <>
      {people.length === 0 && <p className="muted">No onboarding or offboarding under way. Start one from a person's record, or add a new starter.</p>}
      {people.map((p) => {
        const ts = data.filter((t) => t.person === p);
        return (
          <section key={p} className="card">
            <div className="row"><h2 style={{ margin: 0 }}><Link to={`/people/${ts[0].user_id}`}>{p}</Link></h2><span className="muted small">{ts[0].kind}</span></div>
            {ts.map((t) => (
              <label key={t.id} className={`inline task-row ${t.overdue ? "bad" : ""}`}>
                <input type="checkbox" checked={t.done} onChange={() => run(async () => { await api.put(`/api/people/tasks/${t.id}`, { done: !t.done }); await reload(); })} />
                <span>{t.title} <small className="muted">· {t.assignee || t.who}{t.due && ` · ${fmtDate(t.due)}`}</small></span>
              </label>
            ))}
          </section>
        );
      })}
      <ErrorLine error={err} />
    </>
  );
}

interface Opening { id: number; title: string; department: string; employment_type: string; location: string; pay: string; description: string;
  questions: { key: string; label: string }[]; status: string; hiring_manager_id: number | null; candidates: number; by_stage: Record<string, number> }
interface Cand { id: number; opening_id: number | null; opening: string; name: string; email: string; phone: string; stage: string; rating: number | null;
  source: string; answers: Record<string, string>; cover_note: string; has_resume: boolean; resume_name: string; hired_user_id: number | null; created_at: string;
  notes?: { id: number; by: string; text: string; at: string }[] }

function Hiring({ opts }: { opts: Options }) {
  const { data: openings, reload } = useLoad<Opening[]>("/api/people/openings");
  const [sel, setSel] = useState<number | null>(null);
  const { data: cands, reload: reloadC } = useLoad<Cand[]>(`/api/people/candidates${sel ? `?opening_id=${sel}` : ""}`, [sel]);
  const [edit, setEdit] = useState<Opening | "new" | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [run, err] = useAction();
  if (!openings) return <p className="muted">Loading…</p>;
  const careers = `${window.location.origin}/careers`;
  return (
    <>
      <div className="row wrap">
        <select value={sel ?? ""} onChange={(e) => setSel(e.target.value ? +e.target.value : null)}>
          <option value="">All jobs</option>{openings.map((o) => <option key={o.id} value={o.id}>{o.title} ({o.candidates})</option>)}</select>
        <button onClick={() => setEdit("new")}>+ Job opening</button>
        {sel && <button onClick={() => setEdit(openings.find((o) => o.id === sel) ?? null)}>Edit opening</button>}
        <span className="spacer" /><span className="small">Careers page: <a href={careers} target="_blank" rel="noreferrer">{careers}</a></span>
      </div>
      <div className="pipeline">
        {opts.stages.map((st) => (
          <div key={st} className="pipe-col" onDragOver={(e) => e.preventDefault()} onDrop={(e) => {
            const id = +e.dataTransfer.getData("text/plain");
            if (st !== "hired") run(async () => { await api.patch(`/api/people/candidates/${id}`, { stage: st }); await reloadC(); });
          }}>
            <h3>{STAGE_LABEL[st]} ({(cands ?? []).filter((c) => c.stage === st).length})</h3>
            {(cands ?? []).filter((c) => c.stage === st).map((c) => (
              <div key={c.id} className="pipe-card" draggable onDragStart={(e) => e.dataTransfer.setData("text/plain", String(c.id))} onClick={() => setOpen(c.id)}>
                <b>{c.name}</b><div className="small muted">{c.opening}</div>{c.rating && <div className="small">{"★".repeat(c.rating)}</div>}
              </div>
            ))}
          </div>
        ))}
      </div>
      <ErrorLine error={err} />
      {edit && <OpeningForm o={edit === "new" ? null : edit} opts={opts} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
      {open && <CandidateModal id={open} opts={opts} onClose={() => { setOpen(null); reloadC(); reload(); }} />}
    </>
  );
}

function OpeningForm({ o, opts, onClose, onDone }: { o: Opening | null; opts: Options; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ title: o?.title ?? "", department: o?.department ?? "plumbing", employment_type: o?.employment_type ?? "full_time",
    location: o?.location ?? "Sunshine Coast", pay: o?.pay ?? "", description: o?.description ?? "", status: o?.status ?? "open",
    questions: (o?.questions ?? []).map((q) => q.label).join("\n") });
  const [run, err, busy] = useAction();
  const set = (k: string, v: string) => setF({ ...f, [k]: v });
  return (
    <Modal title={o ? "Edit job opening" : "New job opening"} onClose={onClose} wide>
      <form className="form" onSubmit={(e) => { e.preventDefault(); run(async () => {
        const body = { ...f, questions: f.questions.split("\n").map((l) => l.trim()).filter(Boolean).map((label, i) => ({ key: `q${i + 1}`, label })) };
        if (o) await api.put(`/api/people/openings/${o.id}`, body); else await api.post("/api/people/openings", body);
        onDone();
      }); }}>
        <Field label="Job title"><input required value={f.title} onChange={(e) => set("title", e.target.value)} placeholder="e.g. Licensed plumber – maintenance" /></Field>
        <div className="row wrap">
          <Field label="Department"><select value={f.department} onChange={(e) => set("department", e.target.value)}>{opts.departments.map((d) => <option key={d}>{d}</option>)}</select></Field>
          <Field label="Type"><select value={f.employment_type} onChange={(e) => set("employment_type", e.target.value)}>{opts.employment_types.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}</select></Field>
          <Field label="Where"><input value={f.location} onChange={(e) => set("location", e.target.value)} /></Field>
          <Field label="Pay (shown on the ad)"><input value={f.pay} onChange={(e) => set("pay", e.target.value)} placeholder="$42–48/h + van" /></Field>
        </div>
        <Field label="About the job"><textarea rows={6} value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        <Field label="Extra questions on the form (one per line)"><textarea rows={3} value={f.questions} onChange={(e) => set("questions", e.target.value)} placeholder={"Do you have a C class licence?\nWhen could you start?"} /></Field>
        <Field label="Status"><select value={f.status} onChange={(e) => set("status", e.target.value)}><option value="draft">Draft</option><option value="open">Open (on the careers page)</option><option value="closed">Closed</option></select></Field>
        <button className="primary" disabled={busy}>Save</button>
        <ErrorLine error={err} />
      </form>
    </Modal>
  );
}

function CandidateModal({ id, opts, onClose }: { id: number; opts: Options; onClose: () => void }) {
  const { data: c, reload } = useLoad<Cand>(`/api/people/candidates/${id}`);
  const [note, setNote] = useState("");
  const [hiring, setHiring] = useState(false);
  const [h, setH] = useState({ email: "", role: "field", trade: "plumber", start: todayIso(), checklist_id: "" });
  const [run, err, busy] = useAction();
  const nav = useNavigate();
  if (!c) return null;
  const patch = (body: Record<string, unknown>) => run(async () => { await api.patch(`/api/people/candidates/${id}`, body); await reload(); });
  return (
    <Modal title={c.name} onClose={onClose} wide>
      <p className="muted">{c.opening} · {c.email} · {c.phone} · applied {fmtDate(c.created_at)} via {c.source}</p>
      <div className="row wrap">
        <span>Rating</span>{[1, 2, 3, 4, 5].map((n) => <button key={n} className={`link ${c.rating && c.rating >= n ? "star on" : "star"}`} onClick={() => patch({ rating: n })}>★</button>)}
        <span className="spacer" />
        <select value={c.stage} disabled={c.stage === "hired"} onChange={(e) => patch({ stage: e.target.value })}>
          {opts.stages.filter((s) => s !== "hired" || c.stage === "hired").map((s) => <option key={s} value={s}>{STAGE_LABEL[s]}</option>)}</select>
        {c.has_resume && <button onClick={async () => window.open(await fetchBlobUrl(`/api/people/candidates/${c.id}/resume`))}>📄 Résumé</button>}
        {!c.hired_user_id && <button className="primary" onClick={() => { setHiring(true); setH({ ...h, email: c.email }); }}>Hire</button>}
        {c.hired_user_id && <Link to={`/people/${c.hired_user_id}`}>Their record ›</Link>}
      </div>
      {c.cover_note && <p className="policy-text">{c.cover_note}</p>}
      {Object.entries(c.answers || {}).map(([k, v]) => <p key={k} className="small"><b>{k}:</b> {v}</p>)}
      {hiring && (
        <div className="card form">
          <h3>Hire {c.name}</h3>
          <div className="row wrap">
            <Field label="Sign-in email"><input value={h.email} onChange={(e) => setH({ ...h, email: e.target.value })} /></Field>
            <Field label="Uses"><select value={h.role} onChange={(e) => setH({ ...h, role: e.target.value })}><option value="field">Phone app</option><option value="estimator">Office app</option></select></Field>
            <Field label="Trade"><input value={h.trade} onChange={(e) => setH({ ...h, trade: e.target.value })} /></Field>
            <Field label="Start"><input type="date" value={h.start} onChange={(e) => setH({ ...h, start: e.target.value })} /></Field>
            <Field label="Onboarding"><select value={h.checklist_id} onChange={(e) => setH({ ...h, checklist_id: e.target.value })}><option value="">Default</option>
              {opts.checklists.filter((x) => x.kind === "onboarding").map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}</select></Field>
          </div>
          <button className="primary" disabled={busy} onClick={() => run(async () => {
            const r = await api.post<{ user_id: number }>(`/api/people/candidates/${id}/hire`, { ...h, checklist_id: h.checklist_id ? +h.checklist_id : null });
            nav(`/people/${r.user_id}`);
          })}>Hire and start onboarding</button>
          <p className="small muted">Then set their first password in Admin → Users.</p>
        </div>
      )}
      <h3>Notes</h3>
      {(c.notes ?? []).map((n) => <p key={n.id} className="small"><b>{n.by}</b> <span className="muted">{fmtDate(n.at)}</span><br />{n.text}</p>)}
      <div className="row"><input style={{ flex: 1 }} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Interview notes, reference checks…" />
        <button disabled={!note} onClick={() => { patch({ note }); setNote(""); }}>Add</button></div>
      <ErrorLine error={err} />
    </Modal>
  );
}

interface Cycle { id: number; name: string; due: string | null; status: string; reviews: { id: number; user_id: number; name: string; reviewer: string; reviewer_id: number | null; self_done: boolean; manager_done: boolean; shared: boolean; overall: number | null }[] }
function Reviews() {
  const { data, reload } = useLoad<Cycle[]>("/api/people/reviews");
  const { data: people } = useLoad<Row[]>("/api/people");
  const [f, setF] = useState({ name: "", due: "" });
  const [who, setWho] = useState<number[]>([]);
  const [run, err, busy] = useAction();
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <>
      <section className="card">
        <h2>Start a review round</h2>
        <div className="row wrap">
          <input placeholder="e.g. 2026 annual review" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
          <label className="inline small">Due <input type="date" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></label>
          <button className="primary" disabled={busy || !f.name} onClick={() => run(async () => {
            await api.post("/api/people/reviews", { name: f.name, due: f.due || null, user_ids: who }); setF({ name: "", due: "" }); setWho([]); await reload();
          })}>Start</button>
        </div>
        <div className="chips">{(people ?? []).map((p) => (
          <button key={p.user_id} className={`chip ${who.includes(p.user_id) ? "on" : ""}`} onClick={() => setWho(who.includes(p.user_id) ? who.filter((x) => x !== p.user_id) : [...who, p.user_id])}>{p.name}</button>))}</div>
        <p className="small muted">Pick people, or none for everyone. Each person and their manager fill in their side on the phone or in My work; you share it when it's done.</p>
        <ErrorLine error={err} />
      </section>
      {data.map((c) => (
        <section key={c.id} className="card">
          <div className="row"><h2 style={{ margin: 0 }}>{c.name}</h2><span className="muted small">{c.due && `due ${fmtDate(c.due)}`}</span><span className="spacer" />
            <button className="small" onClick={() => run(async () => { await api.put(`/api/people/reviews/${c.id}/status?status=${c.status === "open" ? "closed" : "open"}`); await reload(); })}>
              {c.status === "open" ? "Close" : "Reopen"}</button></div>
          <DataTable rows={c.reviews} cols={[
            { key: "n", label: "Person", render: (r) => r.name },
            { key: "m", label: "Reviewer", render: (r) => r.reviewer || <span className="warn">No manager set</span> },
            { key: "s", label: "Their side", render: (r) => r.self_done ? "✓" : "–" },
            { key: "g", label: "Manager's side", render: (r) => r.manager_done ? "✓" : "–" },
            { key: "o", label: "Score", num: true, render: (r) => r.overall ?? "" },
            { key: "sh", label: "", render: (r) => r.manager_done && <button className="small" onClick={() => run(async () => { await api.patch(`/api/people/reviews/item/${r.id}`, { share: !r.shared }); await reload(); })}>{r.shared ? "Unshare" : "Share with them"}</button> },
          ]} />
        </section>
      ))}
    </>
  );
}

interface SurveyRow { id: number; title: string; status: string; anonymous: boolean; required: boolean; audience: string; responses: number; invited: number; response_rate: number | null }
interface SurveyRes { title: string; responses: number; invited: number; response_rate: number | null; questions: { key: string; label: string; type: string; answers: number;
  average?: number | null; enps?: number | null; by_department?: { department: string; enps: number | null; answers: number }[]; counts?: Record<string, number>; texts?: string[] }[] }
function Surveys() {
  const { data, reload } = useLoad<SurveyRow[]>("/api/people/surveys");
  const [open, setOpen] = useState<number | null>(null);
  const { data: res } = useLoad<SurveyRes>(open ? `/api/people/surveys/${open}` : null, [open]);
  const [f, setF] = useState({ title: "", audience: "all", anonymous: true, required: true });
  const [run, err, busy] = useAction();
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <>
      <section className="card">
        <h2>New eNPS pulse</h2>
        <div className="row wrap">
          <input placeholder="e.g. November pulse" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          <select value={f.audience} onChange={(e) => setF({ ...f, audience: e.target.value })}><option value="all">Everyone</option><option value="field">The boys on the tools</option><option value="office">The office</option></select>
          <label className="inline small"><input type="checkbox" checked={f.anonymous} onChange={(e) => setF({ ...f, anonymous: e.target.checked })} /> Anonymous</label>
          <label className="inline small" title="It pops up over the app and stays until they answer"><input type="checkbox" checked={f.required} onChange={(e) => setF({ ...f, required: e.target.checked })} /> Must answer (pops up until done)</label>
          <button className="primary" disabled={busy || !f.title} onClick={() => run(async () => { await api.post("/api/people/surveys", f); setF({ ...f, title: "" }); await reload(); })}>Send</button>
        </div>
        <p className="small muted">Asks "How likely are you to recommend Peak as a place to work?" (0–10), why, and one thing to do better. Answers come in on the phone.</p>
        <ErrorLine error={err} />
      </section>
      <DataTable rows={data} onRow={(s) => setOpen(s.id)} cols={[
        { key: "t", label: "Survey", render: (s) => s.title }, { key: "a", label: "Who", render: (s) => `${s.audience}${s.required ? " · must answer" : ""}` },
        { key: "r", label: "Answers", num: true, render: (s) => `${s.responses} / ${s.invited}` },
        { key: "s", label: "", render: (s) => <Status value={s.status} /> },
      ]} />
      {open && res && (
        <Modal title={res.title} onClose={() => setOpen(null)} wide>
          <p className="muted">{res.responses} answers of {res.invited} asked ({res.response_rate ?? 0}%)</p>
          {res.questions.map((q) => (
            <div key={q.key} className="card">
              <b>{q.label}</b>
              {q.enps !== undefined && <div className="big-num">eNPS {q.enps === null ? "–" : num(q.enps, 0)}</div>}
              {q.by_department && q.by_department.length > 0 && <div className="small">{q.by_department.map((d) => `${d.department}: ${d.enps === null ? "–" : num(d.enps, 0)} (${d.answers})`).join(" · ")}</div>}
              {q.average !== undefined && q.enps === undefined && <div>Average {q.average ?? "–"}</div>}
              {q.counts && <div className="small">{Object.entries(q.counts).map(([k, v]) => `${k}: ${v}`).join(" · ")}</div>}
              {q.texts && q.texts.map((t, i) => <p key={i} className="small quote">“{t}”</p>)}
            </div>
          ))}
          <button onClick={() => run(async () => { await api.put(`/api/people/surveys/${open}/status?status=${data.find((s) => s.id === open)?.status === "open" ? "closed" : "open"}`); await reload(); })}>
            {data.find((s) => s.id === open)?.status === "open" ? "Close the survey" : "Reopen"}</button>
        </Modal>
      )}
    </>
  );
}

interface PolicyRow { id: number; title: string; body: string; has_file: boolean; file_name: string; version: number; audience: string; active: boolean; signed: number; of: number; not_signed: string[] }
function Policies() {
  const { data, reload } = useLoad<PolicyRow[]>("/api/people/policies");
  const [edit, setEdit] = useState<PolicyRow | "new" | null>(null);
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <>
      <div className="row"><button className="primary" onClick={() => setEdit("new")}>+ Policy or contract to sign</button></div>
      <DataTable rows={data} onRow={(p) => setEdit(p)} cols={[
        { key: "t", label: "Policy", render: (p) => <>{p.title} <small className="muted">v{p.version}</small></> },
        { key: "a", label: "Who signs", render: (p) => ({ all: "Everyone", field: "On the tools", office: "Office", none: "Only when sent" } as Record<string, string>)[p.audience] },
        { key: "s", label: "Signed", render: (p) => <span className={p.signed < p.of ? "warn" : "ok"}>{p.signed} of {p.of}</span> },
        { key: "n", label: "Still to sign", render: (p) => <small>{p.not_signed.slice(0, 6).join(", ")}{p.not_signed.length > 6 && "…"}</small>, hideSm: true },
      ]} />
      {edit && <PolicyForm p={edit === "new" ? null : edit} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </>
  );
}

function PolicyForm({ p, onClose, onDone }: { p: PolicyRow | null; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ title: p?.title ?? "", body: p?.body ?? "", audience: p?.audience ?? "all", new_version: false });
  const [file, setFile] = useState<File | null>(null);
  const { data: sigs } = useLoad<{ name: string; version: number; typed_name: string; signed_at: string; signature: string }[]>(p ? `/api/people/policies/${p.id}/signatures` : null);
  const [run, err, busy] = useAction();
  return (
    <Modal title={p ? p.title : "New policy"} onClose={onClose} wide>
      <form className="form" onSubmit={(e) => { e.preventDefault(); run(async () => {
        const fd = new FormData();
        fd.append("title", f.title); fd.append("body", f.body); fd.append("audience", f.audience); fd.append("new_version", String(f.new_version));
        if (p) fd.append("policy_id", String(p.id));
        if (file) fd.append("file", file);
        await upload("/api/people/policies", fd); onDone();
      }); }}>
        <Field label="Title"><input required value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} placeholder="Drug and alcohol policy" /></Field>
        <Field label="Text to read on the phone (or attach a PDF)"><textarea rows={8} value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} /></Field>
        <Field label="PDF"><input type="file" accept="application/pdf" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
        <Field label="Who signs it"><select value={f.audience} onChange={(e) => setF({ ...f, audience: e.target.value })}>
          <option value="all">Everyone</option><option value="field">People on the tools</option><option value="office">The office</option><option value="none">Only when sent in an onboarding checklist</option></select></Field>
        {p && <label className="inline"><input type="checkbox" checked={f.new_version} onChange={(e) => setF({ ...f, new_version: e.target.checked })} /> It's changed: ask everyone to sign the new version</label>}
        <button className="primary" disabled={busy}>Save</button>
        <ErrorLine error={err} />
      </form>
      {sigs && sigs.length > 0 && (<><h3>Signed</h3>{sigs.map((s, i) => (
        <div key={i} className="row small"><b>{s.name}</b><span>v{s.version}</span><span className="muted">{fmtDate(s.signed_at)} as “{s.typed_name}”</span>
          {s.signature && <img src={s.signature} alt="" className="sig-thumb" />}</div>))}</>)}
    </Modal>
  );
}

function News() {
  const { data, reload } = useLoad<{ id: number; title: string; body: string; audience: string; pinned: boolean; at: string }[]>("/api/people/announcements");
  const [f, setF] = useState({ title: "", body: "", audience: "all", pinned: false, expires: "" });
  const [run, err, busy] = useAction();
  return (
    <>
      <section className="card form">
        <h2>Post to the team</h2>
        <input placeholder="Headline, e.g. Toolbox talk Friday 6:30 at the yard" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <textarea placeholder="More detail (optional)" value={f.body} onChange={(e) => setF({ ...f, body: e.target.value })} />
        <div className="row wrap">
          <select value={f.audience} onChange={(e) => setF({ ...f, audience: e.target.value })}><option value="all">Everyone</option><option value="field">On the tools</option><option value="office">Office</option></select>
          <label className="inline small"><input type="checkbox" checked={f.pinned} onChange={(e) => setF({ ...f, pinned: e.target.checked })} /> Pin to the top</label>
          <label className="inline small">Until <input type="date" value={f.expires} onChange={(e) => setF({ ...f, expires: e.target.value })} /></label>
          <button className="primary" disabled={busy || !f.title} onClick={() => run(async () => { await api.post("/api/people/announcements", { ...f, expires: f.expires || null }); setF({ ...f, title: "", body: "" }); await reload(); })}>Post</button>
        </div>
        <ErrorLine error={err} />
      </section>
      {(data ?? []).map((a) => (
        <div key={a.id} className={`news ${a.pinned ? "pinned" : ""}`}>
          <div className="row"><b>{a.pinned && "📌 "}{a.title}</b><span className="spacer" /><small className="muted">{fmtDate(a.at)} · {a.audience}</small>
            <button className="link small danger" onClick={() => run(async () => { await api.del(`/api/people/announcements/${a.id}`); await reload(); })}>Remove</button></div>
          {a.body && <p>{a.body}</p>}
        </div>
      ))}
    </>
  );
}

interface Report { headcount: number; by_department: Record<string, number>; by_type: Record<string, number>; starters_12m: number; leavers_12m: number; turnover_pct: number;
  average_tenure_years: number | null; leave_liability: number; compliance: { user_id: number; name: string; missing: string[]; expired: number; expiring: number }[];
  upcoming: { user_id: number; name: string; kind: string; date: string; years: number | null }[]; training_12m: { courses: number; hours: number; cost: number };
  missing_emergency_contacts: string[]; gear_out: number }
function Reports() {
  const { data: r } = useLoad<Report>("/api/people/report");
  if (!r) return <p className="muted">Loading…</p>;
  return (
    <>
      <div className="tiles">
        <div className="tile"><b>{r.headcount}</b><span>People</span></div>
        <div className="tile"><b>{r.starters_12m} / {r.leavers_12m}</b><span>Started / left (12 months)</span></div>
        <div className={`tile ${r.turnover_pct > 25 ? "warn" : ""}`}><b>{num(r.turnover_pct, 1)}%</b><span>Staff turnover</span></div>
        <div className="tile"><b>{r.average_tenure_years ?? "–"} y</b><span>Average time with us</span></div>
        <div className="tile"><b>{money(r.leave_liability)}</b><span>Leave owed (annual + long service)</span></div>
        <div className="tile"><b>{r.training_12m.courses}</b><span>Courses (12 m) · {num(r.training_12m.hours, 0)} h · {money(r.training_12m.cost)}</span></div>
      </div>
      <div className="two-col">
        <section className="card">
          <h2>Licences not in order</h2>
          {r.compliance.length === 0 ? <p className="ok">Everyone's licences and tickets are current.</p> : r.compliance.map((c) => (
            <p key={c.user_id}><Link to={`/people/${c.user_id}`}><b>{c.name}</b></Link>: {[c.expired && `${c.expired} expired`, c.expiring && `${c.expiring} expiring`, c.missing.length && `missing ${c.missing.join(", ")}`].filter(Boolean).join(" · ")}</p>))}
          {r.missing_emergency_contacts.length > 0 && <p className="warn small">No emergency contact: {r.missing_emergency_contacts.join(", ")}</p>}
        </section>
        <section className="card">
          <h2>Coming up</h2>
          {r.upcoming.length === 0 && <p className="muted">No birthdays or work anniversaries in the next 30 days.</p>}
          {r.upcoming.map((u, i) => <p key={i}>{u.kind === "birthday" ? "🎂" : "🎉"} <b>{u.name}</b> {fmtDate(u.date)}{u.years ? ` – ${u.years} years` : ""}</p>)}
          <h3>Headcount</h3>
          <p className="small">{Object.entries(r.by_department).map(([k, v]) => `${k} ${v}`).join(" · ")}</p>
          <p className="small">{Object.entries(r.by_type).map(([k, v]) => `${TYPE_LABEL[k] ?? k} ${v}`).join(" · ")}</p>
          <p className="small">{r.gear_out} items of gear out with people.</p>
        </section>
      </div>
    </>
  );
}

function Setup({ opts, onChange }: { opts: Options; onChange: () => void }) {
  const [run, err] = useAction();
  const [ct, setCt] = useState({ name: "", category: "ticket", renew_months: "", required_for: "" });
  const [cl, setCl] = useState<{ id?: number; name: string; kind: string; text: string } | null>(null);
  return (
    <>
      <section className="card">
        <h2>Licences, tickets and training</h2>
        <DataTable rows={opts.credential_types} cols={[
          { key: "n", label: "Name", render: (t) => t.name }, { key: "c", label: "Kind", render: (t) => t.category },
          { key: "r", label: "Renew every", render: (t) => t.renew_months ? `${t.renew_months} months` : "–" },
          { key: "q", label: "Must have", render: (t) => t.required_for.includes("*") ? "Everyone on the tools" : t.required_for.join(", ") },
        ]} />
        <div className="row wrap">
          <input placeholder="Add: e.g. EWP licence" value={ct.name} onChange={(e) => setCt({ ...ct, name: e.target.value })} />
          <select value={ct.category} onChange={(e) => setCt({ ...ct, category: e.target.value })}>{["licence", "ticket", "training", "induction"].map((c) => <option key={c}>{c}</option>)}</select>
          <input type="number" placeholder="Renew (months)" value={ct.renew_months} onChange={(e) => setCt({ ...ct, renew_months: e.target.value })} style={{ width: 130 }} />
          <input placeholder="Must have (trades, comma; * = all)" value={ct.required_for} onChange={(e) => setCt({ ...ct, required_for: e.target.value })} />
          <button disabled={!ct.name} onClick={() => run(async () => {
            await api.post("/api/people/credential-types", { name: ct.name, category: ct.category, renew_months: ct.renew_months ? +ct.renew_months : null,
              required_for: ct.required_for.split(",").map((s) => s.trim()).filter(Boolean) });
            setCt({ name: "", category: "ticket", renew_months: "", required_for: "" }); onChange();
          })}>Add</button>
        </div>
      </section>
      <section className="card">
        <h2>Onboarding and offboarding checklists</h2>
        {opts.checklists.map((c) => (
          <p key={c.id}><button className="link" onClick={() => setCl({ id: c.id, name: c.name, kind: c.kind, text: c.tasks.map((t) => `${t.who} | ${t.due_days} | ${t.title}`).join("\n") })}>{c.name}</button>
            <small className="muted"> {c.kind} · {c.tasks.length} steps</small></p>))}
        <button onClick={() => setCl({ name: "", kind: "onboarding", text: "hr | 0 | " })}>+ Checklist</button>
        {cl && (
          <div className="form">
            <input value={cl.name} placeholder="Name" onChange={(e) => setCl({ ...cl, name: e.target.value })} />
            <select value={cl.kind} onChange={(e) => setCl({ ...cl, kind: e.target.value })}><option value="onboarding">Onboarding</option><option value="offboarding">Offboarding</option></select>
            <Field label="Steps: who (hr, manager or employee) | days from the start date | what" hint="Minus days are before the start date.">
              <textarea rows={10} value={cl.text} onChange={(e) => setCl({ ...cl, text: e.target.value })} /></Field>
            <button className="primary" onClick={() => run(async () => {
              const tasks = cl.text.split("\n").map((l) => l.split("|").map((s) => s.trim())).filter((p) => p.length >= 3 && p[2])
                .map(([who, d, title]) => ({ who: ["hr", "manager", "employee"].includes(who) ? who : "hr", due_days: +d || 0, title }));
              const body = { name: cl.name, kind: cl.kind, tasks };
              if (cl.id) await api.put(`/api/people/checklists/${cl.id}`, body); else await api.post("/api/people/checklists", body);
              setCl(null); onChange();
            })}>Save checklist</button>
          </div>
        )}
      </section>
      <section className="card">
        <h2>Leave</h2>
        {opts.policies.map((p) => <LeavePolicyRow key={p.id} p={p} onSaved={onChange} />)}
        <p className="small muted">Hours a year for a 38-hour week. "Builds up with hours worked" counts approved timesheet hours and paid leave (capped at the person's normal week).
          Set the date leave counts from, and on-costs for cost rates, under Admin → Operations settings.</p>
      </section>
      <ErrorLine error={err} />
    </>
  );
}

function LeavePolicyRow({ p, onSaved }: { p: Options["policies"][number]; onSaved: () => void }) {
  const [f, setF] = useState(p);
  const [run, err] = useAction();
  return (
    <div className="row wrap">
      <input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
      <label className="inline small"><input type="number" style={{ width: 80 }} value={f.hours_per_year} onChange={(e) => setF({ ...f, hours_per_year: +e.target.value })} /> h/yr</label>
      <label className="inline small"><input type="checkbox" checked={f.accrues_on_hours} onChange={(e) => setF({ ...f, accrues_on_hours: e.target.checked })} /> Builds up with hours worked</label>
      <label className="inline small">usable after <input type="number" style={{ width: 60 }} value={f.after_years} onChange={(e) => setF({ ...f, after_years: +e.target.value })} /> years</label>
      <label className="inline small"><input type="checkbox" checked={f.casuals} onChange={(e) => setF({ ...f, casuals: e.target.checked })} /> Casuals too</label>
      <button className="small" onClick={() => run(async () => { await api.put(`/api/people/leave-policies/${p.id}`, f); onSaved(); })}>Save</button>
      <ErrorLine error={err} />
    </div>
  );
}

/* ---------- one person ---------- */
interface PersonRec {
  profile: Record<string, unknown> & { user_id: number; name: string; email: string; phone: string; trade: string; role: string; active: boolean; has_photo: boolean;
    manager: string; years_of_service: number; emergency_contacts: { name: string; relationship: string; phone: string }[] };
  pay: { id: number; effective: string; pay_type: string; amount: number; position: string; reason: string; notes: string; by: string }[];
  hourly_rate: number | null; cost_rate: number;
  compliance: { credentials: Cred[]; missing: string[] };
  leave: Balance[];
  time_off: { id: number; kind: string; start_date: string; end_date: string; hours: number; status: string; notes: string }[];
  adjustments: { id: number; kind: string; day: string; hours: number; reason: string }[];
  files: { id: number; folder: string; filename: string; size: number; employee_can_see: boolean; created_at: string }[];
  gear: { id: number; item: string; serial: string; value: number | null; issued: string | null; returned: string | null; notes: string }[];
  tasks: TaskRow[];
  reviews: { id: number; cycle: string; reviewer: string; self_done: boolean; manager_done: boolean; shared: boolean; overall: number | null }[];
  goals: { id: number; title: string; description: string; due: string | null; progress: number; status: string }[];
  signed: { policy: string; version: number; signed_at: string; typed_name: string }[];
  to_sign: { id: number; title: string }[];
}
type PTab = "personal" | "job" | "leave" | "licences" | "docs" | "onboarding" | "reviews" | "gear";

export function PersonPage() {
  const { userId } = useParams();
  const { data: r, reload } = useLoad<PersonRec>(`/api/people/${userId}`, [userId]);
  const { data: opts } = useLoad<Options>("/api/people/options");
  const { data: people } = useLoad<Row[]>("/api/people");
  const [tab, setTab] = useState<PTab>("personal");
  if (!r || !opts) return <main className="page"><p className="muted">Loading…</p></main>;
  const p = r.profile;
  return (
    <main className="page">
      <Link to="/people">‹ People</Link>
      <div className="row person-head">
        <Avatar userId={p.user_id} name={p.name} has={p.has_photo} />
        <div><h1 style={{ margin: 0 }}>{p.name}</h1>
          <span className="muted">{[p.position as string, p.department as string, TYPE_LABEL[p.employment_type as string]].filter(Boolean).join(" · ")}
            {p.start_date ? ` · ${num(p.years_of_service, 1)} years` : ""}{!p.active && " · signed out (left)"}</span></div>
        <span className="spacer" />
        {p.phone && <a className="button" href={`tel:${p.phone}`}>📞 {p.phone}</a>}
        <a className="button" href={`mailto:${p.email}`}>✉️</a>
      </div>
      <Tabs<PTab> value={tab} onChange={setTab} tabs={[["personal", "Personal"], ["job", "Job & pay"], ["leave", "Leave"], ["licences", `Licences${r.compliance.missing.length ? ` (${r.compliance.missing.length} missing)` : ""}`],
        ["docs", "Documents"], ["onboarding", "On/offboarding"], ["reviews", "Reviews & goals"], ["gear", "Gear"]]} />
      {(tab === "personal" || tab === "job") && <ProfileForm r={r} opts={opts} people={people ?? []} part={tab} onSaved={reload} />}
      {tab === "job" && <PayHistory r={r} onSaved={reload} />}
      {tab === "leave" && <PersonLeave r={r} onSaved={reload} />}
      {tab === "licences" && <PersonLicences r={r} opts={opts} onSaved={reload} />}
      {tab === "docs" && <PersonFiles r={r} onSaved={reload} />}
      {tab === "onboarding" && <PersonTasks r={r} opts={opts} onSaved={reload} />}
      {tab === "reviews" && <PersonReviews r={r} onSaved={reload} />}
      {tab === "gear" && <PersonGear r={r} onSaved={reload} />}
    </main>
  );
}

function ProfileForm({ r, opts, people, part, onSaved }: { r: PersonRec; opts: Options; people: Row[]; part: "personal" | "job"; onSaved: () => void }) {
  const p = r.profile;
  const init = () => ({ name: p.name, phone: p.phone, trade: p.trade, position: (p.position as string) || "", department: (p.department as string) || "",
    employment_type: (p.employment_type as string) || "full_time", status: (p.status as string) || "active", start_date: (p.start_date as string) || "",
    end_date: (p.end_date as string) || "", end_reason: (p.end_reason as string) || "", manager_id: (p.manager_id as number | null) ?? "",
    hours_per_week: (p.hours_per_week as number) ?? 38, award: (p.award as string) || "", apprentice_year: (p.apprentice_year as number | null) ?? "",
    dob: (p.dob as string) || "", personal_email: (p.personal_email as string) || "", address: (p.address as string) || "",
    emergency_contacts: p.emergency_contacts?.length ? p.emergency_contacts : [{ name: "", relationship: "", phone: "" }],
    drivers_licence: (p.drivers_licence as string) || "", shirt_size: (p.shirt_size as string) || "", pants_size: (p.pants_size as string) || "",
    boot_size: (p.boot_size as string) || "", medical_notes: (p.medical_notes as string) || "", notes: (p.notes as string) || "" });
  const [f, setF] = useState(init);
  const [run, err, busy] = useAction();
  const [saved, setSaved] = useState(false);
  const set = (k: string, v: unknown) => { setF({ ...f, [k]: v }); setSaved(false); };
  const save = () => run(async () => {
    await api.put(`/api/people/${p.user_id}/profile`, { ...f, manager_id: f.manager_id === "" ? null : +f.manager_id, apprentice_year: f.apprentice_year === "" ? null : +f.apprentice_year,
      start_date: f.start_date || null, end_date: f.end_date || null, dob: f.dob || null, emergency_contacts: f.emergency_contacts.filter((c) => c.name || c.phone) });
    setSaved(true); onSaved();
  });
  return (
    <section className="card form">
      {part === "personal" ? (
        <>
          <div className="row wrap">
            <Field label="Name"><input value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
            <Field label="Mobile"><input value={f.phone} onChange={(e) => set("phone", e.target.value)} /></Field>
            <Field label="Personal email"><input value={f.personal_email} onChange={(e) => set("personal_email", e.target.value)} /></Field>
            <Field label="Date of birth"><input type="date" value={f.dob} onChange={(e) => set("dob", e.target.value)} /></Field>
          </div>
          <Field label="Home address"><input value={f.address} onChange={(e) => set("address", e.target.value)} /></Field>
          <h3>Emergency contacts</h3>
          {f.emergency_contacts.map((c, i) => (
            <div key={i} className="row wrap">{(["name", "relationship", "phone"] as const).map((k) => (
              <input key={k} placeholder={k} value={c[k]} onChange={(e) => set("emergency_contacts", f.emergency_contacts.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)))} />))}</div>
          ))}
          <button type="button" className="link" onClick={() => set("emergency_contacts", [...f.emergency_contacts, { name: "", relationship: "", phone: "" }])}>+ Contact</button>
          <div className="row wrap">
            <Field label="Shirt"><input value={f.shirt_size} onChange={(e) => set("shirt_size", e.target.value)} /></Field>
            <Field label="Pants"><input value={f.pants_size} onChange={(e) => set("pants_size", e.target.value)} /></Field>
            <Field label="Boots"><input value={f.boot_size} onChange={(e) => set("boot_size", e.target.value)} /></Field>
            <Field label="Driver licence class"><input value={f.drivers_licence} onChange={(e) => set("drivers_licence", e.target.value)} /></Field>
          </div>
          <Field label="Allergies / medical"><textarea value={f.medical_notes} onChange={(e) => set("medical_notes", e.target.value)} /></Field>
        </>
      ) : (
        <>
          <div className="row wrap">
            <Field label="Position"><input value={f.position} onChange={(e) => set("position", e.target.value)} /></Field>
            <Field label="Trade (schedule and rules)"><input value={f.trade} onChange={(e) => set("trade", e.target.value)} /></Field>
            <Field label="Department"><select value={f.department} onChange={(e) => set("department", e.target.value)}><option value="">–</option>{opts.departments.map((d) => <option key={d}>{d}</option>)}</select></Field>
            <Field label="Type"><select value={f.employment_type} onChange={(e) => set("employment_type", e.target.value)}>{opts.employment_types.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]}</option>)}</select></Field>
          </div>
          <div className="row wrap">
            <Field label="Reports to"><select value={String(f.manager_id)} onChange={(e) => set("manager_id", e.target.value)}><option value="">–</option>
              {people.filter((x) => x.user_id !== p.user_id).map((x) => <option key={x.user_id} value={x.user_id}>{x.name}</option>)}</select></Field>
            <Field label="Started"><input type="date" value={f.start_date} onChange={(e) => set("start_date", e.target.value)} /></Field>
            <Field label="Normal hours a week"><input type="number" value={f.hours_per_week} onChange={(e) => set("hours_per_week", +e.target.value)} /></Field>
            <Field label="Apprentice year"><input type="number" min={1} max={4} value={f.apprentice_year} onChange={(e) => set("apprentice_year", e.target.value)} /></Field>
          </div>
          <Field label="Award"><input value={f.award} onChange={(e) => set("award", e.target.value)} placeholder="Plumbing and Fire Sprinklers Award 2020" /></Field>
          <Field label="Private HR notes"><textarea value={f.notes} onChange={(e) => set("notes", e.target.value)} /></Field>
          {f.end_date && <p className="warn">Last day {fmtDate(f.end_date)} ({f.end_reason})</p>}
        </>
      )}
      <div className="row"><button className="primary" disabled={busy} onClick={save}>Save</button>{saved && <span className="ok">Saved</span>}</div>
      <ErrorLine error={err} />
    </section>
  );
}

function PayHistory({ r, onSaved }: { r: PersonRec; onSaved: () => void }) {
  const [f, setF] = useState({ effective: todayIso(), pay_type: "hourly", amount: "", reason: "Pay review", position: "", update_cost_rate: true });
  const [run, err, busy] = useAction();
  return (
    <section className="card">
      <h2>Pay history</h2>
      <p className="small">Now: {r.hourly_rate ? `$${num(r.hourly_rate, 2)}/h` : "not set"} · cost rate on jobs ${num(r.cost_rate, 2)}/h</p>
      <DataTable rows={r.pay} empty="No pay recorded yet." cols={[
        { key: "e", label: "From", render: (x) => fmtDate(x.effective) },
        { key: "a", label: "Pay", num: true, render: (x) => `$${num(x.amount, 2)}${x.pay_type === "hourly" ? "/h" : "/yr"}` },
        { key: "r", label: "Why", render: (x) => x.reason }, { key: "p", label: "Position", render: (x) => x.position, hideSm: true },
        { key: "b", label: "By", render: (x) => x.by, hideSm: true },
        { key: "d", label: "", render: (x) => <button className="link small danger" onClick={() => run(async () => { await api.del(`/api/people/pay/${x.id}`); onSaved(); })}>✕</button> },
      ]} />
      <div className="row wrap">
        <input type="date" value={f.effective} onChange={(e) => setF({ ...f, effective: e.target.value })} />
        <select value={f.pay_type} onChange={(e) => setF({ ...f, pay_type: e.target.value })}><option value="hourly">$ an hour</option><option value="salary">$ a year</option></select>
        <input type="number" step="0.01" placeholder="Amount" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} style={{ width: 110 }} />
        <input placeholder="Why" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
        <input placeholder="New position (optional)" value={f.position} onChange={(e) => setF({ ...f, position: e.target.value })} />
        <label className="inline small"><input type="checkbox" checked={f.update_cost_rate} onChange={(e) => setF({ ...f, update_cost_rate: e.target.checked })} /> Update the job cost rate (+ on-costs)</label>
        <button disabled={busy || !f.amount} onClick={() => run(async () => { await api.post(`/api/people/${r.profile.user_id}/pay`, { ...f, amount: +f.amount }); setF({ ...f, amount: "" }); onSaved(); })}>Add</button>
      </div>
      <ErrorLine error={err} />
    </section>
  );
}

function PersonLeave({ r, onSaved }: { r: PersonRec; onSaved: () => void }) {
  const [f, setF] = useState({ kind: "annual", day: todayIso(), hours: "", reason: "Opening balance" });
  const [run, err, busy] = useAction();
  return (
    <>
      <div className="tiles">
        {r.leave.map((b) => (
          <div key={b.kind} className={`tile ${b.balance < 0 ? "warn" : ""}`}><b>{num(b.balance, 1)} h</b><span>{b.name}</span>
            <small className="muted">{num(b.days, 1)} days · built up {num(b.accrued, 1)} · taken {num(b.taken, 1)}{b.value ? ` · ${money(b.value)}` : ""}{!b.available && " · not usable yet"}</small></div>
        ))}
      </div>
      <section className="card">
        <h2>Leave taken and booked</h2>
        <DataTable rows={r.time_off} cols={[
          { key: "k", label: "Kind", render: (t) => t.kind }, { key: "d", label: "When", render: (t) => `${fmtDate(t.start_date)} – ${fmtDate(t.end_date)}` },
          { key: "h", label: "Hours", num: true, render: (t) => num(t.hours, 1) }, { key: "s", label: "", render: (t) => <Status value={t.status} /> },
        ]} />
        <h3>Opening balances and corrections</h3>
        {r.adjustments.map((a) => <div key={a.id} className="row small"><span>{fmtDate(a.day)}</span><b>{a.kind}</b><span>{a.hours > 0 ? "+" : ""}{a.hours} h</span><span className="muted">{a.reason}</span>
          <button className="link small danger" onClick={() => run(async () => { await api.del(`/api/people/leave-adjustments/${a.id}`); onSaved(); })}>✕</button></div>)}
        <div className="row wrap">
          <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{r.leave.map((b) => <option key={b.kind} value={b.kind}>{b.name}</option>)}</select>
          <input type="date" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value })} />
          <input type="number" step="0.1" placeholder="Hours (+ or −)" value={f.hours} onChange={(e) => setF({ ...f, hours: e.target.value })} style={{ width: 120 }} />
          <input placeholder="Reason" value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
          <button disabled={busy || !f.hours} onClick={() => run(async () => { await api.post(`/api/people/${r.profile.user_id}/leave-adjustments`, { ...f, hours: +f.hours }); setF({ ...f, hours: "" }); onSaved(); })}>Add</button>
        </div>
        <ErrorLine error={err} />
      </section>
    </>
  );
}

function PersonLicences({ r, opts, onSaved }: { r: PersonRec; opts: Options; onSaved: () => void }) {
  const [f, setF] = useState({ type_id: "", number: "", issuer: "", issued: "", expires: "", hours: "", cost: "" });
  const [file, setFile] = useState<File | null>(null);
  const [run, err, busy] = useAction();
  return (
    <section className="card">
      {r.compliance.missing.length > 0 && <p className="bad">Missing for their trade: {r.compliance.missing.join(", ")}</p>}
      <DataTable rows={r.compliance.credentials} empty="None yet." cols={[
        { key: "t", label: "Licence / ticket / course", render: (c) => c.type }, { key: "n", label: "Number", render: (c) => c.number },
        { key: "i", label: "Issued", render: (c) => fmtDate(c.issued), hideSm: true }, { key: "e", label: "Expires", render: (c) => c.expires ? fmtDate(c.expires) : "–" },
        { key: "s", label: "", render: (c) => <Status value={c.status} labels={CRED_LABEL} /> },
        { key: "f", label: "", render: (c) => c.has_file && <button className="link small" onClick={async () => window.open(await fetchBlobUrl(`/api/people/credentials/${c.id}/file`))}>Card</button> },
        { key: "v", label: "Checked", render: (c) => <input type="checkbox" checked={c.verified} onChange={() => run(async () => { await api.patch(`/api/people/credentials/${c.id}`, { verified: !c.verified }); onSaved(); })} /> },
        { key: "d", label: "", render: (c) => <button className="link small danger" onClick={() => run(async () => { if (confirm("Delete this?")) { await api.del(`/api/people/credentials/${c.id}`); onSaved(); } })}>✕</button> },
      ]} />
      <h3>Add</h3>
      <form className="row wrap" onSubmit={(e) => { e.preventDefault(); run(async () => {
        const fd = new FormData(); Object.entries(f).forEach(([k, v]) => fd.append(k, v)); if (file) fd.append("file", file);
        await upload(`/api/people/${r.profile.user_id}/credentials`, fd); setF({ type_id: "", number: "", issuer: "", issued: "", expires: "", hours: "", cost: "" }); setFile(null); onSaved();
      }); }}>
        <select required value={f.type_id} onChange={(e) => setF({ ...f, type_id: e.target.value })}><option value="">Which…</option>{opts.credential_types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select>
        <input placeholder="Number" value={f.number} onChange={(e) => setF({ ...f, number: e.target.value })} />
        <input placeholder="Issuer / RTO" value={f.issuer} onChange={(e) => setF({ ...f, issuer: e.target.value })} />
        <label className="inline small">Issued <input type="date" value={f.issued} onChange={(e) => setF({ ...f, issued: e.target.value })} /></label>
        <label className="inline small">Expires <input type="date" value={f.expires} onChange={(e) => setF({ ...f, expires: e.target.value })} /></label>
        <input type="number" placeholder="Hours" style={{ width: 80 }} value={f.hours} onChange={(e) => setF({ ...f, hours: e.target.value })} />
        <input type="number" placeholder="Cost $" style={{ width: 90 }} value={f.cost} onChange={(e) => setF({ ...f, cost: e.target.value })} />
        <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        <button className="primary" disabled={busy}>Add</button>
      </form>
      <p className="small muted">Leave Expires blank to work it out from the renewal period. Reminders go to them and to you 60, 30 and 7 days before.</p>
      <ErrorLine error={err} />
    </section>
  );
}

function PersonFiles({ r, onSaved }: { r: PersonRec; onSaved: () => void }) {
  const [folder, setFolder] = useState("Contract");
  const [see, setSee] = useState(true);
  const [run, err, busy] = useAction();
  return (
    <section className="card">
      <DataTable rows={r.files} empty="No documents yet." cols={[
        { key: "f", label: "File", render: (f) => <button className="link" onClick={async () => window.open(await fetchBlobUrl(`/api/people/files/${f.id}`))}>{f.filename}</button> },
        { key: "o", label: "Folder", render: (f) => f.folder }, { key: "s", label: "They can see it", render: (f) => f.employee_can_see ? "Yes" : "No (HR only)" },
        { key: "d", label: "Added", render: (f) => fmtDate(f.created_at), hideSm: true },
        { key: "x", label: "", render: (f) => <button className="link small danger" onClick={() => run(async () => { if (confirm("Delete?")) { await api.del(`/api/people/files/${f.id}`); onSaved(); } })}>✕</button> },
      ]} />
      <h3>Signed policies</h3>
      {r.signed.map((s, i) => <p key={i} className="small">✓ {s.policy} v{s.version} – {fmtDate(s.signed_at)} as “{s.typed_name}”</p>)}
      {r.to_sign.length > 0 && <p className="warn small">Still to sign: {r.to_sign.map((x) => x.title).join(", ")}</p>}
      <div className="row wrap">
        <select value={folder} onChange={(e) => setFolder(e.target.value)}>{["Contract", "Licences", "Performance", "Medical", "Payroll", "General"].map((x) => <option key={x}>{x}</option>)}</select>
        <label className="inline small"><input type="checkbox" checked={see} onChange={(e) => setSee(e.target.checked)} /> They can see it on their phone</label>
        <label className="button">{busy ? "Uploading…" : "+ Upload"}<input type="file" multiple hidden onChange={(e) => {
          const files = Array.from(e.target.files || []);
          run(async () => { const fd = new FormData(); files.forEach((f) => fd.append("files", f)); fd.append("folder", folder); fd.append("employee_can_see", String(see));
            await upload(`/api/people/${r.profile.user_id}/files`, fd); onSaved(); });
        }} /></label>
      </div>
      <p className="small muted">Kept apart from company documents: only People-permission users and the person (when ticked) can open them. Tax file numbers and bank details stay in Xero Payroll.</p>
      <ErrorLine error={err} />
    </section>
  );
}

function PersonTasks({ r, opts, onSaved }: { r: PersonRec; opts: Options; onSaved: () => void }) {
  const [tpl, setTpl] = useState("");
  const [off, setOff] = useState({ end_date: todayIso(), end_reason: "resigned", template_id: "" });
  const [run, err, busy] = useAction();
  const [gear, setGear] = useState<string[] | null>(null);
  return (
    <>
      <section className="card">
        {r.tasks.length === 0 && <p className="muted">No checklist steps.</p>}
        {r.tasks.map((t) => (
          <label key={t.id} className={`inline task-row ${t.overdue ? "bad" : ""}`}>
            <input type="checkbox" checked={t.done} onChange={() => run(async () => { await api.put(`/api/people/tasks/${t.id}`, { done: !t.done }); onSaved(); })} />
            <span>{t.title} <small className="muted">· {t.kind} · {t.assignee || t.who}{t.due && ` · ${fmtDate(t.due)}`}</small></span>
          </label>
        ))}
        <div className="row wrap">
          <select value={tpl} onChange={(e) => setTpl(e.target.value)}><option value="">Start a checklist…</option>{opts.checklists.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
          <button disabled={!tpl || busy} onClick={() => run(async () => { await api.post(`/api/people/${r.profile.user_id}/checklists`, { template_id: +tpl }); setTpl(""); onSaved(); })}>Start</button>
        </div>
      </section>
      {r.profile.active && (
        <section className="card">
          <h2>They're leaving</h2>
          <div className="row wrap">
            <label className="inline small">Last day <input type="date" value={off.end_date} onChange={(e) => setOff({ ...off, end_date: e.target.value })} /></label>
            <select value={off.end_reason} onChange={(e) => setOff({ ...off, end_reason: e.target.value })}>{["resigned", "end of contract", "terminated", "retired", "apprenticeship ended"].map((x) => <option key={x}>{x}</option>)}</select>
            <select value={off.template_id} onChange={(e) => setOff({ ...off, template_id: e.target.value })}><option value="">No checklist</option>
              {opts.checklists.filter((c) => c.kind === "offboarding").map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
            <button className="danger" disabled={busy} onClick={() => run(async () => {
              const res = await api.post<{ gear_to_collect: string[] }>(`/api/people/${r.profile.user_id}/offboard`, { ...off, template_id: off.template_id ? +off.template_id : null });
              setGear(res.gear_to_collect); onSaved();
            })}>Start offboarding</button>
          </div>
          {gear && <p className="warn">Collect: {gear.length ? gear.join(", ") : "nothing recorded"}</p>}
          <p className="small muted">Their sign-in stops the day after their last day.</p>
        </section>
      )}
      <ErrorLine error={err} />
    </>
  );
}

function PersonReviews({ r, onSaved }: { r: PersonRec; onSaved: () => void }) {
  const [g, setG] = useState({ title: "", due: "" });
  const [run, err, busy] = useAction();
  return (
    <>
      <section className="card">
        <h2>Reviews</h2>
        <DataTable rows={r.reviews} empty="No reviews yet. Start a round under People → Reviews." cols={[
          { key: "c", label: "Round", render: (x) => x.cycle }, { key: "r", label: "Reviewer", render: (x) => x.reviewer },
          { key: "s", label: "Done", render: (x) => `${x.self_done ? "✓ them" : "– them"} · ${x.manager_done ? "✓ manager" : "– manager"}` },
          { key: "o", label: "Score", num: true, render: (x) => x.overall ?? "" },
          { key: "v", label: "", render: (x) => <ReviewView id={x.id} /> },
          { key: "sh", label: "", render: (x) => x.manager_done && <button className="small" onClick={() => run(async () => { await api.patch(`/api/people/reviews/item/${x.id}`, { share: !x.shared }); onSaved(); })}>{x.shared ? "Unshare" : "Share"}</button> },
        ]} />
      </section>
      <section className="card">
        <h2>Goals</h2>
        {r.goals.map((x) => (
          <div key={x.id} className="goal"><div className="row"><b>{x.title}</b><span className="muted small">{x.due && fmtDate(x.due)}</span><span className="spacer" /><Status value={x.status} /><span>{x.progress}%</span></div>
            <div className="bar"><div style={{ width: `${x.progress}%` }} /></div></div>))}
        <div className="row wrap">
          <input placeholder="New goal, e.g. Get gasfitting licence" value={g.title} onChange={(e) => setG({ ...g, title: e.target.value })} style={{ flex: 1 }} />
          <input type="date" value={g.due} onChange={(e) => setG({ ...g, due: e.target.value })} />
          <button disabled={!g.title || busy} onClick={() => run(async () => { await api.post(`/api/people/${r.profile.user_id}/goals`, { title: g.title, due: g.due || null }); setG({ title: "", due: "" }); onSaved(); })}>Add</button>
        </div>
        <ErrorLine error={err} />
      </section>
    </>
  );
}

function ReviewView({ id }: { id: number }) {
  const [open, setOpen] = useState(false);
  const { data } = useLoad<{ cycle: string; name: string; questions: { key: string; label: string; type: string }[]; self_answers: Record<string, unknown>; manager_answers: Record<string, unknown> }>(open ? `/api/people/reviews/item/${id}` : null, [open]);
  return (
    <>
      <button className="link small" onClick={() => setOpen(true)}>Read</button>
      {open && data && (
        <Modal title={`${data.cycle}: ${data.name}`} onClose={() => setOpen(false)} wide>
          <table className="dt"><thead><tr><th>Question</th><th>Them</th><th>Manager</th></tr></thead><tbody>
            {data.questions.map((q) => <tr key={q.key}><td>{q.label}</td><td>{String(data.self_answers[q.key] ?? "")}</td><td>{String(data.manager_answers[q.key] ?? "")}</td></tr>)}
          </tbody></table>
        </Modal>
      )}
    </>
  );
}

function PersonGear({ r, onSaved }: { r: PersonRec; onSaved: () => void }) {
  const [f, setF] = useState({ item: "", serial: "", value: "", issued: todayIso() });
  const [run, err, busy] = useAction();
  return (
    <section className="card">
      <DataTable rows={r.gear} empty="Nothing issued." cols={[
        { key: "i", label: "Item", render: (g) => g.item }, { key: "s", label: "Serial", render: (g) => g.serial }, { key: "v", label: "Value", num: true, render: (g) => g.value ? money(g.value) : "" },
        { key: "d", label: "Issued", render: (g) => fmtDate(g.issued) },
        { key: "r", label: "Returned", render: (g) => g.returned ? fmtDate(g.returned) : <button className="small" onClick={() => run(async () => { await api.put(`/api/people/gear/${g.id}`, { ...g, returned: todayIso() }); onSaved(); })}>Returned today</button> },
      ]} />
      <div className="row wrap">
        <input placeholder="Item (iPhone, M18 kit, fuel card, keys…)" value={f.item} onChange={(e) => setF({ ...f, item: e.target.value })} style={{ flex: 1 }} />
        <input placeholder="Serial" value={f.serial} onChange={(e) => setF({ ...f, serial: e.target.value })} />
        <input type="number" placeholder="Value" value={f.value} onChange={(e) => setF({ ...f, value: e.target.value })} style={{ width: 90 }} />
        <input type="date" value={f.issued} onChange={(e) => setF({ ...f, issued: e.target.value })} />
        <button disabled={!f.item || busy} onClick={() => run(async () => { await api.post(`/api/people/${r.profile.user_id}/gear`, { ...f, value: f.value ? +f.value : null, issued: f.issued || null }); setF({ ...f, item: "", serial: "", value: "" }); onSaved(); })}>Issue</button>
      </div>
      <ErrorLine error={err} />
    </section>
  );
}
