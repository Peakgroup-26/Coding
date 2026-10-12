import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useApp } from "../App";
import type { LabourRate, Prebuild, PriceBook, PriceItem } from "../types";
import { fmtMoney } from "../util";

type ImportResult = { created: number; updated: number; errors: { row: number; code: string; error: string }[]; columns: Record<string, string> };

export default function PriceBooks() {
  const { user } = useApp();
  const isAdmin = user.role === "admin";
  const [books, setBooks] = useState<PriceBook[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ label: "", copy_from_id: "" });

  const load = useCallback(async () => {
    const b = await api.get<PriceBook[]>("/api/price-books");
    setBooks(b);
    setSelected((s) => s ?? b[0]?.id ?? null);
  }, []);
  useEffect(() => { load(); }, [load]);

  const create = async () => {
    setError("");
    try {
      const b = await api.post<PriceBook>("/api/price-books", { label: form.label, copy_from_id: form.copy_from_id ? Number(form.copy_from_id) : null });
      setForm({ label: "", copy_from_id: "" });
      await load();
      setSelected(b.id);
    } catch (e) { setError((e as Error).message); }
  };

  const book = books.find((b) => b.id === selected);
  return (
    <main className="page">
      <h1>Price books</h1>
      <p className="muted small">
        Each price book is a version of Peak's prices. Import into a draft, check it, then lock it. Jobs priced on a locked
        version keep those rates; for new prices, copy it to a new version.
      </p>
      {error && <p className="error">{error}</p>}
      <div className="two-col left">
        <section className="card">
          <ul className="items big">
            {books.map((b) => (
              <li key={b.id} className={b.id === selected ? "sel" : ""} onClick={() => setSelected(b.id)}>
                <div>
                  <b>{b.label}</b> {b.locked ? <span className="badge ok">Locked</span> : <span className="badge warn">Draft</span>}
                  <div className="muted small">{b.items} items · {b.prebuilds} prebuilds · {b.rates} rates · {b.jobs} jobs</div>
                </div>
              </li>
            ))}
            {books.length === 0 && <li className="muted">No price books yet.</li>}
          </ul>
          {isAdmin && (
            <div className="form">
              <h3>New version</h3>
              <input placeholder="e.g. Peak prices Nov 2026" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
              <select value={form.copy_from_id} onChange={(e) => setForm({ ...form, copy_from_id: e.target.value })}>
                <option value="">Start empty</option>
                {books.map((b) => <option key={b.id} value={b.id}>Copy of {b.label}</option>)}
              </select>
              <button className="primary" disabled={!form.label} onClick={create}>Create</button>
            </div>
          )}
        </section>
        {book && <BookDetail key={book.id} book={book} isAdmin={isAdmin} onChange={load} />}
      </div>
    </main>
  );
}

function BookDetail({ book, isAdmin, onChange }: { book: PriceBook; isAdmin: boolean; onChange: () => void }) {
  const [tab, setTab] = useState<"items" | "prebuilds" | "rates">("prebuilds");
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<PriceItem[]>([]);
  const [prebuilds, setPrebuilds] = useState<Prebuild[]>([]);
  const [rates, setRates] = useState<LabourRate[]>([]);
  const [kind, setKind] = useState<"items" | "prebuilds" | "rates">("items");
  const [columns, setColumns] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const editable = isAdmin && !book.locked;

  const load = useCallback(async () => {
    const q = `?search=${encodeURIComponent(search)}&limit=500`;
    const [i, p, r] = await Promise.all([
      api.get<PriceItem[]>(`/api/price-books/${book.id}/items${q}`),
      api.get<Prebuild[]>(`/api/price-books/${book.id}/prebuilds${q}`),
      api.get<LabourRate[]>(`/api/price-books/${book.id}/rates`),
    ]);
    setItems(i); setPrebuilds(p); setRates(r);
  }, [book.id, search]);
  useEffect(() => { load(); }, [load]);

  const doImport = async (files: FileList | null) => {
    if (!files?.[0]) return;
    setError(""); setResult(null); setBusy(true);
    const fd = new FormData();
    fd.append("kind", kind);
    fd.append("file", files[0]);
    if (columns.trim()) fd.append("columns", columns);
    try { setResult(await api.post<ImportResult>(`/api/price-books/${book.id}/import`, fd)); await load(); onChange(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };
  const lock = async () => {
    if (!window.confirm(`Lock "${book.label}"? Its prices can't change after this.`)) return;
    try { await api.post(`/api/price-books/${book.id}/lock`); onChange(); } catch (e) { setError((e as Error).message); }
  };
  const setDefaultRate = async (code: string) => {
    try { await api.patch(`/api/price-books/${book.id}`, { default_labour_rate_code: code }); onChange(); } catch (e) { setError((e as Error).message); }
  };
  const putRate = async (r: Partial<LabourRate> & { code: string }) => {
    try { await api.put(`/api/price-books/${book.id}/rates`, { description: "", rate: 0, ...r }); load(); } catch (e) { setError((e as Error).message); }
  };

  return (
    <section className="card">
      <div className="row wrap">
        <h2>{book.label}</h2>
        {book.locked ? <span className="badge ok">Locked {book.locked_at && new Date(book.locked_at).toLocaleDateString("en-AU")}</span> : <span className="badge warn">Draft</span>}
        <span className="spacer" />
        <label className="inline">Default labour rate
          <select disabled={!editable} value={book.default_labour_rate_code} onChange={(e) => setDefaultRate(e.target.value)}>
            <option value="">–</option>
            {rates.map((r) => <option key={r.id} value={r.code}>{r.code} ({fmtMoney(r.rate)}/h)</option>)}
          </select>
        </label>
        {editable && <button className="primary" onClick={lock}>Lock this version</button>}
      </div>

      {editable && (
        <div className="callout">
          <b>Import</b>
          <select value={kind} onChange={(e) => setKind(e.target.value as typeof kind)}>
            <option value="items">Price list (catalogue items)</option>
            <option value="prebuilds">Prebuilds</option>
            <option value="rates">Labour rates</option>
          </select>
          <label className="upload">
            <input type="file" accept=".csv,.xlsx,.xlsm" disabled={busy} onChange={(e) => { doImport(e.target.files); e.target.value = ""; }} />
            <span className="button">{busy ? "Importing…" : "Choose CSV or Excel file"}</span>
          </label>
          <input className="wide-input" placeholder='Optional column names, e.g. {"code": "Part No", "cost": "Trade"}' value={columns} onChange={(e) => setColumns(e.target.value)} />
          <div className="small muted" style={{ flexBasis: "100%" }}>
            Columns are recognised from Simpro-style names (Part Number, Description, Trade Price, Labour Time, Charge Out Rate…).
            Prebuilds can be one row per component (code repeated) or have a Components column like "PART-1 x2; PART-2".
          </div>
        </div>
      )}
      {result && (
        <p className={result.errors.length ? "warn" : "ok"}>
          {result.created} added, {result.updated} updated. Columns used: {Object.entries(result.columns).map(([k, v]) => `${k} ← "${v}"`).join(", ")}
          {result.errors.length > 0 && <> · {result.errors.length} row(s) skipped: {result.errors.slice(0, 5).map((e) => `row ${e.row} ${e.code}: ${e.error}`).join("; ")}</>}
        </p>
      )}
      {error && <p className="error">{error}</p>}

      <div className="row wrap">
        <div className="tabs compact">
          <button className={tab === "prebuilds" ? "active" : ""} onClick={() => setTab("prebuilds")}>Prebuilds</button>
          <button className={tab === "items" ? "active" : ""} onClick={() => setTab("items")}>Items</button>
          <button className={tab === "rates" ? "active" : ""} onClick={() => setTab("rates")}>Labour rates</button>
        </div>
        {tab !== "rates" && <input placeholder="Search code or description" value={search} onChange={(e) => setSearch(e.target.value)} />}
      </div>

      {tab === "items" && (
        <table>
          <thead><tr><th>Code</th><th>Description</th><th>Unit</th><th className="r">Cost</th><th>Supplier</th></tr></thead>
          <tbody>{items.map((i) => <tr key={i.id}><td>{i.code}</td><td>{i.description}</td><td>{i.uom}</td><td className="r">{fmtMoney(i.cost)}</td><td>{i.supplier}</td></tr>)}</tbody>
        </table>
      )}
      {tab === "prebuilds" && (
        <table>
          <thead><tr><th>Code</th><th>Description</th><th>Unit</th><th className="r">Labour h</th><th>Rate</th><th>Components</th></tr></thead>
          <tbody>
            {prebuilds.map((p) => (
              <tr key={p.id}>
                <td>{p.code}</td><td>{p.description}</td><td>{p.uom}</td><td className="r">{p.labour_hours}</td>
                <td>{p.labour_rate_code || <span className="muted">default</span>}</td>
                <td className="small">{p.components.map((c) => `${c.code} ×${c.qty}`).join(", ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {tab === "rates" && (
        <table>
          <thead><tr><th>Code</th><th>Description</th><th className="r">$ / hour</th></tr></thead>
          <tbody>
            {rates.map((r) => (
              <tr key={r.id}>
                <td>{r.code}{r.code === book.default_labour_rate_code && <span className="badge ok">default</span>}</td>
                <td>{r.description}</td><td className="r">{fmtMoney(r.rate)}</td>
              </tr>
            ))}
            {editable && <NewRateRow onAdd={putRate} />}
          </tbody>
        </table>
      )}
    </section>
  );
}

function NewRateRow({ onAdd }: { onAdd: (r: { code: string; description: string; rate: number }) => void }) {
  const [r, setR] = useState({ code: "", description: "", rate: "" });
  return (
    <tr>
      <td><input placeholder="Code" value={r.code} onChange={(e) => setR({ ...r, code: e.target.value })} /></td>
      <td><input placeholder="Description" value={r.description} onChange={(e) => setR({ ...r, description: e.target.value })} /></td>
      <td className="r">
        <input className="tiny" type="number" value={r.rate} onChange={(e) => setR({ ...r, rate: e.target.value })} />{" "}
        <button disabled={!r.code || r.rate === ""} onClick={() => { onAdd({ code: r.code, description: r.description, rate: Number(r.rate) }); setR({ code: "", description: "", rate: "" }); }}>Add</button>
      </td>
    </tr>
  );
}
