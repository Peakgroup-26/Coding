/* Money: this month against the forecast (pro-rata to today), WIP, cash flow forecast, monthly budgets, invoices and debtors. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, download } from "../api";
import { DataTable, ErrorLine, fmtDate, money, num, pct, Status, Tabs, useAction, useLoad } from "../ui";
import { SERIES } from "./Charts";
import { Invoices } from "./JobHub";

type Tab = "dash" | "wip" | "cash" | "budget" | "invoices";
interface MtdLine { key: string; label: string; forecast: number; prorated: number; actual: number; variance: number; pct_of_prorated: number | null; state: string; is_cost: boolean; projected: number | null }
interface Mtd { month: string; today: string; workdays_total: number; workdays_elapsed: number; fraction: number; forecast_source: string; lines: MtdLine[]; hours: number;
  drivers: { job_id: number; job_no: string; name: string; labour?: number; materials?: number; subcontract?: number; revenue?: number }[]; tolerance_pct: number }
interface Week { week: string; in_invoices: number; in_forecast: number; in_total: number; out_wages: number; out_suppliers: number; out_forecast: number; out_overheads: number; out_total: number; net: number; balance: number }
interface Cash { opening: number; opening_date: string; weeks: Week[]; lowest: { week: string; balance: number } | null; in_total: number; out_total: number }
interface WipRow { job_id: number; job_no: string; name: string; customer: string; status: string; revenue: number; budget_cost: number; cost_to_date: number; committed: number;
  forecast_cost: number; cost_to_complete: number; forecast_margin: number; forecast_margin_pct: number | null; budget_margin_pct: number | null; percent_complete: number;
  earned: number; invoiced: number; over_under_billed: number; retention_held: number; over_budget: boolean }

const STATE_TEXT: Record<string, string> = { over: "Over", under: "Under", on: "On track", behind: "Behind", ahead: "Ahead", none: "No forecast" };

function Bullet({ l }: { l: MtdLine }) {
  const max = Math.max(l.forecast, l.actual, 1);
  const bad = (l.is_cost && l.state === "over") || (!l.is_cost && l.state === "behind");
  return (
    <div className="bullet">
      <div className="row"><b>{l.label}</b><span className="spacer" /><span className={`state ${bad ? "bad" : l.state === "none" ? "" : "good"}`}>{STATE_TEXT[l.state]}</span></div>
      <div className="track" role="img" aria-label={`${l.label}: ${money(l.actual)} so far, ${money(l.prorated)} expected by today, ${money(l.forecast)} for the month`}>
        <span className="fill" style={{ width: `${(100 * l.actual) / max}%`, background: bad ? SERIES[1] : SERIES[0] }} />
        <span className="mark" style={{ left: `${(100 * l.prorated) / max}%` }} title="Where it should be by today" />
        <span className="end" style={{ left: `${(100 * l.forecast) / max}%` }} />
      </div>
      <div className="small"><b>{money(l.actual)}</b> so far · <span className="muted">{money(l.prorated)} expected by today · {money(l.forecast)} for the month</span>
        {l.forecast > 0 && <> · <b className={bad ? "error" : ""}>{l.variance >= 0 ? "+" : ""}{money(l.variance)}</b></>}</div>
    </div>
  );
}

function CashChart({ weeks }: { weeks: Week[] }) {
  const W = 760, H = 220, L = 60, B = 26, T = 10;
  const vals = weeks.flatMap((w) => [w.in_total, w.out_total, w.balance]);
  const max = Math.max(1, ...vals), min = Math.min(0, ...vals);
  const bw = (W - L - 10) / weeks.length;
  const y = (v: number) => T + (1 - (v - min) / (max - min)) * (H - T - B);
  return (
    <figure>
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Cash flow by week">
        {[min, 0, max].map((v, i) => <g key={i}><line x1={L} x2={W - 10} y1={y(v)} y2={y(v)} stroke="#e3e7ee" /><text x={L - 6} y={y(v) + 4} fontSize="11" textAnchor="end" fill="#6b7686">{money(v)}</text></g>)}
        {weeks.map((w, i) => (
          <g key={w.week}>
            <rect x={L + i * bw + 3} y={y(w.in_total)} width={bw / 2 - 4} height={Math.max(0, y(0) - y(w.in_total))} rx="2" fill={SERIES[0]}><title>{`Week of ${fmtDate(w.week)}: in ${money(w.in_total)}`}</title></rect>
            <rect x={L + i * bw + bw / 2 + 1} y={y(w.out_total)} width={bw / 2 - 4} height={Math.max(0, y(0) - y(w.out_total))} rx="2" fill={SERIES[1]}><title>{`out ${money(w.out_total)}`}</title></rect>
            {(weeks.length <= 13 || i % 2 === 0) && <text x={L + i * bw + bw / 2} y={H - 8} fontSize="10" textAnchor="middle" fill="#1c2430">{fmtDate(w.week).slice(0, 5)}</text>}
          </g>
        ))}
        <polyline fill="none" stroke={SERIES[2]} strokeWidth="2.5" points={weeks.map((w, i) => `${L + i * bw + bw / 2},${y(w.balance)}`).join(" ")} />
      </svg>
      <figcaption className="legend"><span><i style={{ background: SERIES[0] }} /> Money in</span><span><i style={{ background: SERIES[1] }} /> Money out</span>
        <span><i style={{ background: SERIES[2], height: 3 }} /> Bank balance</span></figcaption>
    </figure>
  );
}

export default function Finance() {
  const [tab, setTab] = useState<Tab>(() => ((new URLSearchParams(window.location.search).get("tab") as Tab) || "dash"));
  useEffect(() => { const t = new URLSearchParams(window.location.search).get("tab") as Tab; if (t) setTab(t); }, []);
  return (
    <main className="page">
      <div className="row wrap"><h1 style={{ margin: 0 }}>Money</h1><span className="spacer" />
        <Tabs tabs={[["dash", "Dashboard"], ["wip", "WIP"], ["cash", "Cash flow"], ["budget", "Budgets"], ["invoices", "Invoices & debtors"]]} value={tab} onChange={setTab} /></div>
      {tab === "dash" && <Dash />}
      {tab === "wip" && <Wip />}
      {tab === "cash" && <CashFlow />}
      {tab === "budget" && <Budgets />}
      {tab === "invoices" && <><Debtors /><Invoices /></>}
    </main>
  );
}

function Dash() {
  const { data } = useLoad<{ month: Mtd; wip: Record<string, number>; over_budget: WipRow[]; low_margin: WipRow[]; cash: { opening: number; lowest: { week: string; balance: number } | null; in_13w: number; out_13w: number; weeks: Week[] };
    debtors: Record<string, number>; nps: { nps: number | null; responses: number }; active_jobs: number }>("/api/finance/dashboard");
  if (!data) return <p className="muted">Loading…</p>;
  const m = data.month;
  return (
    <>
      <section className="card">
        <div className="row wrap"><h2 style={{ margin: 0 }}>{new Date(m.month + "-01T00:00:00").toLocaleDateString("en-AU", { month: "long", year: "numeric" })} so far</h2>
          <span className="spacer" /><span className="small muted">{m.workdays_elapsed} of {m.workdays_total} working days ({Math.round(m.fraction * 100)}%) · forecast from {m.forecast_source === "budget" ? "the monthly budget" : "the live jobs (no budget set)"}</span></div>
        <div className="bullets">{m.lines.map((l) => <Bullet key={l.key} l={l} />)}</div>
        <p className="small muted">The tick mark is where each line should be by today if the month's forecast is spread over its working days. Red means more than {m.tolerance_pct}% over (costs) or behind (revenue).</p>
        {m.drivers.length > 0 && (
          <details><summary className="small">Jobs behind this month's costs</summary>
            <DataTable rows={m.drivers} cols={[
              { key: "j", label: "Job", render: (d) => <Link to={`/work/${d.job_id}`}>{d.job_no} {d.name}</Link> },
              { key: "l", label: "Labour", num: true, render: (d) => money(d.labour) },
              { key: "m", label: "Materials", num: true, render: (d) => money(d.materials) },
              { key: "s", label: "Subcontract", num: true, render: (d) => money(d.subcontract) },
              { key: "r", label: "Invoiced", num: true, render: (d) => money(d.revenue) },
            ]} /></details>
        )}
      </section>
      <div className="tiles">
        <div className="tile"><b>{data.active_jobs}</b><span>active jobs</span></div>
        <div className="tile"><b>{money(data.wip.revenue)}</b><span>work on hand (revenue)</span></div>
        <div className="tile"><b>{pct(data.wip.forecast_margin_pct)}</b><span>forecast margin</span></div>
        <div className="tile"><b>{money(data.wip.under_billed)}</b><span>done but not billed</span></div>
        <div className={`tile ${data.cash.lowest && data.cash.lowest.balance < 0 ? "warn" : ""}`}><b>{money(data.cash.lowest?.balance)}</b><span>lowest bank balance (13 weeks) {data.cash.lowest && `w/c ${fmtDate(data.cash.lowest.week)}`}</span></div>
        <div className="tile"><b>{money(Object.entries(data.debtors).filter(([k]) => k !== "current").reduce((s, [, v]) => s + v, 0))}</b><span>overdue debtors</span></div>
        <div className="tile"><b>{data.nps.nps ?? "–"}</b><span>NPS (3 months, {data.nps.responses} replies)</span></div>
      </div>
      <div className="two-col even">
        <section className="card"><h2>Jobs going over budget</h2>
          <DataTable rows={data.over_budget} empty="None. Every job's forecast is inside its budget." cols={[
            { key: "j", label: "Job", render: (r) => <Link to={`/work/${r.job_id}`}>{r.job_no} {r.name}</Link> },
            { key: "b", label: "Budget", num: true, render: (r) => money(r.budget_cost) },
            { key: "f", label: "Forecast", num: true, render: (r) => money(r.forecast_cost) },
            { key: "m", label: "Margin", num: true, render: (r) => `${pct(r.forecast_margin_pct)} (was ${pct(r.budget_margin_pct)})` },
          ]} /></section>
        <section className="card"><h2>Cash, next 13 weeks</h2><CashChart weeks={data.cash.weeks} /></section>
      </div>
    </>
  );
}

function Wip() {
  const [sector, setSector] = useState("");
  const { data } = useLoad<{ rows: WipRow[]; totals: Record<string, number | null> }>(`/api/finance/wip?sector=${sector}`, [sector]);
  if (!data) return <p className="muted">Loading…</p>;
  const t = data.totals;
  return (
    <section className="card">
      <div className="row wrap"><h2 style={{ margin: 0 }}>Work in progress</h2>
        <div className="chips">{[["", "All"], ["residential", "Residential"], ["commercial", "Commercial"], ["maintenance", "Maintenance"], ["civil", "Civil"]].map(([k, l]) => <button key={k} className={sector === k ? "chip on" : "chip"} onClick={() => setSector(k)}>{l}</button>)}</div>
        <span className="spacer" /><button onClick={() => download("/api/finance/wip.csv", "wip.csv")}>Download</button></div>
      <DataTable rows={data.rows} rowClass={(r) => (r.over_budget ? "warn-row" : "")} cols={[
        { key: "j", label: "Job", render: (r) => <Link to={`/work/${r.job_id}`}><b>{r.job_no}</b> {r.name}</Link> },
        { key: "s", label: "Status", hideSm: true, render: (r) => <Status value={r.status} /> },
        { key: "rev", label: "Revenue", num: true, render: (r) => money(r.revenue) },
        { key: "pc", label: "% done", num: true, render: (r) => pct(r.percent_complete) },
        { key: "ctd", label: "Cost to date", num: true, render: (r) => money(r.cost_to_date) },
        { key: "ctc", label: "To complete", num: true, hideSm: true, render: (r) => money(r.cost_to_complete) },
        { key: "fc", label: "Forecast cost", num: true, hideSm: true, render: (r) => money(r.forecast_cost) },
        { key: "fm", label: "Margin", num: true, render: (r) => <span className={r.over_budget ? "error" : ""}>{money(r.forecast_margin)} ({pct(r.forecast_margin_pct)})</span> },
        { key: "e", label: "Earned", num: true, hideSm: true, render: (r) => money(r.earned) },
        { key: "i", label: "Invoiced", num: true, render: (r) => money(r.invoiced) },
        { key: "ou", label: "Over / (under) billed", num: true, render: (r) => <span className={r.over_under_billed < 0 ? "warn" : ""}>{money(r.over_under_billed)}</span> },
      ]} />
      <table className="kv"><tbody>
        <tr><td>Revenue on hand</td><td>{money(t.revenue)}</td><td>Forecast margin</td><td>{money(t.forecast_margin)} ({pct(t.forecast_margin_pct)})</td></tr>
        <tr><td>Cost to date</td><td>{money(t.cost_to_date)}</td><td>Cost to complete</td><td>{money(t.cost_to_complete)}</td></tr>
        <tr><td>Under-billed (work done, not invoiced)</td><td>{money(t.under_billed)}</td><td>Over-billed (invoiced ahead)</td><td>{money(t.over_billed)}</td></tr>
        <tr><td>Retention held by clients</td><td>{money(t.retention_held)}</td><td></td><td></td></tr>
      </tbody></table>
      <p className="small muted">% complete is each job's cost to date over its forecast final cost, unless someone has set it on the job. Earned = revenue × % complete.</p>
    </section>
  );
}

function CashFlow() {
  const [weeks, setWeeks] = useState(13);
  const { data } = useLoad<Cash>(`/api/finance/cashflow?weeks=${weeks}`, [weeks]);
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <section className="card">
      <div className="row wrap"><h2 style={{ margin: 0 }}>Cash flow forecast</h2><span className="spacer" />
        <select value={weeks} onChange={(e) => setWeeks(Number(e.target.value))}><option value={8}>8 weeks</option><option value={13}>13 weeks</option><option value={26}>26 weeks</option></select></div>
      <p className="small">Starting bank balance {money(data.opening)} {data.opening_date && `(${fmtDate(data.opening_date)})`}. Lowest point {money(data.lowest?.balance)} in the week of {fmtDate(data.lowest?.week)}.</p>
      <CashChart weeks={data.weeks} />
      <DataTable rows={data.weeks} cols={[
        { key: "w", label: "Week of", render: (w) => fmtDate(w.week) },
        { key: "ii", label: "Invoices due", num: true, render: (w) => money(w.in_invoices) },
        { key: "if", label: "Still to bill", num: true, hideSm: true, render: (w) => money(w.in_forecast) },
        { key: "ow", label: "Wages", num: true, render: (w) => money(w.out_wages) },
        { key: "os", label: "Suppliers", num: true, render: (w) => money(w.out_suppliers + w.out_forecast) },
        { key: "oo", label: "Overheads", num: true, hideSm: true, render: (w) => money(w.out_overheads) },
        { key: "n", label: "Net", num: true, render: (w) => <span className={w.net < 0 ? "warn" : ""}>{money(w.net)}</span> },
        { key: "b", label: "Balance", num: true, render: (w) => <b className={w.balance < 0 ? "error" : ""}>{money(w.balance)}</b> },
      ]} />
      <p className="small muted">In: invoices sent, on their due dates; work still to bill on each job, spread to its finish date plus the customer's terms. Out: wages from the schedule
        (or each job's remaining labour), supplier bills and open POs on their terms, remaining materials, and the monthly overheads from Budgets. Ex GST.</p>
    </section>
  );
}

interface BudgetMonthRow { month: string; budget: { revenue: number; labour: number; materials: number; subcontract: number; overheads: number; notes: string } | null;
  jobs: Record<string, number>; actual: Record<string, number> }

function Budgets() {
  const { data, reload } = useLoad<BudgetMonthRow[]>("/api/budget-months?months=12");
  const [rows, setRows] = useState<Record<string, Record<string, number>>>({});
  const [run, error] = useAction();
  const [msg, setMsg] = useState("");
  useEffect(() => { if (data) setRows(Object.fromEntries(data.map((r) => [r.month, { revenue: r.budget?.revenue ?? 0, labour: r.budget?.labour ?? 0, materials: r.budget?.materials ?? 0, subcontract: r.budget?.subcontract ?? 0, overheads: r.budget?.overheads ?? 0 }]))); }, [data]);
  if (!data) return <p className="muted">Loading…</p>;
  const keys = ["revenue", "labour", "materials", "subcontract", "overheads"];
  return (
    <section className="card">
      <div className="row wrap"><h2 style={{ margin: 0 }}>Monthly budget (forecast)</h2><span className="spacer" />
        <button onClick={() => run(async () => { await api.post("/api/budget-months/fill", { months: data.map((r) => r.month) }); reload(); setMsg("Filled from the live jobs. Adjust and save."); })}>Fill from the live jobs</button>
        <button className="primary" onClick={() => run(async () => { for (const m of Object.keys(rows)) await api.put("/api/budget-months", { month: m, ...rows[m] }); setMsg("Saved."); reload(); })}>Save</button></div>
      <p className="small muted">What you expect to invoice and spend each month. The dashboard compares each month so far against this, pro-rata by working days.
        "Jobs say" is what the live jobs' remaining budgets add up to, spread to their finish dates.</p>
      {msg && <p className="ok small">{msg}</p>}<ErrorLine error={error} />
      <div className="dt-wrap"><table className="dt compact budget-grid">
        <thead><tr><th>Month</th>{keys.map((k) => <th key={k} className="n">{k}</th>)}<th className="n">Jobs say: revenue / labour / materials</th><th className="n">Actual: revenue / labour / materials</th></tr></thead>
        <tbody>{data.map((r) => (
          <tr key={r.month}>
            <td>{new Date(r.month + "-01T00:00:00").toLocaleDateString("en-AU", { month: "short", year: "numeric" })}</td>
            {keys.map((k) => <td key={k}><input type="number" min={0} step={1000} value={rows[r.month]?.[k] ?? 0} onChange={(e) => setRows({ ...rows, [r.month]: { ...rows[r.month], [k]: Number(e.target.value) } })} /></td>)}
            <td className="n small muted">{money(r.jobs.revenue)} / {money(r.jobs.labour)} / {money((r.jobs.materials ?? 0) + (r.jobs.other ?? 0) + (r.jobs.plant ?? 0))}</td>
            <td className="n small">{r.actual.revenue !== undefined || r.actual.labour !== undefined ? `${money(r.actual.revenue)} / ${money(r.actual.labour)} / ${money(r.actual.materials)}` : ""}</td>
          </tr>))}</tbody>
      </table></div>
      <p className="small muted">{num(data.length, 0)} months shown.</p>
    </section>
  );
}

function Debtors() {
  const { data } = useLoad<{ buckets: Record<string, number>; total: number }>("/api/invoices/aged");
  if (!data) return null;
  return (
    <div className="tiles">
      <div className="tile"><b>{money(data.total)}</b><span>owed to us (inc GST)</span></div>
      {Object.entries(data.buckets).map(([k, v]) => <div key={k} className={`tile ${k !== "current" && v > 0 ? "warn" : ""}`}><b>{money(v)}</b><span>{k === "current" ? "not yet due" : `${k} days overdue`}</span></div>)}
    </div>
  );
}
