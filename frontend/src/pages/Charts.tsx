/* Small inline-SVG charts for the reports. Colours: the validated categorical order (blue, orange, aqua),
   always in this order; text stays in text colours; 2px surface gaps between stacked segments;
   recessive 1px gridlines; one y-axis per chart; a legend for every multi-series chart. */
import { useState } from "react";

export const SERIES = ["#ff6a13", "#2b2b2b", "#ffb27a"];
const GRID = "#e7e2dd";
const INK = "#161616";
const MUTED = "#6f6a66";

const fmtDate = (iso: string) => new Date(iso + "T00:00:00").toLocaleDateString("en-AU", { day: "numeric", month: "short" });

function Legend({ items }: { items: { label: string; colour: string; dash?: boolean }[] }) {
  return (
    <div className="legend">
      {items.map((i) => (
        <span key={i.label}>
          <svg width="18" height="10" aria-hidden>
            {i.dash ? <line x1="0" y1="5" x2="18" y2="5" stroke={i.colour} strokeWidth="2" />
              : <rect x="0" y="1" width="18" height="8" rx="2" fill={i.colour} />}
          </svg> {i.label}
        </span>
      ))}
    </div>
  );
}

function niceMax(v: number): number {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (v <= m * p) return m * p;
  return 10 * p;
}

/** Stage bars over time. */
export function Gantt({ stages }: { stages: { stage: string; start: string; end: string; plumbers: number; apprentices: number; workdays: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!stages.length) return null;
  const t = (iso: string) => new Date(iso + "T00:00:00").getTime();
  const t0 = Math.min(...stages.map((s) => t(s.start)));
  const t1 = Math.max(...stages.map((s) => t(s.end))) + 86400000;
  const W = 760, left = 150, right = 16, rowH = 30, top = 24;
  const H = top + stages.length * rowH + 8;
  const x = (ms: number) => left + ((ms - t0) / (t1 - t0)) * (W - left - right);
  const weeks: number[] = [];
  const first = new Date(t0);
  first.setDate(first.getDate() - ((first.getDay() + 6) % 7));
  for (let d = first.getTime(); d <= t1; d += 7 * 86400000) if (d >= t0) weeks.push(d);
  const step = Math.max(1, Math.ceil(weeks.length / 10));
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Program by stage">
      {weeks.map((w, i) => (
        <g key={w}>
          <line x1={x(w)} x2={x(w)} y1={top - 6} y2={H - 8} stroke={GRID} strokeWidth="1" />
          {i % step === 0 && <text x={x(w) + 3} y={top - 10} fontSize="11" fill={MUTED}>{fmtDate(new Date(w).toISOString().slice(0, 10))}</text>}
        </g>
      ))}
      {stages.map((s, i) => {
        const y = top + i * rowH;
        const x0 = x(t(s.start)), x1 = Math.max(x(t(s.end) + 86400000), x0 + 4);
        return (
          <g key={s.stage} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
            <rect x={0} y={y} width={W} height={rowH} fill="transparent" />
            <text x={0} y={y + rowH / 2 + 4} fontSize="12" fill={INK}>{s.stage}</text>
            <rect x={x0} y={y + 7} width={x1 - x0} height={rowH - 14} rx="4" fill={SERIES[0]} opacity={hover === null || hover === i ? 1 : 0.6} />
            <title>{`${s.stage}: ${fmtDate(s.start)} to ${fmtDate(s.end)}, ${s.workdays} working days, ${s.plumbers} plumbers + ${s.apprentices} apprentices`}</title>
          </g>
        );
      })}
    </svg>
  );
}

/** Stacked bars by week (people on site), with an optional "people available" reference line on the same axis. */
export function StackedWeeks({ weeks, available }: {
  weeks: { week: string; plumbers: number; apprentices: number; supervisors: number }[];
  available?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  if (!weeks.length) return null;
  const roles = [["plumbers", "Plumbers"], ["apprentices", "Apprentices"], ["supervisors", "Supervisors"]] as const;
  const W = 760, H = 220, left = 34, right = 10, top = 10, bottom = 26;
  const totals = weeks.map((w) => w.plumbers + w.apprentices + w.supervisors);
  const max = niceMax(Math.max(...totals, available ?? 0));
  const bw = (W - left - right) / weeks.length;
  const y = (v: number) => top + (1 - v / max) * (H - top - bottom);
  const ticks = [...new Set([0, Math.round(max / 2), max])];  // whole people only
  const step = Math.max(1, Math.ceil(weeks.length / 12));
  return (
    <>
      <Legend items={[...roles.map(([, l], i) => ({ label: l, colour: SERIES[i] })), ...(available ? [{ label: "Your people", colour: MUTED, dash: true }] : [])]} />
      <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="People on site each week">
        {ticks.map((v) => (
          <g key={v}>
            <line x1={left} x2={W - right} y1={y(v)} y2={y(v)} stroke={GRID} strokeWidth="1" />
            <text x={left - 6} y={y(v) + 4} fontSize="11" fill={MUTED} textAnchor="end">{Math.round(v)}</text>
          </g>
        ))}
        {weeks.map((w, i) => {
          let base = 0;
          const x0 = left + i * bw + Math.min(2, bw * 0.15);
          const width = Math.max(1, bw - Math.min(4, bw * 0.3));
          return (
            <g key={w.week} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} opacity={hover === null || hover === i ? 1 : 0.55}>
              <rect x={left + i * bw} y={top} width={bw} height={H - top - bottom} fill="transparent" />
              {roles.map(([k], ri) => {
                const v = w[k];
                if (!v) return null;
                const yTop = y(base + v), yBot = y(base);
                base += v;
                const gap = base - v > 0 ? 2 : 0;
                return <rect key={k} x={x0} y={yTop} width={width} height={Math.max(0, yBot - yTop - gap)} rx="2" fill={SERIES[ri]} />;
              })}
              {i % step === 0 && <text x={left + i * bw + bw / 2} y={H - 8} fontSize="10" fill={MUTED} textAnchor="middle">{fmtDate(w.week)}</text>}
              <title>{`Week of ${fmtDate(w.week)}: ${w.plumbers} plumbers, ${w.apprentices} apprentices, ${w.supervisors} supervisors`}</title>
            </g>
          );
        })}
        {available ? (
          <g>
            <line x1={left} x2={W - right} y1={y(available)} y2={y(available)} stroke={MUTED} strokeWidth="2" />
            <text x={W - right} y={y(available) - 4} fontSize="11" fill={MUTED} textAnchor="end">your people: {available}</text>
          </g>
        ) : null}
      </svg>
    </>
  );
}

/** Value earned per month. */
export function MonthBars({ months }: { months: { month: string; value: number; cumulative: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!months.length) return null;
  const W = 760, H = 200, left = 64, right = 10, top = 10, bottom = 24;
  const max = niceMax(Math.max(...months.map((m) => m.value)));
  const bw = (W - left - right) / months.length;
  const y = (v: number) => top + (1 - v / max) * (H - top - bottom);
  const money = (v: number) => v.toLocaleString("en-AU", { style: "currency", currency: "AUD", maximumFractionDigits: 0 });
  const label = (m: string) => new Date(m + "-01T00:00:00").toLocaleDateString("en-AU", { month: "short", year: "2-digit" });
  return (
    <svg className="chart" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Value earned each month">
      {[0, max / 2, max].map((v) => (
        <g key={v}>
          <line x1={left} x2={W - right} y1={y(v)} y2={y(v)} stroke={GRID} strokeWidth="1" />
          <text x={left - 6} y={y(v) + 4} fontSize="11" fill={MUTED} textAnchor="end">{money(v)}</text>
        </g>
      ))}
      {months.map((m, i) => (
        <g key={m.month} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
          <rect x={left + i * bw + 4} y={y(m.value)} width={Math.max(2, bw - 8)} height={y(0) - y(m.value)} rx="4"
                fill={SERIES[0]} opacity={hover === null || hover === i ? 1 : 0.55} />
          <text x={left + i * bw + bw / 2} y={H - 7} fontSize="10" fill={MUTED} textAnchor="middle">{label(m.month)}</text>
          <title>{`${label(m.month)}: ${money(m.value)} (running total ${money(m.cumulative)})`}</title>
        </g>
      ))}
    </svg>
  );
}
