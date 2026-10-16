/* Estimating workbook (the CostX / CANDY side): workbook rows with variables and quantities linked live to the take-off,
   rates from resources and build-ups; subcontract quotes levelled and awarded; estimate versions compared; the tender
   programme spread into a cash flow. Plus the rate library (resources and build-ups). */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, fetchBlobUrl, upload } from "../api";
import { useApp } from "../App";
import { DataTable, ErrorLine, Field, fmtDate, Modal, money, num, Status, Tabs, useAction, useLoad } from "../ui";

interface Unit { labour: number; material: number; plant: number; subcontract: number }
interface WLine { id: number; section: string; position: number; ref: string; description: string; qty_source: string; formula: string; dimension: string; qty: number;
  uom: string; rate_source: string; rate_code: string; labour_hours_unit: number; labour_rate: number; unit: Unit; unit_total: number; labour_hours: number;
  material_cost: number; labour_cost: number; plant_cost: number; subcontract_cost: number; cost: number; margin_pct: number; margin_override: boolean; sell: number;
  service_id: number | null; stage_id: number | null; stage: string; package_id: number | null; note: string; error: string;
  material: number; plant: number; subcontract: number; labour_hours_typed: number }
interface WB { variables: { id: number; name: string; value: number; note: string }[]; sections: { name: string; lines: WLine[]; cost: number; sell: number; labour_hours: number }[];
  totals: { material_cost: number; labour_cost: number; plant_cost: number; subcontract_cost: number; cost: number; sell: number; labour_hours: number }; errors: number }
interface Dim { key: string; label: string; qty: number; uom: string }
interface Resource { id: number; code: string; kind: string; description: string; unit: string; rate: number; supplier: string; used_in: number }
interface Buildup { id: number; code: string; description: string; unit: string; lines: { resource: string; qty: number; waste_pct: number }[]; notes: string;
  rate: { total: number; labour: number; material: number; plant: number; subcontract: number; labour_hours: number; missing: string[];
    lines: { resource: string; description: string; kind: string; unit: string; qty: number; rate: number; amount: number }[] } }

type WTab = "rows" | "packages" | "versions" | "cashflow";
export function EstimatingTab({ jobId, locked }: { jobId: number; locked: boolean }) {
  const [tab, setTab] = useState<WTab>("rows");
  return (
    <>
      <Tabs<WTab> value={tab} onChange={setTab} tabs={[["rows", "Workbook"], ["packages", "Subcontract & supply quotes"], ["versions", "Versions"], ["cashflow", "Programme & cash flow"]]} />
      {tab === "rows" && <WorkbookRows jobId={jobId} locked={locked} />}
      {tab === "packages" && <Packages jobId={jobId} locked={locked} />}
      {tab === "versions" && <Versions jobId={jobId} />}
      {tab === "cashflow" && <Cashflow jobId={jobId} />}
    </>
  );
}

const QTY_LABEL: Record<string, string> = { manual: "Typed", formula: "Formula", takeoff: "From take-off" };

function WorkbookRows({ jobId, locked }: { jobId: number; locked: boolean }) {
  const { data: wb, reload } = useLoad<WB>(`/api/jobs/${jobId}/workbook`);
  const { data: dims } = useLoad<Dim[]>(`/api/jobs/${jobId}/dimensions`);
  const [edit, setEdit] = useState<WLine | "new" | null>(null);
  const [vars, setVars] = useState<{ name: string; value: number; note: string }[] | null>(null);
  const [copying, setCopying] = useState(false);
  const [run, err] = useAction();
  if (!wb) return <p className="muted">Loading…</p>;
  const v = vars ?? wb.variables;
  return (
    <>
      <div className="two-col">
        <div>
          {wb.errors > 0 && <p className="bad">{wb.errors} row{wb.errors > 1 ? "s" : ""} can't be priced (see the red notes). They block sign-off.</p>}
          {wb.sections.map((s) => (
            <section key={s.name} className="card">
              <div className="row"><h2 style={{ margin: 0 }}>{s.name}</h2><span className="spacer" /><span className="small">{num(s.labour_hours, 1)} h · cost {money(s.cost)} · <b>sell {money(s.sell)}</b></span></div>
              <div className="dt-wrap">
                <table className="dt wb">
                  <thead><tr><th>Ref</th><th>Description</th><th className="n">Qty</th><th>Unit</th><th className="n">Rate</th><th className="n">Labour</th><th className="n">Materials</th>
                    <th className="n hide-sm">Plant</th><th className="n hide-sm">Subcon.</th><th className="n">Cost</th><th className="n">Margin</th><th className="n">Sell</th></tr></thead>
                  <tbody>{s.lines.map((l) => (
                    <tr key={l.id} className={locked ? "" : "click"} onClick={() => !locked && setEdit(l)}>
                      <td>{l.ref}</td>
                      <td>{l.description}{l.qty_source !== "manual" && <small className="muted"> · {l.qty_source === "takeoff" ? `🔗 ${dims?.find((d) => d.key === l.dimension)?.label ?? l.dimension}` : ""}{l.formula ? ` ƒ ${l.formula}` : ""}</small>}
                        {l.rate_source !== "manual" && <small className="muted"> · {l.rate_source} {l.rate_code}</small>}
                        {l.error && <div className="bad small">{l.error}</div>}{l.note && <div className="muted small">{l.note}</div>}</td>
                      <td className="n">{num(l.qty, 2)}</td><td>{l.uom}</td><td className="n">{money(l.unit_total, true)}</td>
                      <td className="n">{money(l.labour_cost)}</td><td className="n">{money(l.material_cost)}</td><td className="n hide-sm">{money(l.plant_cost)}</td>
                      <td className="n hide-sm">{money(l.subcontract_cost)}</td><td className="n">{money(l.cost)}</td>
                      <td className="n">{num(l.margin_pct, 1)}%{l.margin_override && "*"}</td><td className="n"><b>{money(l.sell)}</b></td>
                    </tr>))}</tbody>
                </table>
              </div>
            </section>
          ))}
          {wb.sections.length === 0 && <p className="muted">No workbook rows yet. Add preliminaries (supervision, site sheds, cranes), anything the take-off doesn't draw,
            or rows linked to take-off quantities and priced from build-ups. They price into this estimate with its margins.</p>}
          {!locked && <div className="row"><button className="primary" onClick={() => setEdit("new")}>+ Row</button><button onClick={() => setCopying(true)}>Copy rows from another job</button></div>}
          <ErrorLine error={err} />
        </div>
        <aside>
          <section className="card">
            <h2>Totals</h2>
            <div className="kv small">
              <span>Labour</span><b>{money(wb.totals.labour_cost)} ({num(wb.totals.labour_hours, 1)} h)</b><span>Materials</span><b>{money(wb.totals.material_cost)}</b>
              <span>Plant</span><b>{money(wb.totals.plant_cost)}</b><span>Subcontract</span><b>{money(wb.totals.subcontract_cost)}</b>
              <span>Cost</span><b>{money(wb.totals.cost)}</b><span>Sell</span><b>{money(wb.totals.sell)}</b>
            </div>
            <p className="small muted">Workbook only. The whole estimate (take-off + workbook + allowances) is on the Pricing tab.</p>
          </section>
          <section className="card">
            <h2>Variables</h2>
            <p className="small muted">Use them in formulas, e.g. <code>weeks * 38</code>. In a row linked to the take-off, <code>q</code> is the take-off quantity.</p>
            {v.map((x, i) => (
              <div key={i} className="row">
                <input value={x.name} disabled={locked} onChange={(e) => setVars(v.map((y, j) => (j === i ? { ...y, name: e.target.value } : y)))} style={{ width: 90 }} />
                <input type="number" step="any" disabled={locked} value={x.value} onChange={(e) => setVars(v.map((y, j) => (j === i ? { ...y, value: +e.target.value } : y)))} style={{ width: 80 }} />
                <input placeholder="note" disabled={locked} value={x.note} onChange={(e) => setVars(v.map((y, j) => (j === i ? { ...y, note: e.target.value } : y)))} style={{ flex: 1 }} />
                {!locked && <button className="link danger" onClick={() => setVars(v.filter((_, j) => j !== i))}>✕</button>}
              </div>
            ))}
            {!locked && <div className="row"><button className="link" onClick={() => setVars([...v, { name: "", value: 0, note: "" }])}>+ Variable</button><span className="spacer" />
              {vars && <button className="primary small" onClick={() => run(async () => { await api.put(`/api/jobs/${jobId}/workbook/variables`, vars); setVars(null); await reload(); })}>Save</button>}</div>}
          </section>
          <section className="card">
            <h2>Take-off quantities</h2>
            <p className="small muted">Link a row to any of these and it updates when the drawings are re-measured.</p>
            <div className="dim-list">{(dims ?? []).map((d) => <div key={d.key} className="small row"><span style={{ flex: 1 }}>{d.label}</span><b>{num(d.qty, 2)} {d.uom}</b></div>)}</div>
            {dims && dims.length === 0 && <p className="small muted">Nothing measured yet.</p>}
          </section>
        </aside>
      </div>
      {edit && <LineForm jobId={jobId} line={edit === "new" ? null : edit} dims={dims ?? []} sections={wb.sections.map((s) => s.name)} vars={wb.variables.map((x) => x.name)}
        onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
      {copying && <CopyModal jobId={jobId} onClose={() => setCopying(false)} onDone={() => { setCopying(false); reload(); }} />}
    </>
  );
}

function LineForm({ jobId, line, dims, sections, vars, onClose, onDone }: { jobId: number; line: WLine | null; dims: Dim[]; sections: string[]; vars: string[];
  onClose: () => void; onDone: () => void }) {
  const { settings } = useApp();
  const { data: res } = useLoad<Resource[]>("/api/resources");
  const { data: bus } = useLoad<Buildup[]>("/api/rate-buildups");
  const [f, setF] = useState({
    section: line?.section ?? (sections[0] || "Preliminaries"), ref: line?.ref ?? "", description: line?.description ?? "", qty_source: line?.qty_source ?? "manual",
    qty: line?.qty_source === "manual" ? line.qty : 0, formula: line?.formula ?? "", dimension: line?.dimension ?? "", uom: line?.uom ?? "item",
    rate_source: line?.rate_source ?? "manual", rate_code: line?.rate_code ?? "", labour_hours: line?.labour_hours_typed ?? 0, labour_rate: line?.labour_rate ?? 0,
    material: line?.material ?? 0, plant: line?.plant ?? 0, subcontract: line?.subcontract ?? 0, margin_pct: line?.margin_override ? String(line.margin_pct) : "",
    service_id: line?.service_id ? String(line.service_id) : "", stage_id: line?.stage_id ? String(line.stage_id) : "", note: line?.note ?? "" });
  const [run, err, busy] = useAction();
  const set = (k: string, v: unknown) => setF({ ...f, [k]: v });
  const save = () => run(async () => {
    const body = { ...f, margin_pct: f.margin_pct === "" ? null : +f.margin_pct, service_id: f.service_id ? +f.service_id : null, stage_id: f.stage_id ? +f.stage_id : null };
    if (line) await api.put(`/api/workbook/lines/${line.id}`, body); else await api.post(`/api/jobs/${jobId}/workbook/lines`, body);
    onDone();
  });
  return (
    <Modal title={line ? "Workbook row" : "New workbook row"} onClose={onClose} wide>
      <div className="form">
        <div className="row wrap">
          <Field label="Section"><input list="wb-sections" value={f.section} onChange={(e) => set("section", e.target.value)} />
            <datalist id="wb-sections">{[...new Set([...sections, "Preliminaries", "Subcontract", "Provisional"])].map((s) => <option key={s} value={s} />)}</datalist></Field>
          <Field label="Ref"><input value={f.ref} onChange={(e) => set("ref", e.target.value)} style={{ width: 80 }} /></Field>
          <Field label="Description"><input value={f.description} onChange={(e) => set("description", e.target.value)} style={{ minWidth: 280 }} /></Field>
        </div>
        <h3>Quantity</h3>
        <div className="chips">{Object.entries(QTY_LABEL).map(([k, l]) => <button key={k} className={`chip ${f.qty_source === k ? "on" : ""}`} onClick={() => set("qty_source", k)}>{l}</button>)}</div>
        <div className="row wrap">
          {f.qty_source === "manual" && <Field label="Quantity"><input type="number" step="any" value={f.qty} onChange={(e) => set("qty", +e.target.value)} /></Field>}
          {f.qty_source === "takeoff" && <Field label="Linked to"><select value={f.dimension} onChange={(e) => { const d = dims.find((x) => x.key === e.target.value);
            setF({ ...f, dimension: e.target.value, uom: d?.uom || f.uom }); }}><option value="">Pick a take-off quantity…</option>
            {dims.map((d) => <option key={d.key} value={d.key}>{d.label} ({num(d.qty, 2)} {d.uom})</option>)}</select></Field>}
          {f.qty_source !== "manual" && <Field label={f.qty_source === "takeoff" ? "Adjust (optional), e.g. q * 1.05" : "Formula"} hint={vars.length ? `Variables: ${vars.join(", ")}` : "Add variables beside the workbook"}>
            <input value={f.formula} onChange={(e) => set("formula", e.target.value)} placeholder={f.qty_source === "takeoff" ? "q" : "weeks * 38"} /></Field>}
          <Field label="Unit"><input value={f.uom} onChange={(e) => set("uom", e.target.value)} style={{ width: 80 }} /></Field>
        </div>
        <h3>Rate</h3>
        <div className="chips">{[["manual", "Typed"], ["buildup", "Build-up"], ["resource", "One resource"]].map(([k, l]) => <button key={k} className={`chip ${f.rate_source === k ? "on" : ""}`} onClick={() => set("rate_source", k)}>{l}</button>)}</div>
        {f.rate_source === "manual" && (
          <div className="row wrap">
            <Field label="Labour h / unit"><input type="number" step="any" value={f.labour_hours} onChange={(e) => set("labour_hours", +e.target.value)} /></Field>
            <Field label="Labour $/h"><input type="number" step="any" value={f.labour_rate} onChange={(e) => set("labour_rate", +e.target.value)} /></Field>
            <Field label="Materials $/unit"><input type="number" step="any" value={f.material} onChange={(e) => set("material", +e.target.value)} /></Field>
            <Field label="Plant $/unit"><input type="number" step="any" value={f.plant} onChange={(e) => set("plant", +e.target.value)} /></Field>
            <Field label="Subcontract $/unit"><input type="number" step="any" value={f.subcontract} onChange={(e) => set("subcontract", +e.target.value)} /></Field>
          </div>
        )}
        {f.rate_source === "buildup" && <Field label="Build-up"><select value={f.rate_code} onChange={(e) => set("rate_code", e.target.value)}><option value="">Pick…</option>
          {(bus ?? []).map((b) => <option key={b.code} value={b.code}>{b.code} – {b.description} ({money(b.rate.total, true)}/{b.unit})</option>)}</select></Field>}
        {f.rate_source === "resource" && <Field label="Resource"><select value={f.rate_code} onChange={(e) => set("rate_code", e.target.value)}><option value="">Pick…</option>
          {(res ?? []).map((r) => <option key={r.code} value={r.code}>{r.code} – {r.description} ({money(r.rate, true)}/{r.unit}, {r.kind})</option>)}</select></Field>}
        <div className="row wrap">
          <Field label="Service"><select value={f.service_id} onChange={(e) => set("service_id", e.target.value)}><option value="">–</option>{settings.services.map((s) => <option key={s.id} value={s.id}>{s.code} {s.name}</option>)}</select></Field>
          <Field label="Stage (budget and programme)"><select value={f.stage_id} onChange={(e) => set("stage_id", e.target.value)}><option value="">Unstaged</option>{settings.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
          <Field label="Margin % (blank = the job's)"><input type="number" step="any" value={f.margin_pct} onChange={(e) => set("margin_pct", e.target.value)} style={{ width: 90 }} /></Field>
        </div>
        <Field label="Note"><input value={f.note} onChange={(e) => set("note", e.target.value)} /></Field>
        <div className="row"><button className="primary" disabled={busy || !f.description} onClick={save}>Save</button><span className="spacer" />
          {line && <button className="danger" onClick={() => confirm("Delete this row?") && run(async () => { await api.del(`/api/workbook/lines/${line.id}`); onDone(); })}>Delete</button>}</div>
        <ErrorLine error={err} />
      </div>
    </Modal>
  );
}

function CopyModal({ jobId, onClose, onDone }: { jobId: number; onClose: () => void; onDone: () => void }) {
  const { data } = useLoad<{ id: number; name: string; quote_no: string; rows: number; sections: string[] }[]>("/api/workbook/sources");
  const [src, setSrc] = useState<number | null>(null);
  const [secs, setSecs] = useState<string[]>([]);
  const [run, err, busy] = useAction();
  const s = data?.find((x) => x.id === src);
  return (
    <Modal title="Copy rows from another job" onClose={onClose}>
      <select value={src ?? ""} onChange={(e) => { setSrc(+e.target.value || null); setSecs([]); }}><option value="">Pick a job…</option>
        {(data ?? []).filter((x) => x.id !== jobId).map((x) => <option key={x.id} value={x.id}>{x.quote_no} {x.name} ({x.rows} rows)</option>)}</select>
      {s && <div className="chips">{s.sections.map((x) => <button key={x} className={`chip ${secs.includes(x) ? "on" : ""}`} onClick={() => setSecs(secs.includes(x) ? secs.filter((y) => y !== x) : [...secs, x])}>{x}</button>)}</div>}
      <p className="small muted">Pick sections, or none for all. Variables come across too.</p>
      <button className="primary" disabled={!src || busy} onClick={() => run(async () => { await api.post(`/api/jobs/${jobId}/workbook/copy`, { from_job_id: src, sections: secs }); onDone(); })}>Copy</button>
      <ErrorLine error={err} />
    </Modal>
  );
}

/* --- packages --- */
interface Quote { id: number; company: string; email: string; supplier_id: number | null; status: string; amount: number | null; adjustments: { description: string; amount: number }[];
  levelled: number | null; exclusions: string; notes: string; valid_until: string | null; has_file: boolean; file_name: string; lowest: boolean; over_lowest: number | null;
  over_lowest_pct: number | null; awarded: boolean; invited_at: string | null }
interface Pkg { id: number; name: string; kind: string; scope: string; due: string | null; status: string; awarded_quote_id: number | null; section: string; stage_id: number | null;
  margin_pct: number | null; quotes: Quote[]; received: number; lowest: number | null; spread_pct: number | null }

function Packages({ jobId, locked }: { jobId: number; locked: boolean }) {
  const { data, reload } = useLoad<Pkg[]>(`/api/jobs/${jobId}/packages`);
  const { settings } = useApp();
  const [f, setF] = useState({ name: "", kind: "subcontract", scope: "", due: "", stage_id: "", margin_pct: "" });
  const [run, err, busy] = useAction();
  if (!data) return <p className="muted">Loading…</p>;
  return (
    <>
      {data.map((p) => <PackageCard key={p.id} p={p} locked={locked} reload={reload} />)}
      {!locked && (
        <section className="card">
          <h2>New package</h2>
          <div className="row wrap">
            <input placeholder="e.g. Concrete cutting, Excavation, Fire services, HWS supply" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} style={{ flex: 1 }} />
            <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}><option value="subcontract">Subcontract</option><option value="supply">Supply</option></select>
            <label className="inline small">Quotes due <input type="date" value={f.due} onChange={(e) => setF({ ...f, due: e.target.value })} /></label>
            <select value={f.stage_id} onChange={(e) => setF({ ...f, stage_id: e.target.value })}><option value="">Stage…</option>{settings.stages.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
            <input type="number" placeholder="Margin %" value={f.margin_pct} onChange={(e) => setF({ ...f, margin_pct: e.target.value })} style={{ width: 90 }} />
          </div>
          <textarea placeholder="Scope (goes in the request-for-quote email)" value={f.scope} onChange={(e) => setF({ ...f, scope: e.target.value })} />
          <button className="primary" disabled={busy || !f.name} onClick={() => run(async () => {
            await api.post(`/api/jobs/${jobId}/packages`, { ...f, due: f.due || null, stage_id: f.stage_id ? +f.stage_id : null, margin_pct: f.margin_pct === "" ? null : +f.margin_pct, section: f.kind === "supply" ? "Supply" : "Subcontract" });
            setF({ name: "", kind: "subcontract", scope: "", due: "", stage_id: "", margin_pct: "" }); await reload();
          })}>Add package</button>
          <ErrorLine error={err} />
        </section>
      )}
    </>
  );
}

function PackageCard({ p, locked, reload }: { p: Pkg; locked: boolean; reload: () => Promise<void> }) {
  const [add, setAdd] = useState({ company: "", email: "", amount: "" });
  const [levelling, setLevelling] = useState<Quote | null>(null);
  const [run, err, busy] = useAction();
  return (
    <section className="card">
      <div className="row wrap"><h2 style={{ margin: 0 }}>{p.name}</h2><span className="muted small">{p.kind}{p.due && ` · quotes due ${fmtDate(p.due)}`}</span>
        <Status value={p.status} /><span className="spacer" />
        {p.spread_pct !== null && <span className="small">Spread {num(p.spread_pct, 1)}%</span>}
        {!locked && <button className="small" onClick={() => run(async () => { const r = await api.post<{ sent: number }>(`/api/packages/${p.id}/invite`); alert(`${r.sent} request${r.sent === 1 ? "" : "s"} for quote queued to send.`); await reload(); })}>✉ Ask for quotes</button>}
        {!locked && <button className="link small danger" onClick={() => confirm(`Delete ${p.name}?`) && run(async () => { await api.del(`/api/packages/${p.id}`); await reload(); })}>Delete</button>}</div>
      {p.scope && <p className="small muted">{p.scope}</p>}
      <DataTable rows={p.quotes} empty="No firms yet." rowClass={(q) => (q.awarded ? "awarded" : q.lowest ? "lowest" : "")} cols={[
        { key: "c", label: "Firm", render: (q) => <><b>{q.company}</b>{q.email && <small className="muted"> {q.email}</small>}{q.invited_at && <small className="muted"> · asked {fmtDate(q.invited_at)}</small>}</> },
        { key: "s", label: "", render: (q) => <Status value={q.status} /> },
        { key: "a", label: "Their price", num: true, render: (q) => q.amount === null ? "–" : money(q.amount) },
        { key: "l", label: "Levelling", num: true, render: (q) => q.adjustments.length ? <span title={q.adjustments.map((a) => `${a.description}: ${money(a.amount)}`).join("\n")}>{money(q.adjustments.reduce((s, a) => s + a.amount, 0))}</span> : "" },
        { key: "lv", label: "Levelled", num: true, render: (q) => q.levelled === null ? "–" : <b>{money(q.levelled)}</b> },
        { key: "o", label: "vs lowest", num: true, render: (q) => q.lowest ? <span className="ok">Lowest</span> : q.over_lowest !== null ? `+${money(q.over_lowest)} (${num(q.over_lowest_pct, 1)}%)` : "" },
        { key: "x", label: "Excludes", render: (q) => <small>{q.exclusions}</small>, hideSm: true },
        { key: "f", label: "", render: (q) => q.has_file && <button className="link small" onClick={async () => window.open(await fetchBlobUrl(`/api/package-quotes/${q.id}/file`))}>📄</button> },
        { key: "act", label: "", render: (q) => !locked && <span className="row" style={{ margin: 0 }}>
          <button className="small" onClick={() => setLevelling(q)}>Enter / level</button>
          {q.levelled !== null && !q.awarded && <button className="small primary" onClick={() => run(async () => { await api.post(`/api/packages/${p.id}/award`, { quote_id: q.id }); await reload(); })}>Award</button>}
          {q.awarded && <span className="ok">✓ In the workbook</span>}</span> },
      ]} />
      {!locked && (
        <div className="row wrap">
          <input placeholder="Firm" value={add.company} onChange={(e) => setAdd({ ...add, company: e.target.value })} />
          <input placeholder="Email (to ask for a quote)" value={add.email} onChange={(e) => setAdd({ ...add, email: e.target.value })} />
          <input type="number" placeholder="Price (if you have it)" value={add.amount} onChange={(e) => setAdd({ ...add, amount: e.target.value })} style={{ width: 150 }} />
          <button disabled={!add.company || busy} onClick={() => run(async () => {
            await api.post(`/api/packages/${p.id}/quotes`, { company: add.company, email: add.email, amount: add.amount === "" ? null : +add.amount }); setAdd({ company: "", email: "", amount: "" }); await reload();
          })}>+ Firm</button>
        </div>
      )}
      <ErrorLine error={err} />
      {levelling && <LevelModal q={levelling} onClose={() => setLevelling(null)} onDone={() => { setLevelling(null); reload(); }} />}
    </section>
  );
}

function LevelModal({ q, onClose, onDone }: { q: Quote; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ company: q.company, email: q.email, amount: q.amount === null ? "" : String(q.amount), status: q.status === "invited" ? "received" : q.status,
    exclusions: q.exclusions, notes: q.notes, valid_until: q.valid_until ?? "" });
  const [adj, setAdj] = useState(q.adjustments.length ? q.adjustments : [{ description: "", amount: 0 }]);
  const [file, setFile] = useState<File | null>(null);
  const [run, err, busy] = useAction();
  const total = (+f.amount || 0) + adj.reduce((s, a) => s + (+a.amount || 0), 0);
  return (
    <Modal title={`${q.company}: price and levelling`} onClose={onClose} wide>
      <div className="form">
        <div className="row wrap">
          <Field label="Their price ex GST"><input type="number" step="any" value={f.amount} onChange={(e) => setF({ ...f, amount: e.target.value })} /></Field>
          <Field label="Status"><select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="invited">Asked</option><option value="received">Received</option><option value="declined">Declined</option></select></Field>
          <Field label="Valid until"><input type="date" value={f.valid_until} onChange={(e) => setF({ ...f, valid_until: e.target.value })} /></Field>
          <Field label="Quote PDF"><input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} /></Field>
        </div>
        <Field label="What they've excluded"><textarea value={f.exclusions} onChange={(e) => setF({ ...f, exclusions: e.target.value })} /></Field>
        <h3>Levelling: allow for what they left out, so the prices compare like for like</h3>
        {adj.map((a, i) => (
          <div key={i} className="row">
            <input placeholder="e.g. Traffic control (excluded)" value={a.description} onChange={(e) => setAdj(adj.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)))} style={{ flex: 1 }} />
            <input type="number" step="any" value={a.amount} onChange={(e) => setAdj(adj.map((x, j) => (j === i ? { ...x, amount: +e.target.value } : x)))} style={{ width: 120 }} />
            <button className="link danger" onClick={() => setAdj(adj.filter((_, j) => j !== i))}>✕</button>
          </div>
        ))}
        <button className="link" onClick={() => setAdj([...adj, { description: "", amount: 0 }])}>+ Line</button>
        <p>Levelled price: <b>{money(total)}</b></p>
        <button className="primary" disabled={busy} onClick={() => run(async () => {
          await api.put(`/api/package-quotes/${q.id}`, { ...f, amount: f.amount === "" ? null : +f.amount, valid_until: f.valid_until || null,
            adjustments: adj.filter((a) => a.description || a.amount) });
          if (file) { const fd = new FormData(); fd.append("file", file); await upload(`/api/package-quotes/${q.id}/file`, fd); }
          onDone();
        })}>Save</button>
        <ErrorLine error={err} />
      </div>
    </Modal>
  );
}

/* --- versions --- */
interface Cmp { a: { label: string }; b: { label: string }; totals: Record<string, { a: number; b: number; change: number }>;
  by_stage: { stage: string; a: number; b: number; change: number }[];
  lines: { kind: string; description: string; stage: string; service_code: string; uom: string; qty_a: number; qty_b: number; sell_a: number; sell_b: number; change: number }[] }
function Versions({ jobId }: { jobId: number }) {
  const { data, reload } = useLoad<{ id: number; label: string; sell: number; cost: number; by: string; at: string }[]>(`/api/jobs/${jobId}/versions`);
  const [label, setLabel] = useState("");
  const [a, setA] = useState("");
  const [b, setB] = useState("current");
  const { data: cmp } = useLoad<Cmp>(a ? `/api/jobs/${jobId}/versions/compare?a=${a}&b=${b}` : null, [a, b]);
  const [run, err] = useAction();
  const TOT: [string, string][] = [["sell_ex_gst", "Sell ex GST"], ["cost", "Cost"], ["margin", "Margin"], ["labour_hours", "Labour hours"], ["material_cost", "Materials"], ["labour_cost", "Labour"], ["subcontract_cost", "Subcontract"]];
  return (
    <>
      <section className="card">
        <div className="row wrap">
          <input placeholder="Name this version, e.g. Tender v1, Post-RFI 3, Rev C drawings" value={label} onChange={(e) => setLabel(e.target.value)} style={{ flex: 1 }} />
          <button className="primary" disabled={!label} onClick={() => run(async () => { await api.post(`/api/jobs/${jobId}/versions`, { label }); setLabel(""); await reload(); })}>Save a copy of the estimate now</button>
        </div>
        <DataTable rows={data ?? []} empty="No versions saved yet." cols={[
          { key: "l", label: "Version", render: (v) => v.label }, { key: "s", label: "Sell", num: true, render: (v) => money(v.sell) },
          { key: "c", label: "Cost", num: true, render: (v) => money(v.cost) }, { key: "b", label: "Saved", render: (v) => `${fmtDate(v.at)} ${v.by}` },
          { key: "x", label: "", render: (v) => <button className="link small danger" onClick={() => run(async () => { await api.del(`/api/estimate-versions/${v.id}`); await reload(); })}>✕</button> },
        ]} />
        <ErrorLine error={err} />
      </section>
      {(data ?? []).length > 0 && (
        <section className="card">
          <div className="row wrap"><span>Compare</span>
            <select value={a} onChange={(e) => setA(e.target.value)}><option value="">pick…</option>{(data ?? []).map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}</select>
            <span>with</span><select value={b} onChange={(e) => setB(e.target.value)}><option value="current">the estimate now</option>{(data ?? []).map((v) => <option key={v.id} value={v.id}>{v.label}</option>)}</select></div>
          {cmp && (
            <>
              <div className="tiles">{TOT.map(([k, l]) => cmp.totals[k] && (
                <div key={k} className="tile"><b className={cmp.totals[k].change > 0 ? "warn" : cmp.totals[k].change < 0 ? "ok" : ""}>{cmp.totals[k].change > 0 ? "+" : ""}{k === "labour_hours" ? num(cmp.totals[k].change, 1) : money(cmp.totals[k].change)}</b>
                  <span>{l}: {k === "labour_hours" ? num(cmp.totals[k].a, 1) : money(cmp.totals[k].a)} → {k === "labour_hours" ? num(cmp.totals[k].b, 1) : money(cmp.totals[k].b)}</span></div>))}</div>
              <h3>What changed</h3>
              <DataTable rows={cmp.lines} empty="No differences." cols={[
                { key: "k", label: "", render: (l) => <Status value={l.kind} labels={{ added: "Added", removed: "Removed", changed: "Changed" }} /> },
                { key: "d", label: "Item", render: (l) => <>{l.description} <small className="muted">{l.service_code} · {l.stage}</small></> },
                { key: "q", label: "Qty", num: true, render: (l) => `${num(l.qty_a, 2)} → ${num(l.qty_b, 2)} ${l.uom}` },
                { key: "s", label: "Sell", num: true, render: (l) => `${money(l.sell_a)} → ${money(l.sell_b)}` },
                { key: "c", label: "Change", num: true, render: (l) => <b className={l.change > 0 ? "warn" : "ok"}>{l.change > 0 ? "+" : ""}{money(l.change)}</b> },
              ]} />
            </>
          )}
        </section>
      )}
    </>
  );
}

/* --- programme and cash flow --- */
interface Act { name: string; stages: string[]; start_week: number; weeks: number; curve: string }
interface Prog { start: string; retention_pct: number; retention_cap_pct: number; terms_days: number; pay_suppliers_days: number; activities: Act[]; saved: boolean }
interface CF { months: { month: string; value: number; cost: number; claim: number; retention_held: number; retention_released: number; receipts: number; payments: number; net: number; cumulative: number }[];
  contract: number; cost: number; peak_funding: number; retention_held: number; unplaced_stages: string[]; gantt: { name: string; start: string; finish: string; sell: number }[]; finish: string }

function Cashflow({ jobId }: { jobId: number }) {
  const { data, set } = useLoad<{ programme: Prog; cashflow: CF }>(`/api/jobs/${jobId}/programme`);
  const [p, setP] = useState<Prog | null>(null);
  const [run, err, busy] = useAction();
  const nav = useNavigate();
  if (!data) return <p className="muted">Loading…</p>;
  const prog = p ?? data.programme;
  const cf = data.cashflow;
  const stages = Array.from(new Set([...prog.activities.flatMap((a) => a.stages), ...cf.unplaced_stages]));
  const setAct = (i: number, v: Partial<Act>) => setP({ ...prog, activities: prog.activities.map((a, j) => (j === i ? { ...a, ...v } : a)) });
  const maxAbs = Math.max(1, ...cf.months.map((m) => Math.max(Math.abs(m.cumulative), m.receipts, m.payments)));
  const totalWeeks = Math.max(1, ...prog.activities.map((a) => a.start_week + a.weeks));
  return (
    <>
      <div className="tiles">
        <div className="tile"><b>{money(cf.contract)}</b><span>Contract (sell ex GST)</span></div>
        <div className="tile"><b>{money(cf.contract - cf.cost)}</b><span>Margin</span></div>
        <div className={`tile ${cf.peak_funding > 0 ? "warn" : "ok"}`}><b>{money(cf.peak_funding)}</b><span>Peak funding needed</span></div>
        <div className="tile"><b>{money(cf.retention_held)}</b><span>Retention held</span></div>
        <div className="tile"><b>{fmtDate(cf.finish)}</b><span>Finish</span></div>
      </div>
      <section className="card">
        <h2>Programme</h2>
        <div className="row wrap small">
          <label className="inline">Start <input type="date" value={prog.start} onChange={(e) => setP({ ...prog, start: e.target.value })} /></label>
          <label className="inline">Retention <input type="number" step="0.5" value={prog.retention_pct} onChange={(e) => setP({ ...prog, retention_pct: +e.target.value })} style={{ width: 60 }} />% up to
            <input type="number" step="0.5" value={prog.retention_cap_pct} onChange={(e) => setP({ ...prog, retention_cap_pct: +e.target.value })} style={{ width: 60 }} />% of the contract</label>
          <label className="inline">Paid <input type="number" value={prog.terms_days} onChange={(e) => setP({ ...prog, terms_days: +e.target.value })} style={{ width: 60 }} /> days after claim</label>
          <label className="inline">We pay suppliers in <input type="number" value={prog.pay_suppliers_days} onChange={(e) => setP({ ...prog, pay_suppliers_days: +e.target.value })} style={{ width: 60 }} /> days</label>
        </div>
        <div className="dt-wrap">
          <table className="dt">
            <thead><tr><th>Activity</th><th>Stages in it</th><th className="n">Start week</th><th className="n">Weeks</th><th>Spend curve</th><th style={{ minWidth: 240 }}>Bar</th><th /></tr></thead>
            <tbody>{prog.activities.map((a, i) => (
              <tr key={i}>
                <td><input value={a.name} onChange={(e) => setAct(i, { name: e.target.value })} /></td>
                <td><div className="chips">{stages.map((s) => <button key={s} className={`chip ${a.stages.includes(s) ? "on" : ""}`} onClick={() => setAct(i, { stages: a.stages.includes(s) ? a.stages.filter((x) => x !== s) : [...a.stages, s] })}>{s}</button>)}</div></td>
                <td className="n"><input type="number" min={0} value={a.start_week} onChange={(e) => setAct(i, { start_week: +e.target.value })} style={{ width: 60 }} /></td>
                <td className="n"><input type="number" min={1} value={a.weeks} onChange={(e) => setAct(i, { weeks: +e.target.value })} style={{ width: 60 }} /></td>
                <td><select value={a.curve} onChange={(e) => setAct(i, { curve: e.target.value })}><option value="s">S-curve</option><option value="linear">Even</option><option value="front">Front-loaded</option><option value="back">Back-loaded</option></select></td>
                <td><div className="mini-gantt"><i style={{ left: `${(100 * a.start_week) / totalWeeks}%`, width: `${(100 * a.weeks) / totalWeeks}%` }} /></div></td>
                <td><button className="link danger" onClick={() => setP({ ...prog, activities: prog.activities.filter((_, j) => j !== i) })}>✕</button></td>
              </tr>))}</tbody>
          </table>
        </div>
        {cf.unplaced_stages.length > 0 && <p className="small warn">Not on the programme (spread over the whole job): {cf.unplaced_stages.join(", ")}</p>}
        <div className="row">
          <button className="link" onClick={() => setP({ ...prog, activities: [...prog.activities, { name: "New activity", stages: [], start_week: totalWeeks, weeks: 4, curve: "s" }] })}>+ Activity</button>
          <span className="spacer" />
          <button onClick={() => run(async () => { const r = await api.post<{ board_id: number }>(`/api/jobs/${jobId}/programme/to-board`); nav(`/boards/${r.board_id}`); })}>Make a programme board</button>
          <button className="primary" disabled={busy} onClick={() => run(async () => { set(await api.put(`/api/jobs/${jobId}/programme`, prog)); setP(null); })}>{p ? "Save and work out the cash flow" : prog.saved ? "Saved" : "Save"}</button>
        </div>
        <ErrorLine error={err} />
      </section>
      <section className="card">
        <h2>Cash flow by month</h2>
        <div className="cf-chart">{cf.months.map((m) => (
          <div key={m.month} className="cf-col" title={`${m.month}: in ${money(m.receipts)}, out ${money(m.payments)}, running ${money(m.cumulative)}`}>
            <i className="in" style={{ height: `${(50 * m.receipts) / maxAbs}%` }} /><i className="out" style={{ height: `${(50 * m.payments) / maxAbs}%` }} />
            <b className={m.cumulative < 0 ? "neg" : "pos"} style={{ bottom: `${50 + (50 * m.cumulative) / maxAbs}%` }} />
            <span>{m.month.slice(5)}/{m.month.slice(2, 4)}</span>
          </div>))}</div>
        <p className="small muted"><span className="key in" /> money in · <span className="key out" /> money out · ● running balance. Peak funding is the lowest running balance.</p>
        <div className="dt-wrap">
          <table className="dt">
            <thead><tr><th>Month</th><th className="n">Work done</th><th className="n">Retention held</th><th className="n">Money in</th><th className="n">Money out</th><th className="n">Net</th><th className="n">Running</th></tr></thead>
            <tbody>{cf.months.map((m) => (
              <tr key={m.month}><td>{m.month}</td><td className="n">{money(m.value)}</td><td className="n">{m.retention_held ? money(m.retention_held) : m.retention_released ? `−${money(m.retention_released)}` : ""}</td>
                <td className="n">{money(m.receipts)}</td><td className="n">{money(m.payments)}</td><td className={`n ${m.net < 0 ? "bad" : ""}`}>{money(m.net)}</td>
                <td className={`n ${m.cumulative < 0 ? "bad" : ""}`}><b>{money(m.cumulative)}</b></td></tr>))}</tbody>
          </table>
        </div>
      </section>
    </>
  );
}

/* --- rate library page --- */
export function RateLibrary() {
  const [tab, setTab] = useState<"resources" | "buildups">("resources");
  return (
    <main className="page">
      <h1>Rate library</h1>
      <p className="muted small">Resources are what things cost (labour grades, machines, materials, subcontract rates). Build-ups put resources together into a rate per unit.
        Change a resource and every build-up and workbook row using it reprices.</p>
      <Tabs value={tab} onChange={setTab} tabs={[["resources", "Resources"], ["buildups", "Build-ups"]]} />
      {tab === "resources" ? <Resources /> : <Buildups />}
    </main>
  );
}

function Resources() {
  const { data, reload } = useLoad<Resource[]>("/api/resources");
  const [f, setF] = useState({ code: "", kind: "labour", description: "", unit: "h", rate: "", supplier: "" });
  const [editing, setEditing] = useState<Resource | null>(null);
  const [run, err, busy] = useAction();
  const [msg, setMsg] = useState("");
  return (
    <section className="card">
      <DataTable rows={data ?? []} onRow={setEditing} cols={[
        { key: "c", label: "Code", render: (r) => <b>{r.code}</b> }, { key: "k", label: "Kind", render: (r) => r.kind },
        { key: "d", label: "Description", render: (r) => r.description }, { key: "u", label: "Unit", render: (r) => r.unit },
        { key: "r", label: "Rate", num: true, render: (r) => money(r.rate, true) }, { key: "s", label: "Supplier", render: (r) => r.supplier, hideSm: true },
        { key: "used", label: "In build-ups", num: true, render: (r) => r.used_in || "" },
      ]} />
      <div className="row wrap">
        <input placeholder="Code" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} style={{ width: 110 }} />
        <select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{["labour", "plant", "material", "subcontract", "other"].map((k) => <option key={k}>{k}</option>)}</select>
        <input placeholder="Description" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} style={{ flex: 1 }} />
        <input placeholder="Unit" value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} style={{ width: 60 }} />
        <input type="number" step="any" placeholder="$ rate" value={f.rate} onChange={(e) => setF({ ...f, rate: e.target.value })} style={{ width: 100 }} />
        <button disabled={busy || !f.code} onClick={() => run(async () => { await api.post("/api/resources", { ...f, rate: +f.rate || 0 }); setF({ ...f, code: "", description: "", rate: "" }); await reload(); })}>Add</button>
        <label className="button">Import CSV / Excel<input type="file" accept=".csv,.xlsx" hidden onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) run(async () => { const fd = new FormData(); fd.append("file", file); const r = await upload<{ added: number; updated: number; skipped: string[] }>("/api/resources/import", fd);
            setMsg(`${r.added} added, ${r.updated} updated${r.skipped.length ? `, skipped: ${r.skipped.join("; ")}` : ""}`); await reload(); });
        }} /></label>
      </div>
      <p className="small muted">Import columns: code, kind (labour / plant / material / subcontract), description, unit, rate, supplier. {msg}</p>
      <ErrorLine error={err} />
      {editing && <Modal title={editing.code} onClose={() => setEditing(null)}>
        <ResourceEdit r={editing} onDone={() => { setEditing(null); reload(); }} /></Modal>}
    </section>
  );
}

function ResourceEdit({ r, onDone }: { r: Resource; onDone: () => void }) {
  const [f, setF] = useState(r);
  const [run, err, busy] = useAction();
  return (
    <div className="form">
      {(["code", "description", "unit", "supplier"] as const).map((k) => <Field key={k} label={k}><input value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></Field>)}
      <Field label="Kind"><select value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>{["labour", "plant", "material", "subcontract", "other"].map((k) => <option key={k}>{k}</option>)}</select></Field>
      <Field label="Rate"><input type="number" step="any" value={f.rate} onChange={(e) => setF({ ...f, rate: +e.target.value })} /></Field>
      <div className="row"><button className="primary" disabled={busy} onClick={() => run(async () => { await api.put(`/api/resources/${r.id}`, f); onDone(); })}>Save</button><span className="spacer" />
        <button className="danger" onClick={() => run(async () => { await api.del(`/api/resources/${r.id}`); onDone(); })}>Delete</button></div>
      <ErrorLine error={err} />
    </div>
  );
}

function Buildups() {
  const { data, reload } = useLoad<Buildup[]>("/api/rate-buildups");
  const { data: res } = useLoad<Resource[]>("/api/resources");
  const [edit, setEdit] = useState<Buildup | "new" | null>(null);
  return (
    <section className="card">
      <DataTable rows={data ?? []} onRow={setEdit} cols={[
        { key: "c", label: "Code", render: (b) => <b>{b.code}</b> }, { key: "d", label: "Description", render: (b) => b.description },
        { key: "u", label: "Per", render: (b) => b.unit }, { key: "l", label: "Labour", num: true, render: (b) => `${money(b.rate.labour, true)} (${num(b.rate.labour_hours, 2)} h)` },
        { key: "m", label: "Materials", num: true, render: (b) => money(b.rate.material, true) }, { key: "p", label: "Plant", num: true, render: (b) => money(b.rate.plant, true) },
        { key: "t", label: "Rate", num: true, render: (b) => <b>{money(b.rate.total, true)}</b> },
        { key: "x", label: "", render: (b) => b.rate.missing.length > 0 && <span className="bad small">missing {b.rate.missing.join(", ")}</span> },
      ]} />
      <button className="primary" onClick={() => setEdit("new")}>+ Build-up</button>
      {edit && res && <BuildupForm b={edit === "new" ? null : edit} res={res} onClose={() => setEdit(null)} onDone={() => { setEdit(null); reload(); }} />}
    </section>
  );
}

function BuildupForm({ b, res, onClose, onDone }: { b: Buildup | null; res: Resource[]; onClose: () => void; onDone: () => void }) {
  const [f, setF] = useState({ code: b?.code ?? "", description: b?.description ?? "", unit: b?.unit ?? "m", notes: b?.notes ?? "" });
  const [lines, setLines] = useState(b?.lines ?? [{ resource: "", qty: 1, waste_pct: 0 }]);
  const [run, err, busy] = useAction();
  const byCode = Object.fromEntries(res.map((r) => [r.code, r]));
  const total = lines.reduce((s, l) => s + (byCode[l.resource]?.rate ?? 0) * l.qty * (1 + (l.waste_pct || 0) / 100), 0);
  return (
    <Modal title={b ? b.code : "New build-up"} onClose={onClose} wide>
      <div className="form">
        <div className="row wrap">
          <Field label="Code"><input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} /></Field>
          <Field label="Description"><input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} style={{ minWidth: 260 }} /></Field>
          <Field label="Per"><input value={f.unit} onChange={(e) => setF({ ...f, unit: e.target.value })} style={{ width: 70 }} /></Field>
        </div>
        <table className="dt"><thead><tr><th>Resource</th><th className="n">Qty per {f.unit}</th><th className="n">Waste %</th><th className="n">Rate</th><th className="n">$ per {f.unit}</th><th /></tr></thead>
          <tbody>{lines.map((l, i) => (
            <tr key={i}>
              <td><select value={l.resource} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, resource: e.target.value } : x)))}><option value="">Pick…</option>
                {res.map((r) => <option key={r.code} value={r.code}>{r.code} – {r.description} ({r.kind}, {r.unit})</option>)}</select></td>
              <td className="n"><input type="number" step="any" value={l.qty} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, qty: +e.target.value } : x)))} style={{ width: 80 }} /></td>
              <td className="n"><input type="number" step="any" value={l.waste_pct} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, waste_pct: +e.target.value } : x)))} style={{ width: 60 }} /></td>
              <td className="n">{byCode[l.resource] ? `${money(byCode[l.resource].rate, true)}/${byCode[l.resource].unit}` : ""}</td>
              <td className="n">{money((byCode[l.resource]?.rate ?? 0) * l.qty * (1 + (l.waste_pct || 0) / 100), true)}</td>
              <td><button className="link danger" onClick={() => setLines(lines.filter((_, j) => j !== i))}>✕</button></td>
            </tr>))}
            <tr><td colSpan={4}><button className="link" onClick={() => setLines([...lines, { resource: "", qty: 1, waste_pct: 0 }])}>+ Resource</button></td><td className="n"><b>{money(total, true)}</b></td><td /></tr>
          </tbody></table>
        <Field label="Notes (production rate, assumptions)"><textarea value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} /></Field>
        <div className="row"><button className="primary" disabled={busy || !f.code} onClick={() => run(async () => {
          const body = { ...f, lines: lines.filter((l) => l.resource) };
          if (b) await api.put(`/api/rate-buildups/${b.id}`, body); else await api.post("/api/rate-buildups", body);
          onDone();
        })}>Save</button><span className="spacer" />
          {b && <button className="danger" onClick={() => run(async () => { await api.del(`/api/rate-buildups/${b.id}`); onDone(); })}>Delete</button>}</div>
        <ErrorLine error={err} />
      </div>
    </Modal>
  );
}

