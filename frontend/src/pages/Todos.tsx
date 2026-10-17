/* Daily to-do lists. Everyone has their own list on the phone's Today screen; supervisors, foremen, managers and the office
   set lists for the team. Clocking off needs every task ticked off, or a reason it couldn't be finished. */
import { Fragment, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, download } from "../api";
import { ErrorLine, fmtDate, fmtDay, todayIso, addDays, Tabs, useAction, useLoad, useMic } from "../ui";

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
      <TalkItIn day={day} onSaved={(m) => { setMsg(m); reload(); }} />
      <section className="card stack">
        <h3 style={{ margin: 0 }}>Or type them: set to-dos for {fmtDay(day)}</h3>
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
  const [tab, setTab] = useState<"lists" | "performance">(() => (new URLSearchParams(window.location.search).get("tab") === "performance" ? "performance" : "lists"));
  return (
    <main className="page">
      <h1>To-do lists</h1>
      <Tabs tabs={[["lists", "Lists"], ["performance", "Performance report"]]} value={tab} onChange={setTab} />
      {tab === "lists" && <>
        <p className="muted small">Set each person's to-dos for the day: talk them in or type them. They tick them off on their phone and can't clock off until each one is done or has a reason it couldn't be finished. Reasons come back to whoever set the task.</p>
        <TeamTodos />
      </>}
      {tab === "performance" && <Performance />}
    </main>
  );
}

export function FieldTeamTodos() {
  const [tab, setTab] = useState<"lists" | "performance">("lists");
  return (
    <div className="stack">
      <Link to="/field" className="small">‹ Today</Link>
      <h1>Crew to-dos</h1>
      <Tabs tabs={[["lists", "Lists"], ["performance", "Who's finishing"]]} value={tab} onChange={setTab} />
      {tab === "lists" ? <TeamTodos phone /> : <Performance phone />}
    </div>
  );
}

/* --- talk it in --- */
interface Draft { day: string; used_ai: boolean; unmatched: string[]; lists: { user_id: number; name: string; is_me: boolean; tasks: { text: string; job_id: number | null; job: string }[] }[] }

function TalkItIn({ day, onSaved }: { day: string; onSaved: (msg: string) => void }) {
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [run, error, busy] = useAction();
  const base = useRef("");
  const join = (a: string, b: string) => [a.trim(), b.trim()].filter(Boolean).join(" ");
  const mic = useMic((heard) => setText(join(base.current, heard)), (heard) => setText(join(base.current, heard)), true);
  const listen = () => { if (mic.listening) { mic.stop(); return; } base.current = text; mic.start(); };
  const make = () => run(async () => { if (mic.listening) mic.stop(); setDraft(await api.post<Draft>("/api/field/todos/parse", { text, day })); });
  const save = () => run(async () => {
    const lists = draft!.lists.map((l) => ({ user_id: l.user_id, tasks: l.tasks.filter((t) => t.text.trim()) })).filter((l) => l.tasks.length);
    const r = await api.post<{ added: number; people: number }>("/api/field/todos/batch", { day: draft!.day, lists });
    onSaved(`Added ${r.added} to-do${r.added === 1 ? "" : "s"} for ${r.people} ${r.people === 1 ? "person" : "people"} on ${fmtDay(draft!.day)}. They've been told.`);
    setDraft(null); setText("");
  });
  const edit = (li: number, ti: number, v: string | null) => setDraft({ ...draft!, lists: draft!.lists.map((l, i) => i !== li ? l : {
    ...l, tasks: v === null ? l.tasks.filter((_, j) => j !== ti) : l.tasks.map((t, j) => (j === ti ? { ...t, text: v } : t)) }).filter((l) => l.tasks.length) });
  const n = draft?.lists.reduce((s, l) => s + l.tasks.length, 0) ?? 0;
  return (
    <section className="card stack talk-card">
      <div className="row">
        <h3 style={{ margin: 0, flex: 1 }}>🎤 Talk it in</h3>
        {mic.supported && <button className={`mic-big ${mic.listening ? "on" : ""}`} onClick={listen} aria-label={mic.listening ? "Stop listening" : "Start talking"}>
          {mic.listening ? "■ Stop" : "🎤 Talk"}</button>}
      </div>
      {!draft && <>
        <p className="small muted" style={{ margin: 0 }}>Say it like you'd say it on site: <i>"Dave, pressure test level 2 and clean up the slab. Sam, pack down the trench shield. Everyone lock the container."</i>
          {mic.supported ? "" : " (Your browser can't listen: type it instead, or use the keyboard's microphone.)"}</p>
        <textarea rows={3} className={mic.listening ? "listening" : ""} placeholder={mic.listening ? "Listening…" : "Or type it the same way"} value={text} onChange={(e) => setText(e.target.value)} />
        <div className="row"><button className="primary" onClick={make} disabled={busy || text.trim().length < 3}>{busy ? "Working it out…" : "Make the lists"}</button>
          {text && <button className="link" onClick={() => setText("")}>Clear</button>}</div>
      </>}
      {draft && <>
        <p className="small" style={{ margin: 0 }}>Check these for <b>{fmtDay(draft.day)}</b>{draft.used_ai ? "" : " (read without the AI: check the names)"}. Edit or remove anything, then save.</p>
        {draft.lists.length === 0 && <p className="warn small">Couldn't tell who these were for. Start each person's part with their name.</p>}
        {draft.lists.map((l, li) => (
          <div key={l.user_id} className="draft-person">
            <b>{l.is_me ? "Me" : l.name}</b>
            {l.tasks.map((t, ti) => (
              <div key={ti} className="row draft-task">
                <input value={t.text} onChange={(e) => edit(li, ti, e.target.value)} style={{ flex: 1 }} />
                {t.job && <small className="muted">{t.job}</small>}
                <button className="link" aria-label="Remove" onClick={() => edit(li, ti, null)}>✕</button>
              </div>
            ))}
          </div>
        ))}
        {draft.unmatched.length > 0 && <p className="small warn" style={{ margin: 0 }}>Not given to anyone: {draft.unmatched.join("; ")}</p>}
        <div className="row">
          <button className="primary" onClick={save} disabled={busy || !n}>Save {n} to-do{n === 1 ? "" : "s"}</button>
          <button onClick={() => setDraft(null)}>Back</button>
        </div>
      </>}
      <ErrorLine error={error} />
    </section>
  );
}

/* --- who gets through their list: the management report --- */
interface PerfRow { user_id: number; name: string; trade: string; tasks: number; done: number; not_done: number; untouched: number; done_pct: number | null;
  actioned_pct: number | null; days: number; days_all_done: number; set_by_others: number; carried: number; rating: string;
  periods: Record<string, { tasks: number; done: number; done_pct: number | null }>; reasons: { day: string; task: string; reason: string }[] }
interface Perf { start: string; end: string; group: "week" | "month"; periods: string[]; people: PerfRow[]; thresholds: string;
  totals: { tasks: number; done: number; not_done: number; untouched: number; done_pct: number | null } }

const monthStart = (iso: string) => iso.slice(0, 8) + "01";
const RANGES: [string, string, () => [string, string, "week" | "month"]][] = [
  ["this-week", "This week", () => { const t = todayIso(); const d = new Date(t + "T00:00:00"); return [addDays(t, -((d.getDay() + 6) % 7)), t, "week"]; }],
  ["last-week", "Last week", () => { const t = todayIso(); const d = new Date(t + "T00:00:00"); const m = addDays(t, -((d.getDay() + 6) % 7)); return [addDays(m, -7), addDays(m, -1), "week"]; }],
  ["4-weeks", "Last 4 weeks", () => [addDays(todayIso(), -27), todayIso(), "week"]],
  ["this-month", "This month", () => [monthStart(todayIso()), todayIso(), "week"]],
  ["last-month", "Last month", () => { const s = monthStart(todayIso()); const e = addDays(s, -1); return [monthStart(e), e, "week"]; }],
  ["3-months", "Last 3 months", () => { const s = monthStart(todayIso()); return [monthStart(addDays(monthStart(addDays(s, -1)), -1)), todayIso(), "month"]; }],
  ["12-months", "Last 12 months", () => [monthStart(addDays(todayIso(), -334)), todayIso(), "month"]],
];
const RATE_CLASS: Record<string, string> = { Performing: "ok", Watch: "warn", "Needs attention": "bad", "No to-dos": "" };

function Performance({ phone }: { phone?: boolean }) {
  const [range, setRange] = useState("4-weeks");
  const [custom, setCustom] = useState<[string, string]>([addDays(todayIso(), -27), todayIso()]);
  const [group, setGroup] = useState<"week" | "month">("week");
  const [open, setOpen] = useState<number | null>(null);
  const [run, err] = useAction();
  const [s, e] = range === "custom" ? custom : RANGES.find((r) => r[0] === range)![2]();
  const q = `start=${s}&end=${e}&group=${group}`;
  const { data, error } = useLoad<Perf>(`/api/field/todos/report?${q}`, [q]);
  const pick = (k: string) => { setRange(k); const r = RANGES.find((x) => x[0] === k); if (r) setGroup(r[2]()[2]); };
  const label = (p: string) => (group === "month" ? new Date(p + "-01T00:00:00").toLocaleDateString("en-AU", { month: "short", year: "2-digit" })
    : "w/c " + new Date(p + "T00:00:00").toLocaleDateString("en-AU", { day: "numeric", month: "short" }));
  const counts = (data?.people ?? []).reduce((m, r) => ({ ...m, [r.rating]: (m[r.rating] ?? 0) + 1 }), {} as Record<string, number>);
  return (
    <div className="stack">
      <div className="row wrap">
        <select value={range} onChange={(ev) => pick(ev.target.value)}>
          {RANGES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}<option value="custom">Pick dates…</option></select>
        {range === "custom" && <><input type="date" value={custom[0]} onChange={(ev) => setCustom([ev.target.value, custom[1]])} />
          <input type="date" value={custom[1]} onChange={(ev) => setCustom([custom[0], ev.target.value])} /></>}
        <div className="seg"><button className={group === "week" ? "on" : ""} onClick={() => setGroup("week")}>By week</button>
          <button className={group === "month" ? "on" : ""} onClick={() => setGroup("month")}>By month</button></div>
        <span className="spacer" />
        <button onClick={() => run(() => download(`/api/field/todos/report.xlsx?${q}`, "todo-performance.xlsx"))}>⬇ Export to Excel</button>
      </div>
      <ErrorLine error={error || err} />
      {data && <>
        <div className="tiles">
          <div className={`tile ${(data.totals.done_pct ?? 100) < 65 ? "bad" : (data.totals.done_pct ?? 100) < 85 ? "warn" : "ok"}`}><b>{data.totals.done_pct ?? "–"}%</b>
            <span>of {data.totals.tasks} to-dos finished · {fmtDate(data.start)} to {fmtDate(data.end)}</span></div>
          <div className="tile ok"><b>{counts.Performing ?? 0}</b><span>performing</span></div>
          <div className="tile warn"><b>{counts.Watch ?? 0}</b><span>to watch</span></div>
          <div className="tile bad"><b>{counts["Needs attention"] ?? 0}</b><span>need attention</span></div>
          <div className="tile"><b>{data.totals.not_done}</b><span>couldn't finish (with a reason)</span></div>
          <div className={`tile ${data.totals.untouched ? "warn" : ""}`}><b>{data.totals.untouched}</b><span>never actioned</span></div>
        </div>
        <p className="small muted" style={{ margin: 0 }}>{data.thresholds} Today's unfinished to-dos aren't counted until the day is over.</p>
        <div className="dt-wrap">
          <table className="dt perf-table">
            <thead><tr><th>Person</th><th>Rating</th><th className="n">To-dos</th><th className="n">Finished</th><th className="n hide-sm">Couldn't</th>
              <th className="n hide-sm">Never actioned</th><th className="n hide-sm">Days all done</th>{!phone && <th>{group === "month" ? "Each month" : "Each week"} (% finished)</th>}</tr></thead>
            <tbody>
              {data.people.filter((r) => r.tasks || !phone).map((r) => (
                <Fragment key={r.user_id}>
                  <tr className="click" onClick={() => setOpen(open === r.user_id ? null : r.user_id)}>
                    <td data-label="Person"><b>{r.name}</b> <small className="muted">{r.trade}</small></td>
                    <td data-label="Rating"><span className={`rate-chip ${RATE_CLASS[r.rating]}`}>{r.rating}</span></td>
                    <td className="n" data-label="To-dos">{r.tasks}</td>
                    <td className="n" data-label="Finished">{r.tasks ? <><div className="pct-bar"><span style={{ width: `${r.done_pct ?? 0}%` }} /></div>{r.done_pct}%</> : "–"}</td>
                    <td className="n hide-sm" data-label="Couldn't">{r.not_done || ""}</td>
                    <td className={`n hide-sm ${r.untouched ? "bad" : ""}`} data-label="Never actioned">{r.untouched || ""}</td>
                    <td className="n hide-sm" data-label="Days all done">{r.days ? `${r.days_all_done}/${r.days}` : ""}</td>
                    {!phone && <td data-label="Trend"><div className="spark" title={data.periods.map((p) => `${label(p)}: ${r.periods[p]?.done_pct ?? "–"}%`).join("\n")}>
                      {data.periods.map((p) => { const v = r.periods[p]; return <span key={p} className={v?.done_pct === null || !v ? "none" : v.done_pct >= 85 ? "ok" : v.done_pct >= 65 ? "warn" : "bad"}
                        style={{ height: v?.done_pct != null ? `${Math.max(8, v.done_pct)}%` : "8%" }} title={`${label(p)}: ${v?.done_pct ?? "–"}%`} />; })}
                    </div></td>}
                  </tr>
                  {open === r.user_id && (
                    <tr className="perf-detail"><td colSpan={phone ? 7 : 8}>
                      <div className="small">{data.periods.map((p) => <span key={p} className="period-pill">{label(p)}: <b>{r.periods[p]?.tasks ? `${r.periods[p].done_pct}%` : "–"}</b>
                        {r.periods[p]?.tasks ? ` (${r.periods[p].done}/${r.periods[p].tasks})` : ""}</span>)}</div>
                      {r.reasons.length > 0 ? <><b className="small">Why they couldn't finish</b>
                        <ul className="small reasons">{r.reasons.slice().reverse().map((x, i) => <li key={i}>{fmtDate(x.day)}: <i>{x.task}</i>: {x.reason}</li>)}</ul></>
                        : <p className="small muted">No "couldn't finish" reasons in this period.</p>}
                      <p className="small muted">{r.set_by_others} of {r.tasks} set by a supervisor or the office · {r.carried} carried over from an earlier day.</p>
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </>}
    </div>
  );
}
