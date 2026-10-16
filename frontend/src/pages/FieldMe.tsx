/* The phone's "Me" tab (BambooHR self-service): news, things to do (sign a policy, a review, a survey, onboarding steps),
   leave balances and what they'll be by a date, licences and tickets (snap a photo of the card), my details, gear and files,
   and the team directory. Plus board items assigned to me (Monday.com on the phone). */
import { Fragment, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, fetchBlobUrl, upload } from "../api";
import { Avatar, ErrorLine, fmtDate, num, shrinkImage, SignaturePad, Status, todayIso, useAction, useLoad } from "../ui";

export interface Balance { kind: string; name: string; balance: number; accrued: number; taken: number; booked_or_requested: number; after_bookings: number;
  available: boolean; days: number; value: number | null; per_week: number; projected?: number }
export interface Cred { id: number; type: string; type_id: number; category: string; number: string; issuer: string; issued: string | null; expires: string | null;
  status: string; has_file: boolean; verified: boolean; notes?: string; name?: string; user_id?: number; hours?: number | null; cost?: number | null }
interface Task { id: number; title: string; due: string | null; done: boolean; overdue: boolean; person: string; kind: string; who: string; assignee: string; user_id: number }
interface MyHr {
  tasks: Task[]; policies: { id: number; title: string; version: number }[];
  reviews: { id: number; cycle: string; due: string | null; as: string; person: string }[];
  surveys: { id: number; title: string; anonymous: boolean }[];
  goals: { id: number; title: string; progress: number; due: string | null }[];
  announcements: { id: number; title: string; body: string; pinned: boolean; at: string }[];
}
interface Me extends MyHr {
  profile: Record<string, unknown> & { name: string; email: string; phone: string; position: string; manager: string; years_of_service: number;
    emergency_contacts: { name: string; relationship: string; phone: string }[] };
  pay: { effective: string; pay_type: string; amount: number } | null;
  leave: Balance[];
  compliance: { credentials: Cred[]; missing: string[] };
  credential_types: { id: number; name: string; category: string }[];
  files: { id: number; folder: string; filename: string }[];
  gear: { item: string; serial: string; issued: string | null }[];
  reviews_shared: { id: number; cycle: string }[];
}
export interface WorkItem { board_id: number; board: string; item_id: number; name: string; group: string; due: string | null; bucket: string;
  status_column: string | null; status: string | null; status_label: string; labels: { key: string; label: string; colour: string }[] }

export const CRED_LABEL: Record<string, string> = { current: "Current", expiring: "Expiring soon", expired: "Expired" };

export function MeTab() {
  const { data: me, reload, error } = useLoad<Me>("/api/field/me");
  const [edit, setEdit] = useState(false);
  const [addLic, setAddLic] = useState(false);
  const [projOn, setProjOn] = useState("");
  const [proj, setProj] = useState<Balance[] | null>(null);
  const [run, err] = useAction();
  if (!me) return <p className="muted">{error || "Loading…"}</p>;
  const todo = me.tasks.length + me.policies.length + me.reviews.length + me.surveys.length;
  return (
    <div className="stack">
      <div className="hello"><h1>{me.profile.name}</h1><span className="muted">{me.profile.position || ""}{me.profile.manager ? ` · reports to ${me.profile.manager}` : ""}</span></div>
      {me.announcements.map((a) => (
        <div key={a.id} className={`news ${a.pinned ? "pinned" : ""}`}><b>{a.pinned && "📌 "}{a.title}</b>{a.body && <p>{a.body}</p>}<small className="muted">{fmtDate(a.at)}</small></div>
      ))}
      {todo > 0 && (
        <section className="card">
          <h2>To do ({todo})</h2>
          {me.policies.map((p) => <Link key={`p${p.id}`} className="todo" to={`/field/me/policy/${p.id}`}>✍️ Read and sign: {p.title}<span>›</span></Link>)}
          {me.reviews.map((r) => <Link key={`r${r.id}`} className="todo" to={`/field/me/review/${r.id}`}>⭐ {r.as === "self" ? `${r.cycle}: your side` : `Review ${r.person}`}{r.due && ` · due ${fmtDate(r.due)}`}<span>›</span></Link>)}
          {me.surveys.map((s) => <Link key={`s${s.id}`} className="todo" to={`/field/me/survey/${s.id}`}>💬 {s.title}{s.anonymous && " (anonymous)"}<span>›</span></Link>)}
          {me.tasks.map((t) => (
            <label key={`t${t.id}`} className={`inline task-row ${t.overdue ? "bad" : ""}`}>
              <input type="checkbox" checked={t.done} onChange={() => run(async () => { await api.put(`/api/field/me/tasks/${t.id}`, { done: !t.done }); await reload(); })} />
              <span>{t.title}{t.person && t.user_id && <small className="muted"> · {t.person}</small>}{t.due && <small className="muted"> · {fmtDate(t.due)}</small>}</span>
            </label>
          ))}
          <ErrorLine error={err} />
        </section>
      )}
      <section className="card">
        <div className="row"><h2 style={{ margin: 0 }}>My leave</h2><span className="spacer" /><Link to="/field/timesheet" className="small">Ask for leave ›</Link></div>
        <div className="tiles two">
          {(proj ?? me.leave).filter((b) => b.per_week > 0 || Math.abs(b.balance) > 0.01).map((b) => (
            <div key={b.kind} className="tile">
              <b>{num(proj ? b.projected : b.balance, 1)} h</b><span>{b.name}{!b.available && " (not yet usable)"}</span>
              <small className="muted">{num((proj ? b.projected ?? 0 : b.balance) / 7.6, 1)} days{b.booked_or_requested ? ` · ${num(b.booked_or_requested, 1)} h booked` : ""}</small>
            </div>
          ))}
        </div>
        <div className="row wrap small">
          <span>What will I have by</span>
          <input type="date" value={projOn} min={todayIso()} onChange={async (e) => {
            setProjOn(e.target.value);
            setProj(e.target.value ? await api.get<Balance[]>(`/api/field/me/leave/projected?on=${e.target.value}`) : null);
          }} />
          {proj && <button className="link" onClick={() => { setProj(null); setProjOn(""); }}>Show now</button>}
        </div>
      </section>
      <section className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Licences & tickets</h2><span className="spacer" /><button className="small" onClick={() => setAddLic(!addLic)}>+ Add</button></div>
        {me.compliance.missing.length > 0 && <p className="warn small">Still needed: {me.compliance.missing.join(", ")}</p>}
        {addLic && <AddLicence types={me.credential_types} onDone={() => { setAddLic(false); reload(); }} />}
        {me.compliance.credentials.map((c) => (
          <div key={c.id} className="lic-row">
            <div><b>{c.type}</b><div className="small muted">{[c.number, c.expires ? `expires ${fmtDate(c.expires)}` : "no expiry"].filter(Boolean).join(" · ")}</div></div>
            <span className="spacer" />
            <Status value={c.status} labels={CRED_LABEL} />
            {c.has_file && <button className="link small" onClick={async () => window.open(await fetchBlobUrl(`/api/field/me/credentials/${c.id}/file`))}>Card</button>}
          </div>
        ))}
        {me.compliance.credentials.length === 0 && <p className="muted small">Nothing yet. Add your white card and licences so the office has them.</p>}
      </section>
      {me.goals.length > 0 && (
        <section className="card">
          <h2>My goals</h2>
          {me.goals.map((g) => (
            <div key={g.id} className="goal">
              <div className="row"><b>{g.title}</b><span className="spacer" /><span className="small">{g.progress}%</span></div>
              <input type="range" min={0} max={100} step={10} defaultValue={g.progress}
                onMouseUp={(e) => run(async () => { await api.put(`/api/field/me/goals/${g.id}?progress=${(e.target as HTMLInputElement).value}`); await reload(); })}
                onTouchEnd={(e) => run(async () => { await api.put(`/api/field/me/goals/${g.id}?progress=${(e.target as HTMLInputElement).value}`); await reload(); })} />
            </div>
          ))}
        </section>
      )}
      <section className="card">
        <div className="row"><h2 style={{ margin: 0 }}>My details</h2><span className="spacer" /><button className="small" onClick={() => setEdit(!edit)}>{edit ? "Close" : "Update"}</button></div>
        {edit ? <MyDetails me={me} onDone={() => { setEdit(false); reload(); }} /> : (
          <div className="small kv">
            <span>Phone</span><b>{me.profile.phone || "–"}</b>
            <span>Emergency contact</span><b>{me.profile.emergency_contacts?.[0] ? `${me.profile.emergency_contacts[0].name} (${me.profile.emergency_contacts[0].relationship}) ${me.profile.emergency_contacts[0].phone}` : <span className="warn">Not set</span>}</b>
            <span>Sizes</span><b>{["shirt_size", "pants_size", "boot_size"].map((k) => me.profile[k] as string).filter(Boolean).join(" / ") || "–"}</b>
            <span>Started</span><b>{me.profile.start_date ? `${fmtDate(me.profile.start_date as string)} (${num(me.profile.years_of_service, 1)} years)` : "–"}</b>
            {me.pay && <><span>Pay</span><b>${num(me.pay.amount, 2)}{me.pay.pay_type === "hourly" ? "/h" : "/yr"} from {fmtDate(me.pay.effective)}</b></>}
          </div>
        )}
        <div className="row"><PhotoUpload onDone={reload} /></div>
      </section>
      {(me.gear.length > 0 || me.files.length > 0 || me.reviews_shared.length > 0) && (
        <section className="card">
          {me.gear.length > 0 && <><h3>Gear I have</h3>{me.gear.map((g, i) => <div key={i} className="small">{g.item}{g.serial && ` (${g.serial})`}</div>)}</>}
          {me.files.length > 0 && <><h3>My documents</h3>{me.files.map((f) => (
            <div key={f.id}><button className="link" onClick={async () => window.open(await fetchBlobUrl(`/api/field/me/files/${f.id}`))}>{f.filename}</button> <small className="muted">{f.folder}</small></div>))}</>}
          {me.reviews_shared.length > 0 && <><h3>My reviews</h3>{me.reviews_shared.map((r) => <div key={r.id}><Link to={`/field/me/review/${r.id}`}>{r.cycle}</Link></div>)}</>}
        </section>
      )}
      <Link to="/field/me/people" className="todo">👥 Team directory and who's who<span>›</span></Link>
    </div>
  );
}

function PhotoUpload({ onDone }: { onDone: () => void }) {
  const [run, err] = useAction();
  return (
    <label className="button small">📷 My photo
      <input type="file" accept="image/*" hidden onChange={(e) => {
        const f = e.target.files?.[0];
        if (f) run(async () => { const fd = new FormData(); fd.append("file", await shrinkImage(f, 800), "me.jpg"); await upload("/api/field/me/photo", fd); onDone(); });
      }} />
      <ErrorLine error={err} />
    </label>
  );
}

function AddLicence({ types, onDone }: { types: { id: number; name: string }[]; onDone: () => void }) {
  const [f, setF] = useState({ type_id: "", number: "", issued: "", expires: "" });
  const [file, setFile] = useState<File | null>(null);
  const [run, err, busy] = useAction();
  return (
    <form className="form" onSubmit={(e) => { e.preventDefault(); run(async () => {
      const fd = new FormData();
      Object.entries(f).forEach(([k, v]) => fd.append(k, v));
      if (file) fd.append("file", file.type.startsWith("image/") ? await shrinkImage(file) : file, file.type.startsWith("image/") ? "card.jpg" : file.name);
      await upload("/api/field/me/credentials", fd); onDone();
    }); }}>
      <label>Which one<select required value={f.type_id} onChange={(e) => setF({ ...f, type_id: e.target.value })}>
        <option value="">Pick…</option>{types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
      <label>Number<input value={f.number} onChange={(e) => setF({ ...f, number: e.target.value })} /></label>
      <div className="row"><label>Issued<input type="date" value={f.issued} onChange={(e) => setF({ ...f, issued: e.target.value })} /></label>
        <label>Expires<input type="date" value={f.expires} onChange={(e) => setF({ ...f, expires: e.target.value })} /></label></div>
      <label className="button">📷 Photo of the card {file && "✓"}<input type="file" accept="image/*,application/pdf" capture="environment" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></label>
      <button className="primary" disabled={busy}>Save</button>
      <ErrorLine error={err} />
    </form>
  );
}

function MyDetails({ me, onDone }: { me: Me; onDone: () => void }) {
  const p = me.profile;
  const [f, setF] = useState({
    phone: p.phone || "", personal_email: (p.personal_email as string) || "", address: (p.address as string) || "", dob: (p.dob as string) || "",
    drivers_licence: (p.drivers_licence as string) || "", shirt_size: (p.shirt_size as string) || "", pants_size: (p.pants_size as string) || "",
    boot_size: (p.boot_size as string) || "", medical_notes: (p.medical_notes as string) || "",
    emergency_contacts: p.emergency_contacts?.length ? p.emergency_contacts : [{ name: "", relationship: "", phone: "" }],
  });
  const [run, err, busy] = useAction();
  const set = (k: string, v: string) => setF({ ...f, [k]: v });
  return (
    <form className="form" onSubmit={(e) => { e.preventDefault(); run(async () => {
      await api.put("/api/field/me/profile", { ...f, dob: f.dob || null, emergency_contacts: f.emergency_contacts.filter((c) => c.name || c.phone) }); onDone();
    }); }}>
      <label>Mobile<input type="tel" value={f.phone} onChange={(e) => set("phone", e.target.value)} /></label>
      <label>Personal email<input type="email" value={f.personal_email} onChange={(e) => set("personal_email", e.target.value)} /></label>
      <label>Home address<input value={f.address} onChange={(e) => set("address", e.target.value)} /></label>
      <label>Date of birth<input type="date" value={f.dob} onChange={(e) => set("dob", e.target.value)} /></label>
      <h3>Emergency contact</h3>
      {f.emergency_contacts.map((c, i) => (
        <div key={i} className="stack-sm">
          {(["name", "relationship", "phone"] as const).map((k) => (
            <input key={k} placeholder={k === "name" ? "Name" : k === "relationship" ? "Relationship (partner, mum…)" : "Phone"} value={c[k]}
              onChange={(e) => setF({ ...f, emergency_contacts: f.emergency_contacts.map((x, j) => (j === i ? { ...x, [k]: e.target.value } : x)) })} />
          ))}
        </div>
      ))}
      <button type="button" className="link" onClick={() => setF({ ...f, emergency_contacts: [...f.emergency_contacts, { name: "", relationship: "", phone: "" }] })}>+ Another contact</button>
      <h3>Uniform and PPE sizes</h3>
      <div className="row">
        <label>Shirt<input value={f.shirt_size} onChange={(e) => set("shirt_size", e.target.value)} /></label>
        <label>Pants<input value={f.pants_size} onChange={(e) => set("pants_size", e.target.value)} /></label>
        <label>Boots<input value={f.boot_size} onChange={(e) => set("boot_size", e.target.value)} /></label>
      </div>
      <label>Driver licence class<input value={f.drivers_licence} onChange={(e) => set("drivers_licence", e.target.value)} placeholder="C, LR, MR, HR…" /></label>
      <label>Allergies / medical (for first aid)<textarea value={f.medical_notes} onChange={(e) => set("medical_notes", e.target.value)} /></label>
      <button className="primary" disabled={busy}>Save</button>
      <ErrorLine error={err} />
    </form>
  );
}

export function SignPolicy() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: p } = useLoad<{ id: number; title: string; body: string; has_file: boolean; version: number; signed_at: string | null }>(`/api/field/me/policies/${id}`);
  const [name, setName] = useState("");
  const [sig, setSig] = useState("");
  const [agree, setAgree] = useState(false);
  const [run, err, busy] = useAction();
  if (!p) return <p className="muted">Loading…</p>;
  return (
    <div className="stack">
      <Link to="/field/me">‹ Back</Link>
      <h1>{p.title}</h1>
      {p.body && <div className="card policy-text">{p.body}</div>}
      {p.has_file && <button onClick={async () => window.open(await fetchBlobUrl(`/api/field/me/policies/${p.id}/file`))}>📄 Open the document</button>}
      {p.signed_at ? <p className="ok">You signed this on {fmtDate(p.signed_at)}.</p> : (
        <section className="card form">
          <label className="inline"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} /> I've read and understood it</label>
          <label>Your full name<input value={name} onChange={(e) => setName(e.target.value)} /></label>
          <span className="small muted">Sign with your finger</span>
          <SignaturePad onChange={setSig} />
          <button className="primary" disabled={busy || !agree || name.length < 2}
            onClick={() => run(async () => { await api.post(`/api/field/me/policies/${p.id}/sign`, { typed_name: name, signature: sig, agree }); nav("/field/me"); })}>Sign</button>
          <ErrorLine error={err} />
        </section>
      )}
    </div>
  );
}

interface ReviewOut { id: number; cycle: string; questions: { key: string; label: string; type: string }[]; self_answers: Record<string, unknown>;
  manager_answers: Record<string, unknown>; self_done: boolean; manager_done: boolean; shared: boolean; as: string; name: string; open: boolean; overall: number | null }

export function ReviewForm({ back = "/field/me" }: { back?: string }) {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: r } = useLoad<ReviewOut>(`/api/field/me/reviews/${id}`);
  const [ans, setAns] = useState<Record<string, unknown> | null>(null);
  const [run, err, busy] = useAction();
  if (!r) return <p className="muted">Loading…</p>;
  const mine = r.as === "manager" ? r.manager_answers : r.self_answers;
  const a = ans ?? mine ?? {};
  const done = r.as === "manager" ? r.manager_done : r.self_done;
  const other = r.as === "manager" ? r.self_answers : r.manager_answers;
  return (
    <div className="stack">
      <Link to={back}>‹ Back</Link>
      <h1>{r.cycle}{r.as === "manager" && `: ${r.name}`}</h1>
      {done && <p className="ok small">Sent. {r.as === "self" && !r.shared && "You'll see your manager's side once they share it."}</p>}
      {r.questions.map((q) => (
        <div key={q.key} className="card">
          <b>{q.label}</b>
          {q.type === "rating" ? (
            <div className="nps-scale five">{[1, 2, 3, 4, 5].map((n) => (
              <button key={n} type="button" disabled={done || !r.open} className={a[q.key] === n ? "on" : ""} onClick={() => setAns({ ...a, [q.key]: n })}>{n}</button>))}</div>
          ) : <textarea disabled={done || !r.open} value={(a[q.key] as string) || ""} onChange={(e) => setAns({ ...a, [q.key]: e.target.value })} />}
          {other && other[q.key] !== undefined && other[q.key] !== "" && (r.as === "manager" || r.shared) &&
            <p className="small muted">{r.as === "manager" ? `${r.name} said` : "Manager"}: {String(other[q.key])}</p>}
        </div>
      ))}
      {!done && r.open && (
        <div className="row">
          <button disabled={busy} onClick={() => run(async () => { await api.put(`/api/field/me/reviews/${r.id}`, { answers: a, submit: false }); })}>Save for later</button>
          <button className="primary" disabled={busy} onClick={() => run(async () => { await api.put(`/api/field/me/reviews/${r.id}`, { answers: a, submit: true }); nav(back); })}>Send</button>
        </div>
      )}
      <ErrorLine error={err} />
    </div>
  );
}

export function SurveyForm() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: s } = useLoad<{ id: number; title: string; anonymous: boolean; answered: boolean; open: boolean;
    questions: { key: string; label: string; type: string; options?: string[] }[] }>(`/api/field/me/surveys/${id}`);
  const [a, setA] = useState<Record<string, unknown>>({});
  const [run, err, busy] = useAction();
  if (!s) return <p className="muted">Loading…</p>;
  if (s.answered) return <div className="stack"><Link to="/field/me">‹ Back</Link><p className="ok">Thanks, you've answered this one.</p></div>;
  return (
    <div className="stack">
      <Link to="/field/me">‹ Back</Link>
      <h1>{s.title}</h1>
      {s.anonymous && <p className="small muted">Anonymous: your name isn't kept with your answers.</p>}
      {s.questions.map((q) => (
        <div key={q.key} className="card">
          <b>{q.label}</b>
          {q.type === "enps" && <div className="nps-scale">{Array.from({ length: 11 }, (_, n) => (
            <button key={n} type="button" className={a[q.key] === n ? "on" : ""} onClick={() => setA({ ...a, [q.key]: n })}>{n}</button>))}</div>}
          {q.type === "rating" && <div className="nps-scale five">{[1, 2, 3, 4, 5].map((n) => (
            <button key={n} type="button" className={a[q.key] === n ? "on" : ""} onClick={() => setA({ ...a, [q.key]: n })}>{n}</button>))}</div>}
          {q.type === "choice" && <div className="chips">{(q.options || []).map((o) => (
            <button key={o} type="button" className={`chip ${a[q.key] === o ? "on" : ""}`} onClick={() => setA({ ...a, [q.key]: o })}>{o}</button>))}</div>}
          {q.type === "text" && <textarea value={(a[q.key] as string) || ""} onChange={(e) => setA({ ...a, [q.key]: e.target.value })} />}
        </div>
      ))}
      <button className="primary" disabled={busy || !s.open} onClick={() => run(async () => { await api.post(`/api/field/me/surveys/${s.id}`, { answers: a }); nav("/field/me"); })}>Send</button>
      <ErrorLine error={err} />
    </div>
  );
}

export interface Person { user_id: number; name: string; email: string; phone: string; trade: string; position: string; department: string;
  manager_id: number | null; manager: string; has_photo: boolean; status?: string }

export function Directory({ base = "/field/me" }: { base?: string }) {
  const { data } = useLoad<Person[]>("/api/field/me/directory");
  const [q, setQ] = useState("");
  const [chart, setChart] = useState(false);
  if (!data) return <p className="muted">Loading…</p>;
  const shown = data.filter((p) => !q || `${p.name} ${p.position} ${p.department} ${p.trade}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="stack">
      <Link to={base}>‹ Back</Link>
      <div className="row"><h1 style={{ margin: 0 }}>The team</h1><span className="spacer" />
        <button className="small" onClick={() => setChart(!chart)}>{chart ? "List" : "Org chart"}</button></div>
      {chart ? <OrgChart people={data} /> : (
        <>
          <input placeholder="Search names, roles…" value={q} onChange={(e) => setQ(e.target.value)} />
          {shown.map((p) => (
            <div key={p.user_id} className="person-row">
              <Avatar userId={p.user_id} name={p.name} has={p.has_photo} />
              <div><b>{p.name}</b><div className="small muted">{[p.position || p.trade, p.department].filter(Boolean).join(" · ")}</div></div>
              <span className="spacer" />
              {p.phone && <a className="button small" href={`tel:${p.phone}`}>📞</a>}
              <a className="button small" href={`mailto:${p.email}`}>✉️</a>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

export function OrgChart({ people, onPick }: { people: Person[]; onPick?: (p: Person) => void }) {
  const ids = new Set(people.map((p) => p.user_id));
  const kids = (id: number | null) => people.filter((p) => (id === null ? !p.manager_id || !ids.has(p.manager_id) : p.manager_id === id));
  const Node = ({ p, depth }: { p: Person; depth: number }) => (
    <li>
      <div className="org-node" onClick={() => onPick?.(p)}>
        <Avatar userId={p.user_id} name={p.name} has={p.has_photo} small />
        <div><b>{p.name}</b><div className="small muted">{p.position || p.trade}</div></div>
      </div>
      {depth < 8 && kids(p.user_id).length > 0 && <ul>{kids(p.user_id).map((k) => <Node key={k.user_id} p={k} depth={depth + 1} />)}</ul>}
    </li>
  );
  return <ul className="org-chart">{kids(null).map((p) => <Node key={p.user_id} p={p} depth={0} />)}</ul>;
}

/* --- boards on the phone --- */
export function MyBoardItems({ items }: { items: WorkItem[] }) {
  if (!items.length) return null;
  return (
    <section className="card">
      <h2>Tasks for you</h2>
      {items.slice(0, 12).map((i) => (
        <Link key={i.item_id} className={`todo ${i.bucket === "overdue" ? "blocking" : ""}`} to={`/field/work/${i.item_id}`}>
          <span>{i.name}<small className="muted"> · {i.board}{i.due && ` · ${fmtDate(i.due)}`}</small></span>
          <span>{i.status_label || "›"}</span>
        </Link>
      ))}
    </section>
  );
}

interface FieldItem { id: number; name: string; board: string; values: Record<string, unknown>; shown: Record<string, string>;
  columns: { key: string; title: string; type: string; settings: { labels?: { key: string; label: string; colour: string }[] } }[];
  updates: { id: number; by: string; body: string; at: string }[]; file_list: { id: number; filename: string; is_image: boolean }[];
  subitems: { id: number; name: string; values: Record<string, unknown> }[] }

export function FieldBoardItem() {
  const { itemId } = useParams();
  const { data: it, reload } = useLoad<FieldItem>(`/api/field/my-work/items/${itemId}`);
  const [text, setText] = useState("");
  const [run, err, busy] = useAction();
  if (!it) return <p className="muted">Loading…</p>;
  const statusCols = it.columns.filter((c) => c.type === "status");
  return (
    <div className="stack">
      <Link to="/field">‹ Back</Link>
      <h1>{it.name}</h1>
      <span className="muted small">{it.board}</span>
      {statusCols.map((c) => (
        <div key={c.key} className="card">
          <b>{c.title}</b>
          <div className="chips">{(c.settings.labels || []).map((l) => (
            <button key={l.key} className={`chip ${it.values[c.key] === l.key ? "on" : ""}`} style={it.values[c.key] === l.key ? { background: l.colour, borderColor: l.colour } : {}}
              onClick={() => run(async () => { await api.patch(`/api/field/my-work/items/${it.id}`, { values: { [c.key]: l.key } }); await reload(); })}>{l.label}</button>))}</div>
        </div>
      ))}
      <div className="card small kv">
        {it.columns.filter((c) => c.type !== "status" && it.shown[c.key]).map((c) => <Fragment key={c.key}><span>{c.title}</span><b>{it.shown[c.key]}</b></Fragment>)}
      </div>
      <section className="card">
        <h2>Updates</h2>
        <textarea placeholder="Write an update… @name to tell someone" value={text} onChange={(e) => setText(e.target.value)} />
        <div className="row">
          <button className="primary" disabled={busy || !text.trim()} onClick={() => run(async () => { await api.post(`/api/field/my-work/items/${it.id}/updates`, { body: text }); setText(""); await reload(); })}>Post</button>
          <label className="button">📷 Photo<input type="file" accept="image/*" multiple hidden onChange={(e) => {
            const files = Array.from(e.target.files || []);
            run(async () => { const fd = new FormData(); for (const f of files) fd.append("files", await shrinkImage(f), f.name.replace(/\.\w+$/, ".jpg")); await upload(`/api/field/my-work/items/${it.id}/files`, fd); await reload(); });
          }} /></label>
        </div>
        <ErrorLine error={err} />
        {it.updates.map((u) => <div key={u.id} className="update"><b>{u.by}</b> <small className="muted">{fmtDate(u.at)}</small><p>{u.body}</p></div>)}
        {it.file_list.length > 0 && <div className="small">{it.file_list.map((f) => (
          <button key={f.id} className="link" onClick={async () => window.open(await fetchBlobUrl(`/api/field/my-work/files/${f.id}`))}>📎 {f.filename}</button>))}</div>}
      </section>
    </div>
  );
}
