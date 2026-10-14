import { FormEvent, Fragment, useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, download } from "../api";
import type { CivilBoq, CivilLine, Sheet } from "../types";

const money = (n: number | null | undefined) =>
  n === null || n === undefined ? "" : n.toLocaleString("en-AU", { style: "currency", currency: "AUD" });
const pastJobs = (l: CivilLine) => {
  const n = new Set(l.rate_sources.map((r) => r.job)).size;
  return `from ${n} past job${n === 1 ? "" : "s"}`;
};
const qtyFmt = (n: number) => n.toLocaleString("en-AU", { maximumFractionDigits: 3 });

function NumberCell({ value, placeholder, onSave, disabled }: {
  value: number | null; placeholder?: string; onSave: (v: number | null) => void; disabled?: boolean;
}) {
  const [text, setText] = useState(value === null ? "" : String(value));
  useEffect(() => setText(value === null ? "" : String(value)), [value]);
  const commit = () => {
    const v = text.trim() === "" ? null : Number(text);
    if (v !== null && Number.isNaN(v)) { setText(value === null ? "" : String(value)); return; }
    if (v !== value) onSave(v);
  };
  return (
    <input className="cell num" value={text} placeholder={placeholder} disabled={disabled} inputMode="decimal"
           onChange={(e) => setText(e.target.value)} onBlur={commit}
           onKeyDown={(e) => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }} />
  );
}

export default function CivilBoqView({ jobId, final, sheets }: { jobId: number; final: boolean; sheets: Sheet[] }) {
  const [boq, setBoq] = useState<CivilBoq | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [msg, setMsg] = useState("");
  const [adding, setAdding] = useState({ description: "", unit: "m", qty: "", rate: "", category: "Other" });

  const load = useCallback(() => api.get<CivilBoq>(`/api/jobs/${jobId}/civil/boq`).then(setBoq).catch((e) => setError(e.message)), [jobId]);
  useEffect(() => { load(); }, [load]);

  const patch = async (l: CivilLine, body: Record<string, unknown>) => {
    setError("");
    try { await api.patch(`/api/civil/lines/${l.id}`, body); await load(); }
    catch (e) { setError((e as Error).message); }
  };
  const remove = async (l: CivilLine) => {
    if (!window.confirm(`Delete "${l.description}"?`)) return;
    await api.del(`/api/civil/lines/${l.id}`);
    load();
  };
  const approveAll = async () => {
    setError(""); setMsg("");
    try {
      const r = await api.post<{ approved: number; skipped_need_measuring: number }>(`/api/jobs/${jobId}/civil/approve-all`);
      setMsg(`Approved ${r.approved} line(s).${r.skipped_need_measuring ? ` ${r.skipped_need_measuring} still need a quantity: type it in, then tick them.` : ""}`);
      load();
    } catch (e) { setError((e as Error).message); }
  };
  const reprice = async () => {
    const r = await api.post<{ priced: number }>(`/api/jobs/${jobId}/civil/reprice`);
    setMsg(`Looked up rates again: ${r.priced} line(s) priced from previous jobs.`);
    load();
  };
  const add = async (e: FormEvent) => {
    e.preventDefault();
    await api.post(`/api/jobs/${jobId}/civil/lines`, {
      ...adding, qty: Number(adding.qty || 0), rate: adding.rate === "" ? null : Number(adding.rate),
    });
    setAdding({ ...adding, description: "", qty: "", rate: "" });
    load();
  };

  if (!boq) return <p>{error || "Loading…"}</p>;
  const s = boq.summary;
  const sheetById = Object.fromEntries(sheets.map((x) => [x.id, x]));
  const groups = [...new Set(boq.lines.map((l) => l.category))];

  return (
    <>
      <div className="tiles">
        <div className="tile"><b>{s.lines}</b><span>BOQ lines found</span></div>
        <div className={`tile ${s.lines_suggested ? "warn" : "ok"}`}><b>{s.lines_suggested}</b><span>waiting for your OK</span></div>
        <div className={`tile ${s.needs_measuring ? "warn" : ""}`}><b>{s.needs_measuring}</b><span>need a quantity</span></div>
        <div className={`tile ${s.unpriced ? "warn" : ""}`}><b>{s.unpriced}</b><span>without a past rate</span></div>
        <div className="tile ok"><b>{money(s.total_confirmed_ex_gst)}</b><span>approved total ex GST</span></div>
      </div>
      {error && <p className="error big">{error}</p>}
      {msg && <p className="ok big">{msg}</p>}

      <section className="card actions">
        <div className="big-actions">
          <button className="big primary" disabled={final || !s.lines_suggested} onClick={approveAll}>Approve all ({s.lines_suggested})</button>
          <button className="big" onClick={() => download(`/api/jobs/${jobId}/civil/boq.xlsx`, "Civil_BOQ.xlsx")}>Download Excel BOQ</button>
          <button className="big" disabled={final} onClick={reprice}>Look up rates again</button>
          <Link className="button big" to="/civil-rates">Previous job rates</Link>
        </div>
        <p className="muted small">
          Yellow lines are the AI's suggestions and aren't in the total until ticked. Click a line to see which sheet each
          quantity came from. Type over any quantity or rate to change it.
        </p>
      </section>

      <section className="card">
        <table className="boq">
          <thead>
            <tr><th>OK</th><th>Description</th><th>Unit</th><th className="r">Qty</th><th className="r">Rate</th><th className="r">Amount</th><th>Sheets</th><th></th></tr>
          </thead>
          <tbody>
            {groups.map((cat) => (
              <Fragment key={cat}>
                <tr className="cat"><td colSpan={8}>{cat}</td></tr>
                {boq.lines.filter((l) => l.category === cat).map((l) => (
                  <Fragment key={l.id}>
                    <tr className={`${l.status} ${l.needs_measuring && !l.overridden_qty ? "measure" : ""}`}>
                      <td>
                        <input type="checkbox" checked={l.status === "confirmed"} disabled={final}
                               title={l.status === "confirmed" ? "Approved" : "Approve this line"}
                               onChange={(e) => patch(l, { status: e.target.checked ? "confirmed" : "suggested" })} />
                      </td>
                      <td onClick={() => setOpen(open === l.id ? null : l.id)} className="desc">
                        {l.description}
                        {l.needs_measuring && !l.overridden_qty && <span className="tag warn">needs a quantity</span>}
                        {l.note && <div className="small warn">{l.note}</div>}
                      </td>
                      <td>
                        <select value={l.unit} disabled={final} onChange={(e) => patch(l, { unit: e.target.value })}>
                          {[...new Set([...boq.units, l.unit])].map((u) => <option key={u}>{u}</option>)}
                        </select>
                      </td>
                      <td className="r">
                        <NumberCell value={l.overridden_qty ?? l.qty} disabled={final}
                                    onSave={(v) => patch(l, v === null ? { clear_qty_override: true } : { overridden_qty: v })} />
                        {l.overridden_qty !== null && <div className="small muted">read {qtyFmt(l.qty)}</div>}
                      </td>
                      <td className="r">
                        <NumberCell value={l.rate} placeholder="enter rate" disabled={final}
                                    onSave={(v) => patch(l, v === null ? { clear_rate: true } : { rate: v })} />
                        <div className="small muted" title={l.rate_sources.map((r) => `${r.job}: ${r.description} @ ${money(r.rate)}/${r.unit}`).join("\n")}>
                          {l.rate_overridden ? "typed in" : l.rate_sources.length ? pastJobs(l) : l.rate_note}
                        </div>
                      </td>
                      <td className="r">{money(l.amount)}</td>
                      <td className="small">
                        {[...new Set(l.items.map((i) => i.sheet_id))].map((sid) => sid && sheetById[sid] ? (
                          <Link key={sid} to={`/sheets/${sid}`} className="chip">{sheetById[sid].sheet_no || `p${sheetById[sid].page_no}`}</Link>
                        ) : null)}
                      </td>
                      <td><button className="link danger" disabled={final} onClick={() => remove(l)}>✕</button></td>
                    </tr>
                    {open === l.id && (
                      <tr className="detail">
                        <td></td>
                        <td colSpan={7}>
                          <b>Where this came from</b>
                          {l.items.length === 0 && <p className="muted small">Added by hand.</p>}
                          <ul className="small">
                            {l.items.map((i) => (
                              <li key={i.id}>
                                <b>{i.sheet || "—"}</b>: {i.description}: {qtyFmt(i.qty)} {i.unit}
                                <span className="muted"> ({i.basis}; AI confidence {Math.round(i.confidence * 100)}%)</span>
                              </li>
                            ))}
                          </ul>
                          {l.items.length > 1 && <p className="small muted">{l.combine === "max" ? "Same work shown on several sheets: counted once." : "Separate parts added together."}</p>}
                          {l.rate_sources.length > 0 && (
                            <>
                              <b>Rate from previous jobs</b> <span className="small muted">({l.rate_note}; the middle value is used)</span>
                              <ul className="small">
                                {l.rate_sources.map((r) => <li key={r.rate_id}>{r.job}: {r.description}: {money(r.rate)}/{r.unit}</li>)}
                              </ul>
                            </>
                          )}
                          {l.rate_overridden && !final && <button className="link" onClick={() => patch(l, { clear_rate: true })}>Use the rate from previous jobs instead</button>}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </Fragment>
            ))}
            {boq.lines.length === 0 && <tr><td colSpan={8} className="muted">No quantities yet.</td></tr>}
            <tr className="total"><td></td><td colSpan={4}>Approved total (ex GST)</td><td className="r">{money(s.total_confirmed_ex_gst)}</td><td colSpan={2}></td></tr>
          </tbody>
        </table>

        {!final && (
          <form className="row wrap add-line" onSubmit={add}>
            <b>Add a line:</b>
            <select value={adding.category} onChange={(e) => setAdding({ ...adding, category: e.target.value })}>
              {boq.categories.map((c) => <option key={c}>{c}</option>)}
            </select>
            <input required placeholder="Description" value={adding.description} style={{ minWidth: 260 }}
                   onChange={(e) => setAdding({ ...adding, description: e.target.value })} />
            <select value={adding.unit} onChange={(e) => setAdding({ ...adding, unit: e.target.value })}>
              {boq.units.map((u) => <option key={u}>{u}</option>)}
            </select>
            <input className="tiny" placeholder="Qty" inputMode="decimal" value={adding.qty} onChange={(e) => setAdding({ ...adding, qty: e.target.value })} />
            <input className="tiny" placeholder="Rate" inputMode="decimal" value={adding.rate} onChange={(e) => setAdding({ ...adding, rate: e.target.value })} />
            <button type="submit">Add</button>
            <span className="small muted">Leave the rate blank to look it up from previous jobs.</span>
          </form>
        )}
      </section>
    </>
  );
}
