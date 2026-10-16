/* The phone app for the team on the tools (QuickBooks Workforce / Simpro Mobile / Plant Assessor style):
   Today (clock in and out, switch jobs, breaks), Jobs, Schedule, Pre-start (plant and vehicles), Timesheet,
   and Crew for supervisors. Punches made without reception are kept on the phone and sent when it's back online. */
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, NavLink, Route, Routes, useNavigate, useParams } from "react-router-dom";
import { api, ApiError, fetchBlobUrl, upload } from "../api";
import { useApp } from "../App";
import { AskPeakButton } from "./AskPeak";
import { addDays, DocOut, ErrorLine, fmtDay, getLocation, shrinkImage, hrs, monday, num, PhotoButton, SignaturePad, todayIso, useAction, useLoad } from "../ui";

interface Entry { id: number; job_id: number | null; job_no: string; job: string; task: string; start_at: string; end_at: string | null; local_day: string;
  start_local: string; end_local: string | null; hours: number; break_minutes: number; on_break: boolean; status: string; notes: string; flags: string[]; source: string }
interface Sched { id: number; job_id: number | null; job_no: string; job: string; address: string; day: string; start: string; end: string; kind: string; notes: string; priority: string }
interface Todo { kind: string; plant_id: number; plant: string; text: string }
interface Today { user: { name: string; trade: string }; day: string; current: Entry | null; schedule: Sched[]; today_hours: number; week_hours: number;
  todo: { blocking: Todo[]; reminders: Todo[] }; end_needs: string[]; notifications: { id: number; text: string; link: string; at: string }[];
  vehicles: { id: number; name: string; rego: string }[]; is_supervisor: boolean }
interface JobBrief { id: number; job_no: string; name: string; customer: string; address: string; priority: string; work_status: string; work_type: string;
  kind: string; today?: boolean }
interface PlantRow { id: number; kind: string; name: string; fleet_no: string; rego: string; category: string; status: string; mine: boolean; photos_required: boolean;
  hours: number | null; odometer: number | null; prestart_today: boolean; prestart_passed: boolean; weekly_done: boolean; wash_done: boolean;
  end_day_done: boolean; open_defects: number }

/* --- offline punches --- */
const QKEY = "peak-field-queue";
type Punch = { path: string; body: Record<string, unknown> };
const readQ = (): Punch[] => { try { return JSON.parse(localStorage.getItem(QKEY) || "[]"); } catch { return []; } };
const writeQ = (q: Punch[]) => { try { localStorage.setItem(QKEY, JSON.stringify(q)); } catch { /* full */ } };
async function flushQueue(): Promise<number> {
  const q = readQ();
  let sent = 0;
  while (q.length) {
    try { await api.post(q[0].path, q[0].body); } catch (e) {
      if (e instanceof ApiError && e.status > 0) { q.shift(); continue; }  // the server said no: drop it, the office can fix the time
      break;  // still offline
    }
    q.shift(); sent++;
  }
  writeQ(q);
  return sent;
}
/** Post a punch; if there's no connection, keep it for later (with the time it really happened). */
async function punch(path: string, body: Record<string, unknown>): Promise<"sent" | "queued"> {
  const full = { ...body, at: new Date().toISOString(), client_ref: crypto.randomUUID?.() ?? String(Date.now()) };
  try { await api.post(path, full); return "sent"; } catch (e) {
    if (e instanceof TypeError || (e instanceof ApiError && e.status === 0)) { writeQ([...readQ(), { path, body: full }]); return "queued"; }
    throw e;
  }
}

function useTicker(start: string | null | undefined) {
  const [, set] = useState(0);
  useEffect(() => { if (!start) return; const t = setInterval(() => set((x) => x + 1), 30000); return () => clearInterval(t); }, [start]);
  if (!start) return "";
  const m = Math.max(0, Math.floor((Date.now() - new Date(start).getTime()) / 60000));
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

export default function FieldApp({ onLogout }: { onLogout?: () => void }) {
  const { user } = useApp();
  const [queued, setQueued] = useState(readQ().length);
  useEffect(() => {
    const go = () => flushQueue().then(() => setQueued(readQ().length));
    go();
    window.addEventListener("online", go);
    return () => window.removeEventListener("online", go);
  }, []);
  return (
    <div className="field-app">
      <header className="field-top">
        <b>Peak</b><span className="spacer" /><AskPeakButton />
        {user.role !== "field" && <Link to="/" className="small">Back to the office app</Link>}
        {onLogout && <button className="link small" onClick={onLogout}>Sign out</button>}
      </header>
      {queued > 0 && <div className="offline-bar">{queued} punch{queued > 1 ? "es" : ""} saved on this phone, sending when you're back online.</div>}
      <main className="field-main">
        <Routes>
          <Route index element={<TodayTab onQueued={() => setQueued(readQ().length)} />} />
          <Route path="jobs" element={<JobsTab />} />
          <Route path="jobs/:jobId" element={<FieldJob />} />
          <Route path="schedule" element={<ScheduleTab />} />
          <Route path="prestart" element={<PrestartTab />} />
          <Route path="prestart/:plantId" element={<PlantCheckFlow />} />
          <Route path="timesheet" element={<TimesheetTab />} />
          <Route path="crew" element={<CrewTab />} />
        </Routes>
      </main>
      <nav className="field-tabs">
        <NavLink to="/field" end>🕒<span>Today</span></NavLink>
        <NavLink to="/field/jobs">🧰<span>Jobs</span></NavLink>
        <NavLink to="/field/schedule">📅<span>Schedule</span></NavLink>
        <NavLink to="/field/prestart">🚜<span>Pre-start</span></NavLink>
        <NavLink to="/field/timesheet">🧾<span>Timesheet</span></NavLink>
      </nav>
    </div>
  );
}

function TodayTab({ onQueued }: { onQueued: () => void }) {
  const { data: t, reload, error: loadErr } = useLoad<Today>("/api/field/today");
  const [picking, setPicking] = useState<"in" | "switch" | null>(null);
  const [run, error, busy, setError] = useAction();
  const [problems, setProblems] = useState<string[]>([]);
  const [msg, setMsg] = useState("");
  const timer = useTicker(t?.current?.start_at);
  if (!t) return <p className="muted">{loadErr || "Loading…"}</p>;
  const act = (path: string, body: Record<string, unknown> = {}) => run(async () => {
    setProblems([]); setMsg("");
    try {
      const loc = await getLocation();
      const r = await punch(path, { ...body, ...loc });
      if (r === "queued") { setMsg("No reception: saved on the phone, it'll send when you're back online."); onQueued(); }
      setPicking(null);
      await reload();
    } catch (e) {
      const m = (e as Error).message;
      setProblems([m]);
      throw e;
    }
  });
  const cur = t.current;
  return (
    <div className="stack">
      <div className="hello"><h1>G'day {t.user.name.split(" ")[0]}</h1><span className="muted">{fmtDay(t.day)}</span></div>
      {t.todo.blocking.map((b) => (
        <Link key={b.kind + b.plant_id} to={`/field/prestart/${b.plant_id}?kind=${b.kind === "wash" ? "wash" : "weekly"}`} className="todo blocking">
          ⚠️ {b.text}<span>Do it now ›</span></Link>
      ))}
      {t.todo.reminders.map((b, i) => (
        <Link key={i} to={b.kind === "wash" ? `/field/prestart/${b.plant_id}?kind=wash` : "/field/prestart"} className="todo">{b.text}<span>›</span></Link>
      ))}
      <section className={`clock-card ${cur ? (cur.on_break ? "break" : "on") : ""}`}>
        {cur ? (
          <>
            <div className="small">{cur.on_break ? "On a break" : "Clocked in"} since {cur.start_local}</div>
            <div className="big">{timer}</div>
            <div><b>{cur.job_no} {cur.job || "No job"}</b>{cur.task && <> · {cur.task}</>}</div>
            {cur.job_id && <Link to={`/field/jobs/${cur.job_id}`} className="small">📷 Photos, plans and materials ›</Link>}
            {t.end_needs.map((n) => <p key={n} className="warn small">{n} <Link to="/field/prestart">Pre-start ›</Link></p>)}
            <div className="clock-actions">
              <button onClick={() => setPicking("switch")} disabled={busy}>Switch job</button>
              <button onClick={() => act(cur.on_break ? "/api/field/break/end" : "/api/field/break/start")} disabled={busy}>
                {cur.on_break ? "End break" : "Take a break"}</button>
              <button className="danger big-btn" onClick={() => act("/api/field/clock-out")} disabled={busy}>Clock out</button>
            </div>
          </>
        ) : (
          <>
            <div className="small muted">You're not clocked in</div>
            <button className="primary big-btn" onClick={() => setPicking("in")} disabled={busy || t.todo.blocking.length > 0}>Clock in</button>
          </>
        )}
      </section>
      {problems.map((p) => <p key={p} className="error">{p}</p>)}
      {msg && <p className="warn">{msg}</p>}
      <ErrorLine error={problems.length ? "" : error} />
      {picking && <ClockInSheet title={picking === "in" ? "Clock in to" : "Switch to"} onCancel={() => { setPicking(null); setError(""); }}
                                onPick={(b) => act("/api/field/clock-in", b)} busy={busy} />}
      <div className="tiles two"><div className="tile"><b>{hrs(t.today_hours)}</b><span>today</span></div><div className="tile"><b>{hrs(t.week_hours)}</b><span>this week</span></div></div>
      <section>
        <h2>Today's jobs</h2>
        {t.schedule.length === 0 && <p className="muted small">Nothing scheduled for you today.</p>}
        {t.schedule.map((s) => (
          <Link key={s.id} to={s.job_id ? `/field/jobs/${s.job_id}` : "#"} className="job-tile">
            <b>{s.start}–{s.end}</b> {s.job_no} {s.job || s.kind}
            {s.address && <span className="small muted">{s.address}</span>}{s.notes && <span className="small">{s.notes}</span>}
          </Link>
        ))}
      </section>
      {t.is_supervisor && <Link to="/field/crew" className="job-tile">👷 Clock my crew on or off ›</Link>}
      {t.notifications.length > 0 && (
        <section><h2>Messages</h2>
          {t.notifications.map((n) => (
            <div key={n.id} className="note-row"><span>{n.text}</span>
              <button className="link small" onClick={async () => { await api.post(`/api/field/notifications/${n.id}/read`); reload(); }}>OK</button></div>
          ))}
        </section>
      )}
    </div>
  );
}

function ClockInSheet({ title, onPick, onCancel, busy }: { title: string; onPick: (b: Record<string, unknown>) => void; onCancel: () => void; busy: boolean }) {
  const [q, setQ] = useState("");
  const { data: jobs } = useLoad<JobBrief[]>(`/api/field/jobs?q=${encodeURIComponent(q)}`, [q]);
  const { data: plant } = useLoad<PlantRow[]>("/api/field/plant");
  const [job, setJob] = useState<JobBrief | null>(null);
  const [task, setTask] = useState("");
  const [plantId, setPlantId] = useState<number | "">("");
  const machines = (plant ?? []).filter((p) => p.kind === "plant");
  return (
    <div className="sheet-back" onClick={onCancel}>
      <div className="sheet" onClick={(e) => e.stopPropagation()}>
        <div className="row"><h2 style={{ margin: 0 }}>{title}</h2><span className="spacer" /><button className="link" onClick={onCancel}>Cancel</button></div>
        {!job ? (
          <>
            <input placeholder="Search jobs" value={q} onChange={(e) => setQ(e.target.value)} />
            <div className="pick-list">
              <button className="job-tile" onClick={() => setJob({ id: 0, job_no: "", name: "No job (yard, travel, training)", customer: "", address: "", priority: "", work_status: "", work_type: "", kind: "" })}>
                No job: yard, travel, training</button>
              {jobs?.map((j) => (
                <button key={j.id} className={`job-tile ${j.today ? "today" : ""}`} onClick={() => setJob(j)}>
                  <b>{j.job_no} {j.name}</b>{j.today && <span className="badge ok">Today</span>}
                  <span className="small muted">{[j.customer, j.address].filter(Boolean).join(" · ")}</span>
                </button>
              ))}
            </div>
          </>
        ) : (
          <>
            <p><b>{job.job_no} {job.name}</b> <button className="link small" onClick={() => setJob(null)}>change</button></p>
            <label className="field"><span>What are you doing? (optional)</span>
              <div className="chips">{["Rough-in", "Fit-off", "Drainage", "Service call", "Excavation", "Travel"].map((x) => (
                <button key={x} type="button" className={task === x ? "chip on" : "chip"} onClick={() => setTask(task === x ? "" : x)}>{x}</button>))}</div>
            </label>
            {machines.length > 0 && (
              <label className="field"><span>Operating a machine today?</span>
                <select value={plantId} onChange={(e) => setPlantId(e.target.value ? Number(e.target.value) : "")}>
                  <option value="">No</option>
                  {machines.map((p) => <option key={p.id} value={p.id} disabled={p.status !== "in_service"}>{p.name}{p.fleet_no ? ` (${p.fleet_no})` : ""}
                    {p.status !== "in_service" ? " – out of service" : p.prestart_today ? " ✓ pre-start done" : " – pre-start needed"}</option>)}
                </select>
              </label>
            )}
            <button className="primary big-btn" disabled={busy}
                    onClick={() => onPick({ job_id: job.id || null, task, plant_id: plantId || null })}>{busy ? "…" : title.startsWith("Clock") ? "Clock in" : "Switch"}</button>
          </>
        )}
      </div>
    </div>
  );
}

function JobsTab() {
  const [q, setQ] = useState("");
  const [finished, setFinished] = useState(false);
  const { data } = useLoad<JobBrief[]>(`/api/field/jobs?q=${encodeURIComponent(q)}&finished=${finished}`, [q, finished]);
  return (
    <div className="stack">
      <h1>Jobs</h1>
      <input placeholder="Search by name, number, customer or street" value={q} onChange={(e) => setQ(e.target.value)} />
      <label className="check-line small"><input type="checkbox" checked={finished} onChange={(e) => setFinished(e.target.checked)} /> Show finished jobs too (to add photos you forgot)</label>
      {data?.map((j) => (
        <Link key={j.id} to={`/field/jobs/${j.id}`} className={`job-tile ${j.today ? "today" : ""}`}>
          <b>{j.job_no} {j.name}</b>{j.priority === "urgent" && <span className="badge bad">Urgent</span>}
          {["invoiced", "closed", "complete"].includes(j.work_status) && <span className="badge ok">finished</span>}
          <span className="small muted">{[j.customer, j.address].filter(Boolean).join(" · ")}</span>
        </Link>
      ))}
    </div>
  );
}

interface FieldJobDetail extends JobBrief { description: string; order_no: string; contact: string; customer_phone: string; access_notes: string; site_contact: string;
  documents: DocOut[]; notes: { id: number; ref: string; title: string; body: string; created_by: string; created_at: string; kind: string }[];
  materials: { id: number; description: string; by: string; day: string }[]; pos: { po_no: string; supplier: string; status: string; mine: boolean }[];
  forms: { id: number; name: string; kind: string }[]; completed: boolean; signed_by_name: string;
  plans: { id: number; filename: string; pages: number }[]; specs: { id: number; filename: string; title: string; doc_type: string }[] }

type JobTab = "photos" | "plans" | "materials" | "notes";

function FieldJob() {
  const { jobId } = useParams();
  const { data: j, reload } = useLoad<FieldJobDetail>(`/api/field/jobs/${jobId}`);
  const [tab, setTab] = useState<JobTab>(() => (new URLSearchParams(window.location.search).get("tab") as JobTab) || "photos");
  const [panel, setPanel] = useState<"" | "note" | "po" | "form" | "complete">("");
  const [formId, setFormId] = useState<number | null>(null);
  if (!j) return <p className="muted">Loading…</p>;
  const open = async (url: string) => window.open(await fetchBlobUrl(url), "_blank");
  const done = () => { setPanel(""); reload(); };
  const phone = j.customer_phone || (j.contact.match(/[\d ]{8,}/)?.[0] ?? "");
  const photos = j.documents.filter((d) => d.is_image && d.folder === "Photos");
  const otherDocs = j.documents.filter((d) => !(d.is_image && d.folder === "Photos"));
  const nPlans = j.plans.length + j.specs.length + otherDocs.length;
  return (
    <div className="stack">
      <Link to="/field/jobs" className="small">‹ Jobs</Link>
      <h1>{j.job_no} {j.name}</h1>
      <div className="small muted">{j.customer}{j.order_no && <> · Order {j.order_no}</>}{j.completed && <> · <span className="ok">finished</span></>}</div>
      <div className="action-row">
        {j.address && <a className="btn" href={`https://maps.google.com/?q=${encodeURIComponent(j.address)}`} target="_blank" rel="noreferrer">📍 Directions</a>}
        {phone && <a className="btn" href={`tel:${phone.replace(/\s/g, "")}`}>📞 Call</a>}
      </div>
      {j.address && <p style={{ margin: 0 }}>{j.address}</p>}
      {j.description && <section className="card"><h3>The job</h3><p className="pre">{j.description}</p></section>}
      {(j.access_notes || j.site_contact || j.contact) && (
        <section className="card"><h3>Site</h3>{j.access_notes && <p className="pre">{j.access_notes}</p>}
          {(j.site_contact || j.contact) && <p className="small">Contact: {j.site_contact || j.contact}</p>}</section>
      )}
      <div className="job-tabs">
        {([["photos", `📷 Photos${photos.length ? ` (${photos.length})` : ""}`], ["plans", `📐 Plans & specs${nPlans ? ` (${nPlans})` : ""}`],
          ["materials", `🔩 Materials${j.materials.length ? ` (${j.materials.length})` : ""}`], ["notes", "📝 Notes & forms"]] as [JobTab, string][]).map(([k, l]) => (
          <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{l}</button>))}
      </div>
      {tab === "photos" && <JobPhotos jobId={j.id} photos={photos} onAdded={reload} />}
      {tab === "plans" && (
        <section className="stack">
          {nPlans === 0 && <p className="muted">No plans or documents on this job yet.</p>}
          {j.plans.length > 0 && <h2>Plans</h2>}
          {j.plans.map((f) => <button key={`p${f.id}`} className="job-tile" onClick={() => open(`/api/field/jobs/${j.id}/plans/${f.id}`)}>📐 {f.filename}
            <span className="small muted">{f.pages} page{f.pages === 1 ? "" : "s"}</span></button>)}
          {j.specs.length > 0 && <h2>Scope, specs and reports</h2>}
          {j.specs.map((t) => <button key={`s${t.id}`} className="job-tile" onClick={() => open(`/api/field/jobs/${j.id}/specs/${t.id}`)}>📄 {t.title}
            {t.doc_type && <span className="small muted">{t.doc_type.replace(/_/g, " ")}</span>}</button>)}
          {otherDocs.length > 0 && <h2>Other documents</h2>}
          {otherDocs.map((d) => <button key={d.id} className="job-tile" onClick={() => open(`/api/field/documents/${d.id}`)}>{d.is_image ? "🖼" : "📄"} {d.title || d.filename}
            <span className="small muted">{d.folder}</span></button>)}
        </section>
      )}
      {tab === "materials" && <StockMaterials jobId={j.id} used={j.materials} onAdded={reload} />}
      {tab === "notes" && (
        <section className="stack">
          <div className="grid-buttons">
            <button onClick={() => setPanel("note")}>📝 Add a note</button>
            <button onClick={() => setPanel("po")}>🧾 Get a PO number</button>
            <button onClick={() => setPanel("form")}>✅ Forms & SWMS</button>
            {!j.completed && <button className="primary" onClick={() => setPanel("complete")}>🏁 Job finished</button>}
          </div>
          {panel === "note" && <NoteForm jobId={j.id} onDone={done} />}
          {panel === "po" && <PoForm jobId={j.id} onDone={done} />}
          {panel === "form" && (formId ? <FillForm jobId={j.id} templateId={formId} onDone={() => { setFormId(null); done(); }} /> : (
            <div className="card">{j.forms.map((f) => <button key={f.id} className="job-tile" onClick={() => setFormId(f.id)}>{f.name}</button>)}</div>
          ))}
          {panel === "complete" && <CompleteForm jobId={j.id} onDone={done} />}
          {j.completed && <p className="ok">✓ Completed{j.signed_by_name && <> · signed by {j.signed_by_name}</>}</p>}
          {j.pos.length > 0 && <section><h2>Purchase orders</h2>{j.pos.map((p) => <div key={p.po_no} className="note-row"><b>{p.po_no}</b> {p.supplier} <span className="muted small">{p.status}</span></div>)}</section>}
          {j.notes.length > 0 && <section><h2>Notes</h2>{j.notes.map((n) => <div key={n.id} className="note-row col"><b>{n.title}</b>{n.body !== n.title && <span className="pre small">{n.body}</span>}
            <small className="muted">{n.created_by} · {new Date(n.created_at).toLocaleString("en-AU")}</small></div>)}</section>}
        </section>
      )}
    </div>
  );
}

interface Product { code: string; description: string; brand: string; group: string; unit: string; supplier_id?: number | null; cost?: number; sell?: number }

/** Materials used from stock: search the price files, tap, set how many. The office sees the cost and sell price. */
function StockMaterials({ jobId, used, onAdded }: { jobId: number; used: { id: number; description: string; by: string; day: string }[]; onAdded: () => void }) {
  const [q, setQ] = useState("");
  const { data: found } = useLoad<Product[]>(q.trim().length >= 2 ? `/api/field/products?q=${encodeURIComponent(q)}` : null, [q]);
  const [pick, setPick] = useState<Product | null>(null);
  const [qty, setQty] = useState(1);
  const [typed, setTyped] = useState(false);
  const [text, setText] = useState("");
  const [run, error, busy] = useAction();
  const add = (body: Record<string, unknown>) => run(async () => {
    await api.post(`/api/field/jobs/${jobId}/materials`, body);
    setPick(null); setQ(""); setQty(1); setText(""); setTyped(false); onAdded();
  });
  return (
    <section className="stack">
      {!pick && !typed && (
        <>
          <input placeholder="Search stock: e.g. 100 bend, ball valve, PEX 20" value={q} onChange={(e) => setQ(e.target.value)} />
          {found?.map((p) => (
            <button key={p.code + (p.supplier_id ?? "")} className="job-tile" onClick={() => { setPick(p); setQty(1); }}>
              <b>{p.description}</b><span className="small muted">{[p.brand, p.group, p.unit].filter(Boolean).join(" · ")}</span>
            </button>
          ))}
          {q.trim().length >= 2 && found && found.length === 0 && <p className="muted small">Nothing in the price files matches.</p>}
          <button className="link small" onClick={() => setTyped(true)}>Not in the list? Type it in</button>
        </>
      )}
      {pick && (
        <div className="card">
          <b>{pick.description}</b>
          <div className="qty-row">
            <button onClick={() => setQty(Math.max(0.5, qty - 1))}>−</button>
            <input type="number" inputMode="decimal" min={0.01} step="any" value={qty} onChange={(e) => setQty(Number(e.target.value))} />
            <button onClick={() => setQty(qty + 1)}>+</button>
            <span>{pick.unit || "ea"}</span>
          </div>
          <div className="row"><button className="primary" disabled={busy || qty <= 0} onClick={() => add({ code: pick.code, supplier_id: pick.supplier_id ?? null, qty })}>Add to job</button>
            <button className="link" onClick={() => setPick(null)}>Back</button></div>
        </div>
      )}
      {typed && (
        <div className="card">
          <input placeholder="What did you use?" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="qty-row"><button onClick={() => setQty(Math.max(0.5, qty - 1))}>−</button>
            <input type="number" inputMode="decimal" value={qty} onChange={(e) => setQty(Number(e.target.value))} /><button onClick={() => setQty(qty + 1)}>+</button></div>
          <div className="row"><button className="primary" disabled={busy || !text.trim()} onClick={() => add({ description: text, qty })}>Add to job</button>
            <button className="link" onClick={() => setTyped(false)}>Back</button></div>
          <p className="small muted">The office will price it.</p>
        </div>
      )}
      <ErrorLine error={error} />
      {used.length > 0 && <section><h2>Used on this job</h2>{used.map((m) => <div key={m.id} className="note-row">{m.description}<small className="muted">{m.by} · {fmtDay(m.day)}</small></div>)}</section>}
    </section>
  );
}

function NoteForm({ jobId, onDone }: { jobId: number; onDone: () => void }) {
  const [text, setText] = useState("");
  const [kind, setKind] = useState("note");
  const [photos, setPhotos] = useState<number[]>([]);
  const [run, error, busy] = useAction();
  return (
    <form className="card" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.post(`/api/field/jobs/${jobId}/notes`, { text, kind, photo_ids: photos }); onDone(); }); }}>
      <div className="chips">{[["note", "Note"], ["defect", "Problem / defect"]].map(([k, l]) => <button type="button" key={k} className={kind === k ? "chip on" : "chip"} onClick={() => setKind(k)}>{l}</button>)}</div>
      <textarea rows={3} placeholder="What happened, what's needed" value={text} onChange={(e) => setText(e.target.value)} required />
      <div className="photo-row">
        {photos.map((p) => <span key={p} className="badge ok">📷 added</span>)}
        <PhotoButton label="Add photo" jobId={jobId} onDone={(d) => setPhotos([...photos, d.id])} />
      </div>
      <button className="primary" disabled={busy || !text}>Save</button><ErrorLine error={error} />
    </form>
  );
}

function PoForm({ jobId, onDone }: { jobId: number; onDone: () => void }) {
  const { data: sups } = useLoad<{ id: number; name: string }[]>("/api/field/suppliers");
  const [supplier, setSupplier] = useState<number | "">("");
  const [other, setOther] = useState("");
  const [what, setWhat] = useState("");
  const [po, setPo] = useState("");
  const [run, error, busy] = useAction();
  if (po) return <div className="card po-done"><p>Give the counter this PO number:</p><div className="po-no">{po}</div><button onClick={onDone}>Done</button></div>;
  return (
    <form className="card" onSubmit={(e) => { e.preventDefault(); run(async () => {
      const r = await api.post<{ po_no: string }>(`/api/field/jobs/${jobId}/po`, { supplier_id: supplier || null, supplier_name: other,
        lines: what ? [{ description: what, qty: 1, unit_cost: 0 }] : [], notes: what });
      setPo(r.po_no);
    }); }}>
      <label className="field"><span>Supplier</span>
        <select value={supplier} onChange={(e) => setSupplier(e.target.value ? Number(e.target.value) : "")}>
          <option value="">Choose…</option>{sups?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select></label>
      {!supplier && <input placeholder="…or type the supplier" value={other} onChange={(e) => setOther(e.target.value)} />}
      <textarea rows={2} placeholder="What you're picking up (optional)" value={what} onChange={(e) => setWhat(e.target.value)} />
      <button className="primary big-btn" disabled={busy || (!supplier && !other)}>Get PO number</button><ErrorLine error={error} />
    </form>
  );
}

interface FormField { key: string; label: string; type: string; options?: string[]; required?: boolean }

function FillForm({ jobId, templateId, onDone }: { jobId: number; templateId: number; onDone: () => void }) {
  const { data: t } = useLoad<{ name: string; fields: FormField[] }>(`/api/field/forms/${templateId}`);
  const [a, setA] = useState<Record<string, unknown>>({});
  const [run, error, busy] = useAction();
  if (!t) return null;
  return (
    <form className="card" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.post(`/api/field/jobs/${jobId}/forms/${templateId}`, { answers: a }); onDone(); }); }}>
      <h3>{t.name}</h3>
      {t.fields.map((f) => <FormInput key={f.key} f={f} value={a[f.key]} jobId={jobId} onChange={(v) => setA({ ...a, [f.key]: v })} />)}
      <button className="primary big-btn" disabled={busy}>Submit</button><ErrorLine error={error} />
    </form>
  );
}

function FormInput({ f, value, onChange, jobId }: { f: FormField; value: unknown; onChange: (v: unknown) => void; jobId?: number }) {
  if (f.type === "heading") return <h4>{f.label}</h4>;
  return (
    <div className="field">
      <span>{f.label}{f.required && " *"}</span>
      {f.type === "yesno" && <div className="chips">{[[true, "Yes"], [false, "No"]].map(([v, l]) => (
        <button type="button" key={String(v)} className={value === v ? `chip on ${v ? "" : "no"}` : "chip"} onClick={() => onChange(v)}>{l as string}</button>))}</div>}
      {f.type === "check" && <label className="check-line"><input type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} /> Yes</label>}
      {f.type === "text" && <textarea rows={2} value={String(value ?? "")} onChange={(e) => onChange(e.target.value)} />}
      {f.type === "number" && <input type="number" step="any" inputMode="decimal" value={String(value ?? "")} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />}
      {f.type === "choice" && <div className="chips">{(f.options ?? []).map((o) => <button type="button" key={o} className={value === o ? "chip on" : "chip"} onClick={() => onChange(o)}>{o}</button>)}</div>}
      {f.type === "signature" && <SignaturePad onChange={onChange} />}
      {f.type === "photo" && <PhotoButton label="Take photo" jobId={jobId} done={!!value} onDone={(d) => onChange(d.id)} />}
    </div>
  );
}

function CompleteForm({ jobId, onDone }: { jobId: number; onDone: () => void }) {
  const [sig, setSig] = useState("");
  const [name, setName] = useState("");
  const [notes, setNotes] = useState("");
  const [follow, setFollow] = useState("");
  const [run, error, busy] = useAction();
  return (
    <form className="card" onSubmit={(e: FormEvent) => { e.preventDefault(); run(async () => {
      await api.post(`/api/field/jobs/${jobId}/complete`, { signature: sig, signed_by_name: name, notes, follow_up: follow }); onDone(); }); }}>
      <h3>Finish the job</h3>
      <textarea rows={2} placeholder="What was done" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <input placeholder="Follow-up needed? (leave blank if none)" value={follow} onChange={(e) => setFollow(e.target.value)} />
      <p className="small">Customer signature</p>
      <SignaturePad onChange={setSig} />
      <input placeholder="Customer's name" value={name} onChange={(e) => setName(e.target.value)} />
      <button className="primary big-btn" disabled={busy}>Mark finished</button>
      <p className="small muted">The office is told it's ready to invoice.</p><ErrorLine error={error} />
    </form>
  );
}

function ScheduleTab() {
  const { data } = useLoad<{ entries: Sched[] }>("/api/field/schedule");
  const days: Record<string, Sched[]> = {};
  data?.entries.forEach((e) => { (days[e.day] ??= []).push(e); });
  return (
    <div className="stack">
      <h1>My schedule</h1>
      {data && data.entries.length === 0 && <p className="muted">Nothing published for the next two weeks yet.</p>}
      {Object.entries(days).map(([d, es]) => (
        <section key={d}><h3 className={d === todayIso() ? "today-h" : ""}>{fmtDay(d)}{d === todayIso() && " · today"}</h3>
          {es.map((s) => <Link key={s.id} to={s.job_id ? `/field/jobs/${s.job_id}` : "#"} className="job-tile"><b>{s.start}–{s.end}</b> {s.job_no} {s.job || s.kind}
            {s.address && <span className="small muted">{s.address}</span>}{s.notes && <span className="small">{s.notes}</span>}</Link>)}
        </section>
      ))}
    </div>
  );
}

function PrestartTab() {
  const { data } = useLoad<PlantRow[]>("/api/field/plant");
  const mine = (data ?? []).filter((p) => p.mine);
  const rest = (data ?? []).filter((p) => !p.mine);
  const row = (p: PlantRow) => (
    <Link key={p.id} to={`/field/prestart/${p.id}`} className={`job-tile plant ${p.status !== "in_service" ? "out" : ""}`}>
      <b>{p.kind === "vehicle" ? "🚙" : "🚜"} {p.name}</b>{p.rego && <span className="badge">{p.rego}</span>}
      <span className="small">
        {p.status !== "in_service" ? <span className="error">Out of service</span> : p.kind === "vehicle"
          ? <>{p.weekly_done ? "✓ weekly check" : "⚠ weekly check due"} · {p.wash_done ? "✓ washed this month" : "wash due"}</>
          : <>{p.prestart_today ? (p.prestart_passed ? "✓ pre-start done today" : "✗ failed pre-start") : "Pre-start needed before use"}</>}
        {p.open_defects > 0 && <> · {p.open_defects} open defect{p.open_defects > 1 ? "s" : ""}</>}
      </span>
    </Link>
  );
  return (
    <div className="stack">
      <h1>Pre-start</h1>
      {mine.length > 0 && <section><h2>My vehicle</h2>{mine.map(row)}</section>}
      <section><h2>Plant and equipment</h2>{rest.map(row)}{data && rest.length === 0 && <p className="muted small">No plant in the register yet.</p>}</section>
    </div>
  );
}

interface CheckSpec { plant: { id: number; name: string; kind: string; rego: string; hours: number | null; odometer: number | null }; kind: string;
  fields: FormField[]; photos: string[]; reading: "km" | "hours" }

const CHECK_LABELS: Record<string, string> = { prestart: "Daily pre-start", weekly: "Weekly vehicle check", end_day: "End of day photos", wash: "Monthly wash" };
const PHOTO_LABELS: Record<string, string> = { machine: "Photo of the machine", fuel: "Photo of the fuel gauge", front: "Front of the vehicle",
  back: "Back of the vehicle", exterior: "Outside, washed", interior: "Inside, cleaned" };

function PlantCheckFlow() {
  const { plantId } = useParams();
  const initial = new URLSearchParams(window.location.search).get("kind");
  const { data: plant } = useLoad<PlantRow[]>("/api/field/plant");
  const p = plant?.find((x) => x.id === Number(plantId));
  const [kind, setKind] = useState<string>(initial || "");
  const [mode, setMode] = useState<"check" | "defect">("check");
  useEffect(() => { if (!kind && p) setKind(p.kind === "vehicle" ? "weekly" : p.prestart_today ? "end_day" : "prestart"); }, [p, kind]);
  if (!p) return <p className="muted">Loading…</p>;
  const kinds = p.kind === "vehicle" ? ["weekly", "wash", "prestart"] : ["prestart", "end_day"];
  return (
    <div className="stack">
      <Link to="/field/prestart" className="small">‹ Pre-start</Link>
      <h1>{p.name}</h1>
      <div className="chips">
        {kinds.map((k) => <button key={k} className={mode === "check" && kind === k ? "chip on" : "chip"} onClick={() => { setMode("check"); setKind(k); }}>{CHECK_LABELS[k]}</button>)}
        <button className={mode === "defect" ? "chip on no" : "chip"} onClick={() => setMode("defect")}>Report damage / defect</button>
      </div>
      {mode === "check" && kind && <CheckForm plantId={p.id} kind={kind} key={kind} />}
      {mode === "defect" && <DefectForm plantId={p.id} />}
    </div>
  );
}

function CheckForm({ plantId, kind }: { plantId: number; kind: string }) {
  const nav = useNavigate();
  const { data: spec } = useLoad<CheckSpec>(`/api/field/plant/${plantId}/checklist?kind=${kind}`);
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [photos, setPhotos] = useState<Record<string, number>>({});
  const [reading, setReading] = useState("");
  const [fuel, setFuel] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [result, setResult] = useState<{ passed: boolean; failed: string[] } | null>(null);
  const [run, error, busy] = useAction();
  if (!spec) return null;
  if (result) return (
    <div className={`card ${result.passed ? "" : "attention"}`}>
      <h2>{result.passed ? "✓ All good" : "✗ Not safe to use"}</h2>
      {!result.passed && <><p>These failed and have been reported to your supervisor:</p><ul>{result.failed.map((f) => <li key={f}>{f}</li>)}</ul></>}
      <button className="primary big-btn" onClick={() => nav("/field")}>Back to Today</button>
    </div>
  );
  const needsFuel = kind === "prestart" || kind === "end_day";
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); run(async () => {
      const loc = await getLocation();
      const r = await api.post<{ passed: boolean; failed: string[] }>(`/api/field/plant/${plantId}/check`, {
        kind, answers, photo_ids: photos, notes, fuel_pct: fuel, ...loc,
        ...(reading ? (spec.reading === "km" ? { odometer: Number(reading) } : { hours: Number(reading) }) : {}) });
      setResult(r);
    }); }}>
      {spec.fields.map((f) => <FormInput key={f.key} f={f} value={answers[f.key]} onChange={(v) => setAnswers({ ...answers, [f.key]: v })} />)}
      {kind !== "wash" && (
        <label className="field"><span>{spec.reading === "km" ? "Odometer (km)" : "Hour meter"}{spec.reading === "km" ? spec.plant.odometer ? ` · last ${num(spec.plant.odometer, 0)}` : "" : spec.plant.hours ? ` · last ${num(spec.plant.hours)}` : ""}</span>
          <input type="number" inputMode="decimal" value={reading} onChange={(e) => setReading(e.target.value)} /></label>
      )}
      {needsFuel && (
        <div className="field"><span>Fuel level</span>
          <div className="chips">{[0, 25, 50, 75, 100].map((v) => <button type="button" key={v} className={fuel === v ? "chip on" : "chip"} onClick={() => setFuel(v)}>{v === 0 ? "Empty" : v === 100 ? "Full" : `${v}%`}</button>)}</div></div>
      )}
      {spec.photos.length > 0 && (
        <div className="photo-row">
          {spec.photos.map((k) => <PhotoButton key={k} label={PHOTO_LABELS[k] ?? k} done={!!photos[k]} onDone={(d) => setPhotos((p) => ({ ...p, [k]: d.id }))} />)}
        </div>
      )}
      <textarea rows={2} placeholder="Anything else to report" value={notes} onChange={(e) => setNotes(e.target.value)} />
      <button className="primary big-btn" disabled={busy || spec.photos.some((k) => !photos[k])}>
        {spec.photos.some((k) => !photos[k]) ? "Take the photos first" : "Submit"}</button>
      <ErrorLine error={error} />
    </form>
  );
}

function DefectForm({ plantId }: { plantId: number }) {
  const nav = useNavigate();
  const [f, setF] = useState({ kind: "damage", severity: "minor", description: "" });
  const [photos, setPhotos] = useState<number[]>([]);
  const [run, error, busy] = useAction();
  return (
    <form className="stack" onSubmit={(e) => { e.preventDefault(); run(async () => {
      await api.post(`/api/field/plant/${plantId}/defects`, { ...f, photo_ids: photos }); nav("/field/prestart"); }); }}>
      <div className="chips">{[["damage", "Damage"], ["defect", "Fault"], ["incident", "Incident"]].map(([k, l]) => (
        <button type="button" key={k} className={f.kind === k ? "chip on" : "chip"} onClick={() => setF({ ...f, kind: k })}>{l}</button>))}</div>
      <div className="field"><span>How bad?</span><div className="chips">
        {[["minor", "Minor: still OK to use"], ["major", "Major: fix soon"], ["critical", "Critical: stop using it"]].map(([k, l]) => (
          <button type="button" key={k} className={f.severity === k ? `chip on ${k === "critical" ? "no" : ""}` : "chip"} onClick={() => setF({ ...f, severity: k })}>{l}</button>))}</div></div>
      <textarea rows={3} placeholder="What's wrong and where" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} required />
      <div className="photo-row">
        {photos.map((p) => <span key={p} className="badge ok">📷</span>)}
        <PhotoButton label="Add photo" onDone={(d) => setPhotos([...photos, d.id])} />
      </div>
      <button className="primary big-btn" disabled={busy || f.description.length < 3}>Report it</button>
      {f.severity === "critical" && <p className="warn small">It will be marked out of service until it's fixed.</p>}
      <ErrorLine error={error} />
    </form>
  );
}

function TimesheetTab() {
  const [start, setStart] = useState(monday(todayIso()));
  const { data, reload } = useLoad<{ start: string; entries: Entry[]; days: Record<string, number>; total: number; ordinary: number; overtime: number; can_submit: boolean }>(
    `/api/field/timesheet?start=${start}`, [start]);
  const [adding, setAdding] = useState<"" | "time" | "leave">("");
  const [run, error] = useAction();
  const leave = useLoad<{ id: number; kind: string; start_date: string; end_date: string; status: string }[]>("/api/field/time-off");
  const byDay: Record<string, Entry[]> = {};
  data?.entries.forEach((e) => { (byDay[e.local_day] ??= []).push(e); });
  return (
    <div className="stack">
      <h1>My timesheet</h1>
      <div className="row"><button onClick={() => setStart(addDays(start, -7))}>‹</button><b>Week of {fmtDay(start)}</b><button onClick={() => setStart(addDays(start, 7))}>›</button></div>
      {data && <div className="tiles three"><div className="tile"><b>{hrs(data.total)}</b><span>total</span></div><div className="tile"><b>{hrs(data.ordinary)}</b><span>ordinary</span></div>
        <div className="tile"><b>{hrs(data.overtime)}</b><span>overtime</span></div></div>}
      {Object.entries(byDay).map(([d, es]) => (
        <section key={d}><h3>{fmtDay(d)} <span className="muted small">{hrs(data?.days[d])}</span></h3>
          {es.map((e) => <div key={e.id} className="note-row"><span><b>{e.start_local}–{e.end_local ?? "now"}</b> {e.job_no} {e.job || "No job"}{e.task && ` · ${e.task}`}</span>
            <span className="small"><span className={`status-chip s-${e.status}`}>{e.status}</span> {hrs(e.hours)}</span></div>)}
        </section>
      ))}
      {data?.can_submit && <button className="primary big-btn" onClick={() => run(async () => { await api.post("/api/field/timesheet/submit", { start }); reload(); })}>Submit this week</button>}
      <div className="row">
        <button onClick={() => setAdding(adding === "time" ? "" : "time")}>+ Missed a clock-in</button>
        <button onClick={() => setAdding(adding === "leave" ? "" : "leave")}>+ Ask for leave</button>
      </div>
      {adding === "time" && <ManualTime onDone={() => { setAdding(""); reload(); }} />}
      {adding === "leave" && <LeaveForm onDone={() => { setAdding(""); leave.reload(); }} />}
      {leave.data && leave.data.length > 0 && <section><h2>My leave</h2>{leave.data.map((l) => <div key={l.id} className="note-row">{l.kind} {fmtDay(l.start_date)} – {fmtDay(l.end_date)}<span className={`status-chip s-${l.status}`}>{l.status}</span></div>)}</section>}
      <ErrorLine error={error} />
    </div>
  );
}

function ManualTime({ onDone }: { onDone: () => void }) {
  const { data: jobs } = useLoad<JobBrief[]>("/api/field/jobs");
  const [f, setF] = useState({ job_id: "" as number | "", day: todayIso(), start: "07:00", end: "15:30", break_minutes: 30, notes: "" });
  const [run, error, busy] = useAction();
  return (
    <form className="card" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.post("/api/field/timesheet/manual", { ...f, job_id: f.job_id || null }); onDone(); }); }}>
      <select value={f.job_id} onChange={(e) => setF({ ...f, job_id: e.target.value ? Number(e.target.value) : "" })}>
        <option value="">No job</option>{jobs?.map((j) => <option key={j.id} value={j.id}>{j.job_no} {j.name}</option>)}</select>
      <div className="row wrap"><input type="date" value={f.day} max={todayIso()} onChange={(e) => setF({ ...f, day: e.target.value })} />
        <input type="time" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} /> to <input type="time" value={f.end} onChange={(e) => setF({ ...f, end: e.target.value })} />
        <label className="inline small">Break <input type="number" min={0} style={{ width: 60 }} value={f.break_minutes} onChange={(e) => setF({ ...f, break_minutes: Number(e.target.value) })} /> min</label></div>
      <input placeholder="Why it wasn't clocked (needed)" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} required />
      <button className="primary" disabled={busy}>Add time</button><p className="small muted">The office checks hand-added time.</p><ErrorLine error={error} />
    </form>
  );
}

function LeaveForm({ onDone }: { onDone: () => void }) {
  const [f, setF] = useState({ kind: "annual", start_date: todayIso(), end_date: todayIso(), notes: "" });
  const [run, error, busy] = useAction();
  return (
    <form className="card" onSubmit={(e) => { e.preventDefault(); run(async () => { await api.post("/api/field/time-off", f); onDone(); }); }}>
      <div className="chips">{[["annual", "Annual"], ["sick", "Sick"], ["rdo", "RDO"], ["unpaid", "Unpaid"], ["other", "Other"]].map(([k, l]) => (
        <button type="button" key={k} className={f.kind === k ? "chip on" : "chip"} onClick={() => setF({ ...f, kind: k })}>{l}</button>))}</div>
      <div className="row wrap"><input type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} /> to
        <input type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} /></div>
      <input placeholder="Notes" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
      <button className="primary" disabled={busy}>Ask</button><ErrorLine error={error} />
    </form>
  );
}

function CrewTab() {
  const { data: crew, reload } = useLoad<{ id: number; name: string; trade: string; on: boolean; job: string }[]>("/api/field/crew");
  const { data: jobs } = useLoad<JobBrief[]>("/api/field/jobs");
  const [sel, setSel] = useState<number[]>([]);
  const [job, setJob] = useState<number | "">("");
  const [run, error, busy] = useAction();
  const [msg, setMsg] = useState("");
  const go = (out: boolean) => run(async () => {
    const loc = await getLocation();
    const r = await api.post<{ done: string[] }>("/api/field/crew", { user_ids: sel, job_id: job || null, out, ...loc });
    setMsg(`${out ? "Clocked off" : "Clocked on"}: ${r.done.join(", ")}`); setSel([]); reload();
  });
  const toggle = useCallback((id: number) => setSel((s) => s.includes(id) ? s.filter((x) => x !== id) : [...s, id]), []);
  return (
    <div className="stack">
      <h1>My crew</h1>
      {crew?.map((c) => (
        <label key={c.id} className={`job-tile check ${sel.includes(c.id) ? "today" : ""}`}>
          <input type="checkbox" checked={sel.includes(c.id)} onChange={() => toggle(c.id)} />
          <b>{c.name}</b><span className="small muted">{c.trade}{c.on ? ` · on ${c.job || "the clock"}` : " · off"}</span>
        </label>
      ))}
      <select value={job} onChange={(e) => setJob(e.target.value ? Number(e.target.value) : "")}>
        <option value="">Job…</option>{jobs?.map((j) => <option key={j.id} value={j.id}>{j.job_no} {j.name}</option>)}</select>
      <div className="row"><button className="primary" disabled={busy || !sel.length} onClick={() => go(false)}>Clock on</button>
        <button disabled={busy || !sel.length} onClick={() => go(true)}>Clock off</button></div>
      {msg && <p className="ok small">{msg}</p>}<ErrorLine error={error} />
    </div>
  );
}


/** Photos on a job: take them with the camera or pick several from the gallery, clocked in or not. */
function JobPhotos({ jobId, photos, onAdded }: { jobId: number; photos: DocOut[]; onAdded: () => void }) {
  const camera = useRef<HTMLInputElement>(null);
  const gallery = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [thumbs, setThumbs] = useState<Record<number, string>>({});
  const [open, setOpen] = useState<string>("");
  useEffect(() => {
    let live = true;
    photos.filter((p) => !thumbs[p.id]).slice(0, 30).forEach(async (p) => {
      try { const url = await fetchBlobUrl(`/api/field/documents/${p.id}`); if (live) setThumbs((t) => ({ ...t, [p.id]: url })); } catch { /* skip */ }
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [photos.map((p) => p.id).join(",")]);
  const send = async (files: FileList | null) => {
    const list = Array.from(files ?? []).filter((f) => f.type.startsWith("image/"));
    if (!list.length) return;
    setError("");
    let done = 0;
    for (const f of list) {
      setBusy(`Uploading ${done + 1} of ${list.length}…`);
      try {
        const blob = await shrinkImage(f);
        const form = new FormData();
        form.append("file", new File([blob], f.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }));
        form.append("job_id", String(jobId));
        form.append("folder", "Photos");
        await upload("/api/field/upload", form);
        done++;
      } catch (e) { setError(`${f.name}: ${(e as Error).message}`); }
    }
    setBusy("");
    if (camera.current) camera.current.value = "";
    if (gallery.current) gallery.current.value = "";
    if (done) onAdded();
  };
  return (
    <section className="job-photos">
      <div className="row"><h2 style={{ margin: 0 }}>Photos {photos.length > 0 && <span className="muted small">({photos.length})</span>}</h2></div>
      <div className="action-row">
        <button type="button" className="btn primary" disabled={!!busy} onClick={() => camera.current?.click()}>📷 Take photo</button>
        <button type="button" className="btn" disabled={!!busy} onClick={() => gallery.current?.click()}>🖼 Add from gallery</button>
      </div>
      <input ref={camera} type="file" accept="image/*" capture="environment" hidden onChange={(e) => send(e.target.files)} />
      <input ref={gallery} type="file" accept="image/*" multiple hidden onChange={(e) => send(e.target.files)} />
      {busy && <p className="small">{busy}</p>}
      {error && <p className="error small">{error}</p>}
      {photos.length > 0 && (
        <div className="photo-grid">
          {photos.map((p) => (
            <button key={p.id} type="button" onClick={() => thumbs[p.id] && setOpen(thumbs[p.id])} aria-label={p.title || p.filename}>
              {thumbs[p.id] ? <img src={thumbs[p.id]} alt="" /> : <span className="muted small">…</span>}
            </button>
          ))}
        </div>
      )}
      {open && <div className="photo-view" onClick={() => setOpen("")}><img src={open} alt="" /><span>Tap to close</span></div>}
    </section>
  );
}
