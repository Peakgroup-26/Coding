import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { SalesSettings, SalesStage, Sector } from "../types";
import { STAGE_LABELS } from "../types";
import { SERIES } from "./Charts";

interface Stats { count: number; average: number | null; median: number | null }
interface Group { name: string; leads: number; quoted: number; won: number; lost: number; won_value: number; quoted_value: number;
  quote_rate_pct: number | null; win_rate_pct: number | null; lead_to_quote_days: number | null }
interface Brief { job_id: number; name: string; quote_no: string; sector: Sector; client: string; value: number | null; stage: SalesStage;
  days: number | null; due_date: string | null; estimator: string; contact: string; overdue?: boolean }
interface Dash {
  period: { from: string; to: string; months: number };
  leads: number; quotes_sent: number; won: number; lost: number;
  conversion: { lead_to_quote_pct: number | null; quote_to_win_pct: number | null; lead_to_win_pct: number | null; win_rate_decided_pct: number | null };
  days: { lead_to_quote: Stats; quote_to_win: Stats; lead_to_win: Stats; quote_to_loss: Stats };
  value: { quoted: number; won: number; average_won: number | null; open_quotes: number };
  pipeline: Record<SalesStage, { count: number; value: number }>;
  by_source: Group[]; by_estimator: Group[]; by_sector: Group[];
  monthly: { month: string; leads: number; quotes_sent: number; won: number; lost: number; won_value: number }[];
  open_quotes: Brief[]; to_quote: Brief[];
}

const money = (v: number | null | undefined) => (v ?? 0).toLocaleString("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 });
const pct = (v: number | null) => (v === null ? "–" : `${v}%`);
const days = (s: Stats) => (s.average === null ? "–" : `${s.average} days`);
const monthLabel = (m: string) => new Date(m + "-01T00:00:00").toLocaleDateString("en-AU", { month: "short", year: "2-digit" });

/** Leads, then quotes sent, then wins, as horizontal bars of one series. */
function Funnel({ d }: { d: Dash }) {
  const rows: [string, number, string][] = [
    ["Leads", d.leads, ""], ["Quotes sent", d.quotes_sent, pct(d.conversion.lead_to_quote_pct) + " of leads"],
    ["Won", d.won, pct(d.conversion.quote_to_win_pct) + " of quotes"],
  ];
  const max = Math.max(1, d.leads);
  return (
    <svg className="chart funnel" viewBox="0 0 640 120" role="img" aria-label="Leads to quotes to wins">
      {rows.map(([label, n, note], i) => {
        const w = Math.max(n ? 6 : 0, (n / max) * 400);
        const y = 8 + i * 38;
        return (
          <g key={label}>
            <text x="0" y={y + 19} fontSize="13" fill="#1c2430">{label}</text>
            <rect x="110" y={y} width={w} height="28" rx="4" fill={SERIES[0]} />
            <text x={116 + w} y={y + 19} fontSize="13" fill="#1c2430" fontWeight="600">{n}</text>
            <text x={150 + w} y={y + 19} fontSize="12" fill="#6b7686">{note}</text>
          </g>
        );
      })}
    </svg>
  );
}

function MiniBar({ value, max }: { value: number; max: number }) {
  return <span className="minibar"><span style={{ width: `${max ? (value / max) * 100 : 0}%`, background: SERIES[0] }} /></span>;
}

function GroupTable({ title, rows }: { title: string; rows: Group[] }) {
  if (!rows.length) return null;
  return (
    <section className="card">
      <h2>{title}</h2>
      <table className="num">
        <thead><tr><th>{title.replace("By ", "")}</th><th>Leads</th><th>Quoted</th><th>Quote rate</th><th>Won</th><th>Win rate</th><th>Won value</th><th>Days to quote</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}><td>{r.name}</td><td>{r.leads}</td><td>{r.quoted}</td><td>{pct(r.quote_rate_pct)}</td><td>{r.won}</td>
              <td>{pct(r.win_rate_pct)}</td><td>{money(r.won_value)}</td><td>{r.lead_to_quote_days ?? "–"}</td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export default function Sales() {
  const [settings, setSettings] = useState<SalesSettings | null>(null);
  const [sector, setSector] = useState<"" | Sector>("");
  const [months, setMonths] = useState(12);
  const [d, setD] = useState<Dash | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.get<SalesSettings>("/api/sales/settings").then(setSettings); }, []);
  useEffect(() => {
    api.get<Dash>(`/api/sales/dashboard?sector=${sector}&months=${months}`).then(setD).catch((e) => setError(e.message));
  }, [sector, months]);
  if (!d || !settings) return <main className="page">{error || "Loading…"}</main>;
  const maxMonth = Math.max(1, ...d.monthly.map((m) => m.leads));

  return (
    <main className="page">
      <div className="row wrap">
        <h1 style={{ margin: 0 }}>Sales</h1>
        <div className="tabs" style={{ margin: "0 0 0 12px" }}>
          {settings.sectors.length > 1 && <button className={sector === "" ? "active" : ""} onClick={() => setSector("")}>All</button>}
          {settings.sectors.map((s) => <button key={s.key} className={sector === s.key ? "active" : ""} onClick={() => setSector(s.key)}>{s.label}</button>)}
        </div>
        <span className="spacer" />
        <label className="inline">Period
          <select value={months} onChange={(e) => setMonths(Number(e.target.value))}>
            <option value={3}>Last 3 months</option><option value={6}>Last 6 months</option><option value={12}>Last 12 months</option><option value={24}>Last 2 years</option>
          </select>
        </label>
      </div>
      <p className="muted small">Leads that came in from {new Date(d.period.from + "T00:00:00").toLocaleDateString("en-AU")} and what happened to them.</p>

      <div className="tiles">
        <div className="tile"><b>{d.leads}</b><span>leads</span></div>
        <div className="tile"><b>{pct(d.conversion.lead_to_quote_pct)}</b><span>leads quoted</span></div>
        <div className="tile"><b>{pct(d.conversion.quote_to_win_pct)}</b><span>quotes won</span></div>
        <div className="tile"><b>{pct(d.conversion.lead_to_win_pct)}</b><span>leads won (overall conversion)</span></div>
        <div className="tile ok"><b>{money(d.value.won)}</b><span>won · avg {money(d.value.average_won)}</span></div>
      </div>

      <div className="two-col">
        <section className="card">
          <h2>Lead → quote → job</h2>
          <Funnel d={d} />
          <p className="small muted">
            Of {d.leads} leads, {d.quotes_sent} had a quote sent and {d.won} were won ({d.lost} lost; the rest are still open).
            Of quotes decided in this period, {pct(d.conversion.win_rate_decided_pct)} were won. Quoted value {money(d.value.quoted)}.
          </p>
        </section>
        <section className="card">
          <h2>Time to convert</h2>
          <div className="time-grid">
            <div><b>{days(d.days.lead_to_quote)}</b><span>lead → quote returned</span><small>middle {d.days.lead_to_quote.median ?? "–"} · {d.days.lead_to_quote.count} jobs</small></div>
            <div><b>{days(d.days.quote_to_win)}</b><span>quote → won</span><small>middle {d.days.quote_to_win.median ?? "–"} · {d.days.quote_to_win.count} jobs</small></div>
            <div><b>{days(d.days.lead_to_win)}</b><span>lead → won (total)</span><small>middle {d.days.lead_to_win.median ?? "–"} · {d.days.lead_to_win.count} jobs</small></div>
            <div><b>{days(d.days.quote_to_loss)}</b><span>quote → lost</span><small>{d.days.quote_to_loss.count} jobs</small></div>
          </div>
        </section>
      </div>

      <section className="card">
        <h2>Pipeline now</h2>
        <div className="pipeline">
          {(["lead", "quoting", "quote_sent", "won", "lost"] as SalesStage[]).map((s) => (
            <div key={s} className={`pipe-col ${s}`}>
              <b>{STAGE_LABELS[s]}</b>
              <span className="big-n">{d.pipeline[s]?.count ?? 0}</span>
              <span className="small muted">{money(d.pipeline[s]?.value)}</span>
            </div>
          ))}
        </div>
      </section>

      <div className="two-col">
        <section className="card">
          <h2>Quotes waiting on an answer ({money(d.value.open_quotes)})</h2>
          <table>
            <thead><tr><th>Job</th><th>Client / contact</th><th>Value</th><th>Days out</th></tr></thead>
            <tbody>
              {d.open_quotes.map((q) => (
                <tr key={q.job_id} className={(q.days ?? 0) > 14 ? "warn-row" : ""}>
                  <td><Link to={`/jobs/${q.job_id}`}>{q.name}</Link> <span className="small muted">{q.quote_no}</span></td>
                  <td className="small">{[q.client, q.contact].filter(Boolean).join(" · ")}</td><td>{q.value ? money(q.value) : ""}</td>
                  <td><b>{q.days}</b></td>
                </tr>
              ))}
              {d.open_quotes.length === 0 && <tr><td colSpan={4} className="muted">None.</td></tr>}
            </tbody>
          </table>
          <p className="small muted">Highlighted: out more than two weeks; time to follow up.</p>
        </section>
        <section className="card">
          <h2>Leads still to quote</h2>
          <table>
            <thead><tr><th>Job</th><th>Stage</th><th>Due</th><th>Days since lead</th></tr></thead>
            <tbody>
              {d.to_quote.map((q) => (
                <tr key={q.job_id} className={q.overdue ? "warn-row" : ""}>
                  <td><Link to={`/jobs/${q.job_id}`}>{q.name}</Link> <span className="small muted">{q.estimator}</span></td>
                  <td>{STAGE_LABELS[q.stage]}</td>
                  <td>{q.due_date ? new Date(q.due_date + "T00:00:00").toLocaleDateString("en-AU") : ""}{q.overdue ? " (overdue)" : ""}</td>
                  <td>{q.days}</td>
                </tr>
              ))}
              {d.to_quote.length === 0 && <tr><td colSpan={4} className="muted">None.</td></tr>}
            </tbody>
          </table>
        </section>
      </div>

      <section className="card">
        <h2>Month by month</h2>
        <table className="num">
          <thead><tr><th>Month</th><th>Leads</th><th></th><th>Quotes sent</th><th>Won</th><th>Lost</th><th>Won value</th></tr></thead>
          <tbody>
            {d.monthly.map((m) => (
              <tr key={m.month}><td>{monthLabel(m.month)}</td><td>{m.leads}</td><td style={{ width: 160 }}><MiniBar value={m.leads} max={maxMonth} /></td>
                <td>{m.quotes_sent}</td><td>{m.won}</td><td>{m.lost}</td><td>{money(m.won_value)}</td></tr>
            ))}
          </tbody>
        </table>
      </section>

      {sector === "" && <GroupTable title="By sector" rows={d.by_sector} />}
      <GroupTable title="By lead source" rows={d.by_source} />
      <GroupTable title="By estimator" rows={d.by_estimator} />
    </main>
  );
}
