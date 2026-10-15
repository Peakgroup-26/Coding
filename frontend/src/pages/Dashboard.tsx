import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { StackedWeeks } from "./Charts";

interface Dash {
  jobs: number;
  by_result: Record<string, { count: number; value: number }>;
  win_rate_pct: number | null;
  by_month: { month: string; submitted: number; won: number; count: number }[];
  due_soon: { job_id: number; name: string; kind: string; due_date: string }[];
  workforce: { week: string; plumbers: number; apprentices: number; supervisors: number; jobs: string[]; short: Record<string, number> | null }[];
  planned_jobs: { job_id: number; name: string; result: string; start: string; finish: string; peak_people: number }[];
  headcount: { plumbers?: number; apprentices?: number; supervisors?: number };
  ai: { suggestions_accepted: number; suggestions_edited: number; suggestions_rejected: number; accepted_pct: number | null;
        plans: number; scales_auto_confirmed: number; auto_scale_pct: number | null };
  common_exclusions: { description: string; jobs: number }[];
}

const money = (v: number) => v.toLocaleString("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 });
const d = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-AU", { day: "numeric", month: "short", year: "numeric" });

export default function Dashboard() {
  const [data, setData] = useState<Dash | null>(null);
  const [pending, setPending] = useState(false);
  useEffect(() => { api.get<Dash>(`/api/reports/dashboard?include_pending=${pending}&weeks=26`).then(setData); }, [pending]);
  if (!data) return <main className="page">Loading…</main>;
  const r = (k: string) => data.by_result[k] ?? { count: 0, value: 0 };
  const head = data.headcount ?? {};
  const available = (head.plumbers ?? 0) + (head.apprentices ?? 0) + (head.supervisors ?? 0);
  const shortWeeks = data.workforce.filter((w) => w.short && Object.values(w.short).some((v) => v > 0));

  return (
    <main className="page">
      <h1>Reports</h1>
      <p className="muted">Across the {data.jobs} jobs you can see. Open a job for its material list, labour hours, crew and program.</p>
      <div className="tiles">
        <div className="tile"><b>{r("pending").count}</b><span>tenders pending ({money(r("pending").value)})</span></div>
        <div className="tile ok"><b>{r("won").count}</b><span>won ({money(r("won").value)})</span></div>
        <div className="tile"><b>{r("lost").count}</b><span>lost ({money(r("lost").value)})</span></div>
        <div className="tile"><b>{data.win_rate_pct === null ? "–" : `${data.win_rate_pct}%`}</b><span>win rate (won ÷ decided)</span></div>
        <div className="tile"><b>{data.ai.accepted_pct === null ? "–" : `${data.ai.accepted_pct}%`}</b><span>AI suggestions kept</span></div>
      </div>

      <section className="card">
        <div className="row wrap">
          <h2 style={{ margin: 0 }}>Workforce forecast: next 26 weeks</h2>
          <span className="spacer" />
          <label className="inline"><input type="checkbox" checked={pending} onChange={(e) => setPending(e.target.checked)} /> include pending tenders</label>
        </div>
        {data.planned_jobs.length === 0 ? (
          <p className="muted">Mark jobs as won and give them a start date (on each job's Reports page) to see the people you'll need.</p>
        ) : (
          <>
            <StackedWeeks weeks={data.workforce} available={available || undefined} />
            {available > 0 && (shortWeeks.length
              ? <p className="warn">Short of people in {shortWeeks.length} week{shortWeeks.length === 1 ? "" : "s"}, first the week of {d(shortWeeks[0].week)}
                  {shortWeeks[0].short && ` (${Object.entries(shortWeeks[0].short).filter(([, v]) => v > 0).map(([k, v]) => `${v} ${k}`).join(", ")})`}.</p>
              : <p className="ok">Your people cover every week in this forecast.</p>)}
            {!available && <p className="small muted">Set how many plumbers, apprentices and supervisors you have (Admin portal → Reporting) to see where you'd be short.</p>}
            <table>
              <thead><tr><th>Job</th><th>Status</th><th>Start</th><th>Finish</th><th>Peak people</th></tr></thead>
              <tbody>
                {data.planned_jobs.map((j) => (
                  <tr key={j.job_id}><td><Link to={`/jobs/${j.job_id}/reports`}>{j.name}</Link></td><td>{j.result}</td>
                    <td>{d(j.start)}</td><td>{d(j.finish)}</td><td>{j.peak_people}</td></tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <div className="two-col">
        <section className="card">
          <h2>Tenders by month</h2>
          <table className="num">
            <thead><tr><th>Month</th><th>Tenders</th><th></th><th>Submitted</th><th>Won</th></tr></thead>
            <tbody>
              {data.by_month.map((m) => <tr key={m.month}><td>{m.month}</td><td>{m.count}</td><td /><td>{money(m.submitted)}</td><td>{money(m.won)}</td></tr>)}
              {data.by_month.length === 0 && <tr><td colSpan={5} className="muted">No tenders yet.</td></tr>}
            </tbody>
          </table>
          <p className="small muted">Record each tender's price and result on its job page.</p>
        </section>
        <section className="card">
          <h2>Due in the next 14 days</h2>
          <ul className="plain">
            {data.due_soon.map((j) => <li key={j.job_id}><Link to={`/jobs/${j.job_id}`}>{j.name}</Link> <span className="muted">· {d(j.due_date)}</span></li>)}
            {data.due_soon.length === 0 && <li className="muted">Nothing due.</li>}
          </ul>
          <h3>AI performance</h3>
          <ul className="plain small">
            <li>Plan scales confirmed automatically: {data.ai.scales_auto_confirmed} of {data.ai.plans}{data.ai.auto_scale_pct !== null ? ` (${data.ai.auto_scale_pct}%)` : ""}</li>
            <li>Suggestions kept as they were: {data.ai.suggestions_accepted}, kept after editing: {data.ai.suggestions_edited}, rejected: {data.ai.suggestions_rejected}</li>
          </ul>
          {data.common_exclusions.length > 0 && (
            <>
              <h3>Most common exclusions</h3>
              <ul className="plain small">{data.common_exclusions.map((e) => <li key={e.description}>{e.description} <span className="muted">({e.jobs} jobs)</span></li>)}</ul>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
