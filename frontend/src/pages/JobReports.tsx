import { Fragment, useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, download } from "../api";
import type { Job } from "../types";
import { Gantt, MonthBars, StackedWeeks } from "./Charts";

interface MatRow { group: string; stage: string; service_code?: string; code?: string; description: string; qty: number; uom: string; order_qty: number; order_uom: string; note?: string }
interface LabRow { stage: string; service_code: string; kind: string; description: string; qty: number; uom: string; hours_per_unit: number | null; hours: number; source: string }
interface Labour { rows: LabRow[]; by_stage: { stage: string; hours: number }[]; by_service: { service_code: string; hours: number }[]; total_hours: number; missing: number }
interface Stage { stage: string; hours: number; plumbers: number; apprentices: number; supervisors: number; workdays: number; start: string; end: string; start_overridden: boolean }
interface Program {
  mode: string; target_weeks: number | null; start_date: string; finish_date: string; calendar_weeks: number; working_days: number;
  working_weeks: number; stages: Stage[]; weekly: { week: string; plumbers: number; apprentices: number; supervisors: number; hours: number; stages: string[] }[];
  field_hours: number; supervision_hours: number; pm_hours: number; pm_hours_per_week: number; peak_people: number; base_plumbers: number;
  missing_labour_rates: number; settings: Record<string, number>; cashflow: { month: string; value: number; cumulative: number }[];
}

type Tab = "materials" | "labour" | "program" | "cash";
const d = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-AU", { weekday: "short", day: "numeric", month: "short", year: "numeric" });
const money = (v: number) => v.toLocaleString("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 });

export default function JobReports() {
  const jobId = Number(useParams().jobId);
  const [job, setJob] = useState<Job | null>(null);
  const [tab, setTab] = useState<Tab>("program");
  const [withSuggested, setWithSuggested] = useState(false);
  const [byStage, setByStage] = useState(true);
  const [mats, setMats] = useState<MatRow[]>([]);
  const [lab, setLab] = useState<Labour | null>(null);
  const [prog, setProg] = useState<Program | null>(null);
  const [plan, setPlan] = useState({ start_date: "", target_weeks: "", plumbers: "" });
  const [stagePlan, setStagePlan] = useState<Record<string, { plumbers?: number; start?: string }>>({});
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");

  const q = `include_suggested=${withSuggested}`;
  const load = useCallback(async () => {
    setError("");
    try {
      const [j, m, l, p] = await Promise.all([
        api.get<Job>(`/api/jobs/${jobId}`),
        api.get<{ rows: MatRow[] }>(`/api/jobs/${jobId}/reports/materials?${q}&by_stage=${byStage}`),
        api.get<Labour>(`/api/jobs/${jobId}/reports/labour?${q}`),
        api.get<Program>(`/api/jobs/${jobId}/reports/program?${q}`),
      ]);
      setJob(j); setMats(m.rows); setLab(l); setProg(p);
      setPlan({ start_date: j.start_date ?? "", target_weeks: j.target_weeks ? String(j.target_weeks) : "",
                plumbers: String((j.program as { plumbers?: number } | null)?.plumbers ?? "") });
      setStagePlan(((j.program as { stages?: Record<string, { plumbers?: number; start?: string }> } | null)?.stages) ?? {});
    } catch (e) { setError((e as Error).message); }
  }, [jobId, q, byStage]);
  useEffect(() => { load(); }, [load]);

  const savePlan = async () => {
    setError(""); setMsg("");
    try {
      await api.put(`/api/jobs/${jobId}/program`, {
        start_date: plan.start_date || null, target_weeks: plan.target_weeks ? Number(plan.target_weeks) : null,
        plumbers: plan.plumbers ? Number(plan.plumbers) : null,
        stages: Object.fromEntries(Object.entries(stagePlan).map(([k, v]) => [k, { plumbers: v.plumbers || null, start: v.start || null }])),
      });
      setMsg("Program updated.");
      load();
    } catch (e) { setError((e as Error).message); }
  };

  if (!job) return <main className="page">{error || "Loading…"}</main>;
  const groups = [...new Set(mats.map((m) => (byStage ? `${m.stage} · ` : "") + m.group))];

  return (
    <main className="page">
      <div className="row wrap">
        <Link to={`/jobs/${jobId}`}>← {job.name}</Link>
        <span className="spacer" />
        <label className="inline"><input type="checkbox" checked={withSuggested} onChange={(e) => setWithSuggested(e.target.checked)} /> include items not approved yet</label>
        <button className="primary" onClick={() => download(`/api/jobs/${jobId}/reports.xlsx?${q}`, "Reports.xlsx")}>Download all reports (Excel)</button>
      </div>
      <h1>Reports</h1>
      <div className="tabs big-tabs">
        {([["program", "Crew & program"], ["labour", "Labour hours"], ["materials", "Material list"], ["cash", "Cash flow"]] as [Tab, string][]).map(([k, l]) => (
          <button key={k} className={tab === k ? "active" : ""} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      {error && <p className="error big">{error}</p>}
      {msg && <p className="ok">{msg}</p>}
      {lab && lab.missing > 0 && (
        <p className="warn">
          {lab.missing} item{lab.missing === 1 ? " has" : "s have"} no labour rate, so {lab.missing === 1 ? "it's" : "they're"} not in the hours.
          Add labour to the price book or set productivity rates (Admin portal → Reporting).
        </p>
      )}

      {tab === "program" && prog && (
        <>
          <div className="tiles">
            <div className="tile"><b>{prog.base_plumbers} + {Math.floor(prog.base_plumbers * (prog.settings.apprentice_ratio ?? 0) + 1e-9)}</b><span>plumbers + apprentices</span></div>
            <div className="tile"><b>{Math.max(0, ...prog.stages.map((s) => s.supervisors))}</b><span>supervisors / leading hands</span></div>
            <div className="tile"><b>{prog.pm_hours_per_week} h/wk</b><span>project management ({prog.pm_hours} h)</span></div>
            <div className={`tile ${prog.target_weeks && prog.working_weeks > prog.target_weeks ? "warn" : ""}`}><b>{prog.working_days} days</b><span>working days{prog.target_weeks ? ` (target ${prog.target_weeks} wks = ${Math.floor(prog.target_weeks * (prog.settings.days_per_week ?? 5))} days)` : ""}</span></div>
            <div className="tile"><b>{prog.field_hours.toLocaleString("en-AU")} h</b><span>field labour</span></div>
          </div>
          <section className="card">
            <h2>Plan</h2>
            <div className="row wrap">
              <label>Start on site<input type="date" value={plan.start_date} onChange={(e) => setPlan({ ...plan, start_date: e.target.value })} /></label>
              <label>Finish within (weeks)<input type="number" min={1} step="0.5" value={plan.target_weeks} placeholder="no target"
                     onChange={(e) => setPlan({ ...plan, target_weeks: e.target.value })} /></label>
              <span className="muted">or</span>
              <label>Plumbers on site<input type="number" min={1} value={plan.plumbers} placeholder={`default`} disabled={!!plan.target_weeks}
                     onChange={(e) => setPlan({ ...plan, plumbers: e.target.value })} /></label>
              <button className="primary" onClick={savePlan}>Work it out</button>
            </div>
            <p className="small muted">
              With a target, the app works out the crew needed; without one it uses the crew you give and works out how long it takes.
              Apprentices are {prog.settings.apprentice_ratio} per plumber at {Math.round((prog.settings.apprentice_productivity ?? 0) * 100)}% output;
              one supervisor per {prog.settings.workers_per_supervisor} once the crew reaches {prog.settings.supervisor_from_crew};
              {" "}{prog.settings.hours_per_day} h days; weekends, QLD public holidays and the Christmas shutdown are skipped. Admins set these.
            </p>
          </section>
          <section className="card">
            <h2>Program: {d(prog.start_date)} to {d(prog.finish_date)}</h2>
            <Gantt stages={prog.stages} />
            <table className="num">
              <thead><tr><th>Stage</th><th>Plumbers (override)</th><th>Start (override)</th><th>Hours</th><th>Crew</th><th>Days</th><th>Start</th><th>Finish</th></tr></thead>
              <tbody>
                {prog.stages.map((s) => (
                  <tr key={s.stage}>
                    <td>{s.stage}</td>
                    <td><input className="tiny" type="number" min={1} value={stagePlan[s.stage]?.plumbers ?? ""} placeholder="auto"
                               onChange={(e) => setStagePlan({ ...stagePlan, [s.stage]: { ...stagePlan[s.stage], plumbers: Number(e.target.value) || undefined } })} /></td>
                    <td><input type="date" value={stagePlan[s.stage]?.start ?? ""}
                               onChange={(e) => setStagePlan({ ...stagePlan, [s.stage]: { ...stagePlan[s.stage], start: e.target.value || undefined } })} /></td>
                    <td>{s.hours}</td>
                    <td>{s.plumbers}P + {s.apprentices}A{s.supervisors ? ` + ${s.supervisors}S` : ""}</td>
                    <td>{s.workdays}</td><td>{d(s.start)}</td><td>{d(s.end)}</td>
                  </tr>
                ))}
                {prog.stages.length === 0 && <tr><td colSpan={8} className="muted">No labour hours yet: approve the take-off (or tick "include items not approved yet") and set labour rates.</td></tr>}
              </tbody>
            </table>
            {prog.stages.length > 0 && <p className="small muted">Change a stage's plumbers or start date (e.g. to match the builder's program), then press "Work it out".</p>}
          </section>
          {prog.weekly.length > 0 && (
            <section className="card">
              <h2>People on site each week (peak {prog.peak_people})</h2>
              <StackedWeeks weeks={prog.weekly} />
            </section>
          )}
        </>
      )}

      {tab === "labour" && lab && (
        <>
          <div className="two-col">
            <section className="card">
              <h2>By stage ({lab.total_hours.toLocaleString("en-AU")} h)</h2>
              <table className="num"><thead><tr><th>Stage</th><th></th><th></th><th>Hours</th><th>Days (1 plumber)</th></tr></thead>
                <tbody>{lab.by_stage.map((s) => <tr key={s.stage}><td>{s.stage}</td><td /><td /><td>{s.hours}</td><td>{(s.hours / (prog?.settings.hours_per_day || 8)).toFixed(1)}</td></tr>)}</tbody>
              </table>
            </section>
            <section className="card">
              <h2>By service</h2>
              <table className="num"><thead><tr><th>Service</th><th></th><th></th><th>Hours</th></tr></thead>
                <tbody>{lab.by_service.map((s) => <tr key={s.service_code}><td>{s.service_code}</td><td /><td /><td>{s.hours}</td></tr>)}</tbody>
              </table>
            </section>
          </div>
          <section className="card">
            <h2>Every line</h2>
            <table className="num">
              <thead><tr><th>Stage</th><th>Service</th><th>Description</th><th>Qty</th><th>Unit</th><th>Hours / unit</th><th>Hours</th><th>From</th></tr></thead>
              <tbody>
                {lab.rows.map((r, i) => (
                  <tr key={i} className={r.source === "no labour rate" ? "warn-row" : ""}>
                    <td>{r.stage}</td><td>{r.service_code}</td><td>{r.description}</td><td>{r.qty}</td><td>{r.uom}</td>
                    <td>{r.hours_per_unit ?? "-"}</td><td>{r.hours}</td><td className="small">{r.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}

      {tab === "materials" && (
        <section className="card">
          <div className="row">
            <h2 style={{ margin: 0 }}>Material list</h2>
            <span className="spacer" />
            <label className="inline"><input type="checkbox" checked={byStage} onChange={(e) => setByStage(e.target.checked)} /> split by stage (for staged ordering)</label>
          </div>
          <table className="num">
            <thead><tr><th>Item</th><th>Service</th><th>Code</th><th>Qty</th><th>Unit</th><th>Order</th><th></th></tr></thead>
            <tbody>
              {groups.map((g) => (
                <Fragment key={g}>
                  <tr className="cat"><td colSpan={7}><b>{g}</b></td></tr>
                  {mats.filter((m) => (byStage ? `${m.stage} · ` : "") + m.group === g).map((m, i) => (
                    <tr key={g + i}>
                      <td>{m.description}</td><td>{m.service_code}</td><td className="small">{m.code}</td><td>{m.qty}</td><td>{m.uom}</td>
                      <td><b>{m.order_qty}</b> {m.order_uom}</td><td className="small muted">{m.note}</td>
                    </tr>
                  ))}
                </Fragment>
              ))}
              {mats.length === 0 && <tr><td colSpan={7} className="muted">Nothing approved yet. Tick "include items not approved yet" to see the suggested quantities.</td></tr>}
            </tbody>
          </table>
          <p className="small muted">Pipe includes the waste allowance and is rounded up to stock lengths (set per material by an admin).</p>
        </section>
      )}

      {tab === "cash" && prog && (
        <section className="card">
          <h2>Value earned each month (for progress claims)</h2>
          {prog.cashflow.length === 0 ? (
            <p className="muted">{job.kind === "civil" ? "Approve some priced BOQ lines first." : "Choose a price book for this job (Detailed view → Pricing) to see the money side."}</p>
          ) : (
            <>
              <MonthBars months={prog.cashflow} />
              <table className="num">
                <thead><tr><th>Month</th><th></th><th></th><th>Value (ex GST)</th><th>Running total</th></tr></thead>
                <tbody>{prog.cashflow.map((c) => <tr key={c.month}><td>{c.month}</td><td /><td /><td>{money(c.value)}</td><td>{money(c.cumulative)}</td></tr>)}</tbody>
              </table>
              <p className="small muted">Each stage's value is spread evenly over its working days in the program.</p>
            </>
          )}
        </section>
      )}
    </main>
  );
}
