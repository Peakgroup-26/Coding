/* Safety on the phone: what each of today's jobs still needs (sign the SWMS, the site pre-start, the day's ITP checks),
   hazard and incident reports with photos, toolbox talks, and the actions given to me. */
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { useApp } from "../App";
import { ErrorLine, Field, fmtDate, PhotoButton, SignaturePad, useAction, useLoad } from "../ui";
import type { ItpState, JobItp, JobSwms, Prestart, Question } from "./Safety";
import { PdfShare } from "./Share";

interface DueItem { itp_id: number; itp: string; key: string; activity: string; point: string | null; daily: boolean; failed?: boolean }
export interface Prompt { job_id: number; job_no: string; job: string; swms_to_sign: { id: number; title: string }[];
  prestart: { done: boolean; id: number | null; signed: boolean }; itp_due: DueItem[]; count: number }
interface MyAction { id: number; description: string; due: string | null; overdue: boolean }
interface Today { jobs: Prompt[]; actions: MyAction[] }
interface JobSafety { job: { id: number; job_no: string; name: string; address: string }; swms: JobSwms[]; prestart: Prestart | null; prestart_questions: Question[];
  itps: JobItp[]; prompts: Prompt }

const summary = (p: Prompt) => [p.swms_to_sign.length && `sign ${p.swms_to_sign.length} SWMS`, !p.prestart.signed && (p.prestart.done ? "sign the site pre-start" : "site pre-start"),
  p.itp_due.length && `${p.itp_due.length} ITP check${p.itp_due.length > 1 ? "s" : ""}`].filter(Boolean).join(", ");

/** On the Today screen: one line per job that still needs something. */
export function SafetyPrompts() {
  const { data } = useLoad<Today>("/api/field/safety/today");
  if (!data) return null;
  const jobs = data.jobs.filter((j) => j.count > 0);
  return (
    <>
      {jobs.map((j) => (
        <Link key={j.job_id} to={`/field/safety/jobs/${j.job_id}`} className={`todo ${!j.prestart.signed || j.swms_to_sign.length ? "blocking" : ""}`}>
          🦺 {j.job_no || j.job}: {summary(j)}<span>Do it ›</span></Link>
      ))}
      {data.actions.length > 0 && <Link to="/field/safety" className="todo">✅ {data.actions.length} safety action{data.actions.length > 1 ? "s" : ""} for you<span>›</span></Link>}
    </>
  );
}

export function SafetyTab() {
  const { data, reload } = useLoad<Today>("/api/field/safety/today");
  const [run, error, busy] = useAction();
  const [doneNote, setDoneNote] = useState<Record<number, string>>({});
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <div className="stack">
      <h1>Safety</h1>
      <div className="grid-buttons">
        <Link className="btn danger-soft" to="/field/safety/report">⚠️ Report a hazard or incident</Link>
        <Link className="btn" to="/field/safety/toolbox">🗣 Toolbox talk</Link>
      </div>
      <section>
        <h2>Today's jobs</h2>
        {data.jobs.length === 0 && <p className="muted small">You're not on a job today. Clock in or check your schedule; the job's SWMS, pre-start and ITPs show up here.</p>}
        {data.jobs.map((j) => (
          <Link key={j.job_id} to={`/field/safety/jobs/${j.job_id}`} className="job-tile">
            <b>{j.job_no} {j.job}</b>
            <span className={`small ${j.count ? "warn" : "ok"}`}>{j.count ? `To do: ${summary(j)}` : "✓ All done for today"}</span>
          </Link>
        ))}
      </section>
      {data.actions.length > 0 && (
        <section>
          <h2>Actions for me</h2>
          {data.actions.map((a) => (
            <div key={a.id} className="card">
              <p style={{ margin: 0 }}>{a.overdue ? "🔴 " : ""}{a.description}</p>
              {a.due && <small className={a.overdue ? "bad" : "muted"}>Due {fmtDate(a.due)}</small>}
              <div className="row"><input placeholder="What did you do?" value={doneNote[a.id] ?? ""} onChange={(e) => setDoneNote({ ...doneNote, [a.id]: e.target.value })} style={{ flex: 1 }} />
                <button disabled={busy} onClick={() => run(async () => { await api.post(`/api/field/safety/actions/${a.id}/done`, { note: doneNote[a.id] ?? "" }); reload(); })}>Done</button></div>
            </div>
          ))}
          <ErrorLine error={error} />
        </section>
      )}
    </div>
  );
}

export function FieldJobSafety() {
  const { jobId } = useParams();
  const { data, reload } = useLoad<JobSafety>(`/api/field/safety/jobs/${jobId}`);
  const [open, setOpen] = useState<"" | "prestart" | number>("");
  if (!data) return <p className="muted">Loading…</p>;
  const p = data.prompts;
  const due = new Set(p.itp_due.map((d) => `${d.itp_id}:${d.key}`));
  return (
    <div className="stack">
      <Link to="/field/safety" className="small">‹ Safety</Link>
      <h1>{data.job.job_no} {data.job.name}</h1>
      {data.job.address && <p className="small muted" style={{ margin: 0 }}>{data.job.address}</p>}

      <section className="card">
        <div className="row"><b className="grow card-title">{p.prestart.signed ? "✅" : "⬜"} Site pre-start</b>
          {data.prestart && <PdfShare kind="prestart" id={data.prestart.id} title={`Site pre-start ${data.job.job_no}`} small />}</div>
        {data.prestart && <p className="small muted">Done by {data.prestart.led_by} · signed on: {data.prestart.attendees.map((a) => a.name).join(", ")}</p>}
        {!p.prestart.signed && (open === "prestart"
          ? <PrestartForm jobId={data.job.id} existing={data.prestart} questions={data.prestart_questions} onDone={() => { setOpen(""); reload(); }} />
          : <button className="primary" onClick={() => setOpen("prestart")}>{data.prestart ? "Read it and sign on" : "Do today's site pre-start"}</button>)}
      </section>

      <section>
        <h2>SWMS</h2>
        {data.swms.length === 0 && <p className="muted small">No SWMS on this job. Ask your supervisor if the work needs one.</p>}
        {data.swms.map((s) => (
          <div key={s.id} className="card">
            <div className="row"><b className="grow card-title">{s.i_signed ? "✅" : "⬜"} {s.title}</b><PdfShare kind="swms" id={s.id} title={`SWMS – ${s.title}`} small /></div>
            {open === s.id ? <SwmsSign s={s} onDone={() => { setOpen(""); reload(); }} />
              : <button className={s.i_signed ? "" : "primary"} onClick={() => setOpen(s.id)}>{s.i_signed ? "Read it again" : "Read and sign on"}</button>}
          </div>
        ))}
      </section>

      <section>
        <h2>ITPs</h2>
        {data.itps.length === 0 && <p className="muted small">No inspection and test plans on this job.</p>}
        {data.itps.map((x) => {
          const n = x.items.filter((i) => due.has(`${x.id}:${i.key}`)).length;
          return (
            <Link key={x.id} to={`/field/safety/itp/${x.id}`} className="job-tile">
              <b>{x.name}{x.area && ` – ${x.area}`}</b>
              <span className="small">{x.done}/{x.total} done{n > 0 && <span className="warn"> · {n} to check today</span>}{x.failed > 0 && <span className="bad"> · {x.failed} failed</span>}</span>
            </Link>
          );
        })}
      </section>
      <Link className="btn danger-soft" to={`/field/safety/report?job=${data.job.id}`}>⚠️ Report a hazard or incident on this job</Link>
    </div>
  );
}

function SwmsSign({ s, onDone }: { s: JobSwms; onDone: () => void }) {
  const { user } = useApp();
  const [name, setName] = useState(user.name || "");
  const [sig, setSig] = useState("");
  const [read, setRead] = useState(false);
  const [run, error, busy] = useAction();
  return (
    <div className="stack swms-read">
      <p className="small"><b>High risk work:</b> {s.high_risk.join(", ") || "None"}<br /><b>PPE:</b> {s.ppe.join(", ")}</p>
      {s.site_notes && <p className="small pre"><b>On this site:</b> {s.site_notes}</p>}
      {s.steps.map((st, i) => (
        <div key={i} className="swms-step">
          <b>{i + 1}. {st.step}</b>
          <div className="small"><span className="muted">Hazards:</span> {st.hazards} <span className={`risk r-${st.risk_before}`}>{st.risk_before}</span></div>
          <div className="small"><span className="muted">Controls:</span> {st.controls} <span className={`risk r-${st.risk_after}`}>{st.risk_after}</span></div>
        </div>
      ))}
      {s.i_signed ? <p className="ok small">You've signed on to version {s.version}.</p> : <>
        <label className="check"><input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} /> I've read and understood this SWMS and I'll follow it</label>
        <Field label="Your name"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Sign here"><SignaturePad onChange={setSig} /></Field>
        <ErrorLine error={error} />
        <button className="primary big-btn" disabled={busy || !read || name.trim().length < 2 || !sig}
          onClick={() => run(async () => { await api.post(`/api/field/safety/swms/${s.id}/sign`, { typed_name: name, signature: sig }); onDone(); })}>Sign on</button>
      </>}
    </div>
  );
}

function PrestartForm({ jobId, existing, questions, onDone }: { jobId: number; existing: Prestart | null; questions: Question[]; onDone: () => void }) {
  const [a, setA] = useState<Record<string, unknown>>(existing?.answers ?? {});
  const [sig, setSig] = useState("");
  const [run, error, busy] = useAction();
  const missing = !existing && questions.some((q) => q.type === "yesno" && a[q.key] === undefined);
  return (
    <div className="stack">
      {questions.map((q) => (
        <div key={q.key} className="q">
          <div className="q-label">{q.label}</div>
          {existing ? <div className="small"><b>{a[q.key] === true ? "Yes" : a[q.key] === false ? "No" : Array.isArray(a[q.key]) ? (a[q.key] as string[]).join(", ") : String(a[q.key] ?? "–")}</b></div>
            : q.type === "yesno" ? (
              <div className="seg">{[true, false].map((v) => <button key={String(v)} type="button" className={a[q.key] === v ? "on" : ""} onClick={() => setA({ ...a, [q.key]: v })}>{v ? "Yes" : "No"}</button>)}</div>
            ) : q.type === "multi" ? (
              <div className="chips">{q.options!.map((o) => {
                const cur = (a[q.key] as string[] | undefined) ?? [];
                const on = cur.includes(o);
                return <button key={o} type="button" className={`chip ${on ? "on" : ""}`} onClick={() => setA({ ...a, [q.key]: on ? cur.filter((x) => x !== o) : [...cur, o] })}>{o}</button>;
              })}</div>
            ) : <textarea rows={2} value={String(a[q.key] ?? "")} onChange={(e) => setA({ ...a, [q.key]: e.target.value })} />}
        </div>
      ))}
      <Field label="Sign on"><SignaturePad onChange={setSig} /></Field>
      <ErrorLine error={error} />
      <button className="primary big-btn" disabled={busy || !sig || missing}
        onClick={() => run(async () => { await api.post("/api/field/safety/prestart", { job_id: jobId, answers: existing ? {} : a, signature: sig }); onDone(); })}>
        {existing ? "Sign on" : "Save and sign on"}</button>
      {missing && <small className="muted">Answer every Yes / No question.</small>}
    </div>
  );
}

export function FieldItp() {
  const { itpId } = useParams();
  const { data, reload } = useLoad<JobItp>(`/api/field/safety/itps/${itpId}`);
  const [open, setOpen] = useState<string | null>(null);
  if (!data) return <p className="muted">Loading…</p>;
  const stages = [...new Set(data.items.map((i) => i.stage))];
  return (
    <div className="stack">
      <Link to={`/field/safety/jobs/${data.job_id}`} className="small">‹ Job safety</Link>
      <h1>{data.name}{data.area && ` – ${data.area}`}</h1>
      <div className="progress"><span style={{ width: `${data.total ? (data.done / data.total) * 100 : 0}%` }} /></div>
      <div className="row"><small className="muted" style={{ flex: 1 }}>{data.done} of {data.total} done</small><PdfShare kind="itp" id={data.id} title={`ITP – ${data.name}`} small /></div>
      {stages.map((st) => (
        <section key={st}>
          <h2>{st}</h2>
          {data.items.filter((i) => i.stage === st).map((i) => (
            <div key={i.key} className={`itp-item ${i.done ? "done" : i.failed ? "failed" : ""}`}>
              <button className="itp-head" onClick={() => setOpen(open === i.key ? null : i.key)}>
                <span className="tick">{i.done ? "✅" : i.failed ? "❌" : "⬜"}</span>
                <span className="grow"><b>{i.activity}</b>
                  <small className="block muted">{i.frequency === "daily" ? "Every day · " : ""}{i.check}</small>
                  {i.point_label && <span className={`badge ${i.point === "hold" ? "bad" : ""}`}>{i.point_label}{i.who && `: ${i.who}`}</span>}
                  {i.last && <small className="block">{i.last.result.toUpperCase()} {fmtDate(i.last.day)}{i.last.reading && ` · ${i.last.reading}`}{i.last.signed_name && ` · ✍️ ${i.last.signed_name}`}</small>}
                </span>
              </button>
              {open === i.key && <ItpCheckForm itp={data} item={i} onDone={() => { setOpen(null); reload(); }} />}
            </div>
          ))}
        </section>
      ))}
    </div>
  );
}

function ItpCheckForm({ itp, item, onDone }: { itp: JobItp; item: ItpState; onDone: () => void }) {
  const [result, setResult] = useState<"pass" | "fail" | "na" | "">("");
  const [reading, setReading] = useState("");
  const [notes, setNotes] = useState("");
  const [photos, setPhotos] = useState<number[]>([]);
  const [signer, setSigner] = useState({ name: "", role: item.who });
  const [sig, setSig] = useState("");
  const [run, error, busy] = useAction();
  const needsSign = result === "pass" && (item.point === "hold" || item.point === "witness");
  const save = () => run(async () => {
    await api.post(`/api/field/safety/itps/${itp.id}/check`, { item_key: item.key, result, reading, notes, photos,
      signed_name: needsSign || sig ? signer.name : "", signed_role: needsSign || sig ? signer.role : "", signature: sig });
    onDone();
  });
  return (
    <div className="stack itp-form">
      {item.criteria && <p className="small"><b>Pass if:</b> {item.criteria}</p>}
      <div className="seg">
        <button className={result === "pass" ? "on ok-on" : ""} onClick={() => setResult("pass")}>Pass</button>
        <button className={result === "fail" ? "on bad-on" : ""} onClick={() => setResult("fail")}>Fail</button>
        <button className={result === "na" ? "on" : ""} onClick={() => setResult("na")}>N/A</button>
      </div>
      {(item.record === "reading" || reading) && <Field label="Reading / test result"><input value={reading} onChange={(e) => setReading(e.target.value)} placeholder="e.g. 1.5 m head 15 min, no drop" /></Field>}
      <Field label="Notes"><textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} /></Field>
      <div className="photo-row">
        {[...photos, 0].map((p, n) => <PhotoButton key={n} label={p ? "Photo added" : item.record === "photo" ? "Take a photo" : "Add a photo"} done={!!p} jobId={itp.job_id} folder="ITP"
          onDone={(d) => setPhotos((ps) => [...ps, d.id])} />)}
      </div>
      {(needsSign || item.record === "signature") && result !== "fail" && <>
        <p className="small warn">{item.point_label || "Sign-off"}: {item.who || "the inspector"} signs here.</p>
        <div className="grid2">
          <Field label="Name"><input value={signer.name} onChange={(e) => setSigner({ ...signer, name: e.target.value })} /></Field>
          <Field label="Role"><input value={signer.role} onChange={(e) => setSigner({ ...signer, role: e.target.value })} /></Field>
        </div>
        <SignaturePad onChange={setSig} />
      </>}
      <ErrorLine error={error} />
      <button className="primary" disabled={busy || !result || (needsSign && (!sig || !signer.name.trim()))} onClick={save}>Save</button>
    </div>
  );
}

/** Hazards, near misses, incidents and injuries, with photos. Used on the phone and in the office. */
export function ReportForm({ jobId, onDone }: { jobId?: number; onDone?: () => void }) {
  const today = useLoad<Today>("/api/field/safety/today");
  const [f, setF] = useState({ kind: "hazard", title: "", description: "", immediate_action: "", severity: "medium", treatment: "none", people: "", location: "",
    job_id: jobId ? String(jobId) : "" });
  const [photos, setPhotos] = useState<number[]>([]);
  const [sent, setSent] = useState(false);
  const [run, error, busy] = useAction();
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const hurt = f.kind === "injury" || f.kind === "incident";
  const send = () => run(async () => {
    await api.post("/api/field/safety/report", { ...f, job_id: f.job_id ? Number(f.job_id) : null, photos });
    setSent(true);
  });
  if (sent) return (
    <div className="stack"><p className="ok">Thanks, it's been sent to the office{f.job_id ? " and the job supervisor" : ""}.</p>
      <button onClick={() => (onDone ? onDone() : setSent(false))}>Done</button></div>
  );
  const kinds: [string, string][] = [["hazard", "⚠️ Hazard"], ["near_miss", "😬 Near miss"], ["incident", "💥 Incident"], ["injury", "🩹 Injury"], ["property", "🏚 Damage"], ["environment", "🌿 Spill / environment"]];
  return (
    <div className="stack">
      <div className="chips">{kinds.map(([k, l]) => <button key={k} type="button" className={`chip ${f.kind === k ? "on" : ""}`} onClick={() => setF({ ...f, kind: k })}>{l}</button>)}</div>
      <Field label="What is it? (short)"><input value={f.title} onChange={set("title")} placeholder="e.g. Trench edge collapsing near the footpath" /></Field>
      <Field label="Job"><select value={f.job_id} onChange={set("job_id")}><option value="">Not on a job / yard</option>
        {(today.data?.jobs ?? []).map((j) => <option key={j.job_id} value={j.job_id}>{j.job_no} {j.job}</option>)}
        {jobId && !today.data?.jobs.some((j) => j.job_id === jobId) && <option value={jobId}>This job</option>}</select></Field>
      <Field label="Where exactly"><input value={f.location} onChange={set("location")} /></Field>
      <Field label="What happened / what's the risk"><textarea rows={3} value={f.description} onChange={set("description")} /></Field>
      <Field label="What did you do straight away"><textarea rows={2} value={f.immediate_action} onChange={set("immediate_action")} /></Field>
      <div className="grid2">
        <Field label="How serious"><select value={f.severity} onChange={set("severity")}><option value="low">Low</option><option value="medium">Medium</option>
          <option value="high">High</option><option value="critical">Critical</option></select></Field>
        {hurt && <Field label="Treatment"><select value={f.treatment} onChange={set("treatment")}><option value="none">None</option><option value="first_aid">First aid</option>
          <option value="medical">Medical treatment</option><option value="lost_time">Lost time</option></select></Field>}
      </div>
      {hurt && <Field label="People involved"><input value={f.people} onChange={set("people")} /></Field>}
      <div className="photo-row">
        {[...photos, 0].map((p, n) => <PhotoButton key={n} label={p ? "Photo added" : "Add a photo"} done={!!p} jobId={f.job_id ? Number(f.job_id) : null} folder="Safety"
          onDone={(d) => setPhotos((ps) => [...ps, d.id])} />)}
      </div>
      <ErrorLine error={error} />
      <button className="primary big-btn" onClick={send} disabled={busy || f.title.trim().length < 2}>Send report</button>
      {(f.severity === "critical" || f.treatment === "lost_time" || f.treatment === "medical") && <p className="small bad">Serious injury or dangerous incident? Call 000 first, then your supervisor. Don't disturb the scene.</p>}
    </div>
  );
}

export function FieldReport() {
  const nav = useNavigate();
  const job = Number(new URLSearchParams(window.location.search).get("job")) || undefined;
  return (
    <div className="stack">
      <Link to="/field/safety" className="small">‹ Safety</Link>
      <h1>Report a hazard or incident</h1>
      <ReportForm jobId={job} onDone={() => nav(job ? `/field/safety/jobs/${job}` : "/field/safety")} />
    </div>
  );
}

interface Talk { id: number; job_id: number | null; job: string; topic: string; notes: string; day: string; presenter: string; attendees: { user_id: number; name: string }[] }
export function FieldToolbox() {
  const { user } = useApp();
  const { data, reload } = useLoad<Talk[]>("/api/field/safety/toolbox/recent");
  const today = useLoad<Today>("/api/field/safety/today");
  const [f, setF] = useState({ topic: "", notes: "", job_id: "" });
  const [sig, setSig] = useState("");
  const [signing, setSigning] = useState<number | null>(null);
  const [run, error, busy] = useAction();
  return (
    <div className="stack">
      <Link to="/field/safety" className="small">‹ Safety</Link>
      <h1>Toolbox talks</h1>
      {(data ?? []).map((t) => {
        const mine = t.attendees.some((a) => a.user_id === user.id);
        return (
          <div key={t.id} className="card">
            <div className="row"><b className="grow card-title">{t.topic}</b><PdfShare kind="toolbox" id={t.id} title={`Toolbox talk – ${t.topic}`} small /></div>
            <small className="muted">{t.presenter}{t.job && ` · ${t.job}`}</small>
            {t.notes && <p className="small pre">{t.notes}</p>}
            <p className="small">Signed: {t.attendees.map((a) => a.name).join(", ")}</p>
            {!mine && (signing === t.id ? <>
              <SignaturePad onChange={setSig} />
              <button className="primary" disabled={busy || !sig} onClick={() => run(async () => {
                await api.post(`/api/field/safety/toolbox/${t.id}/sign`, { typed_name: user.name || user.email, signature: sig }); setSigning(null); setSig(""); reload();
              })}>Sign</button></> : <button onClick={() => { setSig(""); setSigning(t.id); }}>I was there: sign</button>)}
          </div>
        );
      })}
      <section className="card">
        <h3>Run a toolbox talk</h3>
        <Field label="Topic"><input value={f.topic} onChange={(e) => setF({ ...f, topic: e.target.value })} placeholder="e.g. Working near live gas mains" /></Field>
        <Field label="Job"><select value={f.job_id} onChange={(e) => setF({ ...f, job_id: e.target.value })}><option value="">Yard / all jobs</option>
          {(today.data?.jobs ?? []).map((j) => <option key={j.job_id} value={j.job_id}>{j.job_no} {j.job}</option>)}</select></Field>
        <Field label="What you covered"><textarea rows={3} value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        {signing === null && <Field label="Your signature"><SignaturePad onChange={setSig} /></Field>}
        <ErrorLine error={error} />
        <button className="primary" disabled={busy || f.topic.trim().length < 2 || signing !== null} onClick={() => run(async () => {
          await api.post("/api/field/safety/toolbox", { ...f, job_id: f.job_id ? Number(f.job_id) : null, signature: sig });
          setF({ topic: "", notes: "", job_id: "" }); setSig(""); reload();
        })}>Start it: the crew sign on their own phones</button>
      </section>
    </div>
  );
}
