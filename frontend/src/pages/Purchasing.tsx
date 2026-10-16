/* Purchasing: purchase orders and bills, suppliers, and supplier price files with the cheapest-supplier report. */
import { useState } from "react";
import { api, download, upload } from "../api";
import { can, useApp } from "../App";
import { DataTable, ErrorLine, Field, fmtDate, Modal, money, pct, Status, Tabs, todayIso, useAction, useLoad } from "../ui";
import { PoEditor } from "./JobHub";

type Tab = "pos" | "suppliers" | "prices" | "compare";

export default function Purchasing() {
  const { user } = useApp();
  const q = new URLSearchParams(window.location.search);
  const [tab, setTab] = useState<Tab>((q.get("tab") as Tab) || "pos");
  const tabs: [Tab, string][] = [["pos", "Purchase orders"], ["suppliers", "Suppliers"]];
  if (can(user, "can_finance")) tabs.push(["prices", "Supplier price files"], ["compare", "Cheapest supplier"]);
  return (
    <main className="page">
      <div className="row wrap"><h1 style={{ margin: 0 }}>Purchasing</h1><span className="spacer" /><Tabs tabs={tabs} value={tab} onChange={setTab} /></div>
      {tab === "pos" && <Pos jobId={q.get("job")} />}
      {tab === "suppliers" && <Suppliers />}
      {tab === "prices" && <PriceFiles />}
      {tab === "compare" && <Compare />}
    </main>
  );
}

interface PoRow { id: number; po_no: string; job_id: number | null; job_no: string; job: string; supplier_id: number | null; supplier: string; category: string; status: string;
  order_date: string | null; required_date: string | null; value: number; bill_ref: string; bill_amount: number | null; bill_variance: number | null; bill_due: string | null;
  bill_paid: string | null; delivery: string; notes: string; lines: { code: string; description: string; qty: number; unit: string; unit_cost: number }[] }

function Pos({ jobId }: { jobId: string | null }) {
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const { data, reload } = useLoad<PoRow[]>(`/api/purchase-orders?status=${status}&q=${encodeURIComponent(q)}${jobId ? `&job_id=${jobId}` : ""}`, [status, q]);
  const [edit, setEdit] = useState<PoRow | "new" | null>(null);
  const [bill, setBill] = useState<PoRow | null>(null);
  return (
    <section className="card">
      <div className="row wrap">
        <div className="tabs compact scroll">{[["", "All"], ["draft", "Draft"], ["sent", "Sent"], ["received", "Received"], ["billed", "Billed"]].map(([k, l]) => (
          <button key={k} className={status === k ? "active" : ""} onClick={() => setStatus(k)}>{l}</button>))}</div>
        <span className="spacer" /><input placeholder="Search PO, supplier, job" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="primary" onClick={() => setEdit("new")}>+ New PO</button>
      </div>
      <DataTable rows={data ?? []} onRow={(r) => setEdit(r)} cols={[
        { key: "n", label: "PO", render: (r) => <b>{r.po_no}</b> },
        { key: "j", label: "Job", render: (r) => (r.job_no ? `${r.job_no} ${r.job}` : "Stock") },
        { key: "s", label: "Supplier", render: (r) => r.supplier },
        { key: "d", label: "Ordered", hideSm: true, render: (r) => fmtDate(r.order_date) },
        { key: "st", label: "Status", render: (r) => <Status value={r.status} /> },
        { key: "v", label: "Value", num: true, render: (r) => money(r.value, true) },
        { key: "b", label: "Bill", num: true, render: (r) => r.bill_amount !== null ? <>{money(r.bill_amount, true)}{Math.abs(r.bill_variance ?? 0) > Math.max(1, r.value * 0.02) && <span className="badge warn" title="Bill differs from the PO">{money(r.bill_variance, true)}</span>}</> : "" },
        { key: "x", label: "", render: (r) => r.status !== "billed" && r.status !== "cancelled" && <button className="link small" onClick={(e) => { e.stopPropagation(); setBill(r); }}>Enter bill</button> },
      ]} />
      <p className="small muted">The team get PO numbers on their phones at the trade counter. Bills in Xero quoting a PO number are matched to it automatically.</p>
      {edit && <PoEditor jobId={jobId ? Number(jobId) : null} po={edit === "new" ? undefined : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); reload(); }} />}
      {bill && <BillForm po={bill} onDone={() => { setBill(null); reload(); }} />}
    </section>
  );
}

function BillForm({ po, onDone }: { po: PoRow; onDone: () => void }) {
  const [f, setF] = useState({ bill_ref: "", bill_amount: po.value, bill_date: todayIso(), bill_due: "" });
  const [run, error] = useAction();
  return (
    <Modal title={`Bill for ${po.po_no}`} onClose={onDone}>
      <Field label="Supplier's invoice number"><input value={f.bill_ref} onChange={(e) => setF({ ...f, bill_ref: e.target.value })} /></Field>
      <Field label="Amount ex GST" hint={`PO value ${money(po.value, true)}`}><input type="number" step="0.01" value={f.bill_amount} onChange={(e) => setF({ ...f, bill_amount: Number(e.target.value) })} /></Field>
      <Field label="Bill date"><input type="date" value={f.bill_date} onChange={(e) => setF({ ...f, bill_date: e.target.value })} /></Field>
      <Field label="Due" hint="Blank = the supplier's terms"><input type="date" value={f.bill_due} onChange={(e) => setF({ ...f, bill_due: e.target.value })} /></Field>
      <button className="primary" onClick={() => run(async () => { await api.post(`/api/purchase-orders/${po.id}/bill`, { ...f, bill_due: f.bill_due || null }); onDone(); })}>Save bill</button>
      <ErrorLine error={error} />
    </Modal>
  );
}

interface Sup { id: number; name: string; email: string; phone: string; account_no: string; terms_days: number; kind: string; active: boolean }

function Suppliers() {
  const { data, reload } = useLoad<Sup[]>("/api/suppliers");
  const [edit, setEdit] = useState<Partial<Sup> | null>(null);
  const [run, error] = useAction();
  return (
    <section className="card">
      <div className="row"><h2 style={{ margin: 0 }}>Suppliers</h2><span className="spacer" /><button onClick={() => setEdit({ terms_days: 30, kind: "materials", active: true })}>+ Supplier</button></div>
      <DataTable rows={data ?? []} onRow={(r) => setEdit(r)} cols={[
        { key: "n", label: "Supplier", render: (r) => <b>{r.name}</b> },
        { key: "k", label: "Type", render: (r) => r.kind },
        { key: "a", label: "Account", hideSm: true, render: (r) => r.account_no },
        { key: "t", label: "Terms", render: (r) => `${r.terms_days} days EOM` },
        { key: "c", label: "Contact", hideSm: true, render: (r) => [r.phone, r.email].filter(Boolean).join(" · ") },
      ]} />
      {edit && (
        <Modal title={edit.id ? edit.name ?? "" : "New supplier"} onClose={() => setEdit(null)}>
          {(["name", "account_no", "email", "phone"] as const).map((k) => <Field key={k} label={k.replace("_", " ")}><input value={String(edit[k] ?? "")} onChange={(e) => setEdit({ ...edit, [k]: e.target.value })} /></Field>)}
          <Field label="Type"><select value={edit.kind} onChange={(e) => setEdit({ ...edit, kind: e.target.value })}>{["materials", "subcontractor", "plant", "other"].map((k) => <option key={k}>{k}</option>)}</select></Field>
          <Field label="Terms (days after end of month)"><input type="number" value={edit.terms_days} onChange={(e) => setEdit({ ...edit, terms_days: Number(e.target.value) })} /></Field>
          <button className="primary" onClick={() => run(async () => {
            const body = { name: edit.name, email: edit.email ?? "", phone: edit.phone ?? "", account_no: edit.account_no ?? "", terms_days: edit.terms_days ?? 30, kind: edit.kind ?? "materials", active: edit.active ?? true };
            if (edit.id) await api.put(`/api/suppliers/${edit.id}`, body); else await api.post("/api/suppliers", body);
            setEdit(null); reload();
          })}>Save</button><ErrorLine error={error} />
        </Modal>
      )}
    </section>
  );
}

const FIELD_LABELS: Record<string, string> = { code: "Product code *", mfr_code: "Manufacturer code", barcode: "Barcode", description: "Description", brand: "Brand",
  group: "Product group", unit: "Unit", price: "Your price *", list_price: "List price" };

function PriceFiles() {
  const sups = useLoad<Sup[]>("/api/suppliers");
  const imports = useLoad<{ id: number; supplier: string; filename: string; effective: string; rows: number; new_items: number; price_up: number; price_down: number; source: string; at: string }[]>("/api/supplier-prices/imports");
  const [sup, setSup] = useState<number | "">("");
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<{ headers: string[]; columns: Record<string, string>; sample: Record<string, string>[]; rows: number; fields: string[] } | null>(null);
  const [cols, setCols] = useState<Record<string, string>>({});
  const [isReece, setIsReece] = useState(false);
  const [run, error, busy] = useAction();
  const [msg, setMsg] = useState("");
  const read = (f: File | null) => run(async () => {
    setFile(f); setPreview(null); setMsg("");
    if (!f || !sup) return;
    const form = new FormData(); form.append("file", f); form.append("supplier_id", String(sup));
    const p = await upload<NonNullable<typeof preview>>("/api/supplier-prices/preview", form);
    setPreview(p); setCols(p.columns);
  });
  const load = () => run(async () => {
    if (!file || !sup) return;
    const form = new FormData(); form.append("file", file); form.append("supplier_id", String(sup)); form.append("columns", JSON.stringify(cols));
    form.append("source", isReece ? "reece_max" : "file");
    const r = await upload<{ rows: number; new_items: number; price_up: number; price_down: number }>("/api/supplier-prices/import", form);
    setMsg(`Loaded ${r.rows} products: ${r.new_items} new, ${r.price_up} dearer, ${r.price_down} cheaper.`); setPreview(null); setFile(null); imports.reload();
  });
  return (
    <div className="two-col even">
      <section className="card">
        <h2>Load a price file</h2>
        <p className="small">Each month: <b>Reece</b> → maX → Account → download the price file (CSV or Excel). Other suppliers → the CSV or spreadsheet they email.
          Columns are found by their headings; fix any here and they're remembered for that supplier.</p>
        <div className="row wrap">
          <select value={sup} onChange={(e) => { setSup(e.target.value ? Number(e.target.value) : ""); setPreview(null); }}>
            <option value="">Supplier…</option>{sups.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>
          <label className="btn">{file ? file.name : "Choose file"}<input type="file" accept=".csv,.xlsx,.xlsm" hidden disabled={!sup} onChange={(e) => read(e.target.files?.[0] ?? null)} /></label>
          <label className="inline small"><input type="checkbox" checked={isReece} onChange={(e) => setIsReece(e.target.checked)} /> Reece maX file</label>
        </div>
        {preview && (
          <>
            <p className="small">{preview.rows} rows. Which column is which?</p>
            <div className="settings-grid">{preview.fields.map((f) => (
              <Field key={f} label={FIELD_LABELS[f] ?? f}><select value={cols[f] ?? ""} onChange={(e) => setCols({ ...cols, [f]: e.target.value })}>
                <option value="">–</option>{preview.headers.map((h) => <option key={h}>{h}</option>)}</select></Field>))}</div>
            <div className="dt-wrap"><table className="dt compact"><thead><tr>{["code", "description", "mfr_code", "price"].map((f) => <th key={f}>{FIELD_LABELS[f]}</th>)}</tr></thead>
              <tbody>{preview.sample.map((r, i) => <tr key={i}>{["code", "description", "mfr_code", "price"].map((f) => <td key={f}>{cols[f] ? r[cols[f]] : ""}</td>)}</tr>)}</tbody></table></div>
            <button className="primary" disabled={busy || !cols.code || !cols.price} onClick={load}>Load {preview.rows} prices</button>
          </>
        )}
        {msg && <p className="ok">{msg}</p>}<ErrorLine error={error} />
        <p className="small muted">Products are matched across suppliers by the manufacturer's code (or barcode), so the same fitting from Reece and Tradelink is compared like for like.</p>
      </section>
      <section className="card">
        <h2>Loaded</h2>
        <DataTable rows={imports.data ?? []} cols={[
          { key: "s", label: "Supplier", render: (r) => <>{r.supplier}{r.source === "reece_max" && <span className="badge">maX</span>}</> },
          { key: "d", label: "Prices from", render: (r) => fmtDate(r.effective) },
          { key: "r", label: "Products", num: true, render: (r) => r.rows },
          { key: "c", label: "Changes", render: (r) => <span className="small">{r.new_items} new · <span className="error">▲{r.price_up}</span> · <span className="ok">▼{r.price_down}</span></span> },
        ]} />
      </section>
    </div>
  );
}

interface CmpRow { product_key: string; description: string; brand: string; group: string; unit: string; cheapest_supplier: string; cheapest_price: number; highest_price: number;
  spread_pct: number; prices: { supplier: string; code: string; price: number }[]; qty_bought: number; saving: number }
interface Cmp { products: number; rows: CmpRow[]; groups: { group: string; products: number; saving: number; cheapest_most_often: string; wins: Record<string, number> }[];
  supplier_wins: Record<string, number>; saving_total: number }

function Compare() {
  const [group, setGroup] = useState("");
  const { data } = useLoad<Cmp>(`/api/supplier-prices/compare?group=${encodeURIComponent(group)}`, [group]);
  const [run, error] = useAction();
  const [msg, setMsg] = useState("");
  if (!data) return <p className="muted">Loading…</p>;
  const sups = Object.keys(data.supplier_wins);
  return (
    <>
      <div className="tiles">
        <div className="tile"><b>{data.products}</b><span>products sold by 2+ suppliers</span></div>
        {sups.map((s) => <div key={s} className="tile"><b>{data.supplier_wins[s]}</b><span>cheapest at {s}</span></div>)}
        <div className="tile ok"><b>{money(data.saving_total)}</b><span>saving on the last 12 months' POs, buying each at the cheapest</span></div>
      </div>
      <section className="card">
        <div className="row wrap"><h2 style={{ margin: 0 }}>By product line</h2><span className="spacer" />
          <button onClick={() => download("/api/supplier-prices/compare.csv", "cheapest-supplier.csv")}>Download every line</button>
          <button onClick={() => window.confirm("Make a new price-book version with every item at its cheapest supplier price? Existing estimates keep their prices.") &&
            run(async () => { const r = await api.post<{ label: string; changed: number }>("/api/supplier-prices/update-price-book", { mode: "cheapest" }); setMsg(`Made "${r.label}" with ${r.changed} prices changed.`); })}>
            Update the price book</button></div>
        {msg && <p className="ok small">{msg}</p>}<ErrorLine error={error} />
        <DataTable rows={data.groups} onRow={(g) => setGroup(g.group === group ? "" : g.group)} cols={[
          { key: "g", label: "Product line", render: (g) => <b className={group === g.group ? "ok" : ""}>{g.group}</b> },
          { key: "p", label: "Products", num: true, render: (g) => g.products },
          { key: "c", label: "Usually cheapest", render: (g) => g.cheapest_most_often },
          { key: "w", label: "Cheapest count", hideSm: true, render: (g) => Object.entries(g.wins).map(([s, n]) => `${s} ${n}`).join(" · ") },
          { key: "s", label: "Saving (12 mo)", num: true, render: (g) => money(g.saving) },
        ]} />
      </section>
      <section className="card">
        <h2>{group ? `${group}: every product` : "Biggest differences"}</h2>
        <DataTable rows={data.rows.slice(0, 300)} cols={[
          { key: "d", label: "Product", render: (r) => <>{r.description}<div className="small muted">{r.brand} · {r.unit}</div></> },
          { key: "c", label: "Cheapest", render: (r) => <><b>{r.cheapest_supplier}</b> {money(r.cheapest_price, true)}</> },
          { key: "o", label: "Others", hideSm: true, render: (r) => r.prices.slice(1).map((p) => `${p.supplier} ${money(p.price, true)}`).join(" · ") },
          { key: "s", label: "Spread", num: true, render: (r) => pct(r.spread_pct) },
          { key: "q", label: "Bought", num: true, hideSm: true, render: (r) => r.qty_bought || "" },
          { key: "v", label: "Saving", num: true, render: (r) => (r.saving ? money(r.saving) : "") },
        ]} />
      </section>
    </>
  );
}
