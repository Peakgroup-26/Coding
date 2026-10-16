/* One live job, end to end: money, budget, time, purchasing and costs, variations, invoices, documents, project items, diary, forms. */
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, fetchBlobUrl, upload } from "../api";
import { can, sees, useApp } from "../App";
import { DataTable, DocOut, ErrorLine, Field, fmtDate, fmtDay, hrs, Modal, money, num, pct, Status, Tabs, todayIso, useAction, useLoad } from "../ui";
import { WORK_LABELS, WorkRow } from "./WorkBoard";
import { JobItpsTab, JobPrestartsTab, JobSwmsTab } from "./Safety";

interface CatRow { category: string; label: string; budget: number; actual: number; committed: number; forecast: number; to_complete: number; variance: number }
export interface Fin {
  contract: number; variations_approved: number; variations_pending: number; revenue: number; budget_cost: number; budget_margin: number; budget_margin_pct: number | null;
  cost_to_date: number; committed: number; forecast_cost: number; cost_to_complete: number; forecast_margin: number; forecast_margin_pct: number | null;
  percent_complete: number; percent_basis: string; earned: number; invoiced: number; received: number; retention_held: number; over_under_billed: number;
  to_invoice: number; hours_budget: number; hours_actual: number; categories: CatRow[]; over_budget: boolean;
}
type Tab = "overview" | "budget" | "time" | "materials" | "costs" | "variations" | "invoices" | "docs" | "project" | "diary" | "forms" | "swms" | "itps" | "prestarts";

export default function JobHub() {
  const { jobId } = useParams();
  const { user } = useApp();
  const fin = can(user, "can_finance");
  const { data: w, reload } = useLoad<WorkRow & { financials: Fin | null }>(`/api/jobs/${jobId}/work`);
  const [tab, setTab] = useState<Tab>(() => (new URLSearchParams(window.location.search).get("tab") as Tab) || "overview");
  if (!w) return <main className="page">Loading…</main>;
  const f = w.financials;
  const tabs: [Tab, string][] = [["overview", "Overview"], ["budget", "Budget"], ["time", "Time"], ["materials", "Materials"], ["costs", "POs & costs"], ["variations", "Variations"],
    ["invoices", "Invoices"], ["docs", "Documents"], ["project", "RFIs & defects"], ["diary", "Site diary"], ["forms", "Forms"],
    ...(sees(user, "safety") ? [["swms", "SWMS"], ["prestarts", "Site pre-starts"]] as [Tab, string][] : []),
    ...(sees(user, "itp") ? [["itps", "ITPs"]] as [Tab, string][] : [])];
  return (
    <main className="page">
      <Link to="/work" className="small">‹ Jobs</Link>
      <div className="row wrap">
        <h1 style={{ margin: 0 }}>{w.job_no} {w.name}</h1>
        <Status value={w.work_status} labels={WORK_LABELS} />
        {w.priority === "urgent" && <span className="badge bad">Urgent</span>}
        <span className="spacer" />
        {w.customer_id ? <Link to={`/customers/${w.customer_id}`}>{w.customer}</Link> : <span>{w.customer}</span>}
        <Link to={`/jobs/${w.id}`} className="small">Estimate & plans ›</Link>
      </div>
      <p className="muted small">{[w.address, w.order_no && `Order ${w.order_no}`, w.billing === "charge" ? "Do and charge" : "Fixed price", w.work_type].filter(Boolean).join(" · ")}</p>
      {f && (
        <div className="tiles">
          <div className="tile"><b>{pct(f.percent_complete)}</b><span>complete ({f.percent_basis})</span></div>
          <div className="tile"><b>{num(f.hours_actual)} / {num(f.hours_budget)}</b><span>hours actual / budget</span></div>
          {fin && <div className="tile"><b>{money(f.revenue)}</b><span>revenue incl. variations</span></div>}
          {fin && <div className="tile"><b>{money(f.cost_to_date)}</b><span>cost to date · {money(f.committed)} committed</span></div>}
          {fin && <div className={`tile ${f.over_budget ? "warn" : "ok"}`}><b>{pct(f.forecast_margin_pct)}</b><span>forecast margin (budget {pct(f.budget_margin_pct)})</span></div>}
          {fin && <div className="tile"><b>{money(f.invoiced)}</b><span>invoiced · {money(f.to_invoice)} to go</span></div>}
        </div>
      )}
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      {tab === "overview" && <Overview w={w} f={f} fin={fin} onSaved={reload} />}
      {tab === "budget" && <Budget jobId={w.id} f={f} onChange={reload} />}
      {tab === "time" && <TimeTab jobId={w.id} />}
      {tab === "materials" && <Materials jobId={w.id} onChange={reload} />}
      {tab === "costs" && <Costs jobId={w.id} onChange={reload} />}
      {tab === "variations" && <Variations jobId={w.id} onChange={reload} />}
      {tab === "invoices" && <Invoices jobId={w.id} onChange={reload} />}
      {tab === "docs" && <Docs jobId={w.id} />}
      {tab === "project" && <Project jobId={w.id} />}
      {tab === "diary" && <Diary jobId={w.id} />}
      {tab === "forms" && <FormsTab jobId={w.id} />}
      {tab === "swms" && <JobSwmsTab jobId={w.id} />}
      {tab === "itps" && <JobItpsTab jobId={w.id} />}
      {tab === "prestarts" && <JobPrestartsTab jobId={w.id} />}
    </main>
  );
}

function Overview({ w, f, fin, onSaved }: { w: WorkRow; f: Fin | null; fin: boolean; onSaved: () => void }) {
  const staff = useLoad<{ id: number; name: string; trade: string }[]>("/api/staff");
  const [form, setForm] = useState({ work_status: w.work_status, priority: w.priority, contract_value: w.contract_value ?? "", percent_complete: w.percent_complete ?? "",
    start_date: w.start_date ?? "", finish_date: w.finish_date ?? "", supervisor_id: w.supervisor_id ?? "", retention_pct: w.retention_pct, order_no: w.order_no,
    description: w.description, contact: w.contact });
  const [run, error, busy] = useAction();
  const [msg, setMsg] = useState("");
  const save = () => run(async () => {
    await api.put(`/api/jobs/${w.id}/work`, { ...form, contract_value: form.contract_value === "" ? null : Number(form.contract_value),
      percent_complete: form.percent_complete === "" ? undefined : Number(form.percent_complete), clear_percent: form.percent_complete === "",
      supervisor_id: form.supervisor_id === "" ? null : Number(form.supervisor_id), start_date: form.start_date || null, finish_date: form.finish_date || null });
    setMsg("Saved."); onSaved();
  });
  return (
    <div className="two-col">
      <section className="card">
        {f && fin && (
          <>
            <h2>Budget against actual</h2>
            <DataTable rows={f.categories} cols={[
              { key: "c", label: "", render: (r) => r.label },
              { key: "b", label: "Budget", num: true, render: (r) => money(r.budget) },
              { key: "a", label: "Actual", num: true, render: (r) => money(r.actual) },
              { key: "m", label: "Committed", num: true, render: (r) => money(r.committed) },
              { key: "f", label: "Forecast", num: true, render: (r) => money(r.forecast) },
              { key: "v", label: "Variance", num: true, render: (r) => <span className={r.variance < 0 ? "error" : ""}>{money(r.variance)}</span> },
            ]} />
            <table className="kv">
              <tbody>
                <tr><td>Contract</td><td>{money(f.contract)}</td><td>Approved variations</td><td>{money(f.variations_approved)} <span className="muted small">({money(f.variations_pending)} pending)</span></td></tr>
                <tr><td>Earned to date</td><td>{money(f.earned)}</td><td>Invoiced</td><td>{money(f.invoiced)} <span className="muted small">received {money(f.received)}</span></td></tr>
                <tr><td>{f.over_under_billed >= 0 ? "Billed ahead" : "Not yet billed"}</td><td>{money(Math.abs(f.over_under_billed))}</td>
                  <td>Retention held</td><td>{money(f.retention_held)}</td></tr>
                <tr><td>Forecast final cost</td><td>{money(f.forecast_cost)}</td><td>Cost to complete</td><td>{money(f.cost_to_complete)}</td></tr>
              </tbody>
            </table>
          </>
        )}
        {w.description && <><h3>Scope</h3><p className="pre">{w.description}</p></>}
        {w.signed_by_name && <p className="ok small">Signed off on site by {w.signed_by_name} {fmtDate(w.completed_at)}</p>}
      </section>
      <section className="card">
        <h2>Details</h2>
        <Field label="Status"><select value={form.work_status} onChange={(e) => setForm({ ...form, work_status: e.target.value })}>
          {Object.entries(WORK_LABELS).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        <Field label="Priority"><select value={form.priority} onChange={(e) => setForm({ ...form, priority: e.target.value })}>
          {["low", "normal", "high", "urgent"].map((p) => <option key={p}>{p}</option>)}</select></Field>
        {fin && <Field label="Contract value (ex GST)"><input type="number" value={form.contract_value} onChange={(e) => setForm({ ...form, contract_value: e.target.value })} /></Field>}
        <Field label="% complete" hint="Blank = worked out from cost"><input type="number" min={0} max={100} value={form.percent_complete} onChange={(e) => setForm({ ...form, percent_complete: e.target.value })} /></Field>
        <Field label="Start"><input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></Field>
        <Field label="Finish"><input type="date" value={form.finish_date} onChange={(e) => setForm({ ...form, finish_date: e.target.value })} /></Field>
        <Field label="Supervisor"><select value={form.supervisor_id} onChange={(e) => setForm({ ...form, supervisor_id: e.target.value })}>
          <option value="">–</option>{staff.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
        {fin && <Field label="Retention %"><input type="number" min={0} max={20} value={form.retention_pct} onChange={(e) => setForm({ ...form, retention_pct: Number(e.target.value) })} /></Field>}
        <Field label="Client order no."><input value={form.order_no} onChange={(e) => setForm({ ...form, order_no: e.target.value })} /></Field>
        <Field label="Site contact"><input value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} /></Field>
        <Field label="Scope / what's needed"><textarea rows={4} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        <button className="primary" onClick={save} disabled={busy}>Save</button> {msg && <span className="ok small">{msg}</span>}
        <ErrorLine error={error} />
      </section>
    </div>
  );
}

interface BudgetLine { id: number; category: string; description: string; stage: string; hours: number; cost: number; source: string }

function Budget({ jobId, f, onChange }: { jobId: number; f: Fin | null; onChange: () => void }) {
  const { data, reload } = useLoad<BudgetLine[]>(`/api/jobs/${jobId}/budget`);
  const [add, setAdd] = useState({ category: "materials", description: "", hours: 0, cost: 0 });
  const [run, error] = useAction();
  const refresh = () => { reload(); onChange(); };
  return (
    <section className="card">
      <div className="row wrap"><h2 style={{ margin: 0 }}>Budget</h2><span className="spacer" />
        <button onClick={() => window.confirm("Replace the lines that came from the estimate with fresh ones from the current take-off?") &&
          run(async () => { await api.post(`/api/jobs/${jobId}/budget/from-estimate`); refresh(); })}>Rebuild from the estimate</button></div>
      <p className="small muted">What the job should cost. Lines from the estimate came from the take-off when the job was won; approved variations add their own.</p>
      <DataTable rows={data ?? []} cols={[
        { key: "c", label: "Category", render: (r) => r.category },
        { key: "d", label: "Line", render: (r) => <>{r.description}{r.source !== "manual" && <span className="muted small"> · {r.source}</span>}</> },
        { key: "h", label: "Hours", num: true, render: (r) => (r.hours ? num(r.hours) : "") },
        { key: "v", label: "Cost", num: true, render: (r) => money(r.cost) },
        { key: "x", label: "", render: (r) => <button className="link small" onClick={() => run(async () => { await api.del(`/api/budget/${r.id}`); refresh(); })}>remove</button> },
      ]} />
      <div className="row wrap">
        <select value={add.category} onChange={(e) => setAdd({ ...add, category: e.target.value })}>
          {["labour", "materials", "subcontract", "plant", "other"].map((c) => <option key={c}>{c}</option>)}</select>
        <input placeholder="Description" value={add.description} onChange={(e) => setAdd({ ...add, description: e.target.value })} />
        {add.category === "labour" && <input type="number" placeholder="Hours" style={{ width: 90 }} value={add.hours || ""} onChange={(e) => setAdd({ ...add, hours: Number(e.target.value) })} />}
        <input type="number" placeholder="Cost $" style={{ width: 110 }} value={add.cost || ""} onChange={(e) => setAdd({ ...add, cost: Number(e.target.value) })} />
        <button onClick={() => run(async () => { await api.post(`/api/jobs/${jobId}/budget`, add); setAdd({ ...add, description: "", hours: 0, cost: 0 }); refresh(); })}>Add line</button>
      </div>
      {f && <p className="small">Total budget {money(f.budget_cost)} · {num(f.hours_budget)} labour hours</p>}
      <ErrorLine error={error} />
    </section>
  );
}

interface TimeRow { id: number; name: string; local_day: string; start_local: string; end_local: string | null; hours: number; task: string; status: string; flags: string[]; notes: string; start_lat: number | null; start_lng: number | null }

function TimeTab({ jobId }: { jobId: number }) {
  const { data } = useLoad<{ entries: TimeRow[]; by_person: { name: string; hours: number }[]; by_task: { task: string; hours: number }[]; total: number }>(`/api/jobs/${jobId}/time`);
  if (!data) return null;
  return (
    <div className="two-col">
      <section className="card">
        <h2>Time on this job ({hrs(data.total)})</h2>
        <DataTable rows={data.entries} cols={[
          { key: "d", label: "Day", render: (r) => fmtDay(r.local_day) },
          { key: "p", label: "Who", render: (r) => r.name },
          { key: "t", label: "Time", render: (r) => `${r.start_local}–${r.end_local ?? "now"}` },
          { key: "k", label: "Task", hideSm: true, render: (r) => r.task },
          { key: "h", label: "Hours", num: true, render: (r) => num(r.hours, 2) },
          { key: "s", label: "", render: (r) => <><Status value={r.status} />{r.start_lat !== null && <a className="small" href={`https://maps.google.com/?q=${r.start_lat},${r.start_lng}`} target="_blank" rel="noreferrer"> 📍</a>}
            {r.flags.map((x) => <span key={x} className="badge warn">{x}</span>)}</> },
        ]} />
      </section>
      <section className="card">
        <h3>By person</h3>{data.by_person.map((p) => <div key={p.name} className="kv-row"><span>{p.name}</span><b>{hrs(p.hours)}</b></div>)}
        <h3>By task</h3>{data.by_task.map((p) => <div key={p.task} className="kv-row"><span>{p.task}</span><b>{hrs(p.hours)}</b></div>)}
      </section>
    </div>
  );
}

interface MatRow { id: number; day: string; description: string; qty: number; unit_cost: number; amount: number; sell_unit: number | null; markup_pct: number | null;
  source: string; ref: string; category: string }
interface StockRow { code: string; supplier_id: number | null; supplier: string; description: string; brand: string; group: string; unit: string; cost: number; sell: number; markup_pct: number; source: string }

/** Materials used from stock: costed at the price-file rate, sold at cost plus the margin (by product group, or the default). */
function Materials({ jobId, onChange }: { jobId: number; onChange: () => void }) {
  const costs = useLoad<MatRow[]>(`/api/jobs/${jobId}/costs`);
  const [q, setQ] = useState("");
  const found = useLoad<StockRow[]>(q.trim().length >= 2 ? `/api/stock/search?q=${encodeURIComponent(q)}` : null, [q]);
  const [pick, setPick] = useState<StockRow | null>(null);
  const [qty, setQty] = useState(1);
  const [markup, setMarkup] = useState<number | "">("");
  const [run, error, busy] = useAction();
  const rows = (costs.data ?? []).filter((c) => c.category === "materials" && (c.source === "stock" || c.source === "field" || c.sell_unit !== null));
  const cost = rows.reduce((s, r) => s + r.amount, 0);
  const sell = rows.reduce((s, r) => s + (r.sell_unit ?? 0) * r.qty, 0);
  const unpriced = rows.filter((r) => r.sell_unit === null);
  return (
    <div className="two-col even">
      <section className="card">
        <h2>Materials used from stock</h2>
        <DataTable rows={rows} cols={[
          { key: "d", label: "Day", hideSm: true, render: (r) => fmtDate(r.day) },
          { key: "x", label: "What", render: (r) => <>{r.description}{r.source === "field" && <span className="badge warn" title="Typed in on the phone: price it">to price</span>}</> },
          { key: "c", label: "Cost", num: true, render: (r) => money(r.amount, true) },
          { key: "m", label: "Margin", num: true, render: (r) => (r.markup_pct !== null ? `${num(r.markup_pct)}%` : "") },
          { key: "s", label: "Sell", num: true, render: (r) => (r.sell_unit !== null ? money(r.sell_unit * r.qty, true) : "") },
          { key: "r", label: "", render: (r) => <button className="link small" onClick={() => run(async () => { await api.del(`/api/costs/${r.id}`); costs.reload(); onChange(); })}>remove</button> },
        ]} empty="Nothing used from stock yet. The team add it from the phone (Materials tab on the job)." />
        <p className="small">Cost {money(cost, true)} · sell {money(sell, true)} · margin {money(sell - cost, true)}{unpriced.length > 0 && <span className="warn"> · {unpriced.length} typed in, to price under POs & costs</span>}</p>
        <p className="small muted">On do-and-charge jobs these go on the invoice line by line at their sell price.</p>
      </section>
      <section className="card">
        <h2>Add from stock</h2>
        <input placeholder="Search the price files and price book" value={q} onChange={(e) => { setQ(e.target.value); setPick(null); }} style={{ width: "100%" }} />
        {!pick && <div className="pick-list">{found.data?.map((p) => (
          <button key={p.code + (p.supplier_id ?? "")} className="job-tile" onClick={() => { setPick(p); setMarkup(p.markup_pct); setQty(1); }}>
            <b>{p.description}</b><span className="small muted">{[p.brand, p.group, p.supplier, `${money(p.cost, true)} cost → ${money(p.sell, true)} sell`].filter(Boolean).join(" · ")}</span>
          </button>))}</div>}
        {pick && (
          <div className="card">
            <b>{pick.description}</b> <span className="small muted">{pick.supplier} · {pick.code}</span>
            <div className="row wrap">
              <label className="inline">Qty <input type="number" min={0.01} step="any" style={{ width: 80 }} value={qty} onChange={(e) => setQty(Number(e.target.value))} /></label>
              <label className="inline">Margin % <input type="number" min={0} style={{ width: 80 }} value={markup} onChange={(e) => setMarkup(e.target.value === "" ? "" : Number(e.target.value))} /></label>
              <span className="small">{money(pick.cost * qty, true)} cost → <b>{money(pick.cost * (1 + Number(markup || 0) / 100) * qty, true)}</b> sell</span>
            </div>
            <div className="row"><button className="primary" disabled={busy} onClick={() => run(async () => {
              await api.post(`/api/jobs/${jobId}/materials`, { code: pick.code, supplier_id: pick.supplier_id, qty, markup_pct: markup === "" ? null : markup });
              setPick(null); setQ(""); costs.reload(); onChange(); })}>Add</button><button className="link" onClick={() => setPick(null)}>Back</button></div>
          </div>
        )}
        <p className="small muted">Prices come from the latest supplier price files (cheapest supplier), else the price book. Margins by product group are set in Admin → Operations & plant.</p>
        <ErrorLine error={error} />
      </section>
    </div>
  );
}

interface Po { id: number; po_no: string; supplier: string; status: string; value: number; bill_amount: number | null; bill_variance: number | null; order_date: string | null; category: string }
interface Cost { id: number; day: string; category: string; description: string; amount: number; supplier: string; source: string }

function Costs({ jobId, onChange }: { jobId: number; onChange: () => void }) {
  const pos = useLoad<Po[]>(`/api/purchase-orders?job_id=${jobId}`);
  const costs = useLoad<Cost[]>(`/api/jobs/${jobId}/costs`);
  const [c, setC] = useState({ day: todayIso(), category: "materials", description: "", qty: 1, unit_cost: 0, supplier: "", ref: "" });
  const [poOpen, setPoOpen] = useState(false);
  const [run, error] = useAction();
  return (
    <div className="two-col even">
      <section className="card">
        <div className="row"><h2 style={{ margin: 0 }}>Purchase orders</h2><span className="spacer" /><button onClick={() => setPoOpen(true)}>+ New PO</button></div>
        <DataTable rows={pos.data ?? []} cols={[
          { key: "n", label: "PO", render: (r) => <b>{r.po_no}</b> },
          { key: "s", label: "Supplier", render: (r) => r.supplier },
          { key: "st", label: "Status", render: (r) => <Status value={r.status} /> },
          { key: "v", label: "Value", num: true, render: (r) => money(r.value, true) },
          { key: "b", label: "Billed", num: true, render: (r) => r.bill_amount !== null ? <>{money(r.bill_amount, true)}{Math.abs(r.bill_variance ?? 0) > r.value * 0.02 && <span className="badge warn">≠ PO</span>}</> : "" },
        ]} />
        <p className="small"><Link to={`/purchasing?job=${jobId}`}>Open in Purchasing ›</Link></p>
      </section>
      <section className="card">
        <h2>Other costs</h2>
        <DataTable rows={costs.data ?? []} cols={[
          { key: "d", label: "Day", render: (r) => fmtDate(r.day) },
          { key: "c", label: "Type", render: (r) => r.category },
          { key: "x", label: "What", render: (r) => <>{r.description}{r.source !== "office" && <span className="muted small"> · {r.source}</span>}</> },
          { key: "a", label: "Amount", num: true, render: (r) => money(r.amount, true) },
          { key: "r", label: "", render: (r) => <button className="link small" onClick={() => run(async () => { await api.del(`/api/costs/${r.id}`); costs.reload(); onChange(); })}>remove</button> },
        ]} />
        <div className="row wrap">
          <input type="date" value={c.day} onChange={(e) => setC({ ...c, day: e.target.value })} />
          <select value={c.category} onChange={(e) => setC({ ...c, category: e.target.value })}>{["materials", "subcontract", "plant", "other"].map((x) => <option key={x}>{x}</option>)}</select>
          <input placeholder="What" value={c.description} onChange={(e) => setC({ ...c, description: e.target.value })} />
          <input placeholder="Supplier" value={c.supplier} onChange={(e) => setC({ ...c, supplier: e.target.value })} />
          <input type="number" placeholder="$ ex GST" style={{ width: 110 }} value={c.unit_cost || ""} onChange={(e) => setC({ ...c, unit_cost: Number(e.target.value) })} />
          <button onClick={() => run(async () => { await api.post(`/api/jobs/${jobId}/costs`, c); setC({ ...c, description: "", unit_cost: 0 }); costs.reload(); onChange(); })}>Add cost</button>
        </div>
        <p className="small muted">Supplier bills from Xero that quote this job's number land here by themselves.</p>
        <ErrorLine error={error} />
      </section>
      {poOpen && <PoEditor jobId={jobId} onClose={() => setPoOpen(false)} onSaved={() => { setPoOpen(false); pos.reload(); onChange(); }} />}
    </div>
  );
}

export function PoEditor({ jobId, po, onClose, onSaved }: { jobId?: number | null; po?: Po & { lines: { code: string; description: string; qty: number; unit: string; unit_cost: number }[]; supplier_id: number | null; notes: string; delivery: string; required_date: string | null; job_id: number | null }; onClose: () => void; onSaved: () => void }) {
  const sups = useLoad<{ id: number; name: string }[]>("/api/suppliers");
  const [f, setF] = useState({ supplier_id: po?.supplier_id ?? "" as number | "", supplier_name: po?.supplier ?? "", category: po?.category ?? "materials", status: po?.status ?? "draft",
    required_date: po?.required_date ?? "", delivery: po?.delivery ?? "Deliver to site", notes: po?.notes ?? "", job_id: po?.job_id ?? jobId ?? null,
    lines: po?.lines ?? [{ code: "", description: "", qty: 1, unit: "ea", unit_cost: 0 }] });
  const [run, error, busy] = useAction();
  const [search, setSearch] = useState("");
  const found = useLoad<{ supplier_id: number; supplier: string; code: string; description: string; price: number; unit: string }[]>(
    search.length >= 3 ? `/api/supplier-prices/search?q=${encodeURIComponent(search)}` : null, [search]);
  const total = f.lines.reduce((s, l) => s + l.qty * l.unit_cost, 0);
  const setLine = (i: number, k: string, v: unknown) => setF({ ...f, lines: f.lines.map((l, j) => (j === i ? { ...l, [k]: v } : l)) });
  return (
    <Modal title={po ? `PO ${po.po_no}` : "New purchase order"} onClose={onClose} wide>
      <div className="row wrap">
        <select value={f.supplier_id} onChange={(e) => setF({ ...f, supplier_id: e.target.value ? Number(e.target.value) : "" })}>
          <option value="">Supplier…</option>{sups.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
        {!f.supplier_id && <input placeholder="or type a supplier" value={f.supplier_name} onChange={(e) => setF({ ...f, supplier_name: e.target.value })} />}
        <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })}>{["materials", "subcontract", "plant", "other"].map((x) => <option key={x}>{x}</option>)}</select>
        <select value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>{(po ? ["draft", "sent", "received", "billed", "cancelled"] : ["draft", "sent"]).map((x) => <option key={x}>{x}</option>)}</select>
        <label className="inline small">Needed <input type="date" value={f.required_date ?? ""} onChange={(e) => setF({ ...f, required_date: e.target.value })} /></label>
        <input placeholder="Delivery" value={f.delivery} onChange={(e) => setF({ ...f, delivery: e.target.value })} />
      </div>
      <div className="dt-wrap"><table className="dt compact">
        <thead><tr><th>Code</th><th>Description</th><th className="n">Qty</th><th>Unit</th><th className="n">Unit cost</th><th className="n">Total</th><th></th></tr></thead>
        <tbody>{f.lines.map((l, i) => (
          <tr key={i}>
            <td><input style={{ width: 90 }} value={l.code} onChange={(e) => setLine(i, "code", e.target.value)} /></td>
            <td><input value={l.description} onChange={(e) => setLine(i, "description", e.target.value)} /></td>
            <td><input type="number" style={{ width: 70 }} value={l.qty} onChange={(e) => setLine(i, "qty", Number(e.target.value))} /></td>
            <td><input style={{ width: 50 }} value={l.unit} onChange={(e) => setLine(i, "unit", e.target.value)} /></td>
            <td><input type="number" step="0.01" style={{ width: 90 }} value={l.unit_cost} onChange={(e) => setLine(i, "unit_cost", Number(e.target.value))} /></td>
            <td className="n">{money(l.qty * l.unit_cost, true)}</td>
            <td><button className="link" onClick={() => setF({ ...f, lines: f.lines.filter((_, j) => j !== i) })}>✕</button></td>
          </tr>))}</tbody>
      </table></div>
      <div className="row wrap">
        <button onClick={() => setF({ ...f, lines: [...f.lines, { code: "", description: "", qty: 1, unit: "ea", unit_cost: 0 }] })}>+ Line</button>
        <input placeholder="Find a product in supplier prices…" value={search} onChange={(e) => setSearch(e.target.value)} />
        <span className="spacer" /><b>Total {money(total, true)} ex GST</b>
      </div>
      {found.data && found.data.length > 0 && (
        <div className="pick-list small">{found.data.slice(0, 8).map((p) => (
          <button key={p.supplier + p.code} className="chip" onClick={() => { setF({ ...f, supplier_id: f.supplier_id || p.supplier_id, lines: [...f.lines.filter((l) => l.description), { code: p.code, description: p.description, qty: 1, unit: p.unit, unit_cost: p.price }] }); setSearch(""); }}>
            {p.description} · {p.supplier} {money(p.price, true)}</button>))}</div>
      )}
      <textarea rows={2} placeholder="Notes for the supplier" value={f.notes} onChange={(e) => setF({ ...f, notes: e.target.value })} />
      <div className="row"><button className="primary" disabled={busy} onClick={() => run(async () => {
        const body = { ...f, supplier_id: f.supplier_id || null, required_date: f.required_date || null };
        if (po) await api.put(`/api/purchase-orders/${po.id}`, body); else await api.post("/api/purchase-orders", body);
        onSaved();
      })}>Save PO</button>
        {po && <button onClick={async () => window.open(await fetchBlobUrl(`/api/purchase-orders/${po.id}/print`), "_blank")}>Print / PDF</button>}
        <button className="link" onClick={onClose}>Cancel</button></div>
      <ErrorLine error={error} />
    </Modal>
  );
}

interface Var { id: number; number: number; title: string; description: string; reason: string; status: string; sell: number; cost: number; hours: number; client_ref: string; submitted_date: string | null; decided_date: string | null }

function Variations({ jobId, onChange }: { jobId: number; onChange: () => void }) {
  const { data, reload } = useLoad<Var[]>(`/api/jobs/${jobId}/variations`);
  const [edit, setEdit] = useState<Partial<Var> | null>(null);
  const [run, error] = useAction();
  const save = () => run(async () => {
    if (!edit) return;
    const body = { title: edit.title, description: edit.description ?? "", reason: edit.reason ?? "client request", status: edit.status ?? "pending",
      sell: Number(edit.sell ?? 0), cost: Number(edit.cost ?? 0), hours: Number(edit.hours ?? 0), client_ref: edit.client_ref ?? "" };
    if (edit.id) await api.put(`/api/variations/${edit.id}`, body); else await api.post(`/api/jobs/${jobId}/variations`, body);
    setEdit(null); reload(); onChange();
  });
  return (
    <section className="card">
      <div className="row"><h2 style={{ margin: 0 }}>Variations</h2><span className="spacer" /><button onClick={() => setEdit({ status: "pending", reason: "client request" })}>+ Variation</button></div>
      <DataTable rows={data ?? []} onRow={(r) => setEdit(r)} cols={[
        { key: "n", label: "#", render: (r) => `V${r.number}` },
        { key: "t", label: "Variation", render: (r) => <>{r.title}<div className="small muted">{r.reason}{r.client_ref && ` · ${r.client_ref}`}</div></> },
        { key: "s", label: "Status", render: (r) => <Status value={r.status} /> },
        { key: "p", label: "Price", num: true, render: (r) => money(r.sell) },
        { key: "c", label: "Our cost", num: true, render: (r) => money(r.cost) },
        { key: "h", label: "Hours", num: true, render: (r) => num(r.hours) },
      ]} />
      <p className="small muted">Approving a variation adds its price to the contract and its cost and hours to the budget.</p>
      {edit && (
        <Modal title={edit.id ? `V${edit.number}` : "New variation"} onClose={() => setEdit(null)}>
          <Field label="Title"><input value={edit.title ?? ""} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></Field>
          <Field label="Description"><textarea rows={3} value={edit.description ?? ""} onChange={(e) => setEdit({ ...edit, description: e.target.value })} /></Field>
          <div className="settings-grid">
            <Field label="Reason"><select value={edit.reason} onChange={(e) => setEdit({ ...edit, reason: e.target.value })}>
              {["client request", "site instruction", "latent condition", "design change", "other"].map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Status"><select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
              {["pending", "submitted", "approved", "rejected"].map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Price to client (ex GST)"><input type="number" value={edit.sell ?? ""} onChange={(e) => setEdit({ ...edit, sell: Number(e.target.value) })} /></Field>
            <Field label="Our cost (materials etc.)"><input type="number" value={edit.cost ?? ""} onChange={(e) => setEdit({ ...edit, cost: Number(e.target.value) })} /></Field>
            <Field label="Labour hours"><input type="number" value={edit.hours ?? ""} onChange={(e) => setEdit({ ...edit, hours: Number(e.target.value) })} /></Field>
            <Field label="Client's reference"><input value={edit.client_ref ?? ""} onChange={(e) => setEdit({ ...edit, client_ref: e.target.value })} /></Field>
          </div>
          <button className="primary" onClick={save}>Save</button><ErrorLine error={error} />
        </Modal>
      )}
    </section>
  );
}

interface Inv { id: number; invoice_no: string; kind: string; issue_date: string; due_date: string; amount: number; retention: number; gst: number; total: number; status: string;
  paid_date: string | null; xero_id: string; overdue: boolean; description: string }

export function Invoices({ jobId, onChange }: { jobId?: number; onChange?: () => void }) {
  const { data, reload } = useLoad<Inv[]>(`/api/invoices${jobId ? `?job_id=${jobId}` : ""}`);
  const [draft, setDraft] = useState<{ kind: string; lines: { description: string; qty: number; unit_price: number }[]; retention?: number; note?: string } | null>(null);
  const [run, error, busy] = useAction();
  const refresh = () => { reload(); onChange?.(); };
  const suggest = () => run(async () => setDraft(await api.get(`/api/invoices/suggest/${jobId}`)));
  const total = draft?.lines.reduce((s, l) => s + l.qty * l.unit_price, 0) ?? 0;
  return (
    <section className="card">
      <div className="row"><h2 style={{ margin: 0 }}>Invoices</h2><span className="spacer" />{jobId && <button className="primary" onClick={suggest}>+ Invoice this job</button>}</div>
      <DataTable rows={data ?? []} rowClass={(r) => (r.overdue ? "warn-row" : "")} cols={[
        { key: "n", label: "Invoice", render: (r) => <b>{r.invoice_no}</b> },
        { key: "k", label: "Type", hideSm: true, render: (r) => r.kind },
        { key: "d", label: "Date", render: (r) => fmtDate(r.issue_date) },
        { key: "due", label: "Due", render: (r) => <>{fmtDate(r.due_date)}{r.overdue && <span className="badge bad">overdue</span>}</> },
        { key: "a", label: "Ex GST", num: true, render: (r) => money(r.amount, true) },
        { key: "t", label: "Total", num: true, render: (r) => money(r.total, true) },
        { key: "s", label: "Status", render: (r) => <><Status value={r.status} />{r.xero_id && <span className="badge ok" title="In Xero">Xero</span>}</> },
        { key: "x", label: "", render: (r) => <span className="row tight">
          {r.status === "draft" && <button className="link small" onClick={() => run(async () => { await api.put(`/api/invoices/${r.id}/status`, { status: "sent" }); refresh(); })}>Send</button>}
          {r.status === "sent" && <button className="link small" onClick={() => run(async () => { await api.put(`/api/invoices/${r.id}/status`, { status: "paid" }); refresh(); })}>Paid</button>}
          <button className="link small" onClick={async () => window.open(await fetchBlobUrl(`/api/invoices/${r.id}/print`), "_blank")}>Print</button></span> },
      ]} />
      <p className="small muted">Sending an invoice pushes it to Xero (when connected) and starts the customer follow-ups set up in Feedback & follow-ups.</p>
      {draft && jobId && (
        <Modal title="New invoice" onClose={() => setDraft(null)} wide>
          {draft.note && <p className="small muted">{draft.note}</p>}
          <div className="dt-wrap"><table className="dt compact"><thead><tr><th>Description</th><th className="n">Qty</th><th className="n">Price</th><th className="n">Amount</th><th></th></tr></thead>
            <tbody>{draft.lines.map((l, i) => (
              <tr key={i}>
                <td><input value={l.description} onChange={(e) => setDraft({ ...draft, lines: draft.lines.map((x, j) => (j === i ? { ...x, description: e.target.value } : x)) })} /></td>
                <td><input type="number" style={{ width: 70 }} value={l.qty} onChange={(e) => setDraft({ ...draft, lines: draft.lines.map((x, j) => (j === i ? { ...x, qty: Number(e.target.value) } : x)) })} /></td>
                <td><input type="number" style={{ width: 110 }} value={l.unit_price} onChange={(e) => setDraft({ ...draft, lines: draft.lines.map((x, j) => (j === i ? { ...x, unit_price: Number(e.target.value) } : x)) })} /></td>
                <td className="n">{money(l.qty * l.unit_price, true)}</td>
                <td><button className="link" onClick={() => setDraft({ ...draft, lines: draft.lines.filter((_, j) => j !== i) })}>✕</button></td>
              </tr>))}</tbody></table></div>
          <div className="row wrap">
            <button onClick={() => setDraft({ ...draft, lines: [...draft.lines, { description: "", qty: 1, unit_price: 0 }] })}>+ Line</button>
            <select value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>{["progress", "final", "deposit", "service"].map((k) => <option key={k}>{k}</option>)}</select>
            <span className="spacer" /><b>{money(total, true)} ex GST</b>
          </div>
          <div className="row">
            <button disabled={busy} onClick={() => run(async () => { await api.post("/api/invoices", { job_id: jobId, kind: draft.kind, lines: draft.lines, retention: draft.retention, status: "draft" }); setDraft(null); refresh(); })}>Save draft</button>
            <button className="primary" disabled={busy} onClick={() => run(async () => { await api.post("/api/invoices", { job_id: jobId, kind: draft.kind, lines: draft.lines, retention: draft.retention, status: "sent" }); setDraft(null); refresh(); })}>Send</button>
          </div>
          <ErrorLine error={error} />
        </Modal>
      )}
      <ErrorLine error={draft ? "" : error} />
    </section>
  );
}

export function Docs({ jobId }: { jobId: number | null }) {
  const url = jobId ? `/api/jobs/${jobId}/docs` : "/api/files";
  const { data, reload } = useLoad<{ folders: string[]; documents: DocOut[] }>(url);
  const [folder, setFolder] = useState("");
  const [upFolder, setUpFolder] = useState("General");
  const [run, error, busy] = useAction();
  const shown = (data?.documents ?? []).filter((d) => !folder || d.folder === folder);
  const send = (files: FileList | null) => run(async () => {
    if (!files?.length) return;
    const form = new FormData();
    Array.from(files).forEach((f) => form.append("files", f));
    form.append("folder", upFolder);
    await upload(jobId ? `/api/jobs/${jobId}/docs` : "/api/files", form);
    reload();
  });
  const open = async (d: DocOut) => window.open(await fetchBlobUrl(`/api/files/${d.id}`), "_blank");
  return (
    <section className="card">
      <div className="row wrap">
        <h2 style={{ margin: 0 }}>Documents</h2><span className="spacer" />
        <select value={upFolder} onChange={(e) => setUpFolder(e.target.value)}>{data?.folders.map((f) => <option key={f}>{f}</option>)}</select>
        <label className="btn">{busy ? "Uploading…" : "Upload"}<input type="file" multiple hidden onChange={(e) => send(e.target.files)} /></label>
      </div>
      <div className="chips">{["", ...(data?.folders ?? [])].map((f) => <button key={f} className={folder === f ? "chip on" : "chip"} onClick={() => setFolder(f)}>{f || "All"} ({(data?.documents ?? []).filter((d) => !f || d.folder === f).length})</button>)}</div>
      <DataTable rows={shown} cols={[
        { key: "n", label: "File", render: (d) => <button className="link" onClick={() => open(d)}>{d.is_image ? "🖼" : "📄"} {d.title || d.filename}</button> },
        { key: "f", label: "Folder", hideSm: true, render: (d) => d.folder },
        { key: "v", label: "Version", render: (d) => (d.version > 1 ? `v${d.version}` : "") },
        { key: "d", label: "Added", render: (d) => fmtDate(d.created_at) },
        { key: "p", label: "On phones", hideSm: true, render: (d) => <input type="checkbox" checked={d.field_visible} onChange={(e) => run(async () => { await api.patch(`/api/files/${d.id}`, { field_visible: e.target.checked }); reload(); })} /> },
        { key: "x", label: "", render: (d) => <button className="link small" onClick={() => window.confirm(`Delete ${d.filename}?`) && run(async () => { await api.del(`/api/files/${d.id}`); reload(); })}>delete</button> },
      ]} />
      <p className="small muted">Upload a file with the same name to the same folder and it becomes the new version; the old one is kept.</p>
      <ErrorLine error={error} />
    </section>
  );
}

interface Item { id: number; kind: string; kind_label: string; ref: string; number: number; title: string; body: string; status: string; priority: string; location: string;
  assignee_id: number | null; assignee: string; assignee_name: string; due_date: string | null; response: string; cost_impact: number | null; variation_id: number | null;
  created_by: string; created_at: string; overdue: boolean; photos: DocOut[] }

function Project({ jobId }: { jobId: number }) {
  const { data, reload } = useLoad<{ kinds: Record<string, string>; items: Item[] }>(`/api/jobs/${jobId}/items`);
  const staff = useLoad<{ id: number; name: string }[]>("/api/staff");
  const [kind, setKind] = useState("");
  const [edit, setEdit] = useState<Partial<Item> | null>(null);
  const [run, error] = useAction();
  const items = (data?.items ?? []).filter((i) => (!kind ? i.kind !== "note" : i.kind === kind));
  const save = () => run(async () => {
    if (!edit) return;
    const body = { kind: edit.kind, title: edit.title, body: edit.body ?? "", status: edit.status ?? "open", priority: edit.priority ?? "normal", location: edit.location ?? "",
      assignee_id: edit.assignee_id || null, assignee_name: edit.assignee_name ?? "", due_date: edit.due_date || null, response: edit.response ?? "",
      cost_impact: edit.cost_impact ?? null };
    if (edit.id) await api.put(`/api/items/${edit.id}`, body); else await api.post(`/api/jobs/${jobId}/items`, body);
    setEdit(null); reload();
  });
  return (
    <section className="card">
      <div className="row wrap"><h2 style={{ margin: 0 }}>RFIs, defects and site records</h2><span className="spacer" />
        <select onChange={(e) => e.target.value && setEdit({ kind: e.target.value, status: "open" })} value="">
          <option value="">+ New…</option>{Object.entries(data?.kinds ?? {}).map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></div>
      <div className="chips">{["", ...Object.keys(data?.kinds ?? {})].map((k) => <button key={k} className={kind === k ? "chip on" : "chip"} onClick={() => setKind(k)}>
        {k ? data?.kinds[k] : "All open records"} ({(data?.items ?? []).filter((i) => (!k ? i.kind !== "note" : i.kind === k)).length})</button>)}</div>
      <DataTable rows={items} onRow={(r) => setEdit(r)} rowClass={(r) => (r.overdue ? "warn-row" : "")} cols={[
        { key: "r", label: "Ref", render: (r) => r.ref },
        { key: "t", label: "Title", render: (r) => <>{r.title}{r.photos.length > 0 && <span className="muted"> 📷{r.photos.length}</span>}</> },
        { key: "s", label: "Status", render: (r) => <Status value={r.status} /> },
        { key: "a", label: "With", hideSm: true, render: (r) => r.assignee },
        { key: "d", label: "Due", render: (r) => <>{fmtDate(r.due_date)}{r.overdue && <span className="badge bad">overdue</span>}</> },
      ]} />
      {edit && (
        <Modal title={edit.id ? `${edit.ref}: ${edit.title}` : `New ${data?.kinds[edit.kind ?? ""]}`} onClose={() => setEdit(null)} wide>
          <Field label="Title"><input value={edit.title ?? ""} onChange={(e) => setEdit({ ...edit, title: e.target.value })} /></Field>
          <Field label={edit.kind === "rfi" ? "Question" : "Details"}><textarea rows={3} value={edit.body ?? ""} onChange={(e) => setEdit({ ...edit, body: e.target.value })} /></Field>
          <div className="settings-grid">
            <Field label="Status"><select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>{["open", "answered", "closed"].map((x) => <option key={x}>{x}</option>)}</select></Field>
            <Field label="Location"><input value={edit.location ?? ""} onChange={(e) => setEdit({ ...edit, location: e.target.value })} /></Field>
            <Field label="Assigned to (staff)"><select value={edit.assignee_id ?? ""} onChange={(e) => setEdit({ ...edit, assignee_id: e.target.value ? Number(e.target.value) : null })}>
              <option value="">–</option>{staff.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select></Field>
            <Field label="…or someone outside"><input value={edit.assignee_name ?? ""} placeholder="e.g. Hydraulic consultant" onChange={(e) => setEdit({ ...edit, assignee_name: e.target.value })} /></Field>
            <Field label="Due"><input type="date" value={edit.due_date ?? ""} onChange={(e) => setEdit({ ...edit, due_date: e.target.value })} /></Field>
            <Field label="Cost impact $"><input type="number" value={edit.cost_impact ?? ""} onChange={(e) => setEdit({ ...edit, cost_impact: e.target.value ? Number(e.target.value) : null })} /></Field>
          </div>
          <Field label="Response / outcome"><textarea rows={2} value={edit.response ?? ""} onChange={(e) => setEdit({ ...edit, response: e.target.value })} /></Field>
          {edit.photos && edit.photos.length > 0 && <div className="row wrap">{edit.photos.map((p) => <button key={p.id} className="link small" onClick={async () => window.open(await fetchBlobUrl(`/api/files/${p.id}`), "_blank")}>📷 {p.filename}</button>)}</div>}
          <div className="row"><button className="primary" onClick={save}>Save</button>
            {edit.id && !edit.variation_id && <button onClick={() => run(async () => { await api.post(`/api/items/${edit.id}/variation`); setEdit(null); reload(); })}>Make a variation from this</button>}
            {edit.variation_id && <span className="small muted">Has a variation</span>}</div>
          <ErrorLine error={error} />
        </Modal>
      )}
    </section>
  );
}

interface Log { id: number; day: string; weather: string; work_done: string; delays: string; deliveries: string; visitors: string; safety: string; lost_hours: number; by: string; crew: { name: string; trade: string; hours: number }[] }

function Diary({ jobId }: { jobId: number }) {
  const { data, reload } = useLoad<Log[]>(`/api/jobs/${jobId}/diary`);
  const [f, setF] = useState({ day: todayIso(), weather: "", work_done: "", delays: "", deliveries: "", visitors: "", safety: "", lost_hours: 0 });
  const crew = useLoad<{ name: string; trade: string; hours: number }[]>(`/api/jobs/${jobId}/diary/crew?day=${f.day}`, [f.day]);
  const [run, error] = useAction();
  return (
    <div className="two-col even">
      <section className="card">
        <h2>Today's diary</h2>
        <div className="row wrap"><input type="date" value={f.day} onChange={(e) => setF({ ...f, day: e.target.value })} />
          <div className="chips">{["Fine", "Overcast", "Showers", "Wet – stood down", "Hot"].map((w) => <button key={w} className={f.weather === w ? "chip on" : "chip"} onClick={() => setF({ ...f, weather: w })}>{w}</button>)}</div></div>
        <p className="small">On site (from timesheets): {crew.data?.length ? crew.data.map((c) => `${c.name} ${num(c.hours)}h`).join(", ") : "nobody clocked on"}</p>
        {[["work_done", "Work done"], ["delays", "Delays / issues"], ["deliveries", "Deliveries"], ["visitors", "Visitors / inspections"], ["safety", "Safety"]].map(([k, l]) => (
          <Field key={k} label={l}><textarea rows={2} value={String(f[k as keyof typeof f])} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></Field>))}
        <Field label="Hours lost (weather / delays)"><input type="number" min={0} value={f.lost_hours} onChange={(e) => setF({ ...f, lost_hours: Number(e.target.value) })} /></Field>
        <button className="primary" onClick={() => run(async () => { await api.post(`/api/jobs/${jobId}/diary`, f); reload(); })}>Save diary</button><ErrorLine error={error} />
      </section>
      <section className="card">
        <h2>Earlier days</h2>
        {data?.map((l) => (
          <details key={l.id}><summary><b>{fmtDay(l.day)}</b> {l.weather} {l.lost_hours > 0 && <span className="badge warn">{l.lost_hours} h lost</span>}</summary>
            <p className="small">{l.crew.map((c) => `${c.name} ${num(c.hours)}h`).join(", ")}</p>
            {l.work_done && <p className="pre small">{l.work_done}</p>}{l.delays && <p className="pre small warn">{l.delays}</p>}
            <small className="muted">{l.by}</small></details>
        ))}
      </section>
    </div>
  );
}

function FormsTab({ jobId }: { jobId: number }) {
  const { data } = useLoad<{ id: number; template: string; fields: { key: string; label: string; type: string }[]; answers: Record<string, unknown>; by: string; at: string }[]>(`/api/jobs/${jobId}/forms`);
  return (
    <section className="card">
      <h2>Forms filled in</h2>
      {data?.length === 0 && <p className="muted">None yet. The team fills them in from the phone app.</p>}
      {data?.map((r) => (
        <details key={r.id}><summary><b>{r.template}</b> · {r.by} · {new Date(r.at).toLocaleString("en-AU")}</summary>
          <table className="kv"><tbody>{r.fields.filter((f) => f.type !== "heading").map((f) => (
            <tr key={f.key}><td>{f.label}</td><td>{f.type === "signature" && typeof r.answers[f.key] === "string" && String(r.answers[f.key]).startsWith("data:")
              ? <img src={String(r.answers[f.key])} alt="signature" style={{ height: 50 }} /> : String(r.answers[f.key] ?? "")}</td></tr>))}</tbody></table>
        </details>
      ))}
    </section>
  );
}

