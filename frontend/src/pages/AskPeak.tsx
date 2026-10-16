/* Ask lorojo (code name AskPeak): talk or type to the company assistant from any page; answers come with reports. And the notification bell. */
import { FormEvent, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, download } from "../api";
import { speak, useLoad, useMic } from "../ui";
import { SERIES } from "./Charts";

export interface Report { title: string; summary: string; columns: string[]; rows: (string | number | null)[][]; chart?: { type: "bar" | "line"; x: string; y: string[] } | null }
interface Msg { id: number; role: "user" | "assistant"; text: string; reports: Report[] }

const STARTERS = [
  "How many labour hours on the Maroochydore Apartments job, actual vs estimated?",
  "Which jobs are going over budget?",
  "Are we on track this month for labour and materials?",
  "Who's working right now?",
  "Which supplier is cheapest for PVC fittings?",
  "What's our NPS by department this quarter?",
];

const fmtCell = (v: string | number | null) => (typeof v === "number" ? v.toLocaleString("en-AU", { maximumFractionDigits: 2 }) : v ?? "");

export function ReportChart({ r }: { r: Report }) {
  if (!r.chart) return null;
  const xi = r.columns.indexOf(r.chart.x);
  const ys = r.chart.y.slice(0, 3).map((y) => r.columns.indexOf(y)).filter((i) => i >= 0);
  const rows = r.rows.slice(0, 40);
  if (xi < 0 || !ys.length || !rows.length) return null;
  const vals = rows.flatMap((row) => ys.map((i) => Number(row[i]) || 0));
  const max = Math.max(1, ...vals), min = Math.min(0, ...vals);
  const W = 640, H = 220, L = 48, B = 34, T = 10;
  const x = (i: number) => L + (i + 0.5) * ((W - L - 8) / rows.length);
  const y = (v: number) => T + (1 - (v - min) / (max - min)) * (H - T - B);
  const bw = Math.min(28, ((W - L - 8) / rows.length) * 0.8 / ys.length);
  return (
    <figure className="report-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={r.title}>
        {[0, 0.5, 1].map((f) => { const v = min + (max - min) * f; return (
          <g key={f}><line x1={L} x2={W - 8} y1={y(v)} y2={y(v)} stroke="#e7e2dd" /><text x={L - 6} y={y(v) + 4} fontSize="11" textAnchor="end" fill="#6f6a66">{fmtCell(Math.round(v))}</text></g>); })}
        {r.chart.type === "bar" ? rows.map((row, i) => ys.map((yi, k) => {
          const v = Number(row[yi]) || 0;
          return <rect key={`${i}-${k}`} x={x(i) - (bw * ys.length) / 2 + k * bw} y={Math.min(y(v), y(0))} width={bw - 2} height={Math.abs(y(v) - y(0))} rx="2" fill={SERIES[k]}>
            <title>{`${row[xi]}: ${r.columns[yi]} ${fmtCell(v)}`}</title></rect>;
        })) : ys.map((yi, k) => (
          <polyline key={k} fill="none" stroke={SERIES[k]} strokeWidth="2" points={rows.map((row, i) => `${x(i)},${y(Number(row[yi]) || 0)}`).join(" ")} />
        ))}
        {rows.map((row, i) => (rows.length <= 12 || i % Math.ceil(rows.length / 12) === 0) &&
          <text key={i} x={x(i)} y={H - 14} fontSize="11" textAnchor="middle" fill="#161616">{String(row[xi]).slice(0, 14)}</text>)}
      </svg>
      {ys.length > 1 && <figcaption className="legend">{ys.map((yi, k) => <span key={yi}><i style={{ background: SERIES[k] }} /> {r.columns[yi]}</span>)}</figcaption>}
    </figure>
  );
}

export function ReportView({ r, onDownload }: { r: Report; onDownload?: () => void }) {
  return (
    <div className="report">
      <div className="row"><b>{r.title}</b><span className="spacer" />{onDownload && <button className="link small" onClick={onDownload}>Download Excel</button>}</div>
      {r.summary && <p className="small muted">{r.summary}</p>}
      <ReportChart r={r} />
      <div className="dt-wrap">
        <table className="dt compact">
          <thead><tr>{r.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>{r.rows.map((row, i) => <tr key={i}>{row.map((v, j) => <td key={j} className={typeof v === "number" ? "n" : ""}>{fmtCell(v)}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}

export function AskPeakButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="ask-btn" onClick={() => setOpen(true)} title="Ask lorojo anything about jobs, hours, money, plant or customers">
        <span aria-hidden>✦</span> <span className="ask-label">Ask lorojo…</span>
      </button>
      {open && <AskPeak onClose={() => setOpen(false)} />}
    </>
  );
}

function AskPeak({ onClose }: { onClose: () => void }) {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [voice, setVoice] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { api.get<{ messages: Msg[] }>("/api/assistant").then((r) => setMsgs(r.messages)).catch(() => {}); input.current?.focus(); }, []);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [msgs, busy]);
  const send = async (t: string) => {
    const q = t.trim();
    if (!q || busy) return;
    setText(""); setError(""); setBusy(true);
    setMsgs((m) => [...m, { id: -Date.now(), role: "user", text: q, reports: [] }]);
    try {
      const r = await api.post<{ messages: Msg[] }>("/api/assistant", { text: q });
      setMsgs((m) => [...m.filter((x) => x.id > 0), ...r.messages]);
      const last = r.messages.filter((x) => x.role === "assistant").pop();
      if (voice && last) speak(last.text);
    } catch (e) { setError((e as Error).message); setMsgs((m) => m.filter((x) => x.id > 0 || x.text !== q)); setText(q); }
    finally { setBusy(false); }
  };
  const mic = useMic((heard) => { setVoice(true); send(heard); }, setText);
  const submit = (e: FormEvent) => { e.preventDefault(); send(text); };
  return (
    <div className="ask-back" onClick={onClose}>
      <aside className="ask-panel" onClick={(e) => e.stopPropagation()} aria-label="Ask lorojo">
        <div className="row">
          <h2 style={{ margin: 0 }}>✦ Ask lorojo</h2><span className="spacer" />
          <button className="link small" onClick={async () => { await api.post("/api/assistant/new"); setMsgs([]); }}>New conversation</button>
          <button className="link" onClick={onClose} aria-label="Close">✕</button>
        </div>
        <div className="ask-msgs">
          {msgs.length === 0 && (
            <div className="starters">
              <p className="muted small">Ask about any job, hours, costs, the schedule, plant, suppliers or customers. It looks it up and makes the report.</p>
              {STARTERS.map((s) => <button key={s} className="starter" onClick={() => send(s)}>{s}</button>)}
            </div>
          )}
          {msgs.map((m) => (
            <div key={m.id} className={`bubble ${m.role}`}>
              {m.text && <p>{m.text}</p>}
              {m.reports.map((r, i) => <ReportView key={i} r={r} onDownload={() => download(`/api/assistant/reports/${m.id}/${i}.xlsx`, "report.xlsx")} />)}
            </div>
          ))}
          {busy && <div className="bubble assistant thinking">Looking it up…</div>}
          <div ref={end} />
        </div>
        {error && <p className="error small">{error}</p>}
        <form className="ask-input" onSubmit={submit}>
          <textarea ref={input} rows={2} value={text} placeholder={mic.listening ? "Listening…" : "Ask anything, or press the microphone"}
                    onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(text); } }} />
          {mic.supported && <button type="button" className={`mic ${mic.listening ? "on" : ""}`} onClick={mic.listening ? mic.stop : mic.start} aria-label="Talk">🎤</button>}
          <button className="primary" disabled={busy || !text.trim()}>Ask</button>
        </form>
      </aside>
    </div>
  );
}

interface Note { id: number; kind: string; text: string; link: string; at: string; read: boolean }

export function Bell() {
  const { data, reload } = useLoad<Note[]>("/api/notifications");
  const [open, setOpen] = useState(false);
  useEffect(() => { const t = setInterval(reload, 60000); return () => clearInterval(t); }, [reload]);
  const unread = data?.filter((n) => !n.read).length ?? 0;
  return (
    <div className="bell">
      <button className="link" onClick={() => setOpen(!open)} aria-label={`${unread} new notifications`}>🔔{unread > 0 && <span className="dot">{unread}</span>}</button>
      {open && (
        <div className="bell-menu" onClick={() => setOpen(false)}>
          <div className="row"><b>Notifications</b><span className="spacer" />
            {unread > 0 && <button className="link small" onClick={async (e) => { e.stopPropagation(); await api.post("/api/notifications/read-all"); reload(); }}>Mark all read</button>}</div>
          {(data ?? []).length === 0 && <p className="muted small">Nothing yet.</p>}
          {data?.map((n) => <Link key={n.id} to={n.link || "#"} className={`note ${n.read ? "" : "unread"}`}>{n.text}<small>{new Date(n.at).toLocaleString("en-AU")}</small></Link>)}
        </div>
      )}
    </div>
  );
}
