/* Daily to-do lists. Everyone has their own list on the phone's Today screen; supervisors, foremen, managers and the office
   set lists for the team. Clocking off needs every task ticked off, or a reason it couldn't be finished. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { ErrorLine, fmtDay, todayIso, addDays, useAction, useLoad } from "../ui";

export interface Task { id: number; user_id: number; user: string; day: string; text: string; job_id: number | null; job: string; set_by_id: number | null;
  set_by: string; status: "open" | "done" | "not_done"; comment: string; done_at: string | null; carried_from: number | null }
interface Mine { day: string; tasks: Task[]; open: number; leads_team: boolean }
interface Person { user_id: number; name: string; trade: string; phone: string; tasks: Task[]; done: number; not_done: number; open: number }
interface Team { day: string; people: Person[]; leads_team: boolean }

/** One task: tick it, or say why it couldn't be done. */
function TaskRow({ t, me, onChange, canRemove }: { t: Task; me?: number; onChange: () => void; canRemove?: boolean }) {
  const [why, setWhy] = useState<string | null>(null);
  const [run, error, busy] = useAction();
  const set = (status: Task["status"], comment = "") => run(async () => { await api.patch(`/api/field/todos/${t.id}`, { status, comment }); setWhy(null); onChange(); });
  const remove = () => run(async () => { await api.del(`/api/field/todos/${t.id}`); onChange(); });
  return (
    <div className={`todo-item ${t.status}`}>
      <div className="row">
        <button className="todo-tick" aria-label={t.status === "done" ? "Mark not done" : "Tick off"} disabled={busy}
          onClick={() => set(t.status === "done" ? "open" : "done")}>{t.status === "done" ? "✓" : t.status === "not_done" ? "✗" : ""}</button>
        <span className="grow">
          <span className="todo-text">{t.text}</span>
          <small className="block muted">{[t.job, t.set_by && t.set_by_id !== me ? `set by ${t.set_by}` : "", t.carried_from ? "carried over" : ""].filter(Boolean).join(" · ")}</small>
          {t.status === "not_done" && <small className="block warn">Couldn't finish: {t.comment}</small>}
          {t.status === "done" && t.comment && <small className="block muted">{t.comment}</small>}
        </span>
        {t.status === "open" && why === null && <button className="link small" onClick={() => setWhy("")}>Couldn't finish</button>}
        {t.status === "not_done" && <button className="link small" onClick={() => set("open")} disabled={busy}>Undo</button>}
        {canRemove && <button className="link small" aria-label="Remove" onClick={remove} disabled={busy}>✕</button>}
      </div>
      {why !== null && (
        <div className="row todo-why">
          <input autoFocus placeholder="Why? e.g. waiting on the concrete truck" value={why} onChange={(e) => setWhy(e.target.value)} style={{ flex: 1 }} />
          <button className="primary small" disabled={busy || why.trim().length < 3} onClick={() => set("not_done", why)}>Save</button>
          <button className="link small" onClick={() => setWhy(null)}>Cancel</button>
        </div>
      )}
      <ErrorLine error={error} />
    </div>
  );
}

/** The phone's Today screen: my list, and how many are left before I can clock off. */
export function MyTodos({ me, onOpen, clockedIn }: { me: number; onOpen: (n: number) => void; clockedIn: boolean }) {
  const { data, reload } = useLoad<Mine>("/api/field/todos");
  const [text, setText] = useState("");
  const [run, error, busy] = useAction();
  useEffect(() => { if (data) onOpen(data.open); }, [data, onOpen]);
  if (!data) return null;
  const add = () => run(async () => { await api.post("/api/field/todos", { texts: text.split("\n"), day: data.day }); setText(""); reload(); });
  const done = data.tasks.filter((t) => t.status !== "open").length;
  return (
    <section className={`card todo-card ${data.open && clockedIn ? "attention" : ""}`}>
      <div className="row">
        <h3 style={{ margin: 0, flex: 1 }}>📋 To-do today</h3>
        {data.tasks.length > 0 && <span className={`small ${data.open ? "warn" : "ok"}`}>{done} of {data.tasks.length} done</span>}
      </div>
      {data.tasks.length === 0 && <p className="small muted">Nothing on your list. Add your own below{data.leads_team ? ", or set the crew's" : ""}.</p>}
      {data.tasks.map((t) => <TaskRow key={t.id} t={t} me={me} onChange={reload} canRemove={t.set_by_id === me} />)}
      {data.open > 0 && clockedIn && <p className="small warn" style={{ margin: "6px 0 0" }}>Tick these off, or tap "Couldn't finish" and say why, before you clock off.</p>}
      <div className="row todo-add">
        <input placeholder="Add a to-do" value={text} onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && text.trim()) add(); }} style={{ flex: 1 }} />
        <button onClick={add} disabled={busy || !text.trim()}>Add</button>
      </div>
      <ErrorLine error={error} />
      {data.leads_team && <Link to="/field/todos" className="small">👷 Set the crew's to-dos ›</Link>}
    </section>
  );
}

/** Supervisors, foremen, managers and the office: set lists for the team and see who's finished. */
export function TeamTodos({ phone }: { phone?: boolean }) {
  const [day, setDay] = useState(todayIso());
  const { data, reload } = useLoad<Team>(`/api/field/todos/team?day=${day}`, [day]);
  const jobs = useLoad<{ id: number; job_no: string; name: string }[]>("/api/field/jobs");
  const [sel, setSel] = useState<number[]>([]);
  const [text, setText] = useState("");
  const [job, setJob] = useState("");
  const [msg, setMsg] = useState("");
  const [run, error, busy] = useAction();
  if (!data) return <p className="muted">Loading…</p>;
  const me = data.people[0]?.user_id;
  const add = () => run(async () => {
    const lines = text.split("\n").filter((l) => l.trim());
    await api.post("/api/field/todos", { user_ids: sel, texts: lines, day, job_id: job ? Number(job) : null });
    setMsg(`Added ${lines.length} to-do${lines.length > 1 ? "s" : ""} for ${sel.length} ${sel.length > 1 ? "people" : "person"}. They've been told.`);
    setText(""); reload();
  });
  const carry = () => run(async () => {
    const r = await api.post<{ carried: number }>("/api/field/todos/carry", { from_day: addDays(day, -1), to_day: day, user_ids: data.people.map((p) => p.user_id) });
    setMsg(r.carried ? `Carried ${r.carried} unfinished to-do${r.carried > 1 ? "s" : ""} over from the day before.` : "Nothing unfinished from the day before.");
    reload();
  });
  const toggle = (id: number) => setSel(sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]);
  const totals = data.people.reduce((s, p) => ({ done: s.done + p.done, nd: s.nd + p.not_done, open: s.open + p.open }), { done: 0, nd: 0, open: 0 });
  return (
    <div className="stack">
      <div className="row wrap">
        <div className="seg">
          {[addDays(todayIso(), -1), todayIso(), addDays(todayIso(), 1)].map((d, i) => (
            <button key={d} className={day === d ? "on" : ""} onClick={() => setDay(d)}>{["Yesterday", "Today", "Tomorrow"][i]}</button>))}
        </div>
        <input type="date" value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
        {!phone && <span className="muted small">{fmtDay(day)} · {totals.done} done · {totals.nd} couldn't finish · {totals.open} still open</span>}
      </div>
      <section className="card stack">
        <h3 style={{ margin: 0 }}>Set to-dos for {fmtDay(day)}</h3>
        <div className="chips">
          {data.people.map((p) => <button key={p.user_id} type="button" className={`chip ${sel.includes(p.user_id) ? "on" : ""}`} onClick={() => toggle(p.user_id)}>
            {p.user_id === me ? "Me" : p.name}</button>)}
          {data.people.length > 2 && <button type="button" className="chip" onClick={() => setSel(sel.length === data.people.length - 1 ? [] : data.people.slice(1).map((p) => p.user_id))}>
            {sel.length === data.people.length - 1 ? "Clear" : "Whole crew"}</button>}
        </div>
        <textarea rows={3} placeholder={"One to-do per line, e.g.\nPressure test level 2 stack\nClean up and lock the site container"} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="row wrap">
          <select value={job} onChange={(e) => setJob(e.target.value)}><option value="">No particular job</option>
            {(jobs.data ?? []).map((j) => <option key={j.id} value={j.id}>{j.job_no} {j.name}</option>)}</select>
          <button className="primary" onClick={add} disabled={busy || !sel.length || !text.trim()}>Add to {sel.length || "…"} {sel.length === 1 ? "list" : "lists"}</button>
          <button onClick={carry} disabled={busy}>Carry over yesterday's unfinished</button>
        </div>
        {msg && <p className="ok small" style={{ margin: 0 }}>{msg}</p>}
        <ErrorLine error={error} />
      </section>
      <div className={phone ? "stack" : "todo-grid"}>
        {data.people.filter((p) => p.tasks.length || p.user_id !== me).sort((a, b) => Number(b.tasks.length > 0) - Number(a.tasks.length > 0)).map((p) => (
          <section key={p.user_id} className="card todo-person">
            <div className="row">
              <b className="grow">{p.user_id === me ? "Me" : p.name} <small className="muted">{p.trade}</small></b>
              {p.tasks.length > 0 && <span className={`small ${p.open ? "warn" : "ok"}`}>{p.done}/{p.tasks.length}{p.not_done ? ` · ${p.not_done} ✗` : ""}</span>}
              {p.phone && p.user_id !== me && <a href={`tel:${p.phone.replace(/[^\d+]/g, "")}`} className="small" aria-label={`Call ${p.name}`}>📞</a>}
            </div>
            {p.tasks.length === 0 && <p className="small muted" style={{ margin: 0 }}>No to-dos.</p>}
            {p.tasks.map((t) => <TaskRow key={t.id} t={t} me={me} onChange={reload} canRemove={t.set_by_id === me || p.user_id !== me} />)}
          </section>
        ))}
      </div>
    </div>
  );
}

export default function TodosPage() {
  return (
    <main className="page">
      <h1>To-do lists</h1>
      <p className="muted small">Set each person's to-dos for the day. They tick them off on their phone and can't clock off until each one is done or has a reason it couldn't be finished. Reasons come back to whoever set the task.</p>
      <TeamTodos />
    </main>
  );
}

export function FieldTeamTodos() {
  return (
    <div className="stack">
      <Link to="/field" className="small">‹ Today</Link>
      <h1>Crew to-dos</h1>
      <TeamTodos phone />
    </div>
  );
}
