import { DragEvent, useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, download, upload } from "../api";
import type { AutopilotStatus, Job, Sheet } from "../types";
import CivilBoqView from "./CivilBoq";
import TenderDocs from "./TenderDocs";
import ChatPanel from "./ChatPanel";

const fmt = (n: number | undefined, dp = 0) => (n ?? 0).toLocaleString("en-AU", { maximumFractionDigits: dp, minimumFractionDigits: dp });

function Progress({ st }: { st: AutopilotStatus }) {
  const pct = st.total ? Math.round(((st.done ?? 0) / st.total) * 100) : null;
  return (
    <div className="card autopilot-progress">
      <div className="spinner" />
      <div style={{ flex: 1 }}>
        <h2>Reading the plans…</h2>
        <p>{st.step}</p>
        <div className="bar"><div className={pct === null ? "indeterminate" : ""} style={{ width: pct === null ? "30%" : `${pct}%` }} /></div>
        <p className="muted small">You can leave this page; it keeps going in the background.</p>
      </div>
    </div>
  );
}

function NeedsYou({ items }: { items: AutopilotStatus["attention"] }) {
  if (!items?.length) return null;
  return (
    <section className="card needs-you">
      <h2>Needs you ({items.length})</h2>
      <ul>
        {items.map((a, i) => (
          <li key={i}>
            {a.sheet_id ? <Link to={`/sheets/${a.sheet_id}`}><b>{a.sheet}</b></Link> : null}
            {a.sheet_id ? ": " : ""}{a.message}
          </li>
        ))}
      </ul>
    </section>
  );
}

function AddPlans({ jobId, disabled, onDone }: { jobId: number; disabled: boolean; onDone: () => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");
  const send = async (list: FileList | null) => {
    const files = Array.from(list ?? []).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (!files.length) return;
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    setError("");
    setBusy(0);
    try { await upload(`/api/jobs/${jobId}/add-plans`, form, setBusy); onDone(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  };
  const drop = (e: DragEvent) => { e.preventDefault(); if (!disabled) send(e.dataTransfer.files); };
  return (
    <div className="add-plans" onDragOver={(e) => e.preventDefault()} onDrop={drop}>
      <button disabled={disabled || busy !== null} onClick={() => input.current?.click()}>
        {busy !== null ? `Uploading ${Math.round(busy * 100)}%` : "+ Add plans or a new revision"}
      </button>
      <input ref={input} type="file" accept=".pdf,application/pdf" multiple hidden onChange={(e) => send(e.target.files)} />
      {error && <span className="error small"> {error}</span>}
    </div>
  );
}

export default function JobOverview() {
  const jobId = Number(useParams().jobId);
  const [job, setJob] = useState<Job | null>(null);
  const [st, setSt] = useState<AutopilotStatus | null>(null);
  const [sheets, setSheets] = useState<Sheet[]>([]);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [changes, setChanges] = useState(0); // bumps when tender requirements change what's shown
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const alive = useRef(true);

  const load = useCallback(async () => {
    const [j, s] = await Promise.all([api.get<Job>(`/api/jobs/${jobId}`), api.get<AutopilotStatus>(`/api/jobs/${jobId}/autopilot`)]);
    setJob(j);
    setSt(s);
    if (!s.running) setSheets(await api.get<Sheet[]>(`/api/jobs/${jobId}/sheets`));
    return s;
  }, [jobId]);

  /** Refresh now, and every 2 s while the autopilot is working. */
  const poll = useCallback(() => {
    clearTimeout(timer.current);
    const tick = async () => {
      try {
        const s = await load();
        if (alive.current && (s.running || s.state === "queued" || s.state === "running")) timer.current = setTimeout(tick, 2000);
      } catch (e) { setError((e as Error).message); }
    };
    tick();
  }, [load]);

  useEffect(() => {
    alive.current = true;
    poll();
    return () => { alive.current = false; clearTimeout(timer.current); };
  }, [poll]);

  const rerun = async (reread: boolean) => {
    setError(""); setMsg("");
    try { await api.post(`/api/jobs/${jobId}/autopilot`, { reread }); poll(); }
    catch (e) { setError((e as Error).message); }
  };

  const approveAll = async () => {
    const s = st?.summary ?? {};
    const n = (s.runs_suggested ?? 0) + (s.counts_suggested ?? 0);
    if (!window.confirm(`Approve all ${n} suggested pipe runs and counts? They'll go into the totals and the estimate. You can still change or delete any of them afterwards.`)) return;
    setBusy(true); setError("");
    try {
      const r = await api.post<{ runs: number; counts: number; estimate_lines: number; flags: number }>(`/api/jobs/${jobId}/approve-all`);
      setMsg(`Approved ${r.runs} runs and ${r.counts} counts. The estimate has ${r.estimate_lines} fitting lines${r.flags ? ` and ${r.flags} check-measure flag(s) to look at` : ""}.`);
      await load();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  if (!job || !st) return <main className="page">{error ? <p className="error">{error}</p> : "Loading…"}</main>;
  const running = st.running || st.state === "queued" || st.state === "running";
  const s = st.summary ?? {};
  const civil = job.kind === "civil";
  const plans = sheets.filter((x) => x.is_current && x.is_hydraulic && x.classification === "plan");
  const waiting = (s.runs_suggested ?? 0) + (s.counts_suggested ?? 0);

  return (
    <div className="with-chat">
    <main className="page overview">
      <div className="row wrap">
        <Link to="/">← All jobs</Link>
        <span className="spacer" />
        {!civil && <Link to={`/jobs/${jobId}/details`}>Detailed view (sheets, estimate, pricing) →</Link>}
      </div>
      <div className="row wrap title-row">
        <h1>{job.name}</h1>
        <span className={`badge ${civil ? "civil" : "hyd"}`}>{civil ? "Civil BOQ" : "Hydraulic take-off"}</span>
        {job.status === "final" && <span className="badge final">Final</span>}
      </div>
      {job.client && <p className="muted">{job.client}</p>}

      {running && <Progress st={st} />}
      {st.state === "failed" && <div className="card bad-card"><b>The read stopped with an error:</b> {st.error} <button onClick={() => rerun(false)}>Try again</button></div>}
      {st.state === "interrupted" && <div className="card warn-card">The read was interrupted by a server restart. <button onClick={() => rerun(false)}>Carry on</button></div>}
      {st.state === "never" && !civil && (
        <div className="card">This job was set up by hand. <button onClick={() => rerun(false)}>Read the plans automatically</button></div>
      )}
      {error && <p className="error big">{error}</p>}
      {msg && <p className="ok big">{msg}</p>}

      {!running && !civil && (
        <>
          <div className="tiles">
            <div className="tile"><b>{fmt(s.sheets)}</b><span>sheets read</span></div>
            <div className="tile"><b>{fmt(s.scales_confirmed)} / {fmt(plans.length)}</b><span>plan scales confirmed</span></div>
            <div className="tile"><b>{fmt(s.metres, 1)} m</b><span>of pipe found</span></div>
            <div className="tile"><b>{fmt((s.counts_suggested ?? 0) + (s.counts_confirmed ?? 0))}</b><span>items counted</span></div>
            <div className={`tile ${waiting ? "warn" : "ok"}`}><b>{fmt(waiting)}</b><span>waiting for your OK</span></div>
          </div>

          <NeedsYou items={st.attention} />
          <TenderDocs jobId={jobId} civil={false} final={job.status === "final"} running={running} version={changes}
                      onChanged={() => { setChanges((c) => c + 1); poll(); }} />

          <section className="card actions">
            <h2>Next steps</h2>
            <div className="big-actions">
              {plans[0] && <Link className="button big" to={`/sheets/${plans[0].id}`}>1. Check it on the drawings</Link>}
              <button className="big primary" disabled={busy || !waiting || job.status === "final"} onClick={approveAll}>
                2. Approve everything ({fmt(waiting)})
              </button>
              <button className="big" onClick={() => download(`/api/jobs/${jobId}/export.xlsx`, "BOQ.xlsx")}>3. Download Excel BOQ</button>
              <button className="big" onClick={() => download(`/api/jobs/${jobId}/simpro.csv`, "simpro.csv").catch((e) => setError(e.message))}>Simpro CSV</button>
            </div>
            <p className="muted small">
              Nothing the AI found counts until you approve it. Suggested runs show dashed on the drawings; you can fix or delete any of them first.
            </p>
          </section>

          <section className="card">
            <h2>Plans</h2>
            <table>
              <thead><tr><th>Sheet</th><th>Title</th><th>Rev</th><th>Scale</th><th></th></tr></thead>
              <tbody>
                {plans.map((p) => (
                  <tr key={p.id}>
                    <td>{p.sheet_no || `p${p.page_no}`}</td>
                    <td>{p.title}</td>
                    <td>{p.revision}</td>
                    <td>{p.scale_verified ? <span className="ok">✓ {p.stated_scale || "checked"}</span> : <span className="warn">Needs checking</span>}</td>
                    <td><Link to={`/sheets/${p.id}`}>Open</Link></td>
                  </tr>
                ))}
                {plans.length === 0 && <tr><td colSpan={5} className="muted">No hydraulic plans found. <Link to={`/jobs/${jobId}/details`}>See all sheets</Link></td></tr>}
              </tbody>
            </table>
            <p className="small muted">{sheets.filter((x) => !x.is_hydraulic || x.classification !== "plan").length} other sheets (sections, details, other trades) are in the <Link to={`/jobs/${jobId}/details`}>detailed view</Link>.</p>
          </section>
        </>
      )}

      {!running && civil && (
        <>
          <NeedsYou items={st.attention} />
          <TenderDocs jobId={jobId} civil final={job.status === "final"} running={running} version={changes}
                      onChanged={() => { setChanges((c) => c + 1); poll(); }} />
          <CivilBoqView key={changes} jobId={jobId} final={job.status === "final"} sheets={sheets} />
        </>
      )}

      {!running && (
        <div className="row wrap footer-actions">
          <AddPlans jobId={jobId} disabled={job.status === "final"} onDone={poll} />
          <button onClick={() => rerun(false)} disabled={job.status === "final"}>Run the autopilot again</button>
          <button onClick={() => { if (window.confirm("Read every sheet again with the AI? Approved work is kept.")) rerun(true); }}
                  disabled={job.status === "final"}>Re-read every sheet</button>
        </div>
      )}
    </main>
    <ChatPanel jobId={jobId} kind={civil ? "civil" : "hydraulic"} onChanged={() => { setChanges((c) => c + 1); poll(); }} />
    </div>
  );
}
