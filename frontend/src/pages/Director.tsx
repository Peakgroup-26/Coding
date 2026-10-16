/* The director's dashboard: the team's eNPS and the clients' NPS month by month, side by side, with the headlines. */
import { Link } from "react-router-dom";
import { money, num, useLoad } from "../ui";

interface TeamMonth { month: string; enps: number | null; responses: number; promoters: number; passives: number; detractors: number; departments: Record<string, number | null> }
interface ClientMonth { month: string; nps: number | null; responses: number; departments: Record<string, number | null> }
interface Data {
  team: TeamMonth[]; clients: ClientMonth[]; team_now: TeamMonth | null; clients_now: ClientMonth | null;
  clients_overall: { nps: number | null; responses: number; response_rate: number | null };
  client_departments: { key: string; label: string; nps: number | null; responses: number }[];
  client_types: { key: string; label: string; nps: number | null; responses: number }[];
  recent_client_comments: { customer: string; score: number; comment: string; at: string | null }[];
  surveys_waiting: number; open_surveys: number;
  people: { headcount: number; turnover_pct: number; licence_problems: number; feedback_open: number };
  money?: { labour?: { actual: number; forecast_to_date: number }; materials?: { actual: number; forecast_to_date: number }; [k: string]: unknown } | null;
}
const mlabel = (m: string) => new Date(m + "-01T00:00:00").toLocaleDateString("en-AU", { month: "short", year: "2-digit" });
const npsClass = (v: number | null | undefined) => (v === null || v === undefined ? "" : v >= 50 ? "ok" : v >= 0 ? "warn" : "bad");
const fmt = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${num(v, 0)}`);

function NpsLines({ team, clients }: { team: TeamMonth[]; clients: ClientMonth[] }) {
  const W = 760, H = 260, L = 40, R = 12, T = 14, B = 34;
  const n = team.length;
  const x = (i: number) => L + (i * (W - L - R)) / Math.max(1, n - 1);
  const y = (v: number) => T + ((100 - v) * (H - T - B)) / 200;
  const path = (vals: (number | null)[]) => vals.map((v, i) => (v === null ? null : `${x(i)},${y(v)}`)).filter(Boolean).map((p, i) => `${i ? "L" : "M"}${p}`).join(" ");
  const tv = team.map((t) => t.enps), cv = clients.map((c) => c.nps);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="nps-lines" role="img" aria-label="Team eNPS and client NPS by month">
      {[-100, -50, 0, 50, 100].map((v) => <g key={v}><line x1={L} x2={W - R} y1={y(v)} y2={y(v)} stroke={v === 0 ? "#cfc7c0" : "#eee9e4"} strokeDasharray={v === 0 ? "" : "3 4"} />
        <text x={L - 6} y={y(v) + 4} fontSize="11" textAnchor="end" fill="#6f6a66">{v}</text></g>)}
      {team.map((t, i) => <text key={t.month} x={x(i)} y={H - 12} fontSize="11" textAnchor="middle" fill="#6f6a66">{mlabel(t.month)}</text>)}
      <path d={path(cv)} fill="none" stroke="#ffb27a" strokeWidth={3} />
      <path d={path(tv)} fill="none" stroke="#ff6a13" strokeWidth={3} />
      {cv.map((v, i) => v !== null && <circle key={`c${i}`} cx={x(i)} cy={y(v)} r={4.5} fill="#fff" stroke="#ffb27a" strokeWidth={2.5}><title>Clients {mlabel(clients[i].month)}: {fmt(v)} ({clients[i].responses})</title></circle>)}
      {tv.map((v, i) => v !== null && <circle key={`t${i}`} cx={x(i)} cy={y(v)} r={4.5} fill="#ff6a13"><title>Team {mlabel(team[i].month)}: {fmt(v)} ({team[i].responses})</title></circle>)}
    </svg>
  );
}

export default function Director() {
  const { data: d, error } = useLoad<Data>("/api/director");
  if (!d) return <main className="page"><p className="muted">{error || "Loading…"}</p></main>;
  const tn = d.team_now, cn = d.clients_now;
  const depts = Array.from(new Set(d.team.flatMap((t) => Object.keys(t.departments))));
  const cdepts = Array.from(new Set(d.clients.flatMap((c) => Object.keys(c.departments))));
  const lab = d.money?.labour as { actual: number; forecast_to_date: number } | undefined;
  const mat = d.money?.materials as { actual: number; forecast_to_date: number } | undefined;
  return (
    <main className="page">
      <div className="row"><h1 style={{ margin: 0 }}>Director's dashboard</h1><span className="spacer" />
        <Link to="/people?tab=surveys" className="button">Team surveys</Link><Link to="/crm" className="button">Client feedback</Link></div>
      <div className="tiles">
        <div className="tile big"><b className={npsClass(tn?.enps)}>{fmt(tn?.enps)}</b><span>Team eNPS{tn ? ` · ${mlabel(tn.month)} · ${tn.responses} answers` : ""}</span></div>
        <div className="tile big"><b className={npsClass(cn?.nps)}>{fmt(cn?.nps)}</b><span>Client NPS{cn ? ` · ${mlabel(cn.month)} · ${cn.responses} answers` : ""}</span></div>
        <div className={`tile ${d.surveys_waiting ? "warn" : ""}`}><b>{d.surveys_waiting}</b><span>Team survey answers still to come</span></div>
        <div className={`tile ${d.people.feedback_open ? "warn" : ""}`}><b>{d.people.feedback_open}</b><span>Staff feedback not yet read</span></div>
        <div className="tile"><b>{d.people.headcount}</b><span>People · turnover {num(d.people.turnover_pct, 1)}%</span></div>
        <div className={`tile ${d.people.licence_problems ? "warn" : ""}`}><b>{d.people.licence_problems}</b><span>People with licences out of date</span></div>
        {lab && <div className="tile"><b>{money(lab.actual)}</b><span>Labour this month · forecast {money(lab.forecast_to_date)}</span></div>}
        {mat && <div className="tile"><b>{money(mat.actual)}</b><span>Materials this month · forecast {money(mat.forecast_to_date)}</span></div>}
      </div>
      <section className="card">
        <div className="row wrap"><h2 style={{ margin: 0 }}>NPS by month</h2><span className="spacer" />
          <span className="legend"><i style={{ background: "#ff6a13" }} /> Team (eNPS)</span><span className="legend"><i style={{ background: "#ffb27a" }} /> Clients</span></div>
        <NpsLines team={d.team} clients={d.clients} />
        <p className="small muted">NPS runs from −100 to +100: the % who'd score you 9–10 minus the % who'd score 0–6. Above +50 is excellent; below 0 needs attention.</p>
      </section>
      <div className="two-col">
        <section className="card">
          <h2>Team, month by month</h2>
          <div className="dt-wrap">
            <table className="dt">
              <thead><tr><th>Month</th><th className="n">eNPS</th><th className="n">Answers</th><th style={{ minWidth: 140 }}>Promoters / passives / detractors</th>
                {depts.map((k) => <th key={k} className="n">{k}</th>)}</tr></thead>
              <tbody>{[...d.team].reverse().map((t) => (
                <tr key={t.month}><td>{mlabel(t.month)}</td><td className={`n ${npsClass(t.enps)}`}><b>{fmt(t.enps)}</b></td><td className="n">{t.responses || ""}</td>
                  <td>{t.responses > 0 && <div className="pd-bar"><i className="p" style={{ flex: t.promoters }} /><i className="m" style={{ flex: t.passives }} /><i className="d" style={{ flex: t.detractors }} /></div>}</td>
                  {depts.map((k) => <td key={k} className={`n ${npsClass(t.departments[k])}`}>{fmt(t.departments[k])}</td>)}</tr>))}</tbody>
            </table>
          </div>
          <p className="small muted">Departments show only where at least 3 people answered, so nobody's answer can be picked out.</p>
        </section>
        <section className="card">
          <h2>Clients, month by month</h2>
          <div className="dt-wrap">
            <table className="dt">
              <thead><tr><th>Month</th><th className="n">NPS</th><th className="n">Answers</th>{cdepts.map((k) => <th key={k} className="n">{k}</th>)}</tr></thead>
              <tbody>{[...d.clients].reverse().map((c) => (
                <tr key={c.month}><td>{mlabel(c.month)}</td><td className={`n ${npsClass(c.nps)}`}><b>{fmt(c.nps)}</b></td><td className="n">{c.responses || ""}</td>
                  {cdepts.map((k) => <td key={k} className={`n ${npsClass(c.departments[k])}`}>{fmt(c.departments[k])}</td>)}</tr>))}</tbody>
            </table>
          </div>
          <h3>By client type (12 months)</h3>
          {d.client_types.map((t) => <div key={t.key} className="row small" style={{ margin: "3px 0" }}><span style={{ flex: 1 }}>{t.label}</span><b className={npsClass(t.nps)}>{fmt(t.nps)}</b><span className="muted">{t.responses}</span></div>)}
          {d.recent_client_comments.length > 0 && <><h3>What clients said lately</h3>
            {d.recent_client_comments.map((c, i) => <p key={i} className="small quote"><b>{c.score}/10</b> {c.customer}: “{c.comment}”</p>)}</>}
        </section>
      </div>
    </main>
  );
}
